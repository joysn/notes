# Vector Search — From Basics to Production

## Part 1: The Problem Vector Search Solves

### Traditional search is brittle

Oracle Text / full-text search builds an **inverted index**: word → list of documents containing that word. Search for "kubernetes deployment failing" and it looks for those exact tokens.

Problems:
- Search "k8s deploy broken" — **zero results** (different words, same meaning)
- Search "container orchestration issue" — **zero results** (related concept, no token overlap)
- Search "deployment" — results include military deployments, software deployments, and cloud deployments — **no context**

**The core insight:** Words are symbols. The same meaning can be expressed with different symbols. Traditional search matches symbols. Vector search matches *meaning*.

### The analogy

Think of it like DNS vs. service mesh discovery:
- **DNS** (like keyword search): You must know the exact hostname. `my-svc.namespace.svc.cluster.local` works. `that-backend-thing` doesn't.
- **Service mesh** (like vector search): You describe what you need (labels, capabilities), and the system finds matching services based on *properties*, not exact names.

---

## Part 2: What Is a Vector?

A vector is just an array of numbers.

```
[0.12, -0.45, 0.78, 0.03, ..., -0.22]   # typically 384 to 3072 numbers
```

Each number represents a position along one "dimension" of meaning. Think of it as coordinates — but instead of 3D space (x, y, z), it's 384-dimensional or 1536-dimensional space.

### 2D intuition

Imagine plotting words on a 2D chart:

```
        "happy"
  "joyful" *  * "glad"

                          "fast"
                   "quick" * * "rapid"

  "sad" *
    * "unhappy"
```

Words with similar meaning cluster together. "Happy", "joyful", and "glad" are near each other. "Sad" is far from them.

Now extend this from 2 dimensions to 1536 dimensions. That's a vector embedding — a point in high-dimensional space where **distance = difference in meaning**.

### What each dimension captures

No single dimension maps cleanly to a human concept like "sentiment" or "topic." Instead, dimensions capture **learned statistical patterns** from training on massive text:
- Some combination of dimensions captures formality vs. casual
- Another captures technical vs. non-technical
- Another captures positive vs. negative sentiment
- Hundreds of other subtle patterns

You don't design these dimensions — the model learns them.

---

## Part 3: Embeddings — How Data Becomes Vectors

An **embedding model** converts raw data (text, images, code) into vectors.

```
Input text: "Kubernetes pod stuck in CrashLoopBackOff"
    |
    v
[Embedding Model]  (e.g., OpenAI text-embedding-3-small, 1536 dims)
    |
    v
Output: [0.023, -0.187, 0.445, ..., 0.091]  # 1536 floats
```

### Key properties

1. **Same model, same vector space**: Everything embedded by the same model lives in the same coordinate system. You can compare any two vectors.
2. **Similar meaning = close vectors**: "Pod in CrashLoopBackOff" and "Container keeps restarting" produce vectors that are close together.
3. **Different meaning = far vectors**: "Pod in CrashLoopBackOff" and "Quarterly revenue report" produce vectors far apart.
4. **Deterministic**: Same input + same model = same vector every time.

### Popular embedding models

| Model | Dimensions | Provider | Notes |
|---|---|---|---|
| `text-embedding-3-small` | 1536 | OpenAI | Good balance of cost/quality |
| `text-embedding-3-large` | 3072 | OpenAI | Higher quality, more compute |
| `voyage-3` | 1024 | Voyage AI | Strong for code and retrieval |
| `all-MiniLM-L6-v2` | 384 | Open source (HuggingFace) | Runs locally, fast, decent quality |
| `mxbai-embed-large` | 1024 | Open source | Strong open-source option |

### Hands-on example

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer('all-MiniLM-L6-v2')

texts = [
    "Kubernetes pod stuck in CrashLoopBackOff",
    "Container keeps restarting after deployment",
    "How to configure Nginx reverse proxy",
    "Annual company holiday party planning",
]

embeddings = model.encode(texts)

# embeddings[0] and embeddings[1] will be CLOSE (similar meaning)
# embeddings[0] and embeddings[3] will be FAR (unrelated)
```

---

## Part 4: Measuring Similarity — Distance Metrics

Once you have vectors, you need to compare them. "How close are these two points in high-dimensional space?"

### Cosine Similarity (most common)

Measures the **angle** between two vectors, ignoring magnitude.

```
cosine_similarity = dot(A, B) / (||A|| * ||B||)

Result range: -1 to 1
  1.0  = identical direction (same meaning)
  0.0  = perpendicular (unrelated)
 -1.0  = opposite (rare in practice)
```

**Why cosine?** It doesn't care about vector length, only direction. Two documents of different lengths about the same topic will have similar direction.

### Euclidean Distance (L2)

Straight-line distance between two points. Smaller = more similar.

```
L2 = sqrt(sum((a_i - b_i)^2))
```

### Dot Product

```
dot(A, B) = sum(a_i * b_i)
```

Larger = more similar. Faster to compute but affected by vector magnitude.

### Which to use?

| Metric | When | Analogy |
|---|---|---|
| **Cosine** | Default choice. Normalized comparison. | "Are these heading in the same direction?" |
| **L2** | When magnitude matters | "How far apart are these?" |
| **Dot product** | Pre-normalized vectors, speed-critical | "Quick similarity check" |

Most embedding models are trained with cosine similarity in mind. **Start with cosine.**

---

## Part 5: Vector Indexes (ANN) — Overview

### The fundamental problem

You have 1 million vectors stored. A new query vector arrives. You need the 10 closest vectors.

**Brute force:** Compare the query against all 1 million vectors. This works but is O(n). At 1M vectors with 1536 dimensions, that's ~6 billion floating-point operations per query. **Too slow.**

### Approximate Nearest Neighbor (ANN) indexes

ANN indexes trade a small amount of accuracy for massive speed gains. Instead of checking every vector, they organize vectors so you can narrow the search space quickly.

**Analogy:** Instead of checking every server in every datacenter for the closest one to a user, first narrow to the right region, then the right rack, then compare servers in that rack.

### Index types at a glance

| Index | Speed | Memory | Recall | Build Time | Best For |
|---|---|---|---|---|---|
| Flat (brute force) | Slow | Low | 100% | None | < 50K vectors, ground truth |
| IVF | Fast | Medium | ~95% | Medium | Millions of vectors |
| HNSW | Very fast | High | ~99% | Slow | When quality matters most |
| IVF-PQ | Fast | Very low | ~90% | Medium | Billions of vectors, memory-constrained |

---

## Part 5a: HNSW (Hierarchical Navigable Small World) — Deep Dive

### Concept 1: Graph-Based Search

Forget vectors for a moment. Think about how you find a person in a city you've never visited.

**Brute force approach:** Knock on every door in the city and ask "Are you John?" This is what brute-force vector search does.

**Graph approach:** You land at the airport and ask someone: "Do you know John?" They say "No, but my friend lives in John's neighborhood — talk to her." You go to her, she says "John lives two streets over, ask the shopkeeper on Oak Street." The shopkeeper says "John is my neighbor, house #42."

You found John in 3 hops instead of checking every house.

**This is a graph-based search.** Each person (node) knows a few other people (edges/connections). You navigate from person to person, getting closer each hop.

In vector search terms:
- Each **node** is a stored vector
- Each **edge** connects a vector to some other vectors it "knows about"
- **Searching** means starting at some node and hopping to whichever neighbor is closest to your query, repeating until you can't get any closer

```
You're looking for something near Q (the query):

Start at A (random entry point)
  A knows: [B, F, K]
  K is closest to Q → hop to K

At K:
  K knows: [A, M, R, P]
  R is closest to Q → hop to R

At R:
  R knows: [K, S, T]
  T is closest to Q → hop to T

At T:
  T knows: [R, U, V]
  None are closer to Q than T itself → STOP
  T is the answer (or very near it)
```

This is called **"greedy search on a graph."** At each step, you move to whichever neighbor gets you closest to the target.

### Concept 2: The Problem With a Single Graph

A single flat graph has a problem: **you can get stuck in local optima.**

Imagine the city analogy again. You're in the east side of town. Everyone you ask only knows people nearby. But John lives on the west side. Nobody on the east side has a direct connection to the west side. You keep hopping between east-side neighbors and never reach John.

```
Cluster A (east side)          Cluster B (west side)
  V1 -- V2 -- V3                V7 -- V8 -- V9
  |           |                  |           |
  V4 -- V5 -- V6                V10-- V11-- V12

  No edges between clusters!
  If you start at V1 and need V11, you're stuck.
```

Two possible fixes:

**Fix 1: Long-range connections** — Some connections go across the city, not just to neighbors. This is a "Small World" network. Most connections are local, but a few are long-range. This ensures you can reach any part of the graph.

**Fix 2: Multiple layers** — Have an "express" layer on top with just a few well-connected nodes that span the whole space, then progressively denser layers underneath.

**HNSW does both.**

### Concept 3: Small World Networks

In real social networks, you can reach anyone through roughly 6 connections (six degrees of separation). This works because:

- **Most connections are local** (you know your neighbors, colleagues)
- **A few connections are long-range** (you know someone in another country)

A **Navigable Small World (NSW)** graph for vectors has the same structure:

```
Without long-range edges (regular graph):
  A -- B -- C -- D -- E -- F -- G -- H -- I -- J
  To get from A to J: 9 hops (must traverse the whole chain)

With long-range edges (small world graph):
  A -- B -- C -- D -- E -- F -- G -- H -- I -- J
  A -------- D                  (long-range)
  D ------------------- H      (long-range)
  A to J: A → D → H → I → J = 4 hops
```

The long-range edges are shortcuts. But how do you decide which long-range edges to create? This is where the hierarchical part comes in.

### Concept 4: Skip Lists — The Key Intuition

Before understanding HNSW, you need to understand **skip lists**. This is the single most important concept.

A skip list is a data structure for sorted data. Imagine a sorted linked list:

```
Layer 0 (all elements):
  1 → 3 → 5 → 7 → 9 → 11 → 13 → 15 → 17 → 19 → 21

To find 19: start at 1, hop through every element → 9 hops
```

Now add "express lanes" — higher layers that skip over elements:

```
Layer 2:   1 ─────────────────── 11 ─────────────────── 21
Layer 1:   1 ────── 5 ────── 9 ────── 13 ────── 17 ────── 21
Layer 0:   1 → 3 → 5 → 7 → 9 → 11 → 13 → 15 → 17 → 19 → 21
```

To find 19:
- **Layer 2:** Start at 1. Next is 11 (less than 19, go). Next is 21 (too far). Drop down from 11.
- **Layer 1:** At 11. Next is 13 (go). Next is 17 (go). Next is 21 (too far). Drop down from 17.
- **Layer 0:** At 17. Next is 19. **Found it.** Total: 5 hops instead of 9.

**How elements get assigned to layers:** By coin flip! Each element starts at layer 0. Flip a coin — heads, promote to layer 1. Flip again — heads, promote to layer 2. Tails, stop.

This means:
- ~100% of elements are on layer 0
- ~50% on layer 1
- ~25% on layer 2
- ~12.5% on layer 3

The top layer has very few elements spread far apart (express lane). The bottom layer has everything (local street).

### Concept 5: HNSW = Skip List Structure + Graph Search

Now combine:

- **Skip list** gives you the layered structure (highway → local road)
- **Graph search** gives you the ability to navigate in high-dimensional space (no sorted order exists in 1536 dimensions)

In a skip list, elements are sorted so you can go "left" or "right." In 1536-dimensional space, there's no left or right. So instead of a sorted chain, each layer is a **graph** where you navigate by choosing the neighbor closest to your target.

```
Skip list (1D, sorted):
  Layer 2:   1 ————— 11 ————— 21
  Navigation: go right if value < target, else drop down

HNSW (1536D, no sort order):
  Layer 2:   V3 ————— V88 ————— V501
  Navigation: hop to whichever neighbor is closest to query, else drop down
```

**Each layer in HNSW is a navigable small world graph.** Upper layers are sparse (few nodes, long-distance edges). Lower layers are dense (many nodes, short-distance edges).

### HNSW Parameters

**M (max edges per node per layer):** How many neighbors each vector connects to when inserted. Think of it as "when a new person moves to town, they make M friends." M=16 is a common default.

Note: M controls connections made during insertion. Existing nodes can accumulate more connections (up to Mmax, typically 2*M for layer 0) since other nodes also connect to them.

**ef_construction (construction search width):** When inserting a new vector, how hard you try to find its best neighbors. Higher = slower build but better quality connections. Typically 128-256.

**m_L (level multiplier):** Controls the probability distribution for layer assignment. Typically `1/ln(M)`. Rarely tuned directly.

### HNSW Construction — Full Walkthrough with 6 Vectors

**Setup:** 6 vectors in 2D (for visualization), M=2.

```
        V2(2,8)
                      V5(7,7)

  V0(1,4)

        V3(3,3)
                V4(6,3)
                            V1(9,2)
```

**Distance reference table** (every decision below uses these):

```
         V0     V1     V2     V3     V4     V5
  V0      —     8.2    4.1    2.2    5.1    6.7
  V1     8.2     —     9.2    6.1    3.2    5.4
  V2     4.1    9.2     —     5.1    6.4    5.1
  V3     2.2    6.1    5.1     —     3.0    5.7
  V4     5.1    3.2    6.4    3.0     —     4.1
  V5     6.7    5.4    5.1    5.7    4.1     —
```

**Layer assignments** (by coin flip):

```
  V0 → Layer 1
  V1 → Layer 0
  V2 → Layer 0
  V3 → Layer 0
  V4 → Layer 2  (lucky roll)
  V5 → Layer 1
```

#### Insert V0 — First vector

V0 is assigned to Layer 1. It's the first vector. Nothing to connect to. V0 becomes the **entry point**.

```
Layer 1:  V0
Layer 0:  V0

Entry point: V0

Edge lists:
  V0 Layer 1: []
  V0 Layer 0: []
```

#### Insert V1 — Second vector

V1 is assigned to Layer 0 only.

**Search phase** (always starts at the top, at the entry point):

```
Layer 1:  At V0.
          V1 doesn't belong on this layer, so we're just navigating.
          V0 has no neighbors here. Best position found = V0.
          Drop down to Layer 0.

Layer 0:  At V0.
          V0 has no neighbors. Search ends.
          Candidates found: [V0 (dist 8.2)]
```

**Connection phase** (only on V1's assigned layers — Layer 0):

```
Layer 0:  M=2, but only 1 candidate exists.
          Connect V1 ↔ V0.
```

**Result:**

```
Layer 1:  V0
Layer 0:  V0 ———— V1

Entry point: V0

Edge lists:
  V0 Layer 0: [V1]
  V1 Layer 0: [V0]
```

#### Insert V2 — Third vector

V2 is assigned to Layer 0 only.

**Search phase:**

```
Layer 1:  At V0. No neighbors. Drop down.

Layer 0:  At V0. Neighbors: [V1].

          Distances to V2:
            V0 → V2 = 4.1
            V1 → V2 = 9.2   (discovered through V0's neighbor list)

          V0 is closer than V1. No neighbor improves on V0. Search ends.
          Candidates found: [V0 (4.1), V1 (9.2)]
```

**Connection phase:**

```
Layer 0:  M=2, we have 2 candidates.
          Connect V2 ↔ V0  AND  V2 ↔ V1.
```

**Result:**

```
Layer 1:  V0
Layer 0:  V0 ———— V1
           |      /
           V2 ———

Entry point: V0

Edge lists:
  V0 Layer 0: [V1, V2]
  V1 Layer 0: [V0, V2]
  V2 Layer 0: [V0, V1]
```

#### Insert V3 — Fourth vector

V3 is assigned to Layer 0 only.

**Search phase:**

```
Layer 1:  At V0. No neighbors here. Drop down.

Layer 0:  At V0. Neighbors: [V1, V2].

          Distances to V3:
            V0 → V3 = 2.2
            V1 → V3 = 6.1   (discovered via V0's neighbor list)
            V2 → V3 = 5.1   (discovered via V0's neighbor list)

          No neighbor is closer to V3 than V0 itself.
          Expand search — check V1's neighbors: [V0, V2] (already seen).
          Check V2's neighbors: [V0, V1] (already seen).
          No new candidates.

          All candidates: [V0 (2.2), V2 (5.1), V1 (6.1)]
```

**Connection phase:**

```
Layer 0:  M=2. Top 2 nearest: V0 (2.2) and V2 (5.1).
          Connect V3 ↔ V0  AND  V3 ↔ V2.

Check existing nodes (Mmax=4 for layer 0):
  V0 now has [V1, V2, V3] = 3 connections. Under Mmax=4 → OK.
  V2 now has [V0, V1, V3] = 3 connections. Under Mmax=4 → OK.
```

**Result:**

```
Layer 1:  V0
Layer 0:  V0 ———— V1
           |\     /
           | V2 —
           |/
           V3

Entry point: V0

Edge lists:
  V0 Layer 0: [V1, V2, V3]
  V1 Layer 0: [V0, V2]
  V2 Layer 0: [V0, V1, V3]
  V3 Layer 0: [V0, V2]
```

#### Insert V4 — Fifth vector

V4 is assigned to **Layer 2** — higher than the current max (Layer 1). V4 becomes the **new entry point**.

**Search phase:**

The current entry point is still V0. Highest existing layer is 1. Search begins there.

```
Layer 1:  At V0. No neighbors on this layer.
          V0 → V4 = 5.1. Best found = V0. Drop down.

Layer 0:  At V0. Neighbors: [V1, V2, V3].

          Distances to V4:
            V0 → V4 = 5.1   (current position)
            V1 → V4 = 3.2   (via V0's list) ← closer! Hop to V1.
            V2 → V4 = 6.4   (via V0's list)
            V3 → V4 = 3.0   (via V0's list) ← even closer! Hop to V3.

          At V3. Neighbors: [V0, V2].
            V0 → V4 = 5.1   (already seen)
            V2 → V4 = 6.4   (already seen)
            Neither closer than V3 (3.0).

          Also visit V1 (it was in our candidate list at 3.2).
          At V1. Neighbors: [V0, V2]. Already seen. No new candidates.

          All candidates: [V3 (3.0), V1 (3.2), V0 (5.1), V2 (6.4)]
```

**Connection phase:**

```
Layer 0:  M=2. Top 2: V3 (3.0) and V1 (3.2).
          Connect V4 ↔ V3  AND  V4 ↔ V1.

Layer 1:  Only V0 exists here. M=2 but only 1 candidate.
          Connect V4 ↔ V0.

Layer 2:  No other nodes. V4 is alone.

V4 becomes the new entry point (highest layer node).

Check existing nodes:
  V3 now has [V0, V2, V4] = 3. Mmax=4 → OK.
  V1 now has [V0, V2, V4] = 3. Mmax=4 → OK.
  V0 Layer 1 now has [V4] = 1. OK.
```

**Result:**

```
Layer 2:  V4                        ← new entry point
Layer 1:  V0 ———— V4
Layer 0:  V0 ———— V1
           |\     /|
           | V2 —  |
           |/      |
           V3 ———— V4

Entry point: V4

Edge lists:
  Layer 2:
    V4: []
  Layer 1:
    V0: [V4]
    V4: [V0]
  Layer 0:
    V0: [V1, V2, V3]
    V1: [V0, V2, V4]
    V2: [V0, V1, V3]
    V3: [V0, V2, V4]
    V4: [V1, V3]
```

#### Insert V5 — Sixth vector

V5 is assigned to Layer 1.

**Search phase:**

```
Layer 2:  Start at entry point V4.
          V4 is alone here. V4 → V5 = 4.1. Best found = V4. Drop down.

Layer 1:  At V4. Neighbors: [V0].
          V4 → V5 = 4.1   (current position)
          V0 → V5 = 6.7   (via V4's list — farther, don't hop)
          V4 is still the closest. No improvement. Drop down.

          But V5 IS assigned to Layer 1, so we connect here.
          Candidates on Layer 1: [V4 (4.1), V0 (6.7)]
          M=2 → Connect V5 ↔ V4  AND  V5 ↔ V0 at Layer 1.

Layer 0:  At V4. Neighbors: [V1, V3].
          V4 → V5 = 4.1   (current position)
          V1 → V5 = 5.4   (farther)
          V3 → V5 = 5.7   (farther)
          No hop. V4 is closest.

          Expand — check V1's neighbors: [V0 (6.7), V2 (5.1)].
          V2 → V5 = 5.1 — new candidate, but still farther than V4.
          Check V3's neighbors: [V0, V2] — already seen.

          All candidates: [V4 (4.1), V2 (5.1), V1 (5.4), V3 (5.7), V0 (6.7)]
          M=2 → Connect V5 ↔ V4  AND  V5 ↔ V2 at Layer 0.
```

**Check existing node limits:**

```
  V4 Layer 1: [V0, V5] = 2. OK.
  V0 Layer 1: [V4, V5] = 2. OK.
  V4 Layer 0: [V1, V3, V5] = 3. Mmax=4 → OK.
  V2 Layer 0: [V0, V1, V3, V5] = 4. Mmax=4 → OK (at the limit).
```

#### Final HNSW Graph

```
Layer 2:  V4

Layer 1:  V0 ———— V4
            \     /
             V5 —

Layer 0:  V0 ———— V1
           |\     /|
           | V2 —  |
           |/|     |
           V3 ———— V4
               \   /
                V5 (connected to V2 and V4)

Entry point: V4

Complete edge lists:
  Layer 2:
    V4: []

  Layer 1:
    V0: [V4, V5]
    V4: [V0, V5]
    V5: [V0, V4]

  Layer 0:
    V0: [V1, V2, V3]       — 3 connections
    V1: [V0, V2, V4]       — 3 connections
    V2: [V0, V1, V3, V5]   — 4 connections (at Mmax limit)
    V3: [V0, V2, V4]       — 3 connections
    V4: [V1, V3, V5]       — 3 connections
    V5: [V2, V4]           — 2 connections
```

### Searching the HNSW Graph — Worked Example

Query: **Q(5,7)** — find the nearest vector.

```
Layer 2:  Start at entry point V4(6,3).
          V4 → Q = 4.1
          V4 has no neighbors on Layer 2.
          Drop down, carrying V4 as our position.

Layer 1:  At V4. Neighbors: [V0, V5]
          V0(1,4) → Q = 5.0   (farther than V4's 4.1)
          V5(7,7) → Q = 2.0   ← closer! Hop to V5.

          At V5. Neighbors: [V0, V4]
          V0 → Q = 5.0   (farther)
          V4 → Q = 4.1   (farther)
          V5 is still the best. No improvement. Drop down.

Layer 0:  At V5. Neighbors: [V2, V4]
          V2(2,8) → Q = 3.2   (farther than V5's 2.0)
          V4(6,3) → Q = 4.1   (farther)
          No improvement.

          Expand — check V2's neighbors: [V0(5.0), V1(6.4), V3(4.5)]
          Check V4's neighbors: [V1, V3] (already considered)
          None closer than V5's 2.0.

Answer: V5 (distance 2.0)
Total distance computations: 9 (out of 6 vectors)
```

With 6 vectors the savings are minimal. But with 1 million vectors, you'd typically compute ~100-200 distances because:
- Layer 2 skips you to the right region (a few comparisons)
- Layer 1 narrows to the right neighborhood (a few more)
- Layer 0 finds the exact answer locally (a few more)

### Why HNSW Works — Summary

The layers solve the "stuck in wrong neighborhood" problem:
- **Top layers** have few nodes spread far apart → jump to the **right region** (catch a flight)
- **Middle layers** have more nodes → narrow to the **right neighborhood** (take a bus)
- **Bottom layer** has all nodes → find the **exact nearest neighbor** (walk to the house)

Without the hierarchy, a flat graph could take hundreds of hops. With the hierarchy, 3-5 layer transitions gets you there.

---

## Part 5b: IVF (Inverted File Index) — Deep Dive

### Concept 1: The Clustering Intuition

Imagine you run 100 Kubernetes clusters across the world. A user in Tokyo hits your API. You need to route them to the nearest cluster.

**Brute force:** Measure latency to all 100 clusters, pick the lowest. Works, but slow.

**Smarter approach:** You know clusters are grouped into regions — US-East, US-West, EU, Asia-Pacific. First figure out which **region** is closest (4 comparisons), then check the clusters within that region (maybe 25 comparisons). Total: 29 comparisons instead of 100.

That's exactly what IVF does with vectors. Group similar vectors into clusters ahead of time. At query time, figure out which cluster(s) the query belongs to, then only search within those clusters.

### Concept 2: What Is k-means Clustering?

IVF depends on k-means, so you need to understand this first.

**The problem:** Given a bunch of points scattered in space, group them into k clusters where each point belongs to the nearest cluster center.

**The analogy:** Imagine you're placing 4 fire stations in a city. You want each station to be in the center of the area it serves, minimizing response time for all houses.

**How k-means works — step by step with a real example:**

Let's use 8 vectors in 2D, and cluster into k=3 groups:

```
Our 8 vectors:
  A(1,1)  B(2,2)  C(1,3)       ← these are close to each other
  D(7,1)  E(8,2)               ← these are close to each other
  F(5,7)  G(6,8)  H(7,7)       ← these are close to each other

Plotted:
              G(6,8)
         F(5,7)    H(7,7)

    C(1,3)

    B(2,2)
                        E(8,2)
    A(1,1)        D(7,1)
```

#### Iteration 0 — Initialize centroids

Pick k=3 random vectors as starting centroids. Say we pick A(1,1), F(5,7), D(7,1):

```
  C1 = (1,1)    ← centroid 1 (started at A)
  C2 = (5,7)    ← centroid 2 (started at F)
  C3 = (7,1)    ← centroid 3 (started at D)
```

#### Iteration 1 — Assign + Update

**Assign:** For each vector, compute distance to all 3 centroids. Assign to the nearest:

```
  Vector   dist→C1(1,1)  dist→C2(5,7)  dist→C3(7,1)   Assigned to
  A(1,1)     0.0           7.2           6.0           C1 ✓
  B(2,2)     1.4           5.8           5.1           C1 ✓
  C(1,3)     2.0           5.7           6.3           C1 ✓
  D(7,1)     6.0           6.3           0.0           C3 ✓
  E(8,2)     7.1           5.8           1.4           C3 ✓
  F(5,7)     7.2           0.0           6.3           C2 ✓
  G(6,8)     8.6           1.4           7.1           C2 ✓
  H(7,7)     8.5           2.0           6.0           C2 ✓
```

Clusters after assignment:
```
  Cluster 1: [A(1,1), B(2,2), C(1,3)]
  Cluster 2: [F(5,7), G(6,8), H(7,7)]
  Cluster 3: [D(7,1), E(8,2)]
```

**Update:** Recompute each centroid as the mean of its members:

```
  C1 = mean(A, B, C) = ((1+2+1)/3, (1+2+3)/3) = (1.33, 2.0)
  C2 = mean(F, G, H) = ((5+6+7)/3, (7+8+7)/3) = (6.0, 7.33)
  C3 = mean(D, E)     = ((7+8)/2, (1+2)/2)     = (7.5, 1.5)
```

#### Iteration 2 — Assign + Update

**Assign** with new centroids C1(1.33, 2.0), C2(6.0, 7.33), C3(7.5, 1.5):

```
  Vector   dist→C1(1.33,2)  dist→C2(6,7.33)  dist→C3(7.5,1.5)  Assigned to
  A(1,1)     1.05              7.6               6.5              C1 ✓
  B(2,2)     0.67              5.9               5.5              C1 ✓
  C(1,3)     1.05              6.2               6.6              C1 ✓
  D(7,1)     5.8               6.4               0.7              C3 ✓
  E(8,2)     6.7               5.6               0.7              C3 ✓
  F(5,7)     6.1               1.0               5.9              C2 ✓
  G(6,8)     7.4               0.67              6.6              C2 ✓
  H(7,7)     7.5               1.1               5.5              C2 ✓
```

Same assignments as before! Centroids won't change. **Converged.**

**Final result:**

```
  Centroid 1 (1.33, 2.0)  → [A, B, C]       ← bottom-left cluster
  Centroid 2 (6.0, 7.33)  → [F, G, H]       ← top-right cluster
  Centroid 3 (7.5, 1.5)   → [D, E]          ← bottom-right cluster

  Plotted:
              G(6,8)
         F(5,7) ★C2 H(7,7)       ★ = centroid

    C(1,3)
   ★C1
    B(2,2)
                        E(8,2)
    A(1,1)        D(7,1) ★C3
```

Each centroid sits at the "center of gravity" of its cluster.

### Concept 3: Inverted Lists — The Data Structure

After clustering, IVF stores vectors in **inverted lists** — one list per cluster. This is why it's called "Inverted File."

Think of it like a warehouse with labeled bins:

```
  Bin 1 (centroid at 1.33, 2.0):  [A, B, C]     ← vectors + their IDs
  Bin 2 (centroid at 6.0, 7.33):  [F, G, H]
  Bin 3 (centroid at 7.5, 1.5):   [D, E]

  Also stored: the centroid table
  [C1(1.33, 2.0),  C2(6.0, 7.33),  C3(7.5, 1.5)]
```

The centroid table is small (just k vectors) and fits in memory. The inverted lists hold the actual vectors, grouped by cluster.

### How IVF Search Works

A query arrives: **Q(6,6)**. Find the nearest vector.

**Step 1 — Compare Q to all centroids** (only k=3 comparisons):

```
  Q(6,6) → C1(1.33, 2.0) = 5.9
  Q(6,6) → C2(6.0, 7.33) = 1.33   ← closest!
  Q(6,6) → C3(7.5, 1.5)  = 4.7
```

**Step 2 — Search within the closest cluster(s):**

With nprobe=1 (search only the 1 nearest cluster):

```
  Search Cluster 2: [F(5,7), G(6,8), H(7,7)]

  Q(6,6) → F(5,7) = 1.4
  Q(6,6) → G(6,8) = 2.0
  Q(6,6) → H(7,7) = 1.4

  Best: F or H (tied at 1.4)
```

**Total comparisons: 3 (centroids) + 3 (cluster members) = 6**, instead of 8 for brute force.

### The nprobe Parameter — Why It Matters

What if the actual nearest vector is in a **neighboring cluster**? With nprobe=1, we'd miss it.

Example: Query **Q(6,3)** — this sits right between Cluster 2 and Cluster 3:

```
  Q(6,3) → C1(1.33, 2.0) = 4.8
  Q(6,3) → C2(6.0, 7.33) = 4.3
  Q(6,3) → C3(7.5, 1.5)  = 2.1   ← closest centroid
```

With nprobe=1, we only search Cluster 3: [D(7,1), E(8,2)]

```
  Q(6,3) → D(7,1) = 2.2
  Q(6,3) → E(8,2) = 2.2
  Answer: D or E (dist 2.2)
```

But look at Cluster 2: F(5,7) is at distance 4.1, and H(7,7) is at 4.1. Those are farther, so nprobe=1 was fine here.

Now try **Q(6,5)** — even more between the clusters:

```
  Q(6,5) → C2(6.0, 7.33) = 2.3
  Q(6,5) → C3(7.5, 1.5)  = 3.8

  nprobe=1 → search Cluster 2: [F(5,7), G(6,8), H(7,7)]
    F(5,7) → Q = 2.2
    G(6,8) → Q = 3.0
    H(7,7) → Q = 2.2
    Answer: F or H (dist 2.2)

  But what about Cluster 3?
    D(7,1) → Q = 4.1
    E(8,2) → Q = 3.6
    These are farther. nprobe=1 was fine again.
```

The risk is when the true nearest neighbor is in an adjacent cluster. **nprobe=2 or nprobe=3** checks multiple clusters to catch border cases:

```
nprobe=1:  Check 1 cluster.  Fast. Might miss border cases.
nprobe=2:  Check 2 clusters. Slower. Catches most border cases.
nprobe=k:  Check all clusters. Same as brute force. 100% recall.
```

**The tradeoff is linear:** doubling nprobe roughly doubles search time but improves recall. In practice, nprobe = 5-20 out of thousands of clusters gives excellent results.

### Scaling to Real Numbers

```
1 million vectors, 1536 dimensions, nlist=1000 clusters:

Brute force:   1,000,000 distance computations per query
IVF nprobe=1:  1,000 (centroids) + ~1,000 (one cluster) = 2,000 → 500x faster
IVF nprobe=10: 1,000 (centroids) + ~10,000 (ten clusters) = 11,000 → 90x faster

10 million vectors, nlist=3162 (sqrt of 10M):
Brute force:   10,000,000 per query
IVF nprobe=10: 3,162 + ~31,620 = ~35,000 → 280x faster
```

### How Many Clusters? Choosing nlist

```
Rule of thumb:
  nlist = sqrt(N)  to  4 * sqrt(N)

  1M vectors   → nlist = 1,000 to 4,000
  10M vectors  → nlist = 3,162 to 12,649
  100M vectors → nlist = 10,000 to 40,000

Too few clusters (nlist=10 for 1M vectors):
  Each cluster has ~100K vectors → searching one cluster is still slow

Too many clusters (nlist=100K for 1M vectors):
  Each cluster has ~10 vectors → centroids dominate search cost
  Also, k-means training with 100K centroids is very slow

Sweet spot: each cluster has ~1,000 to ~10,000 vectors
```

### IVF Build Cost

The expensive part is **k-means training**, not the final assignment.

```
k-means cost: O(n × k × iterations × dimensions)

Example: 1M vectors, k=1000, 20 iterations, 1536 dims
  = 1,000,000 × 1,000 × 20 × 1,536 floating-point ops
  ≈ very roughly a few minutes on modern hardware

Optimization: You don't need all vectors for training.
  Sample 50,000-100,000 vectors, run k-means on the sample,
  then assign all 1M vectors to the resulting centroids.
  This makes training much faster with minimal quality loss.
```

### IVF vs. HNSW — When to Use Which

| Aspect | IVF | HNSW |
|---|---|---|
| **Memory** | Low (just centroids + vectors) | High (vectors + graph edges) |
| **Build time** | Moderate (k-means) | Slow (graph construction) |
| **Query speed** | Fast | Faster |
| **Recall at same speed** | Lower (~95%) | Higher (~99%) |
| **Supports adding vectors** | Easy (assign to cluster) | Easy (insert into graph) |
| **Supports deleting vectors** | Easy (remove from list) | Hard (graph edges become stale) |
| **Best for** | Memory-constrained, large scale | Quality-critical, latency-critical |

---

## Part 5c: PQ (Product Quantization) — Deep Dive

### The Problem: Vectors Are Memory Hogs

Before understanding PQ, you need to feel the pain it solves.

A single vector from a typical embedding model:
```
1536 dimensions × 4 bytes per float = 6,144 bytes = 6 KB per vector
```

Scale that up:
```
1 million vectors:    6 KB × 1M   =  6 GB
10 million vectors:   6 KB × 10M  = 60 GB
100 million vectors:  6 KB × 100M = 600 GB
1 billion vectors:    6 KB × 1B   = 6 TB
```

HNSW and IVF both store the full vectors. At 100M+ vectors, you either need a massive machine or you shard across many nodes. Both are expensive.

**PQ asks:** Can we compress each vector from 6 KB to something much smaller, while still being able to compute approximate distances?

### Concept 1: Why Not Just Round the Numbers?

The simplest compression: reduce precision. Instead of 32-bit floats, use 8-bit integers.

```
Original:  [0.1234, -0.4567, 0.7891]   ← 4 bytes each
Rounded:   [0.12, -0.46, 0.79]          ← still need floats
Int8:      [31, -117, 202]              ← 1 byte each (after scaling)
```

This is called **scalar quantization**. It gives 4x compression (32-bit → 8-bit). Better than nothing, but:
- 1B vectors: 6 TB → 1.5 TB. Still huge.
- Quality loss is spread evenly across all dimensions — not ideal.

**PQ does something fundamentally different.** Instead of compressing individual numbers, it compresses *groups of dimensions* using learned patterns.

### Concept 2: The Dictionary Analogy

Imagine you're compressing text messages. You notice people send similar phrases repeatedly:

```
Message 1: "Hey, how are you? Want to grab lunch?"
Message 2: "Hi, how's it going? Want to get coffee?"
Message 3: "Hey, how are you? Want to get coffee?"
```

Instead of storing each message character by character, you build a **dictionary of common phrases**:

```
Dictionary:
  Phrase 0: "Hey, how are you?"
  Phrase 1: "Hi, how's it going?"
  Phrase 2: "Want to grab lunch?"
  Phrase 3: "Want to get coffee?"
```

Now compress:
```
Message 1: [Phrase 0, Phrase 2]  → stored as [0, 2]  (2 bytes)
Message 2: [Phrase 1, Phrase 3]  → stored as [1, 3]  (2 bytes)
Message 3: [Phrase 0, Phrase 3]  → stored as [0, 3]  (2 bytes)
```

Each message is now 2 bytes instead of ~40 characters. The dictionary itself is small and shared.

**PQ does exactly this, but with sub-vectors instead of phrases.** It splits each vector into segments, builds a dictionary (codebook) of common patterns for each segment, and replaces each segment with its dictionary ID.

### Concept 3: Splitting Vectors into Segments

A 1536-dimensional vector is too complex to build a dictionary for directly. But if you split it into smaller pieces, each piece is manageable.

```
Original vector (1536 dims):
[d0, d1, d2, ... d191 | d192, d193, ... d383 | ... | d1344, d1345, ... d1535]
 ←── segment 0 ──→    ←── segment 1 ──→           ←── segment 7 ──→

Split into m=8 segments of 192 dimensions each.
```

Now each segment is a 192-dimensional mini-vector. You can build a separate dictionary for each segment position.

**Why this works:** Dimensions within a segment tend to have correlated patterns. The model might use dimensions 0-191 to capture one aspect of meaning and 192-383 for another. Patterns within each segment repeat across vectors, making them compressible.

### Terminology Guide — Segment, Group, Centroid, Codebook, Code

These terms build on each other in a specific order:

```
Step 1 — SEGMENT (m total)
  Split the original vector into m slices.
  1536 dims, m=8 → each segment is 192 dims.
  A segment is just a piece of the vector.

Step 2 — GROUP (k groups per segment)
  For each segment position, take that segment from ALL vectors in the DB
  and cluster them using k-means into k groups.
  k=256 means 256 groups of similar segment values.

Step 3 — CENTROID (one per group)
  Each group has one centroid — the average of all segment values in
  that group. The centroid has (total_dims / m) dimensions.
  For 1536 dims, m=8: each centroid is 192 dims.

Step 4 — CODEBOOK (one per segment = m total)
  A codebook is simply the complete list of centroids for one segment.
  Codebook 0 = all 256 centroids for segment 0.
  Codebook 1 = all 256 centroids for segment 1.
  It's a lookup table: given a number, return the centroid.
  Think: codebook = the dictionary, centroids = the dictionary entries.

Step 5 — CODE (one per segment per vector)
  When encoding a vector, you compare each segment to the centroids in
  the corresponding codebook and find the nearest one. The CODE is the
  ID number (0 to 255) of that nearest centroid.
  Think: code = the row number in the codebook lookup table.
  An encoded vector = m codes = m bytes (one byte per segment).
```

**Visual of the relationship:**

```
┌──────────────────────────────────────────────────────────────┐
│                       PQ STRUCTURE                            │
│                                                              │
│  Codebook 0          Codebook 1         ...   Codebook 7     │
│  (for segment 0)     (for segment 1)          (segment 7)    │
│  ┌──────────────┐   ┌──────────────┐         ┌────────────┐ │
│  │Code 0: [...]  │   │Code 0: [...]  │         │Code 0: [..]│ │
│  │Code 1: [...]  │   │Code 1: [...]  │         │Code 1: [..]│ │
│  │Code 2: [...]  │   │Code 2: [...]  │         │Code 2: [..]│ │
│  │  ...          │   │  ...          │         │  ...       │ │
│  │Code 255:[...] │   │Code 255:[...] │         │Code 255:[.]│ │
│  └──────────────┘   └──────────────┘         └────────────┘ │
│                                                              │
│  Each [...] is a centroid with (total_dims / m) dimensions   │
│  Each Code is just the row number (0 to 255)                 │
│  Each Codebook is just the lookup table for one segment      │
│                                                              │
│  Encoded vector = [code_from_CB0, code_from_CB1, ...,        │
│                    code_from_CB7]                             │
│                 = [42, 187, 3, 201, 99, 55, 128, 12]         │
│                   (8 bytes total — one byte per code)         │
│                                                              │
│  To decode: look up Codebook 0 entry 42 → 192-dim centroid   │
│             look up Codebook 1 entry 187 → 192-dim centroid  │
│             concatenate all 8 → approximate 1536-dim vector  │
└──────────────────────────────────────────────────────────────┘
```

**In plain terms:**
- **Segment** = a slice of the vector
- **Group** = a cluster of similar segment values (from k-means)
- **Centroid** = the center of a group (what the group is represented by)
- **Codebook** = the full list of centroids for one segment (the lookup table)
- **Code** = the row number in that lookup table (the address of the nearest centroid)

### Why 256⁸ combinations from only 2,048 centroids

Each encoded vector has 8 codes, and each code can independently be any value from 0 to 255. The total number of possible encoded vectors is a **Cartesian product** of the codebooks:

```
Segment 0: 256 choices  ─┐
Segment 1: 256 choices   │
Segment 2: 256 choices   │
Segment 3: 256 choices   ├──→ 256 × 256 × 256 × 256 × 256 × 256 × 256 × 256
Segment 4: 256 choices   │    = 256⁸ = 2⁶⁴ ≈ 1.8 × 10¹⁹ combinations
Segment 5: 256 choices   │
Segment 6: 256 choices   │
Segment 7: 256 choices  ─┘

But you only STORE 8 × 256 = 2,048 centroids.
```

**Analogy:** A combination lock with 8 dials, each with 256 positions. The lock has 256⁸ possible combinations, but the lock itself only has 8 × 256 = 2,048 physical notches. The exponential explosion comes from the **independence** of each dial — the choices multiply, not add.

### PQ Construction — Full Walkthrough

Let me use a small concrete example. 6 vectors in **4 dimensions**, split into **m=2 segments** of 2 dims each, with **k=2 centroids** per codebook (in practice k=256, but k=2 keeps the math visible).

**Our 6 vectors:**

```
V0 = (1, 2, 8, 9)
V1 = (2, 1, 2, 1)
V2 = (1, 3, 7, 8)
V3 = (8, 7, 8, 7)
V4 = (9, 8, 1, 2)
V5 = (7, 9, 7, 9)
```

#### Step 1 — Split every vector into segments

```
              Segment 0 (dims 0-1)    Segment 1 (dims 2-3)
V0 (1,2,8,9):     (1, 2)                  (8, 9)
V1 (2,1,2,1):     (2, 1)                  (2, 1)
V2 (1,3,7,8):     (1, 3)                  (7, 8)
V3 (8,7,8,7):     (8, 7)                  (8, 7)
V4 (9,8,1,2):     (9, 8)                  (1, 2)
V5 (7,9,7,9):     (7, 9)                  (7, 9)
```

Now we have two piles of 2D mini-vectors — one pile per segment position.

#### Step 2 — Build a codebook for each segment (k-means)

**Codebook for Segment 0** — cluster the 6 seg-0 mini-vectors into k=2 groups:

```
Seg-0 values: (1,2), (2,1), (1,3), (8,7), (9,8), (7,9)

These naturally form 2 groups:
  Low group:  (1,2), (2,1), (1,3)  → centroid = (1.33, 2.0)
  High group: (8,7), (9,8), (7,9)  → centroid = (8.0, 8.0)

Codebook 0:
  Code 0 → centroid (1.33, 2.0)    ← represents "low" segment-0 values
  Code 1 → centroid (8.0, 8.0)     ← represents "high" segment-0 values
```

**Codebook for Segment 1** — cluster the 6 seg-1 mini-vectors into k=2 groups:

```
Seg-1 values: (8,9), (2,1), (7,8), (8,7), (1,2), (7,9)

Two groups:
  Low group:  (2,1), (1,2)          → centroid = (1.5, 1.5)
  High group: (8,9), (7,8), (8,7), (7,9) → centroid = (7.5, 8.25)

Codebook 1:
  Code 0 → centroid (1.5, 1.5)     ← represents "low" segment-1 values
  Code 1 → centroid (7.5, 8.25)    ← represents "high" segment-1 values
```

**These codebooks are the learned dictionaries.** They're small and shared across all vectors.

#### Step 3 — Encode each vector

For each vector, replace each segment with its nearest codebook entry:

```
V0 = (1,2 | 8,9)
  Seg 0: (1,2) → nearest to Code 0 (1.33,2.0) dist=0.4  vs Code 1 (8.0,8.0) dist=9.2  → Code 0
  Seg 1: (8,9) → nearest to Code 0 (1.5,1.5) dist=9.7   vs Code 1 (7.5,8.25) dist=0.9  → Code 1
  Encoded: [0, 1]

V1 = (2,1 | 2,1)
  Seg 0: (2,1) → Code 0 (dist 1.2)  vs Code 1 (dist 8.6)  → Code 0
  Seg 1: (2,1) → Code 0 (dist 0.7)  vs Code 1 (dist 8.9)  → Code 0
  Encoded: [0, 0]

V2 = (1,3 | 7,8)
  Seg 0: (1,3) → Code 0 (dist 1.1)  vs Code 1 (dist 8.6)  → Code 0
  Seg 1: (7,8) → Code 0 (dist 8.3)  vs Code 1 (dist 0.6)  → Code 1
  Encoded: [0, 1]

V3 = (8,7 | 8,7)
  Seg 0: (8,7) → Code 0 (dist 8.0)  vs Code 1 (dist 1.0)  → Code 1
  Seg 1: (8,7) → Code 0 (dist 8.2)  vs Code 1 (dist 1.4)  → Code 1
  Encoded: [1, 1]

V4 = (9,8 | 1,2)
  Seg 0: (9,8) → Code 0 (dist 9.7)  vs Code 1 (dist 1.0)  → Code 1
  Seg 1: (1,2) → Code 0 (dist 0.7)  vs Code 1 (dist 8.8)  → Code 0
  Encoded: [1, 0]

V5 = (7,9 | 7,9)
  Seg 0: (7,9) → Code 0 (dist 8.6)  vs Code 1 (dist 1.4)  → Code 1
  Seg 1: (7,9) → Code 0 (dist 9.3)  vs Code 1 (dist 0.9)  → Code 1
  Encoded: [1, 1]
```

**Summary of encoded vectors:**

```
V0: [0, 1]    (was 4 floats = 16 bytes, now 2 bytes)
V1: [0, 0]
V2: [0, 1]
V3: [1, 1]
V4: [1, 0]
V5: [1, 1]
```

**Compression: 16 bytes → 2 bytes = 8x smaller.**

Notice V0 and V2 have the same code [0, 1]. Their seg-0 parts are similar — (1,2) vs (1,3) — and their seg-1 parts are similar — (8,9) vs (7,8). PQ can't distinguish them anymore. This is the **lossy** nature of PQ — like how JPEG can't distinguish two slightly different shades of blue.

In practice with k=256 centroids (instead of k=2), each codebook has 256 entries, giving much finer-grained representation.

#### Step 4 — What's actually stored

```
Codebook 0 (shared, small):
  Code 0: (1.33, 2.0)
  Code 1: (8.0, 8.0)

Codebook 1 (shared, small):
  Code 0: (1.5, 1.5)
  Code 1: (7.5, 8.25)

Encoded vectors (one per vector, tiny):
  V0: [0, 1]
  V1: [0, 0]
  V2: [0, 1]
  V3: [1, 1]
  V4: [1, 0]
  V5: [1, 1]
```

### How PQ Distance Search Works — The Clever Trick

A query arrives: **Q = (2, 3, 7, 8)**. Find the nearest vector.

**Naive approach:** Decompress each vector (replace codes with centroids), then compute distances. This works but defeats the speed purpose.

**PQ's trick: Asymmetric Distance Computation (ADC).**

The key insight: the **query is NOT compressed**. Only the stored vectors are compressed. You use the full-precision query against the compressed vectors.

#### Step 1 — Split the query into segments

```
Q = (2, 3, 7, 8)
  Q segment 0: (2, 3)
  Q segment 1: (7, 8)
```

#### Step 2 — Build a distance lookup table

Precompute the **squared distance** from each query segment to every centroid in that segment's codebook:

```
Segment 0 — Q_seg0 = (2, 3):
  → Codebook 0, Code 0 (1.33, 2.0):  (2-1.33)² + (3-2.0)²   = 0.45 + 1.0   = 1.45
  → Codebook 0, Code 1 (8.0, 8.0):   (2-8.0)²  + (3-8.0)²   = 36.0 + 25.0  = 61.0

Segment 1 — Q_seg1 = (7, 8):
  → Codebook 1, Code 0 (1.5, 1.5):   (7-1.5)²  + (8-1.5)²   = 30.25 + 42.25 = 72.5
  → Codebook 1, Code 1 (7.5, 8.25):  (7-7.5)²  + (8-8.25)²  = 0.25 + 0.0625 = 0.31

Lookup table:
  Segment 0: { Code 0: 1.45,  Code 1: 61.0 }
  Segment 1: { Code 0: 72.5,  Code 1: 0.31 }
```

This table has m × k entries. In our example: 2 segments × 2 codes = 4 entries.
In practice: 8 segments × 256 codes = 2,048 entries. Tiny, fits in CPU cache.

#### Step 3 — Compute approximate distances using table lookups

For each stored vector, the approximate distance is just **the sum of table lookups**:

```
V0 [0, 1]:  table[seg0][code 0] + table[seg1][code 1] = 1.45 + 0.31  =  1.76
V1 [0, 0]:  table[seg0][code 0] + table[seg1][code 0] = 1.45 + 72.5  = 73.95
V2 [0, 1]:  table[seg0][code 0] + table[seg1][code 1] = 1.45 + 0.31  =  1.76
V3 [1, 1]:  table[seg0][code 1] + table[seg1][code 1] = 61.0 + 0.31  = 61.31
V4 [1, 0]:  table[seg0][code 1] + table[seg1][code 0] = 61.0 + 72.5  = 133.5
V5 [1, 1]:  table[seg0][code 1] + table[seg1][code 1] = 61.0 + 0.31  = 61.31

Ranking: V0/V2 (1.76) < V3/V5 (61.31) < V1 (73.95) < V4 (133.5)
Answer: V0 or V2 (tied — PQ can't tell them apart)
```

**Each distance computation was just 2 table lookups + 1 addition.** In practice with m=8 segments: 8 lookups + 7 additions per vector. Compared to a full distance computation (1536 multiplications + 1535 additions), this is ~100x fewer operations.

#### Verification: How close is the approximation?

Let's check actual squared distances from Q(2,3,7,8):

```
V0 (1,2,8,9):  (2-1)² + (3-2)² + (7-8)² + (8-9)² = 1+1+1+1     =  4.0
V1 (2,1,2,1):  (2-2)² + (3-1)² + (7-2)² + (8-1)² = 0+4+25+49    = 78.0
V2 (1,3,7,8):  (2-1)² + (3-3)² + (7-7)² + (8-8)² = 1+0+0+0      =  1.0  ← true nearest
V3 (8,7,8,7):  (2-8)² + (3-7)² + (7-8)² + (8-7)² = 36+16+1+1    = 54.0
V4 (9,8,1,2):  (2-9)² + (3-8)² + (7-1)² + (8-2)² = 49+25+36+36  = 146.0
V5 (7,9,7,9):  (2-7)² + (3-9)² + (7-7)² + (8-9)² = 25+36+0+1    = 62.0

True ranking:  V2 (1.0) < V0 (4.0) < V3 (54.0) < V5 (62.0) < V1 (78.0) < V4 (146.0)
PQ ranking:    V0/V2 (1.76) < V3/V5 (61.31) < V1 (73.95) < V4 (133.5)
```

PQ correctly identified V0 and V2 as the nearest (tied because they share the same code). The overall ranking is preserved. The absolute distances differ (1.76 vs 1.0/4.0) but the **ordering** is close, which is what matters for search.

With k=256 instead of k=2, V0 and V2 would likely get different codes and PQ could distinguish them.

### Why "Product" Quantization?

The name comes from the fact that the total codebook is the **Cartesian product** of all sub-codebooks.

```
With m=2 segments and k=2 codes each:
  Total possible codes: 2 × 2 = 4 combinations
  [0,0], [0,1], [1,0], [1,1]

With m=8 segments and k=256 codes each:
  Total possible codes: 256⁸ ≈ 1.8 × 10¹⁹ combinations
  But only need to store: 8 × 256 = 2,048 centroids
```

You get an astronomically large "effective codebook" (10¹⁹ possible representations) while only storing 2,048 centroids. This is the power of the product structure.

### Real-World PQ Numbers

```
Typical config: 1536 dims, m=8 segments, k=256 codes (8-bit)

Per-vector storage:
  Original:  1536 × 4 bytes = 6,144 bytes
  PQ:        8 codes × 1 byte = 8 bytes
  Compression: 768x

Codebook storage (shared, one copy):
  8 codebooks × 256 centroids × 192 dims × 4 bytes = 1.5 MB

Memory for 1 billion vectors:
  Original:  6,144 GB (6 TB)
  PQ:        8 GB + 1.5 MB codebook ≈ 8 GB
  Fits on a single machine.

Search speed per vector:
  Original:  1536 multiplies + 1535 adds = 3,071 operations
  PQ (ADC):  8 lookups + 7 adds = 15 operations
  ~200x fewer operations per vector
```

### Tradeoff: Compression vs. Accuracy

```
More segments (larger m):
  More codes per vector → less compression → better accuracy
  m=8:  8 bytes per vector, moderate accuracy
  m=16: 16 bytes per vector, better accuracy
  m=32: 32 bytes per vector, good accuracy (but less compression benefit)

More centroids (larger k):
  Finer codebook → better accuracy → more memory for codebooks
  k=16 (4-bit):   very coarse, fast training
  k=256 (8-bit):  standard, good balance     ← most common
  k=1024 (10-bit): finer, slower training, slightly better

Fewer/smaller segments:
  More compression but lower recall.
  Think of it like JPEG quality slider:
    Low quality  (m=4, k=64):   4 bytes/vector, ~85% recall
    Medium       (m=8, k=256):  8 bytes/vector, ~90% recall
    High quality (m=16, k=256): 16 bytes/vector, ~95% recall
```

---

## Part 5d: IVF-PQ — The Combination

In practice, IVF and PQ are combined. IVF narrows the search space (check only relevant clusters), and PQ compresses the vectors within each cluster so they fit in memory.

### How IVF-PQ Works

**Build phase:**

```
Step 1: Run IVF clustering (k-means on full vectors)
  → Each vector is assigned to a cluster

Step 2: Compute residuals
  For each vector, subtract its cluster centroid:
    residual = vector - centroid

  Why? The centroid captures the "coarse" location. The residual
  captures the "fine" detail within the cluster. Residuals are
  smaller in magnitude and easier to quantize accurately.

  Analogy: GPS coordinates.
    Full vector = "37.7749° N, 122.4194° W" (San Francisco)
    Centroid    = "37.77° N, 122.42° W" (neighborhood center)
    Residual    = "+0.0049°, +0.0006°" (offset from center)
    The residual is smaller and needs less precision.

Step 3: Train PQ codebooks on the residuals

Step 4: Encode each residual with PQ
```

**Query phase:**

```
Step 1: Find nearest nprobe centroids (IVF step — fast)
Step 2: For each centroid, compute query residual:
          query_residual = query - centroid
Step 3: Build PQ lookup table for this residual
Step 4: Use table lookups to scan vectors in the cluster (PQ step — fast)
Step 5: Return top results across all probed clusters
```

**Memory for 1 billion vectors with IVF-PQ:**

```
Without PQ:  1B × 6,144 bytes = 6 TB        ← needs a cluster of machines
With IVF-PQ: 1B × 8 bytes + codebooks + centroids ≈ 8 GB  ← one machine
```

### When to Use Each

```
< 100K vectors:     Brute force (flat index). Fast enough, 100% recall.
100K - 1M vectors:  HNSW. Best recall, acceptable memory.
1M - 10M vectors:   HNSW or IVF. HNSW if memory allows, IVF if constrained.
10M - 100M vectors: IVF-PQ or HNSW with quantization. Memory becomes the driver.
100M+ vectors:      IVF-PQ. Only option that fits in reasonable memory.
1B+ vectors:        Sharded IVF-PQ across multiple nodes.
```

---

## Part 6: Vector Database Landscape — Deep Dive

### What a Vector Database Actually Does

A vector database is not just "a database that stores arrays." It must handle:

1. **Store** vectors with associated metadata and original content
2. **Index** vectors for fast approximate search (HNSW, IVF, etc.)
3. **Search** by similarity (nearest neighbor queries)
4. **Filter** results by metadata (e.g., "nearest to X where category = 'runbook'")
5. **CRUD** operations — insert, update, delete vectors while keeping the index consistent

The hard part isn't storage — it's maintaining a fast, correct index as data changes.

### Architecture Patterns

```
Pattern 1: Embedded (library)
  Your app process ←→ [Vector library in-process]
  Examples: Chroma, FAISS, Annoy
  Like: SQLite

  Pros: Zero ops, no network hop, fast prototyping
  Cons: Single process, no concurrent access, limited scale

Pattern 2: Client-Server
  Your app ←→ [Network] ←→ [Vector DB server]
  Examples: Qdrant, Milvus, Weaviate
  Like: PostgreSQL, MySQL

  Pros: Concurrent access, independent scaling, replication
  Cons: Network latency, ops overhead, another service to manage

Pattern 3: Extension on existing DB
  Your app ←→ [Network] ←→ [PostgreSQL + pgvector]
  Examples: pgvector, Oracle 23ai AI Vector Search
  Like: PostGIS (spatial extension for Postgres)

  Pros: No new infrastructure, existing backups/HA/monitoring work,
        can JOIN vectors with relational data in one query
  Cons: Not optimized purely for vector workloads, may lag on
        cutting-edge features

Pattern 4: Managed SaaS
  Your app ←→ [Network] ←→ [Vendor's cloud service]
  Examples: Pinecone, MongoDB Atlas Vector Search
  Like: RDS, Cloud SQL

  Pros: Zero ops, auto-scaling, built-in monitoring
  Cons: Vendor lock-in, data leaves your network, cost at scale
```

### Dedicated Vector Databases — Details

| DB | Language | Index Types | Hybrid Search | Deployment | Notable Feature |
|---|---|---|---|---|---|
| **Pinecone** | Closed | Proprietary | Yes | SaaS only | Serverless tier, simplest to start |
| **Weaviate** | Go | HNSW | Yes (BM25 + vector) | Self-host or Cloud | GraphQL API, multi-modal (text + image) |
| **Milvus** | Go/C++ | HNSW, IVF, PQ, DiskANN | Yes | Self-host or Zilliz Cloud | CNCF project, GPU-accelerated, scales to billions |
| **Qdrant** | Rust | HNSW | Yes (sparse + dense) | Self-host or Cloud | Rust performance, rich filtering, payload indexes |
| **Chroma** | Python | HNSW (via hnswlib) | No | Embedded or client-server | Simplest API, great for prototyping |

### Vector Extensions on Existing Databases — Details

| DB | Extension | Index Types | Hybrid | Why Choose It |
|---|---|---|---|---|
| **PostgreSQL** | `pgvector` | HNSW, IVF | Yes (with `tsvector`) | Already run Postgres, want JOINs with relational data |
| **Oracle 23ai** | AI Vector Search | HNSW, IVF | Yes (with Oracle Text) | Already on Oracle, want vectors + full-text in one query |
| **Redis** | Redis Stack | HNSW, Flat | Yes | Need sub-millisecond latency, already run Redis |
| **Elasticsearch** | Dense vector field | HNSW | Yes (BM25 + kNN) | Already run ES for logging, want to add semantic search |
| **MongoDB** | Atlas Vector Search | HNSW-like | Yes (with Atlas Search) | Already on Atlas, want vectors near your documents |

### pgvector — A Closer Look (Since You Know Postgres)

pgvector adds a `vector` data type and operators to PostgreSQL.

```sql
-- Enable extension
CREATE EXTENSION vector;

-- Create table with a vector column
CREATE TABLE documents (
  id         SERIAL PRIMARY KEY,
  content    TEXT,
  metadata   JSONB,
  embedding  vector(1536)    -- 1536-dimensional vector
);

-- Insert a vector
INSERT INTO documents (content, metadata, embedding)
VALUES (
  'How to scale the ingestion service',
  '{"type": "runbook", "team": "platform"}',
  '[0.023, -0.187, 0.445, ...]'   -- 1536 floats
);

-- Create HNSW index
CREATE INDEX ON documents
  USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 200);

-- Search: find 5 nearest vectors
SELECT content, metadata,
       embedding <=> '[0.1, -0.2, ...]'::vector AS distance
FROM documents
ORDER BY embedding <=> '[0.1, -0.2, ...]'::vector
LIMIT 5;

-- Hybrid search: vector similarity + metadata filter
SELECT content,
       embedding <=> '[0.1, -0.2, ...]'::vector AS distance
FROM documents
WHERE metadata->>'type' = 'runbook'
ORDER BY embedding <=> '[0.1, -0.2, ...]'::vector
LIMIT 5;

-- Hybrid search: vector + full-text keyword search
SELECT content,
       embedding <=> query_embedding AS vector_distance,
       ts_rank(to_tsvector(content), to_tsquery('crashloop & pod')) AS text_rank
FROM documents
WHERE to_tsvector(content) @@ to_tsquery('crashloop & pod')
ORDER BY embedding <=> query_embedding
LIMIT 10;
```

**pgvector operators:**
```
<=>  Cosine distance
<->  L2 (Euclidean) distance
<#>  Negative inner product
```

**Why pgvector is often the right starting point:**
- You already know Postgres (backups, replication, monitoring, HA)
- Vectors live alongside your relational data — no separate system to sync
- Standard SQL — JOIN vectors with users, tags, permissions
- HNSW index performance is competitive with dedicated vector DBs for < 10M vectors

### How to Choose — Decision Framework

```
                              ┌─────────────────────┐
                              │ How many vectors?    │
                              └─────────┬───────────┘
                                        │
                          ┌─────────────┼─────────────┐
                          │             │             │
                      < 1M          1M-100M        > 100M
                          │             │             │
                    ┌─────┴─────┐   ┌───┴────┐   ┌───┴────┐
                    │ Already   │   │ Memory │   │ Must   │
                    │ run PG?   │   │ OK?    │   │ shard  │
                    └─────┬─────┘   └───┬────┘   └───┬────┘
                     Y/       \N     Y/     \N       │
                    │         │     │       │        │
                 pgvector   Chroma  HNSW    IVF-PQ   Milvus
                             or    (Qdrant, (Milvus) or
                           Qdrant  Milvus)           Pinecone

Cross-cutting concerns:
  Need hybrid search?        → Weaviate, Elasticsearch, pgvector+tsvector
  Need GPU acceleration?     → Milvus (supports GPU indexing)
  Need multi-tenancy?        → Qdrant (native), Pinecone (namespaces)
  Want zero ops?             → Pinecone, Chroma (embedded)
  On Oracle ecosystem?       → Oracle 23ai AI Vector Search
```

---

## Part 7: The Search Pipeline — Deep Dive

The search pipeline has two halves: **ingestion** (getting documents in) and **query** (getting answers out). Both matter, but ingestion determines 80% of search quality. You could have the best HNSW index in the world — if your chunks are garbage, the vectors will be garbage, and no search algorithm can recover from bad vectors.

**The analogy:** Think of it like building a library. Ingestion is how you organize books on shelves (by topic? alphabetically? randomly?). Search is how you find a book when someone asks. If books are randomly shelved with pages ripped out and chapters mixed together, even the smartest librarian can't find what you need. But if books are cleanly organized by topic with a good index card system, even a simple search finds the right book fast.

### The Full Ingestion Pipeline

```
┌──────────────────────────────────────────────────────────┐
│                    INGESTION PIPELINE                     │
│                                                          │
│  Raw Sources                                             │
│  ├── Confluence pages                                    │
│  ├── Runbooks (Markdown)                                 │
│  ├── Slack threads                                       │
│  ├── Incident postmortems                                │
│  ├── Code comments / READMEs                             │
│  └── Jira / Linear tickets                               │
│         │                                                │
│         v                                                │
│  [1. EXTRACT]  Parse raw content → plain text            │
│         │       Strip HTML, parse Markdown, extract       │
│         │       from PDF, handle code blocks              │
│         v                                                │
│  [2. CLEAN]    Remove boilerplate, headers, footers      │
│         │       Normalize whitespace, fix encoding        │
│         v                                                │
│  [3. CHUNK]    Split into passages (the critical step)   │
│         │                                                │
│         v                                                │
│  [4. ENRICH]   Add metadata to each chunk                │
│         │       source_url, author, date, section_title,  │
│         │       document_type, team                       │
│         v                                                │
│  [5. EMBED]    Convert each chunk to a vector            │
│         │       (batch API calls for efficiency)          │
│         v                                                │
│  [6. STORE]    Write to vector DB                        │
│         │       vector + metadata + original text         │
│         v                                                │
│  [7. INDEX]    Build/update ANN index                    │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### Step-by-Step Walkthrough With a Real Document

To make this concrete, let's trace a real runbook through all 7 steps:

```
Title: Ingestion Service — Troubleshooting Guide
Team: Platform
Last Updated: 2024-12-15

## Overview
The ingestion service reads events from Kafka and writes to PostgreSQL.
It processes ~2M events/day across 8 partitions.

## Common Failure: OOM Kill
When the service exceeds its 4GB memory limit, Kubernetes OOM-kills it.
This usually happens when batch sizes exceed 5000 events.

To fix:
1. Check current batch size: kubectl get cm ingestion-config -o yaml
2. Reduce BATCH_SIZE to 1000
3. If still OOM, increase memory limit in values.yaml to 6GB

## Common Failure: Kafka Consumer Lag
When the consumer group falls behind, lag increases.
Root causes:
- Slow downstream DB writes (check pg_stat_activity for locks)
- Too few consumer replicas (should equal partition count)
- Poison pill messages blocking processing

## Deployment
Helm chart: platform-services/ingestion
Replicas: 8 (must match Kafka partition count)
Memory: 4GB request, 6GB limit
CPU: 500m request, 2 cores limit
```

#### Step 1: EXTRACT — Raw Content to Plain Text

Strips the source format and produces clean text.

```
Input:  Confluence page (HTML with macros, CSS, navigation chrome)
Output: Plain text with structure preserved

What gets stripped:
  - HTML tags (<div>, <span>, <p>)
  - Confluence macros ({expand}, {code}, {panel})
  - Navigation elements (sidebar, breadcrumbs, header/footer)
  - CSS/JS
  - Embedded images (or replaced with alt text)

What gets preserved:
  - Headings (converted from <h2> to ## etc.)
  - Code blocks (critical for runbooks!)
  - Lists (numbered and bulleted)
  - Tables (converted to text)
```

**Why this matters for DevOps content specifically:**

Runbooks contain kubectl commands, YAML configs, and log excerpts. If extraction corrupts these, the chunk becomes useless:

```
Bad extraction (HTML tag boundary truncated the command):
  "Check current batch size: kubectl get cm ingestion-config -o"

Good extraction:
  "Check current batch size: kubectl get cm ingestion-config -o yaml"
```

**Common extraction tools:**

```
HTML → text:         BeautifulSoup, Trafilatura, Unstructured
Markdown → text:     Almost pass-through (Markdown is already near-text)
PDF → text:          PyMuPDF, pdfplumber, Unstructured
Slack threads:       Slack API export → JSON → extract message text
Jira/Linear:         API export → extract description + comments
```

#### Step 2: CLEAN — Normalize the Content

Removes noise that would pollute embeddings.

```
Before cleaning:
  "Last updated: Dec 15, 2024 | Author: Platform Team | Views: 1,234
   
   
   ## Overview
   The ingestion service reads events from Kafka...
   
   ---
   © 2024 Netskope Inc. All rights reserved.
   Powered by Confluence | Report a problem"

After cleaning:
  "## Overview
   The ingestion service reads events from Kafka..."
```

**What gets removed:** Page metadata (views, author — goes into metadata fields instead), boilerplate headers/footers, excessive whitespace, Unicode noise (zero-width spaces, smart quotes → regular quotes), navigation text ("Back to top", "Table of contents").

**What stays:** All actual content, section headers, code blocks, commands, lists, tables.

**Key principle:** Anything that describes *what the page is about* stays in the text. Anything that's *about the page itself* (metadata) gets stripped from text and stored separately as structured metadata fields.

#### Step 3: CHUNK — The Make-or-Break Step

This is where 80% of search quality is determined. The embedding model converts each chunk into ONE vector. If the chunk mixes unrelated topics, the vector becomes a blurry average of both — useful for neither.

**Analogy:** Think of embedding like taking a photograph. If your frame captures exactly one subject (a building), the photo is clear and useful. If the frame captures half a building and half a car, the photo represents neither well.

**The fundamental tension:**

```
Too small:  "Reduce BATCH_SIZE to 1000"
            → Embedding captures: "something about reducing batch size"
            → Missing: WHY (OOM), WHERE (ingestion service), HOW (kubectl)
            → Search for "ingestion OOM fix" won't find this chunk

Too large:  The entire 500-word document as one chunk
            → Embedding captures: a blurry average of OOM + Kafka lag + deployment
            → Search for "ingestion OOM fix" finds this, but also returns it
              for "kafka lag", "deployment config", and everything else
            → Low precision — too many false positives

Just right: The "Common Failure: OOM Kill" section as one chunk
            → Embedding captures: OOM kill in ingestion service, with fix steps
            → Search for "ingestion OOM fix" → direct hit with high similarity
```

##### Chunking Strategy 1: Fixed-Size Chunking

Split every N tokens, with overlap between chunks.

```
Document: "The ingestion service reads from Kafka topics. It
processes messages in batches of 1000. When a batch fails,
it retries 3 times with exponential backoff. The monitoring
dashboard shows batch processing latency. Alert thresholds
are set at p99 > 500ms. The deployment uses 4 replicas
behind a load balancer. Each replica needs 2GB RAM."

Chunk size: 50 tokens, Overlap: 10 tokens

Chunk 1 (tokens 0-50):
"The ingestion service reads from Kafka topics. It processes
messages in batches of 1000. When a batch fails, it retries
3 times with exponential backoff."

Chunk 2 (tokens 40-90):
"it retries 3 times with exponential backoff. The monitoring
dashboard shows batch processing latency. Alert thresholds
are set at p99 > 500ms."

Chunk 3 (tokens 80-130):
"Alert thresholds are set at p99 > 500ms. The deployment uses
4 replicas behind a load balancer. Each replica needs 2GB RAM."
```

**Why overlap?** Without it, a sentence split across two chunks loses context in both:

```
Without overlap:
  Chunk 1: "...it retries 3 times with"     ← incomplete thought
  Chunk 2: "exponential backoff. The..."     ← lost the retry count

With 10-token overlap:
  Chunk 1: "...it retries 3 times with exponential backoff."  ← complete
  Chunk 2: "it retries 3 times with exponential backoff. The..." ← also has it
```

**Pros:** Simple, predictable chunk sizes, works for any content.
**Cons:** Splits can land mid-sentence or mid-paragraph, mixing topics.

##### Chunking Strategy 2: Semantic / Section-Based Chunking

Split at natural document boundaries — headers, paragraphs, section breaks.

```
Markdown document:

## Error Handling                    ← chunk boundary
The service retries failed batches
3 times with exponential backoff.
Errors are logged to CloudWatch.

## Monitoring                        ← chunk boundary
Dashboard: grafana.internal/d/ingest
Alert: p99 latency > 500ms pages
the oncall team via PagerDuty.

## Deployment                        ← chunk boundary
4 replicas, 2GB RAM each.
Deployed via Helm chart in
the platform-services namespace.
```

Each section becomes its own chunk. The section header is included for context.

**Pros:** Each chunk is topically coherent. Better embeddings.
**Cons:** Sections vary wildly in size — some may be too long (diluted embedding) or too short (not enough context).

##### Chunking Strategy 3: Recursive Chunking (Most Practical)

Try to split at the largest natural boundary that fits within the size limit. Fall back to smaller boundaries if needed.

```
Split hierarchy:
  1. Try to split by section headers (##, ###)
  2. If a section is still too long, split by paragraphs (\n\n)
  3. If a paragraph is still too long, split by sentences (. ? !)
  4. If a sentence is too long (rare), split by tokens

Example:
  Section "Error Handling" is 2000 tokens (too long for 512 limit)
  → Split into paragraphs
  → Paragraph 1 is 400 tokens ✓
  → Paragraph 2 is 800 tokens (too long)
    → Split into sentences
    → Sentence group fits in 512 ✓
```

This is what LangChain's `RecursiveCharacterTextSplitter` and similar tools implement.

##### Chunking Strategy 4: Context-Enriched Chunks

Prepend context (document title, section header, metadata) to each chunk before embedding. The chunk's vector then captures not just the content but WHERE it came from.

```
Raw chunk:
  "4 replicas, 2GB RAM each."

Context-enriched chunk:
  "Document: Ingestion Service Runbook
   Section: Deployment
   Content: 4 replicas, 2GB RAM each."
```

The enriched version produces a much better embedding because the model knows this is about deployment configuration, not abstract numbers.

##### Chunking Our Example Document (Recursive + Context-Enriched)

In practice, you combine Strategy 3 + 4. Let's chunk our example runbook:

```
Step 1: Split by section headers (##)

  Chunk candidate A: "## Overview\nThe ingestion service reads events
                      from Kafka and writes to PostgreSQL..."
                      → ~30 tokens. Short but topically pure. ✓ Keep.

  Chunk candidate B: "## Common Failure: OOM Kill\nWhen the service
                      exceeds its 4GB memory limit..."
                      → ~80 tokens. Good size, single topic. ✓ Keep.

  Chunk candidate C: "## Common Failure: Kafka Consumer Lag\nWhen the
                      consumer group falls behind..."
                      → ~60 tokens. Good size, single topic. ✓ Keep.

  Chunk candidate D: "## Deployment\nHelm chart: platform-services..."
                      → ~40 tokens. Short but self-contained. ✓ Keep.
```

Every section fits within our 512-token limit. No need to split further.

**But what if the OOM section was 800 tokens long?**

```
Step 2: Section too long → split by paragraphs

  Chunk B1: "## Common Failure: OOM Kill
             When the service exceeds its 4GB memory limit, Kubernetes
             OOM-kills it. This usually happens when batch sizes exceed
             5000 events."
             → ~40 tokens. Describes the problem. ✓

  Chunk B2: "## Common Failure: OOM Kill
             To fix:
             1. Check current batch size: kubectl get cm ingestion-config -o yaml
             2. Reduce BATCH_SIZE to 1000
             3. If still OOM, increase memory limit in values.yaml to 6GB"
             → ~50 tokens. Fix steps. ✓

  Notice: We PREPEND the section header "## Common Failure: OOM Kill"
  to BOTH sub-chunks. Without it, Chunk B2 is just a list of kubectl
  commands with no context about what they're fixing.
```

**The final enriched chunks (what actually gets embedded):**

```
Chunk 1:
  "Document: Ingestion Service — Troubleshooting Guide
   Team: Platform | Updated: 2024-12-15
   Section: Overview

   The ingestion service reads events from Kafka and writes to PostgreSQL.
   It processes ~2M events/day across 8 partitions."

Chunk 2:
  "Document: Ingestion Service — Troubleshooting Guide
   Team: Platform | Updated: 2024-12-15
   Section: Common Failure: OOM Kill

   When the service exceeds its 4GB memory limit, Kubernetes OOM-kills it.
   This usually happens when batch sizes exceed 5000 events.
   To fix:
   1. Check current batch size: kubectl get cm ingestion-config -o yaml
   2. Reduce BATCH_SIZE to 1000
   3. If still OOM, increase memory limit in values.yaml to 6GB"

Chunk 3:
  "Document: Ingestion Service — Troubleshooting Guide
   Team: Platform | Updated: 2024-12-15
   Section: Common Failure: Kafka Consumer Lag

   When the consumer group falls behind, lag increases.
   Root causes:
   - Slow downstream DB writes (check pg_stat_activity for locks)
   - Too few consumer replicas (should equal partition count)
   - Poison pill messages blocking processing"

Chunk 4:
  "Document: Ingestion Service — Troubleshooting Guide
   Team: Platform | Updated: 2024-12-15
   Section: Deployment

   Helm chart: platform-services/ingestion
   Replicas: 8 (must match Kafka partition count)
   Memory: 4GB request, 6GB limit
   CPU: 500m request, 2 cores limit"
```

Each chunk carries its own context. If someone searches "ingestion service memory limit", Chunk 2 matches strongly — the embedding captures "ingestion", "OOM", "memory limit", "fix steps" in a single coherent vector.

##### Chunking Rules of Thumb

```
Chunk size:
  256-512 tokens:  Good for precise retrieval (Q&A use case)
  512-1024 tokens: Good for summarization / broader context
  > 1024 tokens:   Usually too large — embedding becomes diluted

Overlap:
  10-20% of chunk size (e.g., 50-100 tokens for 512-token chunks)

For your runbooks / incident docs:
  1. Split by section headers first
  2. If a section > 512 tokens, split by paragraph
  3. Include section header in every sub-chunk
  4. Keep code blocks, YAML configs, and log excerpts intact (don't split mid-block)
  5. Store source URL, section title, and date as metadata
```

#### Step 4: ENRICH — Add Metadata to Each Chunk

Attaches structured metadata fields that enable **filtering at search time**. This is separate from the text enrichment above — these are stored as columns/fields alongside the vector, not embedded into the vector.

```
Chunk 2 stored as:

  {
    "text": "Document: Ingestion Service — Troubleshooting Guide...",
    "embedding": [0.05, -0.22, 0.41, ...],   ← 384 or 1536 floats

    "metadata": {
      "source_url": "https://confluence.internal/pages/ingestion-troubleshooting",
      "title": "Ingestion Service — Troubleshooting Guide",
      "section": "Common Failure: OOM Kill",
      "team": "platform",
      "doc_type": "runbook",
      "last_updated": "2024-12-15",
      "author": "platform-team",
      "service": "ingestion-service",
      "tags": ["oom", "memory", "kubernetes"]
    }
  }
```

**Why metadata matters — the real power:**

```
Query: "OOM fix" (no filter)
  → Searches all 50,000 chunks across all teams/services
  → Returns OOM fixes for ingestion, auth-service, billing, API gateway...
  → User has to mentally filter "which one is for MY service?"

Query: "OOM fix" (filter: team=platform, service=ingestion-service)
  → Searches only ~500 chunks for platform team's ingestion service
  → Returns exactly the right runbook chunk
  → This is what the Slack bot should do — it knows which channel/service
```

This is exactly what the pgvector demo does with `team` and `doc_type` filters in the WHERE clause.

#### Step 5: EMBED — Convert Text to Vectors

Sends each chunk through the embedding model and gets back a vector.

```
Input:  "Document: Ingestion Service — Troubleshooting Guide
         Section: Common Failure: OOM Kill
         When the service exceeds its 4GB memory limit..."

Output: [0.052, -0.218, 0.413, 0.031, -0.187, ..., 0.094]
        ← 384 floats (all-MiniLM-L6-v2) or 1536 floats (OpenAI)
```

**Batch processing — critical for efficiency:**

```
DON'T do this (one API call per chunk):
  for chunk in chunks:
      embedding = model.encode(chunk.text)
      save(embedding)
  → 1,000 chunks × 200ms per call = 200 seconds
  → Plus: rate limits will throttle you

DO this (batch):
  batch_size = 100
  for i in range(0, len(chunks), batch_size):
      batch = chunks[i:i+batch_size]
      embeddings = model.encode([c.text for c in batch])
      save_all(embeddings)
  → 1,000 chunks / 100 per batch = 10 API calls × 500ms = 5 seconds
```

**Local vs API embedding:**

```
Local (sentence-transformers):
  model = SentenceTransformer('all-MiniLM-L6-v2')
  embeddings = model.encode(texts, batch_size=64, show_progress_bar=True)

  Pros: Free, no network, full control, works offline
  Cons: Needs GPU for speed, limited model quality (384 dims)
  Best for: Dev/testing, small-medium corpus, cost-sensitive

API (OpenAI, Voyage, Cohere):
  response = openai.embeddings.create(
      input=texts,
      model="text-embedding-3-small"    # 1536 dims
  )

  Pros: Better model quality, no GPU needed, easy scaling
  Cons: Cost ($0.02/1M tokens), network dependency, latency
  Best for: Production, large corpus, quality-critical
```

**The golden rule:** Use the SAME model for ingestion and search. If you embed documents with `all-MiniLM-L6-v2`, you MUST embed queries with `all-MiniLM-L6-v2`. Mixing models produces vectors in different vector spaces — like comparing GPS coordinates from different map projections.

#### Step 6: STORE — Write to Vector Database

Saves the vector, text, and metadata together.

In pgvector:

```sql
INSERT INTO documents (title, content, section, team, doc_type,
                       service, last_updated, source_url, embedding)
VALUES (
  'Ingestion Service — Troubleshooting Guide',
  'When the service exceeds its 4GB memory limit...',
  'Common Failure: OOM Kill',
  'platform',
  'runbook',
  'ingestion-service',
  '2024-12-15',
  'https://confluence.internal/pages/...',
  '[0.052, -0.218, 0.413, ...]'::vector
);
```

**Idempotency — handling document updates:**

Documents change. Runbooks get updated. Three strategies:

```
Strategy 1: Delete and re-insert (simple)
  DELETE FROM documents WHERE source_url = '...';
  INSERT INTO documents (...) VALUES (...);

  Pros: Simple, no stale chunks
  Cons: Brief window where old chunks are deleted but new aren't inserted yet
  Best for: Small corpus like ~1,000 runbooks

Strategy 2: Versioned inserts
  INSERT with a version column + timestamp
  At query time: WHERE version = (SELECT MAX(version) WHERE source_url = ...)
  Periodic cleanup: DELETE WHERE version < current - 1

  Pros: No deletion window, can compare versions
  Cons: More storage, query complexity

Strategy 3: Content hash (detects changes efficiently)
  hash = sha256(chunk_text)
  If hash exists in DB → skip (content hasn't changed, no need to re-embed)
  If hash is new → insert
  If old hash missing from new batch → delete (chunk was removed from source)

  Pros: Only re-embeds changed content, saves API costs
  Cons: Slightly more logic
  Best for: 100K+ documents where embedding API costs matter
```

#### Step 7: INDEX — Build/Update the ANN Index

After all vectors are stored, build the index for fast search.

```sql
-- pgvector HNSW index
CREATE INDEX idx_docs_hnsw ON documents
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 200);
```

**When to build the index:**

```
Initial load (batch):
  1. Insert all documents (no index yet — inserts are fast)
  2. Build index after all inserts complete
  → Index build scans all vectors at once, more efficient

Ongoing updates (incremental):
  HNSW supports incremental inserts — new vectors are added to
  the existing graph. No full rebuild needed.

  But: after many inserts/deletes, the graph quality degrades.
  Schedule periodic REINDEX:

  REINDEX INDEX idx_docs_hnsw;  -- rebuilds from scratch
```

**For ~1,000 runbooks, the real-world flow:**

```
  1. Nightly cron job:
     - Pull updated pages from Confluence API
     - Extract → Clean → Chunk → Enrich → Embed
     - Delete old chunks for updated pages
     - Insert new chunks

  2. Weekly REINDEX (optional at this scale, paranoia)

  3. Total time: ~2-3 minutes for 1,000 docs
     - Embedding: 1,000 chunks × local model = ~30 seconds
     - DB operations: < 10 seconds
     - Index build: < 5 seconds (tiny dataset for HNSW)
```

### Full Architecture — Ingestion + Search Together

For a Slack bot + CI pipeline use case:

```
┌──────────────────────────────────────────────────────────────────┐
│                 INGESTION (runs nightly or on doc change)        │
│                                                                  │
│  Confluence ──┐                                                  │
│  GitHub READMEs ──→ [Extract] → [Clean] → [Chunk] → [Enrich]   │
│  Runbooks ────┘           │                                      │
│                           v                                      │
│                     [Embed (batch)] → [Store in pgvector]        │
│                                     → [Build/refresh HNSW index] │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│                 SEARCH (runs on every query)                      │
│                                                                  │
│  Slack bot msg ──→ [Embed query] → [pgvector search]             │
│       or                           (with team/service filter)    │
│  CI failure ─────→                      │                        │
│                                         v                        │
│                                   [Top 3-5 chunks]               │
│                                         │                        │
│                                         v                        │
│                                   [LLM prompt + context]         │
│                                         │                        │
│                                         v                        │
│                                   [Response in Slack / CI comment]│
└──────────────────────────────────────────────────────────────────┘
```

### The Query Pipeline — Deep Dive

The query pipeline is what runs every time someone asks a question. It needs to be fast (< 2 seconds total) and accurate. Let's trace a query end-to-end.

```
User in Slack: "Why does the ingestion service keep crashing?"
```

#### Query Step 1: Query Preprocessing

The user's raw query may not be ideal for vector search. Preprocessing improves it.

**Problem:** Users type questions the way they talk to humans, not the way information is stored in documents.

```
User types:       "Why does the ingestion service keep crashing?"
Documents say:    "CrashLoopBackOff means the container keeps crashing..."
                  "OOM killed — check memory limits"
                  "Kafka rebalance triggered pod restart"

The user said "crashing" — the docs say "CrashLoopBackOff", "OOM killed",
"pod restart". Vector search handles some of this (semantic similarity),
but it can miss domain-specific terms.
```

**Three preprocessing techniques:**

**1a. Query Expansion (keyword enrichment)**

Add domain-specific synonyms and related terms to the query before embedding.

```
Original:  "ingestion service keep crashing"

Expanded:  "ingestion service keep crashing CrashLoopBackOff
            OOM restart failure pod"

Can be done with:
  - A static synonym dictionary (simple, fast)
    {"crashing": ["CrashLoopBackOff", "OOM", "restart", "failure"]}
  - An LLM call (flexible, slower)
    "Given this query, add Kubernetes-specific terms that mean the same thing"
```

The expanded query produces a richer embedding that's closer to how the runbooks describe the same problems.

**1b. Query Rewriting (LLM-assisted)**

Use an LLM to reformulate the user's question into a better search query.

```
User question:     "Why does the ingestion service keep crashing?"

LLM rewrite:       "ingestion service crash causes: OOM, CrashLoopBackOff,
                     memory limit exceeded, Kafka rebalance pod restart"

Why this helps: The rewrite packs more search-relevant terms into the query
while preserving the intent. The embedding of the rewrite will be closer
to the embeddings of the relevant runbook chunks.
```

**1c. Multi-Query Generation**

Generate multiple search queries from one user question, search with each, then merge results.

```
User question:  "Why does the ingestion service keep crashing?"

Generated queries:
  Q1: "ingestion service crash root cause"
  Q2: "ingestion service CrashLoopBackOff OOM"
  Q3: "ingestion pod restart troubleshooting"

Search with all three → merge results using RRF (Part 8)
```

**Why multiple queries?** A single query embedding sits at one point in vector space. It might be close to some relevant chunks but far from others that use different vocabulary. Three different queries cover more of the relevant vector space.

```
                    Vector Space
                    
        Chunk: "OOM kill guide"
             ●
                    ● Q2 hits this

  Q1 ●                          ● Chunk: "pod restart FAQ"
                                       ● Q3 hits this
  
       ● Chunk: "crash root cause"
         Q1 hits this

  A single query can only be near SOME of these chunks.
  Multiple queries cover more ground.
```

**When to use each technique:**

```
Query expansion:   Always. Cheap (dictionary lookup) or moderate (LLM call).
                   Biggest bang for the buck.

Query rewriting:   When queries are conversational / long-form.
                   "Hey my thing keeps breaking and I don't know what to do"
                   → "service crash troubleshooting steps"

Multi-query:       When recall matters more than latency.
                   Adds ~200-500ms (extra search calls).
                   Great for Slack bot (user can wait 2s), bad for
                   autocomplete (needs < 100ms).
```

#### Query Step 2: Embed the Query

Same model as ingestion. Non-negotiable.

```
Query text: "ingestion service crash causes: OOM, CrashLoopBackOff,
             memory limit exceeded, Kafka rebalance pod restart"

Embedding model: all-MiniLM-L6-v2 (same as ingestion!)

Query vector: [0.052, -0.218, 0.413, ..., 0.094]   ← 384 floats
```

This is a single model.encode() call — fast (~5-10ms locally, ~50-100ms via API).

#### Query Step 3: Vector Search (ANN Retrieval)

Find the top-K nearest chunks to the query vector.

```sql
-- pgvector query
SELECT title, content, section, team, doc_type,
       1 - (embedding <=> query_vec::vector) AS similarity
FROM documents
ORDER BY embedding <=> query_vec::vector
LIMIT 20;
```

**Important: Retrieve MORE than you need.** If you want 5 final results, retrieve 20. The extras give the reranker (Step 5) more candidates to work with.

```
Why over-retrieve:

  Retrieve top-5:
    Position 1-5 from vector search. These are the bi-encoder's best guesses.
    If the bi-encoder made a mistake (ranked a mediocre chunk at #3), you're stuck.

  Retrieve top-20:
    Position 1-20 from vector search. Maybe the BEST chunk is at position #8
    (bi-encoder slightly misjudged it). The reranker gets a second look
    and can promote it to #1.

  Rule of thumb: retrieve 3-4x your final result count.
  Want 5 results → retrieve 20.
```

**Pre-filtering vs Post-filtering:**

```
Pre-filtering (filter BEFORE vector search):
  SELECT ... FROM documents
  WHERE team = 'platform'                    ← filter first
  ORDER BY embedding <=> query_vec::vector   ← then search within filtered set
  LIMIT 20;

  Pros: Searches fewer vectors → faster
  Cons: If filter is too strict, may miss relevant results

Post-filtering (filter AFTER vector search):
  SELECT ... FROM (
    SELECT ... FROM documents
    ORDER BY embedding <=> query_vec::vector  ← search all
    LIMIT 100
  ) sub
  WHERE team = 'platform'                     ← filter after
  LIMIT 20;

  Pros: Vector search sees everything, won't miss results
  Cons: Slower (scans more vectors), may return fewer than 20 after filtering

pgvector with WHERE clause does pre-filtering.
For most cases, pre-filtering is the right choice.
```

#### Query Step 4: Metadata Filtering

Often combined with Step 3 (as WHERE clauses in the SQL query). The Slack bot can automatically add filters based on context:

```
Slack channel: #platform-ingestion
  → Auto-add: team='platform', service='ingestion-service'

CI failure pipeline:
  → Auto-add: doc_type IN ('runbook', 'postmortem'), team='devops'

User in #general with no context:
  → No filter. Search everything.
```

This is one of the biggest advantages of pgvector over standalone vector databases — metadata filtering is just SQL WHERE clauses. No separate filter API, no query language to learn.

#### Query Step 5: Reranking

Take the top-20 candidates from vector search and rerank them using a more accurate (but slower) model.

**Why reranking exists — the bi-encoder limitation:**

```
Bi-encoder (embedding model):
  Encodes query and document SEPARATELY.
  The query becomes one vector. Each document becomes one vector.
  Similarity = how close the two vectors are.

  Problem: The query "how to fix OOM in ingestion service" becomes
  a SINGLE vector that must simultaneously be close to:
    - chunks about OOM
    - chunks about ingestion service
    - chunks about fixing/troubleshooting

  This single vector is a COMPROMISE between all these concepts.
  It can't perfectly represent the AND relationship between them.
```

```
Cross-encoder (reranker model):
  Feeds query AND document together into ONE model.
  The model sees both simultaneously and can reason about their relationship.

  "how to fix OOM in ingestion service" + "Kafka consumer lag troubleshooting"
  → Model sees these together → low score (it's about Kafka, not OOM)

  "how to fix OOM in ingestion service" + "When service exceeds 4GB memory
   limit, Kubernetes OOM-kills it. To fix: reduce BATCH_SIZE..."
  → Model sees these together → high score (exact match of intent)
```

**Worked example:**

```
Vector search returned top-5 (bi-encoder scores):
  Rank 1 (0.85): "CrashLoopBackOff means container keeps crashing..."  [devops/runbook]
  Rank 2 (0.82): "When service exceeds 4GB memory limit, OOM-kills..." [platform/runbook]
  Rank 3 (0.79): "Consumer lag is the difference between latest offset.." [platform/runbook]
  Rank 4 (0.77): "Pods OOM killed: check memory limits, heap size..."  [devops/faq]
  Rank 5 (0.75): "Container orchestration troubleshooting overview..."  [devops/runbook]

Cross-encoder reranking (sees query + doc pairs):
  Query: "why does the ingestion service keep crashing?"

  Rank 1 → rerank score 0.94: "When service exceeds 4GB memory limit..."
           (was Rank 2 — the cross-encoder recognized this is about ingestion + crashing)

  Rank 2 → rerank score 0.88: "CrashLoopBackOff means container keeps crashing..."
           (was Rank 1 — generic, not ingestion-specific)

  Rank 3 → rerank score 0.82: "Pods OOM killed: check memory limits..."
           (was Rank 4 — relevant but generic)

  Rank 4 → rerank score 0.41: "Container orchestration troubleshooting overview..."
           (was Rank 5 — too generic)

  Rank 5 → rerank score 0.23: "Consumer lag is the difference between..."
           (was Rank 3 — cross-encoder correctly identified this is about
            Kafka lag, NOT crashing. Bi-encoder was fooled by shared
            "ingestion service" context.)
```

**Key insight:** The bi-encoder ranked the Kafka lag chunk at #3 because it came from the same "Ingestion Service" document (shares context). The cross-encoder read both the query and the chunk together and correctly demoted it — the query asks about crashing, not consumer lag.

**Common reranker models:**

```
Model                          Speed (per pair)  Quality
─────────────────────────────────────────────────────────
cross-encoder/ms-marco-MiniLM  ~5ms              Good
bge-reranker-base              ~10ms             Better
Cohere Rerank API              ~20ms             Best (API)
cross-encoder/ms-marco-L12     ~30ms             Best (local)

For 20 candidates: 20 × 10ms = 200ms total. Acceptable.
```

**When to use reranking:**

```
Always use when:
  - Answer quality matters more than latency
  - You have a Slack bot / chatbot (users accept 1-2s response)
  - Your corpus has many similar documents (runbooks from same service)

Skip when:
  - Latency budget is < 100ms (autocomplete, typeahead)
  - Corpus is small (< 100 docs) — vector search alone is accurate enough
  - Simple keyword lookups (no semantic ambiguity)
```

#### Query Step 6: Results Assembly

Package the final ranked chunks with metadata for display or LLM generation.

```python
results = [
    {
        "rank": 1,
        "similarity": 0.94,
        "title": "Ingestion Service — Troubleshooting Guide",
        "section": "Common Failure: OOM Kill",
        "content": "When the service exceeds its 4GB memory limit...",
        "team": "platform",
        "doc_type": "runbook",
        "source_url": "https://confluence.internal/pages/...",
        "last_updated": "2024-12-15"
    },
    ...
]
```

For a Slack bot, this might be formatted as:

```
Found 3 relevant results for "why does the ingestion service keep crashing?"

1. [94% match] Ingestion Service — OOM Kill (platform/runbook)
   When the service exceeds its 4GB memory limit, Kubernetes OOM-kills it.
   Fix: reduce BATCH_SIZE to 1000 or increase memory limit to 6GB.
   📄 https://confluence.internal/pages/...

2. [88% match] Kubernetes CrashLoopBackOff Guide (devops/runbook)
   CrashLoopBackOff means the container keeps crashing...
   📄 https://confluence.internal/pages/...

3. [82% match] OOM Troubleshooting (devops/faq)
   Check: memory limits, heap size, Grafana memory dashboard...
   📄 https://confluence.internal/pages/...
```

#### Query Step 7: LLM Generation (RAG)

If doing RAG (covered in depth in Part 9), feed the top chunks to an LLM:

```
[System prompt + retrieved chunks + user question]
     → LLM generates grounded answer with citations
```

### End-to-End Latency Breakdown

For a production Slack bot query:

```
Step                          Time       Notes
──────────────────────────────────────────────────────────
1. Query preprocessing        50-200ms   LLM rewrite (skip if using simple expansion)
2. Embed query                10-100ms   10ms local, 100ms API
3. Vector search (pgvector)   5-50ms     Depends on corpus size, HNSW ef_search
4. Metadata filtering         0ms        Part of SQL WHERE clause
5. Reranking (20 candidates)  100-300ms  Depends on model
6. Results assembly           1-5ms      Formatting
7. LLM generation (RAG)      500-2000ms Claude/GPT response time
──────────────────────────────────────────────────────────
Total without RAG:            ~200-600ms (search-only Slack bot)
Total with RAG:               ~700-2500ms (AI-generated answer)
```

For ~1,000 runbooks, vector search (Step 3) will be < 5ms. The bottleneck is LLM generation if using RAG, or reranking if not.

### Bi-Encoders vs. Cross-Encoders — Summary

```
                    Bi-Encoder                    Cross-Encoder
                    (embedding model)             (reranker model)
────────────────────────────────────────────────────────────────────
How it works        Encode query and doc          Feed query+doc into
                    separately → compare          one model together
                    vectors

Pre-compute docs?   Yes (embed once at            No (must process each
                    ingestion time)               query-doc pair fresh)

Speed               Milliseconds for              50-100ms per pair
                    millions of docs

Accuracy            Good                          Better (sees both
                                                  at once, catches
                                                  nuance)

Use for             First pass: narrow            Second pass: rerank
                    1M → 20 candidates            20 → 5 final results

Examples            all-MiniLM-L6-v2              cross-encoder/ms-marco
                    text-embedding-3-small        bge-reranker-base
                    voyage-3                      Cohere Rerank
```

The two-stage pattern (bi-encoder → cross-encoder) is the standard production architecture for any serious search system. Fast recall first, precise ranking second.

---

## Part 8: Hybrid Search — Deep Dive

### Why Vector Search Alone Isn't Enough

Vector search is semantic — great at meaning, bad at specifics.

```
Scenario 1 — Vector search fails:
  Query: "ERR-4521"
  Vector search returns: docs about "common error codes", "error handling patterns"
  Missed: the one doc that mentions ERR-4521 specifically
  Why: "ERR-4521" as a string has no semantic meaning to the embedding model

Scenario 2 — Keyword search fails:
  Query: "container keeps restarting"
  Keyword search returns: nothing (no doc contains this exact phrase)
  Missed: the doc about "CrashLoopBackOff troubleshooting"
  Why: different words, same meaning

Neither alone is sufficient. Hybrid search uses both.
```

### BM25 — How Keyword Search Scores Documents

BM25 is the standard keyword scoring algorithm (used in Elasticsearch, Solr, Oracle Text internally). You should understand it at a conceptual level.

**The intuition:** A document is relevant if it contains the query terms, especially rare query terms, and especially if those terms appear frequently in the document but not in other documents.

Three factors:

**1. Term Frequency (TF):** How often does the query word appear in THIS document?

```
Doc: "The pod crashed. Check the pod logs. Restart the pod."
Query: "pod"

"pod" appears 3 times → higher TF → more relevant (with diminishing returns)
```

**2. Inverse Document Frequency (IDF):** How rare is this word across ALL documents?

```
"pod" appears in 500 of 10,000 docs → moderately rare → moderate IDF
"the" appears in 9,900 of 10,000 docs → very common → low IDF (almost 0)
"CrashLoopBackOff" appears in 5 of 10,000 docs → very rare → high IDF

A match on "CrashLoopBackOff" is worth far more than a match on "the"
```

**3. Document Length Normalization:** Longer documents naturally contain more words. Normalize so short, focused documents aren't penalized.

```
BM25(query, doc) ≈ Σ  IDF(term) × TF(term, doc) / (TF + k × (1 - b + b × docLen/avgDocLen))

Don't memorize the formula. Just know:
  - Rare query terms contribute more (IDF)
  - More occurrences in the doc help, with diminishing returns (TF with saturation)
  - Long documents are slightly penalized (length normalization)
```

### How Hybrid Search Merges Results

You run two searches in parallel and need to merge the results. The most common method is **Reciprocal Rank Fusion (RRF)**.

**The problem:** Vector search returns cosine distances (0 to 1). BM25 returns scores (0 to ~25). You can't directly compare them — the scales are completely different.

**RRF solution:** Ignore the scores entirely. Only use the **rank** (position) from each result list.

```
Formula:
  RRF_score(doc) = Σ  1 / (k + rank_in_list)

  k = 60 (constant, dampens the impact of rank differences)
```

**Worked example:**

Query: "ERR-4521 pod crashloop"

```
Vector search results:            BM25 keyword results:
  Rank 1: Doc_A (crashloop guide)   Rank 1: Doc_C (has "ERR-4521" exact)
  Rank 2: Doc_B (pod restart FAQ)   Rank 2: Doc_A (has "pod" and "crashloop")
  Rank 3: Doc_D (OOM errors)        Rank 3: Doc_E (has "ERR-4521" in title)
  Rank 4: Doc_E (error patterns)    Rank 4: Doc_B (has "pod")
  Rank 5: Doc_F (k8s debugging)     Rank 5: Doc_F (has "crashloop")
```

Compute RRF scores (k=60):

```
Doc_A: 1/(60+1) + 1/(60+2) = 0.01639 + 0.01613 = 0.03252   ← appears in BOTH lists
Doc_B: 1/(60+2) + 1/(60+4) = 0.01613 + 0.01563 = 0.03175
Doc_C: 0        + 1/(60+1) = 0       + 0.01639 = 0.01639   ← only in BM25
Doc_D: 1/(60+3) + 0        = 0.01587 + 0       = 0.01587   ← only in vector
Doc_E: 1/(60+4) + 1/(60+3) = 0.01563 + 0.01587 = 0.03150
Doc_F: 1/(60+5) + 1/(60+5) = 0.01538 + 0.01538 = 0.03077

Final ranking:
  1. Doc_A (0.03252) — high in both lists ← best result
  2. Doc_B (0.03175)
  3. Doc_E (0.03150)
  4. Doc_F (0.03077)
  5. Doc_C (0.01639)
  6. Doc_D (0.01587)
```

**Key insight:** Doc_A ranked high in both searches, so it wins. Doc_C had the exact "ERR-4521" match (keyword) but wasn't semantically relevant. Doc_D was semantically relevant but lacked exact terms. RRF balances both signals.

Documents that appear in both lists get a significant boost — they're relevant by both criteria.

### Hybrid Search in Practice

**pgvector + tsvector (PostgreSQL):**

```sql
-- Vector similarity + full-text keyword in one query
WITH vector_results AS (
  SELECT id, content,
         embedding <=> query_vec AS vec_distance,
         ROW_NUMBER() OVER (ORDER BY embedding <=> query_vec) AS vec_rank
  FROM documents
  ORDER BY embedding <=> query_vec
  LIMIT 20
),
keyword_results AS (
  SELECT id, content,
         ts_rank(to_tsvector('english', content),
                 plainto_tsquery('ERR-4521 pod crashloop')) AS text_score,
         ROW_NUMBER() OVER (ORDER BY ts_rank(...) DESC) AS kw_rank
  FROM documents
  WHERE to_tsvector('english', content) @@
        plainto_tsquery('ERR-4521 pod crashloop')
  LIMIT 20
)
SELECT COALESCE(v.id, k.id) AS id,
       COALESCE(v.content, k.content) AS content,
       (1.0/(60 + COALESCE(v.vec_rank, 1000)) +
        1.0/(60 + COALESCE(k.kw_rank, 1000))) AS rrf_score
FROM vector_results v
FULL OUTER JOIN keyword_results k ON v.id = k.id
ORDER BY rrf_score DESC
LIMIT 5;
```

**Oracle 23ai (Oracle Text + AI Vector Search in one query):**

```sql
SELECT doc_id, content,
       VECTOR_DISTANCE(embedding, :query_vector, COSINE) AS vec_dist,
       SCORE(1) AS text_score
FROM documents
WHERE CONTAINS(content, 'ERR-4521 AND pod AND crashloop', 1) > 0
ORDER BY VECTOR_DISTANCE(embedding, :query_vector, COSINE)
FETCH FIRST 10 ROWS ONLY;
```

### When to Use Hybrid vs. Pure Vector

```
Use pure vector search when:
  - Queries are natural language ("how do I fix X")
  - No specific identifiers or codes in queries
  - Recall of meaning matters more than exact match

Use hybrid when:
  - Queries contain specific identifiers (error codes, ticket IDs, hostnames)
  - Users might search for exact phrases
  - Domain has specific terminology that embeddings may not capture well
  - You want the safety net of both approaches

In practice: almost always use hybrid. The cost is minimal
(one extra search + merge) and the quality improvement is significant.
```

---

## Part 9: RAG (Retrieval-Augmented Generation) — Deep Dive

### The Problem RAG Solves

LLMs have two fundamental limitations:

1. **Knowledge cutoff:** They don't know about your internal docs, recent events, or proprietary information.
2. **Hallucination:** When they don't know the answer, they make one up confidently.

RAG solves both by **retrieving relevant facts first**, then asking the LLM to answer using only those facts.

```
Without RAG:
  User: "What's the max replica count for the ingestion service?"
  LLM: "Based on typical microservice patterns, I'd recommend 10-20 replicas."
       ← Made up. Sounds plausible. Completely wrong for your system.

With RAG:
  User: "What's the max replica count for the ingestion service?"
  [Vector search retrieves: runbook chunk saying "max replicas: 8, limited by
   Kafka partition count — scaling beyond 8 wastes resources"]
  LLM: "The max is 8 replicas, limited by the Kafka partition count.
        Scaling beyond 8 won't improve throughput."
       ← Grounded in your actual documentation.
```

### RAG Architecture — End to End

```
┌─────────────────────────────────────────────────────────────────┐
│                         RAG PIPELINE                            │
│                                                                 │
│  User: "Why does the ingestion service keep crashing?"          │
│         │                                                       │
│         v                                                       │
│  [1. QUERY ANALYSIS]                                            │
│  │  Optionally: use an LLM to analyze the query                │
│  │  - Generate search queries (may differ from user question)  │
│  │  - Identify what type of info is needed                     │
│  │  - Generate keyword + semantic search terms                 │
│  │                                                              │
│  │  User query: "Why does the ingestion service keep crashing?" │
│  │  Generated searches:                                         │
│  │    Vector: "ingestion service crash restart failure"          │
│  │    Keyword: "ingestion AND (crash OR OOM OR CrashLoopBackOff)"│
│  │                                                              │
│         v                                                       │
│  [2. RETRIEVAL]                                                 │
│  │  Run hybrid search (vector + keyword)                        │
│  │  Retrieve top-K chunks (K=10-20)                             │
│  │  Optionally: rerank with cross-encoder                       │
│  │  Select top-N (N=3-5) for the prompt                         │
│  │                                                              │
│  │  Retrieved:                                                  │
│  │    Chunk 1: "Ingestion service OOM at >6GB. Increase memory  │
│  │             limit or reduce batch size." (runbook, 2024-03)  │
│  │    Chunk 2: "Incident 2024-01-15: ingestion pods crashed     │
│  │             due to Kafka rebalance storm." (postmortem)       │
│  │    Chunk 3: "Known issue: ingestion v2.3 has memory leak     │
│  │             in JSON parser. Fixed in v2.4." (Jira ticket)    │
│  │                                                              │
│         v                                                       │
│  [3. PROMPT CONSTRUCTION]                                       │
│  │  Build a prompt with retrieved context + user question        │
│  │                                                              │
│         v                                                       │
│  [4. LLM GENERATION]                                            │
│  │  LLM generates answer grounded in the retrieved context      │
│  │                                                              │
│         v                                                       │
│  [5. RESPONSE + CITATIONS]                                      │
│     "The ingestion service crashes for three known reasons:      │
│      1. OOM — it hits 6GB limit under load [Source: runbook]     │
│      2. Kafka rebalance storms [Source: incident 2024-01-15]     │
│      3. Memory leak in v2.3's JSON parser [Source: JIRA-1234]    │
│      Check your version first — v2.4 fixes the leak."           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Prompt Construction — The Critical Detail

How you construct the prompt determines answer quality.

**Basic prompt (works but fragile):**

```
Answer the following question using only the provided context.
If the context doesn't contain enough information, say so.

Context:
{chunk_1}
{chunk_2}
{chunk_3}

Question: {user_question}
```

**Better prompt (production-grade):**

```
You are a DevOps assistant answering questions about our internal systems.
Use ONLY the provided context to answer. Do not use prior knowledge.
If the context doesn't contain enough information, say "I don't have
enough information to answer this" — do not guess.

When you reference information from the context, cite the source
in brackets like [Source: document_title].

Context documents:

[Source: Ingestion Service Runbook, Section: Memory Configuration]
Ingestion service OOM at >6GB. Increase memory limit in values.yaml
or reduce batch size via BATCH_SIZE env var. Default: 1000.

[Source: Incident Postmortem 2024-01-15]
Root cause: Kafka consumer group rebalance triggered by broker restart.
All pods attempted simultaneous partition reassignment, causing memory
spikes. Mitigation: added max.poll.interval.ms=600000.

[Source: JIRA-1234, Status: Resolved in v2.4]
Memory leak in JSON parser when processing malformed messages.
Unreleased byte buffers accumulate over 4-6 hours. Fixed in v2.4
by switching to streaming parser.

Question: Why does the ingestion service keep crashing?
```

**Key prompt design principles:**
1. **Instruction to use only the context** — prevents hallucination
2. **Source labels on each chunk** — enables citations in the answer
3. **Say "I don't know" instruction** — prevents fabrication
4. **Role setting** — frames the model's behavior
5. **Metadata in context** — dates, status, section titles help the LLM weigh information

### RAG Failure Modes and Fixes

```
Problem 1: Retrieved chunks are irrelevant
  Symptom: LLM says "based on the context" but gives a wrong answer
  Cause: Vector search returned poor results (bad chunking, wrong model)
  Fix: Improve chunking, try different embedding model, add reranker

Problem 2: Answer is correct but incomplete
  Symptom: LLM gives partial answer, misses key details
  Cause: Relevant info was in chunk #6 but you only used top-3
  Fix: Increase K (retrieve more), use reranker to surface better chunks

Problem 3: LLM ignores context and hallucinates
  Symptom: Answer contains information not in any retrieved chunk
  Cause: Weak "use only context" instruction, or model overrides it
  Fix: Stronger system prompt, lower temperature (0.0-0.1), validate
       answer against context programmatically

Problem 4: Contradictory context
  Symptom: Retrieved chunks disagree with each other
  Cause: Outdated docs mixed with current docs
  Fix: Include dates in metadata, instruct LLM to prefer recent sources,
       filter by date during retrieval

Problem 5: "I don't have enough information" too often
  Symptom: System refuses to answer questions it should be able to
  Cause: Retrieval returns chunks that are related but don't directly answer
  Fix: Query expansion (generate multiple search queries), relax "only context"
       instruction slightly, use larger chunks for more context
```

### RAG Evaluation — How to Measure Quality

You can't improve what you don't measure. Three dimensions:

**1. Retrieval quality** — Did we find the right chunks?

```
Precision@K: Of the K chunks retrieved, how many are relevant?
  Retrieved 5 chunks, 3 are actually useful → Precision@5 = 60%

Recall@K: Of all relevant chunks in the DB, how many did we find?
  10 relevant chunks exist, we found 3 of them → Recall@10 = 30%

Measure by: manually labeling a set of queries with "gold" relevant chunks,
then comparing retrieval results.
```

**2. Answer quality** — Is the generated answer correct?

```
Faithfulness: Does the answer only contain information from the context?
  (No hallucinated facts)

Relevance: Does the answer actually address the question?
  (Not a correct but off-topic response)

Completeness: Does the answer cover all key points from the context?
  (Not just partial information)

Measure by: human evaluation on a sample, or use an LLM-as-judge
(ask Claude to rate answer quality given the question and context).
```

**3. End-to-end quality** — Does the user get what they need?

```
User satisfaction, task completion rate, time to answer.
Hardest to measure but most important.
```

### RAG vs. Fine-Tuning vs. Long Context

```
RAG:
  How: Retrieve relevant docs, feed to LLM at query time
  Best for: Factual Q&A over documents that change frequently
  Pros: No training, fresh data, citations, transparent
  Cons: Retrieval quality limits answer quality, latency (search + generate)

Fine-tuning:
  How: Train the model on your specific data
  Best for: Changing model behavior/style/format, domain adaptation
  Pros: No retrieval step, can capture patterns/style
  Cons: Expensive, data becomes stale (need retraining), no citations

Long context window (e.g., 200K tokens):
  How: Stuff all documents directly into the prompt
  Best for: Small document sets (< 200K tokens total)
  Pros: No chunking/indexing needed, model sees everything
  Cons: Expensive per query (all tokens processed every time),
        doesn't scale beyond context limit, slower

In practice:
  Small corpus (< 50 docs): Long context may be simpler
  Medium (50-10K docs): RAG
  Large (10K+ docs): RAG + hybrid search + reranking
  Behavior change: Fine-tuning + RAG (combine both)
```

---

## Part 10: Production Considerations — Deep Dive

### Capacity Planning

**Memory estimation formula:**

```
Total Memory = Vector Storage + Index Overhead + Metadata + Query Buffers

Vector Storage:
  num_vectors × dimensions × bytes_per_float
  Example: 5M × 1536 × 4 = 30 GB

Index Overhead (depends on index type):
  HNSW: ~1.5-2x vector storage (graph edges)
    5M vectors, M=16: each vector stores ~32 edges × 4 bytes = 128 bytes/vector
    5M × 128 = 640 MB for edges + 30 GB vectors ≈ 31 GB
    Rule of thumb: 1.5x vector storage for HNSW

  IVF: minimal overhead (just centroids)
    nlist=2000, 1536 dims: 2000 × 1536 × 4 = 12 MB
    Plus vector storage: 30 GB + 12 MB ≈ 30 GB

  PQ: dramatically less
    5M × 8 bytes (codes) + codebooks = 40 MB + 1.5 MB ≈ 42 MB

Metadata Storage:
  Depends on what you store. Typically 100-500 bytes per vector.
  5M × 300 bytes = 1.5 GB

Query Buffers:
  Concurrent queries × working memory per query
  ~100 MB for typical workloads

Total for 5M vectors with HNSW:
  30 GB (vectors) + 15 GB (HNSW overhead) + 1.5 GB (metadata) + 0.1 GB (buffers)
  ≈ 47 GB → need a 64 GB instance
```

**Quick reference table:**

```
Vectors    | HNSW Memory  | IVF Memory  | IVF-PQ Memory
100K       | 1 GB         | 0.6 GB      | 10 MB
1M         | 10 GB        | 6 GB        | 80 MB
10M        | 100 GB       | 60 GB       | 800 MB
100M       | 1 TB         | 600 GB      | 8 GB
1B         | 10 TB        | 6 TB        | 80 GB

(Assuming 1536 dims, 4 bytes/float, HNSW M=16, PQ m=8 k=256)
```

### Deployment Patterns on Kubernetes

**Pattern 1: pgvector Sidecar (< 1M vectors)**

```yaml
# Simple: Postgres with pgvector as part of your app stack
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: vector-db
spec:
  replicas: 1                    # single primary
  template:
    spec:
      containers:
      - name: postgres
        image: pgvector/pgvector:pg16
        resources:
          requests:
            memory: "16Gi"       # vectors live in memory
            cpu: "4"
          limits:
            memory: "16Gi"
        volumeMounts:
        - name: data
          mountPath: /var/lib/postgresql/data
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      resources:
        requests:
          storage: 50Gi          # SSD for index persistence
```

**Pattern 2: Dedicated Vector DB Cluster (1M - 100M vectors)**

```
                    ┌─────────────┐
                    │   Load      │
                    │  Balancer   │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
         ┌────┴────┐  ┌───┴────┐  ┌───┴────┐
         │ Qdrant  │  │ Qdrant │  │ Qdrant │
         │ Node 1  │  │ Node 2 │  │ Node 3 │
         │ (shard  │  │ (shard │  │ (shard │
         │  0,1)   │  │  2,3)  │  │  4,5)  │
         └─────────┘  └────────┘  └────────┘

  Each node holds a subset of vectors (sharded)
  Replication factor 2: each shard exists on 2 nodes
  Query hits all nodes in parallel, results merged
```

**Pattern 3: Separate Ingestion and Query Paths (100M+ vectors)**

```
Ingestion:
  [Docs] → [Chunker] → [Embedding API] → [Queue] → [Batch Writer] → [Vector DB]
           (CPU pods)    (GPU pods or      (Kafka)    (DB writer      (StatefulSet)
                          API calls)                    pods)

Query:
  [User] → [API] → [Embedding API] → [Vector DB] → [Reranker] → [LLM] → [Response]
            (pod)    (cached/fast)      (read       (GPU pod)    (API)
                                        replicas)

Why separate?
  - Ingestion is batch, bursty, can tolerate latency
  - Query is real-time, must be fast
  - Different scaling needs (ingestion scales with doc volume,
    query scales with user traffic)
  - Ingestion can write to primary, queries hit read replicas
```

### Performance Tuning — Practical Guide

**HNSW tuning:**

```
ef_construction (build time):
  Default: 200
  Higher (400+): better graph quality, 2x slower build
  Lower (64): faster build, slightly worse recall
  Tune: only if build time is a bottleneck, otherwise leave at 200

ef_search (query time):
  Default: varies (often 10-40 in pgvector)
  Higher (100-200): better recall, ~2-3x slower queries
  Lower (10): faster queries, might miss results
  Tune: start at 40, increase until recall@10 > 95% on your test set

M (connections per node):
  Default: 16
  Higher (32-64): better recall + faster search, but 2-4x more memory
  Lower (4-8): less memory, but worse recall
  Tune: 16 is good for most cases. Increase to 32 if memory allows
        and you need better recall.

Summary:
  For quality:  M=32, ef_construction=400, ef_search=100
  For speed:    M=16, ef_construction=200, ef_search=40
  For memory:   M=8,  ef_construction=100, ef_search=20
```

**IVF tuning:**

```
nlist (number of clusters):
  Rule: sqrt(N) to 4*sqrt(N)
  1M vectors: nlist=1000 to 4000
  Tune: higher nlist → more granular clusters → better recall but more
        centroid comparisons. Start with sqrt(N).

nprobe (clusters to search):
  Start at: nlist/100 to nlist/10
  nlist=1000: start with nprobe=10
  Tune: increase nprobe until recall@10 > 95%.
        Doubling nprobe roughly doubles latency.
```

### Monitoring Dashboard — What to Track

```
┌──────────────────────────────────────────────────────────────┐
│                    VECTOR SEARCH DASHBOARD                    │
│                                                              │
│  LATENCY                          THROUGHPUT                 │
│  ┌──────────────────────┐         ┌─────────────────────┐    │
│  │ Query p50:    5 ms   │         │ Queries/sec:  120   │    │
│  │ Query p95:   15 ms   │         │ Inserts/sec:   50   │    │
│  │ Query p99:   45 ms   │         │                     │    │
│  │ Embed:       20 ms   │         │                     │    │
│  │ Rerank:     200 ms   │         │                     │    │
│  │ LLM:       800 ms   │         │                     │    │
│  │ Total RAG: 1040 ms   │         │                     │    │
│  └──────────────────────┘         └─────────────────────┘    │
│                                                              │
│  RESOURCES                         QUALITY                   │
│  ┌──────────────────────┐         ┌─────────────────────┐    │
│  │ Vector memory: 28 GB │         │ Avg similarity: 0.82│    │
│  │ Index memory:  14 GB │         │ Empty results:  2%  │    │
│  │ Disk usage:    50 GB │         │ Low-score (%<0.5): 8│    │
│  │ CPU: 35%             │         │ Recall@10: 94%      │    │
│  │ Connections: 45/100  │         │                     │    │
│  └──────────────────────┘         └─────────────────────┘    │
│                                                              │
│  ALERTS                                                      │
│  ⚠ Query p99 > 100ms for 5 minutes                          │
│  ⚠ Memory > 80% of node capacity                            │
│  🔴 Recall@10 dropped below 90%                              │
│  ⚠ Embedding API error rate > 1%                             │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

**Key alerts to set up:**

```
Critical:
  - Query latency p99 > 200ms (sustained 5 min)
  - Memory usage > 85% of node capacity
  - Vector DB node down / unreachable
  - Embedding API 5xx rate > 5%

Warning:
  - Query latency p95 > 100ms
  - Average similarity score dropping (indicates embedding drift or bad data)
  - Empty result rate > 5%
  - Index build time increasing (sign of data growth)

Operational:
  - Disk usage > 70% (plan expansion)
  - Connection pool usage > 70%
  - Queue depth for ingestion pipeline > 1000
```

### Re-Indexing Strategies

Embedding model changes mean **all vectors must be regenerated**. This is the most operationally expensive event in a vector search system.

**Why model changes force re-indexing:**

```
Model A embeds "kubernetes" as [0.5, -0.3, 0.8, ...]
Model B embeds "kubernetes" as [0.1,  0.7, -0.2, ...]

These are INCOMPATIBLE. You cannot compare a Model A vector to a Model B vector.
Mixing models in the same index produces garbage results.
```

**Strategy 1: Blue-Green Re-indexing (zero downtime)**

```
Timeline:

Day 1:  [Production Index A] ← all queries go here
        Start building [Shadow Index B] with new model
        (background job, doesn't affect production)

Day 3:  [Production Index A] ← still serving queries
        [Shadow Index B] build complete
        Run quality evaluation on Index B

Day 4:  Switch traffic:
        [Index B] ← all queries now go here
        [Index A] kept as rollback for 24h

Day 5:  Delete Index A if Index B is healthy

Like a Kubernetes rolling deployment, but for your vector index.
```

**Strategy 2: Incremental Migration (for huge datasets)**

```
For billion-scale indexes that take days to rebuild:

1. Create new collection/table with new model
2. Migrate documents in batches (100K per batch)
3. Query BOTH old and new, merge results (weighted toward new)
4. As migration proceeds, weight shifts toward new
5. Once complete, cut over entirely

More complex but avoids a multi-day "no updates" window.
```

**CI/CD integration:**

```
Treat the embedding model like a database schema version:

# In your config/deployment
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_MODEL_VERSION=v1  # increment when model changes
INDEX_NAME=docs-v1          # index name includes version

# In CI/CD pipeline
if model_version changed:
  trigger_reindex_job()
  wait_for_quality_check()
  switch_traffic()
```

---

## Part 11: pgvector Hands-On Deep Dive

### Step 1: Run PostgreSQL with pgvector (Docker)

```bash
# Pull and run pgvector-enabled Postgres
docker run -d \
  --name pgvector-lab \
  -e POSTGRES_PASSWORD=vector123 \
  -e POSTGRES_DB=vectordb \
  -p 5432:5432 \
  pgvector/pgvector:pg16

# Connect
docker exec -it pgvector-lab psql -U postgres -d vectordb
```

### Step 2: Enable the Extension

```sql
-- pgvector ships with the image but must be activated per database
CREATE EXTENSION vector;

-- Verify
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
```

### Step 3: Understand the `vector` Data Type

pgvector adds a new data type `vector(n)` where n = number of dimensions.

```sql
-- A vector is just an array of floats with a fixed size
SELECT '[1.0, 2.0, 3.0]'::vector(3);

-- Dimensions must match the declared size
SELECT '[1.0, 2.0]'::vector(3);
-- ERROR: expected 3 dimensions, not 2

-- You can do math on vectors
SELECT '[1, 2, 3]'::vector(3) + '[4, 5, 6]'::vector(3);
-- [5,7,9]
```

### Step 4: Create a Table

A runbook search system — modeled for DevOps use.

```sql
CREATE TABLE documents (
    id          SERIAL PRIMARY KEY,
    title       TEXT NOT NULL,
    content     TEXT NOT NULL,
    team        TEXT,
    doc_type    TEXT,            -- 'runbook', 'postmortem', 'faq'
    created_at  TIMESTAMP DEFAULT now(),
    embedding   vector(384)     -- 384-dim model (all-MiniLM-L6-v2)
);
```

Why 384? We'll use `all-MiniLM-L6-v2` which runs locally without an API key. Production would use 1536-dim (OpenAI) or 1024-dim (Voyage).

### Step 5: Python — Generate Real Embeddings and Insert

```bash
pip install sentence-transformers psycopg2-binary
```

```python
import psycopg2
from sentence_transformers import SentenceTransformer

# Load a small, free, local embedding model
model = SentenceTransformer('all-MiniLM-L6-v2')  # 384 dimensions

# Sample documents (imagine these are chunks from your runbooks)
documents = [
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

# Generate embeddings for all documents
contents = [doc["content"] for doc in documents]
embeddings = model.encode(contents)

print(f"Generated {len(embeddings)} embeddings, each {len(embeddings[0])} dimensions")
# Generated 10 embeddings, each 384 dimensions

# Connect to PostgreSQL
conn = psycopg2.connect(
    host="localhost", port=5432,
    dbname="vectordb", user="postgres", password="vector123"
)
cur = conn.cursor()

# Insert documents with embeddings
for doc, emb in zip(documents, embeddings):
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
print("Inserted all documents with embeddings")
```

### Step 6: The Three Distance Operators

pgvector provides three operators. All return values where **lower = more similar** so `ORDER BY` always means "most similar first."

```sql
-- The three distance operators:
--   <=>  Cosine distance     (1 - cosine_similarity)
--   <->  L2 distance         (Euclidean)
--   <#>  Negative inner product

-- Cosine distance vs Cosine similarity:
--   cosine_distance = 1 - cosine_similarity
--   Similarity 1.0 (identical)   → Distance 0.0
--   Similarity 0.8 (very close)  → Distance 0.2
--   Similarity 0.0 (unrelated)   → Distance 1.0
```

### Step 7: Semantic Search — SQL

```sql
-- "Find documents similar to the OOM Troubleshooting doc"
SELECT title, doc_type, team,
       embedding <=> (SELECT embedding FROM documents
                      WHERE title = 'OOM Troubleshooting') AS distance
FROM documents
WHERE title != 'OOM Troubleshooting'
ORDER BY distance
LIMIT 5;

-- Result:
--  Kubernetes Pod CrashLoopBackOff Guide   | runbook  | devops   | 0.28
--  Ingestion Service Postmortem 2024-01-15 | postmortem| platform | 0.45
--  Ingestion Service Runbook               | runbook  | platform | 0.50
--  ...
```

CrashLoopBackOff guide is most similar to OOM doc — both about pods crashing.

### Step 8: Semantic Search with a Real Query (Python)

```python
# Embed the user's question with the SAME model
query = "Why is my pod keep restarting?"
query_embedding = model.encode(query)

cur.execute("""
    SELECT title, content, team, doc_type,
           1 - (embedding <=> %s::vector) AS similarity
    FROM documents
    ORDER BY embedding <=> %s::vector
    LIMIT 5
""", (
    f"[{','.join(str(x) for x in query_embedding)}]",
    f"[{','.join(str(x) for x in query_embedding)}]"
))

print(f"\nQuery: '{query}'\n")
for row in cur.fetchall():
    title, content, team, doc_type, similarity = row
    print(f"  [{similarity:.3f}] ({doc_type}/{team}) {title}")
    print(f"           {content[:80]}...")
    print()

# Output:
#   [0.712] (runbook/devops) Kubernetes Pod CrashLoopBackOff Guide
#            CrashLoopBackOff means the container keeps crashing and Kubernetes is ...
#
#   [0.458] (faq/devops) OOM Troubleshooting
#            If pods are OOM killed, check: 1) memory limits in values.yaml ...
#
#   [0.391] (postmortem/platform) Ingestion Service Postmortem 2024-01-15
#            Root cause: Kafka consumer group rebalance triggered by broker restart...
```

"Why is my pod keep restarting?" matched "CrashLoopBackOff" — different words, same meaning. This is vector search's superpower.

### Step 9: Metadata Filtering

Combine vector similarity with WHERE clauses — pgvector's killer feature over standalone vector DBs.

```sql
-- Only search runbooks from the platform team
SELECT title, 1 - (embedding <=> $query_vec) AS similarity
FROM documents
WHERE doc_type = 'runbook' AND team = 'platform'
ORDER BY embedding <=> $query_vec
LIMIT 3;

-- Only documents from the last 6 months
SELECT title, 1 - (embedding <=> $query_vec) AS similarity
FROM documents
WHERE created_at > now() - interval '6 months'
ORDER BY embedding <=> $query_vec
LIMIT 5;

-- Complex: runbooks OR postmortems, from platform or devops
SELECT title, 1 - (embedding <=> $query_vec) AS similarity
FROM documents
WHERE doc_type IN ('runbook', 'postmortem')
  AND team IN ('platform', 'devops')
ORDER BY embedding <=> $query_vec
LIMIT 5;
```

Vectors live alongside relational data. You can JOIN, filter, aggregate — all standard SQL.

### Step 10: Create Indexes for Fast Search

Without an index, pgvector does brute-force search. Fine for 10 documents, unusable at 1M+.

#### HNSW Index (recommended default)

```sql
CREATE INDEX idx_documents_embedding_hnsw
ON documents
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 200);

-- Parameters:
--   vector_cosine_ops  → for <=> operator (cosine distance)
--   vector_l2_ops      → for <-> operator (L2 distance)
--   vector_ip_ops      → for <#> operator (inner product)
--
--   m = 16             → connections per node (more = better recall, more memory)
--   ef_construction = 200 → build quality (more = slower build, better graph)
```

**Control search quality at query time:**

```sql
-- Default ef_search is low (40 in most versions). Increase for better recall.
SET hnsw.ef_search = 100;

-- Per-transaction override
BEGIN;
SET LOCAL hnsw.ef_search = 200;  -- only for this transaction
SELECT ...;
COMMIT;
```

#### IVF Index (alternative)

```sql
CREATE INDEX idx_documents_embedding_ivf
ON documents
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);       -- number of clusters (nlist)

-- Control clusters to search at query time
SET ivfflat.probes = 10;
```

**Which index to choose:**

```
< 100K vectors  → no index needed (brute force is fine)
100K - 1M       → HNSW (if memory allows)
1M - 10M        → HNSW with careful tuning, or IVF
10M+            → IVF (HNSW memory becomes impractical)
```

### Step 11: Hybrid Search — Vector + Full-Text Keyword

Combine pgvector with PostgreSQL's built-in full-text search.

```sql
-- Add a tsvector column for keyword search
ALTER TABLE documents ADD COLUMN tsv tsvector;

-- Populate it from the content
UPDATE documents SET tsv = to_tsvector('english', content);

-- Create a GIN index for fast keyword search
CREATE INDEX idx_documents_tsv ON documents USING gin(tsv);

-- Auto-update tsvector on future inserts/updates
CREATE OR REPLACE FUNCTION update_tsv() RETURNS trigger AS $$
BEGIN
    NEW.tsv := to_tsvector('english', NEW.content);
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_update_tsv
    BEFORE INSERT OR UPDATE OF content ON documents
    FOR EACH ROW EXECUTE FUNCTION update_tsv();
```

**Simple hybrid: keyword filter + vector ranking**

```sql
-- Find docs that mention kafka/consumer/lag (keyword filter),
-- then rank by semantic similarity
SELECT title, content,
       1 - (embedding <=> $query_vec) AS similarity,
       ts_rank(tsv, plainto_tsquery('english', 'kafka consumer lag')) AS text_rank
FROM documents
WHERE tsv @@ plainto_tsquery('english', 'kafka consumer lag')
ORDER BY embedding <=> $query_vec
LIMIT 5;
```

**Full hybrid with Reciprocal Rank Fusion (RRF):**

```sql
WITH vector_results AS (
    SELECT id, title, content,
           ROW_NUMBER() OVER (
               ORDER BY embedding <=> $query_vec
           ) AS vec_rank
    FROM documents
    ORDER BY embedding <=> $query_vec
    LIMIT 20
),
keyword_results AS (
    SELECT id, title, content,
           ROW_NUMBER() OVER (
               ORDER BY ts_rank(tsv, plainto_tsquery('english', $query_text)) DESC
           ) AS kw_rank
    FROM documents
    WHERE tsv @@ plainto_tsquery('english', $query_text)
    LIMIT 20
)
SELECT
    COALESCE(v.id, k.id) AS id,
    COALESCE(v.title, k.title) AS title,
    COALESCE(v.content, k.content) AS content,
    v.vec_rank,
    k.kw_rank,
    COALESCE(1.0 / (60 + v.vec_rank), 0) +
    COALESCE(1.0 / (60 + k.kw_rank), 0) AS rrf_score
FROM vector_results v
FULL OUTER JOIN keyword_results k ON v.id = k.id
ORDER BY rrf_score DESC
LIMIT 5;
```

### Step 12: Python Search Function

```python
def search(query_text, top_k=5, team=None, doc_type=None):
    """Hybrid search: vector similarity + optional metadata filters."""

    query_emb = model.encode(query_text)
    query_vec = f"[{','.join(str(x) for x in query_emb)}]"

    conditions = []
    params = [query_vec, query_vec]

    if team:
        conditions.append("team = %s")
        params.append(team)
    if doc_type:
        conditions.append("doc_type = %s")
        params.append(doc_type)

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    params.append(top_k)

    cur.execute(f"""
        SELECT title, content, team, doc_type,
               1 - (embedding <=> %s::vector) AS similarity
        FROM documents
        {where_clause}
        ORDER BY embedding <=> %s::vector
        LIMIT %s
    """, params)

    results = []
    for row in cur.fetchall():
        results.append({
            "title": row[0], "content": row[1],
            "team": row[2], "doc_type": row[3],
            "similarity": float(row[4])
        })
    return results

# Usage:
results = search("Why is my pod keep restarting?")
for r in results:
    print(f"  [{r['similarity']:.3f}] {r['title']}")

# Filtered: only platform team runbooks
results = search("kafka is slow", team="platform", doc_type="runbook")
```

### Step 13: RAG with Claude

```python
import anthropic

client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY env var

def ask_rag(question, top_k=3, team=None):
    """Search docs, then generate an answer with Claude."""

    # Step 1: Retrieve relevant chunks
    results = search(question, top_k=top_k, team=team)

    if not results:
        return "No relevant documents found."

    # Step 2: Build context from retrieved chunks
    context_parts = []
    for r in results:
        context_parts.append(
            f"[Source: {r['title']} ({r['doc_type']}/{r['team']}) "
            f"similarity={r['similarity']:.2f}]\n{r['content']}"
        )
    context = "\n\n".join(context_parts)

    # Step 3: Generate answer with Claude
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": f"""Answer the following question using ONLY the provided context.
If the context doesn't contain enough information, say so.
Cite sources in brackets like [Source: document_title].

Context:
{context}

Question: {question}"""
        }]
    )

    return message.content[0].text

# Usage
answer = ask_rag("Why is my pod crashing and how do I fix it?")
print(answer)
```

### Step 14: Monitoring pgvector Performance

```sql
-- Check index size
SELECT pg_size_pretty(pg_relation_size('idx_documents_embedding_hnsw')) AS index_size;

-- Check total table size (including vectors)
SELECT pg_size_pretty(pg_total_relation_size('documents')) AS total_size;

-- Verify index is being used (not brute-force Seq Scan)
EXPLAIN ANALYZE
SELECT title
FROM documents
ORDER BY embedding <=> '[0.1, 0.2, ...]'::vector(384)
LIMIT 5;
-- Should show: Index Scan using idx_documents_embedding_hnsw
-- NOT: Seq Scan (that means brute force)

-- If a filtered query falls back to Seq Scan, create a partial index:
CREATE INDEX idx_docs_platform_hnsw
ON documents USING hnsw (embedding vector_cosine_ops)
WHERE team = 'platform';
-- Only covers platform team docs — smaller and faster
```

### Step 15: Production-Ready Schema

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE documents (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title       TEXT NOT NULL,
    content     TEXT NOT NULL,
    chunk_index INTEGER DEFAULT 0,    -- which chunk of the source doc
    source_url  TEXT,
    team        TEXT NOT NULL,
    doc_type    TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT now(),
    updated_at  TIMESTAMP DEFAULT now(),
    embedding   vector(1536),         -- production model (e.g., OpenAI)
    tsv         tsvector              -- for keyword search
);

-- HNSW index for vector search
CREATE INDEX idx_docs_hnsw ON documents
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);

-- GIN index for full-text keyword search
CREATE INDEX idx_docs_tsv ON documents USING gin(tsv);

-- B-tree indexes for common filters
CREATE INDEX idx_docs_team ON documents(team);
CREATE INDEX idx_docs_type ON documents(doc_type);
CREATE INDEX idx_docs_created ON documents(created_at);

-- Auto-update tsvector and updated_at
CREATE OR REPLACE FUNCTION update_doc_triggers() RETURNS trigger AS $$
BEGIN
    NEW.tsv := to_tsvector('english', NEW.content);
    NEW.updated_at := now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_update_doc
    BEFORE INSERT OR UPDATE OF content ON documents
    FOR EACH ROW EXECUTE FUNCTION update_doc_triggers();

-- Partial index for common filtered search
CREATE INDEX idx_docs_runbook_hnsw ON documents
    USING hnsw (embedding vector_cosine_ops)
    WHERE doc_type = 'runbook';
```

### pgvector Quick Reference Card

```
SETUP:
  CREATE EXTENSION vector;
  column_name vector(dims)

OPERATORS (all: lower = more similar):
  <=>    Cosine distance
  <->    L2 (Euclidean) distance
  <#>    Negative inner product

INDEXES:
  USING hnsw (col vector_cosine_ops) WITH (m=16, ef_construction=200)
  USING ivfflat (col vector_cosine_ops) WITH (lists=100)

  Operator class must match the operator you use:
    vector_cosine_ops  → for <=>
    vector_l2_ops      → for <->
    vector_ip_ops      → for <#>

RUNTIME TUNING:
  SET hnsw.ef_search = 100;       -- HNSW search quality (default ~40)
  SET ivfflat.probes = 10;        -- IVF clusters to check

CONVERT DISTANCE TO SIMILARITY:
  1 - (embedding <=> query_vec)   -- cosine similarity (0 to 1)

HYBRID SEARCH:
  to_tsvector('english', content) -- build keyword index
  tsv @@ plainto_tsquery(...)     -- keyword match
  Combine with ORDER BY embedding <=> query_vec

EXPLAIN:
  EXPLAIN ANALYZE SELECT ... ORDER BY embedding <=> ... LIMIT 5;
  Look for "Index Scan" (good) vs "Seq Scan" (brute force)
```

---

## Part 12: Vector Search vs. Oracle Text (Comparison)

| Aspect | Vector Search | Oracle Text |
|---|---|---|
| **Goal** | Find semantically similar content | Find text matching keywords/patterns |
| **How it matches** | Distance between numeric vectors | Token/word matching with linguistic rules |
| **Handles synonyms** | Inherently (via embeddings) | Via thesaurus/stemming configuration |
| **Index structure** | HNSW, IVF, etc. | Inverted index (token → document) |
| **Requires ML model** | Yes | No |
| **Built into Oracle DB** | Yes (since 23ai) | Yes (long-standing feature) |

**Where they overlap:**
- Both solve the "find relevant content" problem
- Both live inside Oracle DB (as of 23ai)
- Oracle Text's `ABOUT` operator does rudimentary concept/theme matching — closest it gets to semantic search
- They can be **combined** in Oracle 23ai for hybrid search

**Key distinction:** Oracle Text is fundamentally lexical — operates on words and rules. Vector search is fundamentally semantic — operates on meaning learned by a model. Oracle Text won't know "king" and "monarch" are related unless you configure a thesaurus; vector search knows this inherently.

---

## Hands-On Learning Path

**Week 1 — Foundations:**
1. Install `sentence-transformers` and embed some runbook text
2. Compute cosine similarity by hand (numpy) to build intuition
3. Try different queries and see which documents come back close

**Week 2 — Vector DB:**
4. Set up pgvector in a local Postgres container (Docker)
5. Load embeddings, create an HNSW index, run queries
6. Compare brute-force vs. HNSW performance

**Week 3 — Pipeline:**
7. Build a simple ingestion pipeline: read docs → chunk → embed → store
8. Build a query endpoint
9. Add hybrid search (pgvector + `tsvector` for keyword)

**Week 4 — RAG:**
10. Connect search results to Claude API for answer generation
11. Experiment with chunk sizes and top-K values
12. Evaluate answer quality
