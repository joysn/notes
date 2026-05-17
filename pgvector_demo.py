"""
pgvector Demo — Vector Search with PostgreSQL
Run pgvector_setup.sh first to start the Postgres container.

Usage:
    pip install sentence-transformers psycopg2-binary
    python pgvector_demo.py
"""

import psycopg2
from sentence_transformers import SentenceTransformer

# ──────────────────────────────────────────────
# Config — change DB_PORT if you remapped it
# ──────────────────────────────────────────────
DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "vectordb"
DB_USER = "postgres"
DB_PASS = "vector123"


# ──────────────────────────────────────────────
# Sample documents (DevOps runbooks, postmortems, FAQs)
# ──────────────────────────────────────────────
DOCUMENTS = [
    {
        "title": "Ingestion Service Runbook",
        "content": "The ingestion service reads from Kafka topics in batches of 1000. "
                   "When a batch fails, it retries 3 times with exponential backoff. "
                   "Max replicas: 8, limited by Kafka partition count.",
        "team": "platform",
        "doc_type": "runbook"
    },
    {
        "title": "Ingestion Service Postmortem 2024-01-15",
        "content": "Root cause: Kafka consumer group rebalance triggered by broker restart. "
                   "All pods attempted simultaneous partition reassignment causing memory spikes. "
                   "Mitigation: set max.poll.interval.ms=600000.",
        "team": "platform",
        "doc_type": "postmortem"
    },
    {
        "title": "Kubernetes Pod CrashLoopBackOff Guide",
        "content": "CrashLoopBackOff means the container keeps crashing and Kubernetes "
                   "is waiting longer between restart attempts. Common causes: OOM killed, "
                   "missing config map, failed health check, application error on startup.",
        "team": "devops",
        "doc_type": "runbook"
    },
    {
        "title": "Monitoring and Alerting Setup",
        "content": "All services expose Prometheus metrics on /metrics endpoint. "
                   "Grafana dashboards are at grafana.internal. PagerDuty integration "
                   "fires alerts when p99 latency exceeds 500ms for 5 minutes.",
        "team": "observability",
        "doc_type": "runbook"
    },
    {
        "title": "Nginx Reverse Proxy Configuration",
        "content": "Nginx sits in front of all public-facing services. SSL termination "
                   "happens at Nginx. Rate limiting is configured at 100 req/s per IP. "
                   "Configuration lives in /etc/nginx/conf.d/ on the gateway pods.",
        "team": "platform",
        "doc_type": "runbook"
    },
    {
        "title": "Database Connection Pooling",
        "content": "PgBouncer runs as a sidecar in all pods that connect to PostgreSQL. "
                   "Max pool size is 20 per pod. If connections are exhausted, check for "
                   "long-running queries or missing transaction commits.",
        "team": "platform",
        "doc_type": "runbook"
    },
    {
        "title": "Deployment Rollback Procedure",
        "content": "To rollback a deployment: kubectl rollout undo deployment/<name>. "
                   "For Helm: helm rollback <release> <revision>. Always check "
                   "helm history <release> first to identify the target revision.",
        "team": "devops",
        "doc_type": "runbook"
    },
    {
        "title": "OOM Troubleshooting",
        "content": "If pods are OOM killed, check: 1) memory limits in values.yaml "
                   "2) heap size for Java services (-Xmx flag) "
                   "3) memory leak indicators in Grafana memory dashboard "
                   "4) recent code changes that increased memory footprint.",
        "team": "devops",
        "doc_type": "faq"
    },
    {
        "title": "Kafka Consumer Lag Runbook",
        "content": "Consumer lag is the difference between the latest offset and the "
                   "consumer group offset. If lag is increasing: check consumer health, "
                   "increase partition count and consumer replicas proportionally, "
                   "verify no poison pill messages blocking processing.",
        "team": "platform",
        "doc_type": "runbook"
    },
    {
        "title": "Secret Management with Vault",
        "content": "All secrets are stored in HashiCorp Vault. Pods access secrets via "
                   "the Vault Agent sidecar injector. Secrets rotate every 90 days. "
                   "If a pod cannot start due to missing secrets, check Vault seal status "
                   "and the service account role binding.",
        "team": "security",
        "doc_type": "runbook"
    },
]


# ──────────────────────────────────────────────
# Load embedding model (~90MB download on first run)
# ──────────────────────────────────────────────
print("Loading embedding model (first run downloads ~90MB)...")
model = SentenceTransformer('all-MiniLM-L6-v2')  # 384 dimensions
print("Model loaded.\n")


# ──────────────────────────────────────────────
# Connect to PostgreSQL
# ──────────────────────────────────────────────
print(f"Connecting to PostgreSQL at {DB_HOST}:{DB_PORT}...")
conn = psycopg2.connect(
    host=DB_HOST, port=DB_PORT,
    dbname=DB_NAME, user=DB_USER, password=DB_PASS
)
print("Connected.\n")


# ──────────────────────────────────────────────
# Setup: extension + table + index
# ──────────────────────────────────────────────
conn.autocommit = True
cur = conn.cursor()

cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

cur.execute("DROP TABLE IF EXISTS documents;")
cur.execute("""
    CREATE TABLE documents (
        id          SERIAL PRIMARY KEY,
        title       TEXT NOT NULL,
        content     TEXT NOT NULL,
        team        TEXT,
        doc_type    TEXT,
        created_at  TIMESTAMP DEFAULT now(),
        embedding   vector(384)
    );
""")
print("Created table 'documents'")


# ──────────────────────────────────────────────
# Generate embeddings and insert
# ──────────────────────────────────────────────
conn.autocommit = False

print("Generating embeddings...")
contents = [doc["content"] for doc in DOCUMENTS]
embeddings = model.encode(contents)
print(f"Generated {len(embeddings)} embeddings, each {len(embeddings[0])} dims")

for doc, emb in zip(DOCUMENTS, embeddings):
    cur.execute("""
        INSERT INTO documents (title, content, team, doc_type, embedding)
        VALUES (%s, %s, %s, %s, %s::vector)
    """, (
        doc["title"],
        doc["content"],
        doc["team"],
        doc["doc_type"],
        f"[{','.join(str(x) for x in emb)}]"
    ))

conn.commit()
print(f"Inserted {len(DOCUMENTS)} documents\n")


# ──────────────────────────────────────────────
# Create HNSW index
# ──────────────────────────────────────────────
conn.autocommit = True
cur.execute("""
    CREATE INDEX idx_docs_hnsw ON documents
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);
""")
print("Created HNSW index\n")
conn.autocommit = False


# ──────────────────────────────────────────────
# Search function
# ──────────────────────────────────────────────
def search(query_text, top_k=5, team=None, doc_type=None):
    """Semantic search with optional metadata filters."""
    query_emb = model.encode(query_text)
    query_vec = f"[{','.join(str(x) for x in query_emb)}]"

    conditions = []
    filter_params = []

    if team:
        conditions.append("team = %s")
        filter_params.append(team)
    if doc_type:
        conditions.append("doc_type = %s")
        filter_params.append(doc_type)

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    # Params must match SQL placeholder order:
    # SELECT ... <=> %s::vector  →  query_vec
    # WHERE team = %s            →  filter_params
    # ORDER BY ... <=> %s::vector → query_vec
    # LIMIT %s                   →  top_k
    params = [query_vec] + filter_params + [query_vec, top_k]

    cur.execute(f"""
        SELECT title, content, team, doc_type,
               1 - (embedding <=> %s::vector) AS similarity
        FROM documents
        {where_clause}
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """, params)

    return [
        {"title": r[0], "content": r[1], "team": r[2],
         "doc_type": r[3], "similarity": float(r[4])}
        for r in cur.fetchall()
    ]


# ──────────────────────────────────────────────
# Demo: Run sample queries
# ──────────────────────────────────────────────
print("=" * 60)
print("  VECTOR SEARCH DEMO")
print("=" * 60)

queries = [
    ("Why is my pod keep restarting?", None, None),
    ("how to rollback a bad deployment", None, None),
    ("kafka messages piling up", None, None),
    ("how do I store secrets securely", None, None),
    ("pod crashing with memory errors", "devops", None),          # filtered by team
    ("how to configure rate limiting", "platform", "runbook"),    # filtered by team + type
]

for query_text, team, doc_type in queries:
    filter_desc = ""
    if team or doc_type:
        filters = []
        if team:
            filters.append(f"team={team}")
        if doc_type:
            filters.append(f"type={doc_type}")
        filter_desc = f"  [filter: {', '.join(filters)}]"

    print(f'\nQuery: "{query_text}"{filter_desc}')
    print("-" * 60)

    results = search(query_text, top_k=3, team=team, doc_type=doc_type)
    for r in results:
        print(f"  [{r['similarity']:.3f}] ({r['doc_type']}/{r['team']}) {r['title']}")
        print(f"           {r['content'][:80]}...")

print("\n" + "=" * 60)
print("  DONE")
print("=" * 60)


# ──────────────────────────────────────────────
# Cleanup
# ──────────────────────────────────────────────
cur.close()
conn.close()
