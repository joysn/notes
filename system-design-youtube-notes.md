# Study Notes

---

## Context Engineering for AI

**Source:** *The Complete Guide to Context Engineering for AI* by Sean Falconer, Head of AI at Confluent (2026, 40 pages)

### Core Thesis

The bottleneck for production AI systems isn't the model -- it's the **context**. Bigger LLMs won't fix hallucinations, stale data, or unreliable agents. Better context will. **Context engineering** is the discipline of designing, assembling, and governing the information environment that AI systems use to think and act.

### The Fundamental Shift

- Traditional ML: data = training asset
- Foundation models & agents: data = **runtime context**
- The question is no longer "what data do we train on?" but "what context does the model need *right now* to make the right decision?"
- You no longer control logic by writing code; you control it by shaping what information the model receives

### Data vs. Context

| | Data | Context |
|---|---|---|
| **What** | Raw material: events, records, documents, logs, metrics | Curated slice of information assembled for a specific decision at a specific time |
| **Scope** | Spread across your systems | Focused on what the model needs *right now* |
| **Form** | Whatever the source system produces | Cleaned, structured, filtered, enriched, compressed |

**More context is not better; more *relevant* context is better.** Research shows "context rot" -- accuracy degrades as you stuff more tokens in.

### AI Development Lifecycle (Context-Centered)

1. **Design** -- Define goal, scope, success metrics, safe tools
2. **Data Preparation** -- Identify and structure data sources (historical + real-time)
3. **Context Engineering** -- Build pipelines/policies turning raw data into high-quality context (retrieval, filtering, enrichment, compression, access control)
4. **Evaluate** -- Automated evals + human-in-the-loop testing
5. **Deploy** -- Integrate with clear boundaries, fallbacks, human oversight
6. **Observe** -- Capture traces, monitor behavior, track failures, feed back into design

### Four Pillars of Context Engineering

**1. System Prompt**
- Defines agent's identity, goals, constraints, heuristics
- Aligns behavior but cannot compensate for lack of relevant data

**2. Tools**
- APIs, functions, data access points the agent can call
- Key: clear schemas, simple names, predictable outputs
- Only useful if the data they return is clean and current

**3. Data Retrieval**
- Hardest engineering problem -- determines what info the model actually sees
- Must supply high-signal, low-noise, up-to-date context
- Industry shifting from "preload everything" to "retrieve just in time"
- RAG is a step forward but not a silver bullet

**4. Long-Horizon Optimization**
- Memory, traceability, evaluation loops, feedback mechanisms
- Captures what happened, why, and how to improve next time

### Why Agents Raise the Bar (vs. Simple RAG)

| System | Context Needs |
|---|---|
| **Prompt-based LLM** | Instructions + recent conversation |
| **RAG system** | Above + searchable corpora + careful retrieval |
| **Agent** | All above + live state + tools + policies + memory of past actions |

### Context Window Limits

Even with huge context windows, larger windows introduce:
- Cost growth proportional to context size
- Latency growth
- Cognitive overload / "context rot"
- Attention dilution -- irrelevant text drowns important parts

### Three Practical Challenges in Production

1. **Iterating on data and context** -- failures often caused by missing/stale/noisy context, not the model
2. **Running reliably** -- need timeouts, circuit breakers, idempotency, guard models, observability
3. **Governance and trust** -- audit trails, access controls, provenance tracking

### Continuous Context Architecture (Vendor-Neutral)

The data must be both **clean AND current**. Three runtime requirements:

1. **Streaming data capture** -- every business change flows as continuous events
2. **Stream processing** -- transform, enrich, filter, join real-time + historical data into meaningful representations
3. **Low-latency context serving** -- retrieve specific slices of state in milliseconds

Plus: **end-to-end governance** (identity/access controls, audit logs, lineage, policy enforcement, drift detection)

---

## Designing YouTube / Netflix

**Source:** *Grokking the System Design Interview* (pages 82-91)

### Scope

A simplified video sharing service: upload, view, search videos. Not covering recommendations, channels, or subscriptions.

### Requirements

**Functional:**
- Upload, view, share videos
- Search by video title
- Track stats (views, likes/dislikes)
- Comments on videos

**Non-Functional:**
- Highly reliable (no uploaded video lost)
- Highly available (availability > consistency -- AP system)
- Real-time streaming experience (no lag)

### Capacity Estimation

| Metric | Value |
|---|---|
| Total users | 1.5 billion |
| DAU | 800 million |
| Views/user/day | 5 |
| Upload:view ratio | 1:200 |

```
Views/sec:   800M * 5 / 86400 = ~46K views/sec
Uploads/sec: 46K / 200 = ~230 uploads/sec
Storage:     500 hrs/min * 60 min * 50MB = 1500 GB/min (25 GB/sec)
Upload BW:   ~5 GB/sec incoming
Download BW: ~1 TB/sec outgoing (at 1:200 ratio)
```

**Key takeaway:** Massively read-heavy (200:1). Every design choice optimizes for reads/streaming.

### System APIs

```
uploadVideo(api_dev_key, video_title, description, tags[],
            category_id, default_language, recording_details, video_contents)
→ HTTP 202 (accepted, encoding async)

searchVideo(api_dev_key, search_query, user_location,
            maximum_videos_to_return, page_token)
→ JSON list of {title, thumbnail, creation_date, view_count}

streamVideo(api_dev_key, video_id, offset, codec, resolution)
→ Media stream (video chunk) from given offset
```

`offset` enables seeking + cross-device resume. `codec`/`resolution` enable adaptive streaming.

### High-Level Architecture

```
                                                    ┌──────────┐
                                                    │  Encode  │
                                                    └────▲─────┘
                                                         │
┌────────┐    ┌────────────┐    ┌────────────┐    ┌──────┴──────┐
│ Client │───>│ Web Server │───>│ App Server │───>│  Processing │
│        │<───│            │<───│            │    │    Queue    │
└────────┘    └────────────┘    └─────┬──────┘    └─────────────┘
   │                                  │
   │                            ┌─────┴──────┐
   │                            │            │
   │                     ┌──────▼──┐  ┌──────▼───────────┐
   │                     │  User   │  │ Video Metadata   │
   │                     │   DB    │  │      DB          │
   │                     └─────────┘  └──────────────────┘
   │
   │         ┌───────────────────────────┐
   └────────>│ Video & Thumbnail Storage │
             │   (distributed file sys)  │
             └───────────────────────────┘
```

**Upload flow:** Client -> Web Server -> App Server -> Processing Queue -> Encoder (async) -> Distributed Storage + Metadata DB. User gets HTTP 202 immediately, notified when encoding completes.

### Database Schema

**Video metadata (MySQL):** VideoID, Title, Description, Size, Thumbnail, Uploader/UserID, likes, dislikes, views

**Comments (MySQL):** CommentID, VideoID, UserID, Comment, TimeOfCreation

**User data (MySQL):** UserID, Name, Email, Address, Age, Registration details

### Detailed Component Design

**Read/Write Separation:**
- Master-slave replication for metadata (writes to master, reads from slaves)
- Brief staleness acceptable (milliseconds)
- Video files in distributed file storage with multiple copies

**Thumbnail Storage:**
- Small files (~5KB), ~5 per video, very high read traffic
- **Bigtable** -- combines small files into one disk block (efficient reads)
- Keep hot thumbnails in cache

**Video Uploads:**
- Support resumable uploads (large files, connection drops)
- Async encoding via processing queue into multiple formats

### Metadata Sharding

**By UserID:** All user's videos on one server. Problem: hot users, uneven distribution.

**By VideoID (preferred):** Hash VideoID to server. Even distribution. To find user's videos, query all shards and aggregate. Use **consistent hashing** to minimize data movement.

### Video Deduplication

Duplicates waste storage, cache, bandwidth, energy. **Inline deduplication** during upload:
- Run matching algorithms (Block Matching, Phase Correlation) as user uploads
- Duplicate found -> stop upload, reference existing copy
- Higher quality duplicate -> replace old
- Partial match -> upload only missing chunks

### Load Balancing

- **Consistent hashing** among cache servers
- Dynamic HTTP redirections for overflow (busy server -> less busy neighbor)
- Tradeoff: each redirect adds an HTTP round-trip

### Caching

**Metadata cache:** Memcache + LRU eviction. 80-20 rule: cache 20% of daily read volume.

**Video cache:** Geographically distributed cache servers pushing content closer to users.

### CDN (Content Delivery Network)

- Popular videos go to CDNs (replicated at edge locations worldwide)
- Fewer hops, lower latency, CDN serves from memory
- Less popular videos (1-20 views/day) served from origin data centers
- CDN is how you handle ~1 TB/sec outgoing bandwidth without melting origin infra

### Fault Tolerance

**Consistent hashing** for DB distribution: dead server's load auto-redistributes to neighbors; new server takes proportional slice. Minimizes data movement.

### Interview Presentation Order

1. Clarify requirements (scope)
2. Estimate scale (back-of-envelope math)
3. Define APIs (external interface)
4. High-level architecture (boxes and arrows)
5. Database schema
6. Deep dive into components (encoding pipeline, read/write separation, thumbnails)
7. Scaling concerns (sharding, dedup, caching, CDN, LB, fault tolerance)

**Core insight:** It's a read-heavy system where the dominant cost is bandwidth. Every design decision exists to handle the 200:1 read:write ratio and massive outgoing bandwidth.

### BLOB Storage (Binary Large Object Storage)

BLOB storage is optimized for storing large, unstructured binary data -- videos, images, audio, documents. This is where the actual video files live (not in MySQL).

**Why not store videos in a regular database?**

| Concern | Regular DB (MySQL/Postgres) | BLOB Storage |
|---|---|---|
| **File size** | Struggles with files > few MB | Designed for GB/TB-sized files |
| **Read performance** | Optimized for structured queries, not streaming | Optimized for sequential reads of large files |
| **Cost** | Expensive per GB (SSDs, IOPS) | Cheap per GB (commodity disks, object storage) |
| **Scalability** | Vertical scaling (bigger machine) | Horizontal scaling (add more nodes) |
| **Backup/replication** | DB replication carries all that binary weight | Built-in replication and geo-distribution |

**How it fits in the architecture:**

```
┌──────────────┐          ┌─────────────────────────┐
│   App Server │──PUT────>│     BLOB Storage         │
│              │          │  video_id -> binary data  │
│              │  returns │  (replicated across       │
│              │<─────────│   multiple nodes/regions) │
│              │  path    └─────────────────────────┘
└──────┬───────┘
       │ stores path/URL
       ▼
┌──────────────┐
│  Metadata DB │
│  (MySQL)     │
│  file_path ──┼──> "blob://videos/abc123.mp4"
└──────────────┘
```

**Types of BLOB storage:**

| Type | Examples | Notes |
|---|---|---|
| Distributed File Systems | HDFS, GlusterFS | Splits files into 128MB blocks, replicates across nodes |
| Cloud Object Storage | Amazon S3, GCS, Azure Blob | Most common today. S3 = 11 nines durability |
| Company-specific | Google Colossus (YouTube), S3 + Open Connect CDN (Netflix) | Custom-built for massive scale |

**Key properties:**

1. **Immutable (write-once, read-many)** -- videos uploaded once, read millions of times. Don't "edit" a blob, upload a new version.

2. **Chunking** -- large files split into chunks (64-256MB blocks):
   - Enables parallel uploads/downloads
   - Enables resumable uploads (re-upload only failed chunk)
   - Enables streaming from any offset (seek to minute 45)

3. **Replication** -- each chunk replicated (typically 3 copies) across different nodes/racks/data centers. This is how "no uploaded video should ever be lost" is achieved.

4. **Flat namespace** -- no directory hierarchy. Objects addressed by key:
   ```
   videos/2024/03/abc123/720p.mp4
   videos/2024/03/abc123/1080p.mp4
   videos/2024/03/abc123/thumb_001.jpg
   ```

**Upload + viewing flow:**

```
Upload:
  Client -> Web Server -> App Server -> Queue -> Encoder
    -> encodes to 360p, 720p, 1080p
    -> stores all in BLOB Storage
    -> paths saved in Metadata DB

Viewing:
  Client -> CDN (cache hit?) -> if miss -> BLOB Storage -> serve + cache at CDN
```

**When to use what:**

| Use Case | Storage Type |
|---|---|
| Video/audio/image files | **BLOB storage** |
| Video metadata (title, views, likes) | **SQL database** (MySQL) |
| Thumbnails (small, high read traffic) | **Bigtable** + cache |
| User profiles | **SQL database** |
| Search index | **Elasticsearch / inverted index** |

**Core principle:** Store structured data in databases, store binary blobs in blob storage, link them with a reference (path/URL).

### BLOB Storage Internals -- How It Actually Works

#### 1. How a Video Gets Stored

A 2GB video is NOT saved as a single file on one disk. Three steps:

**Chunking:** File split into fixed-size chunks (typically 64MB-256MB):

```
2GB video file
    ├── Chunk 0:   bytes 0          - 67,108,863       (64MB)
    ├── Chunk 1:   bytes 67,108,864 - 134,217,727      (64MB)
    ├── Chunk 2:   bytes 134,217,728 - 201,326,591     (64MB)
    │   ...
    └── Chunk 31:  bytes 2,013,265,920 - 2,147,483,647 (last chunk)
```

**Replication:** Each chunk replicated (typically 3 copies) across different machines, racks, and data centers:

```
Chunk 0 ──> Copy A: Node 5,  Rack 2, DC-East
         ──> Copy B: Node 12, Rack 7, DC-East
         ──> Copy C: Node 31, Rack 3, DC-West
```

Placement is intentional -- different racks/DCs so a single rack power failure doesn't lose all copies.

**Metadata Registration:** A metadata server (Name Node in HDFS, Master in GFS) records where every chunk lives:

```
File: videos/abc123/1080p.mp4
Size: 2,147,483,647 bytes | Chunks: 32 | Chunk size: 64MB

Chunk Index │ Chunk ID     │ Replicas (node:disk)
────────────┼──────────────┼──────────────────────────────
0           │ chk_a9f3e1   │ node5:/disk2, node12:/disk1, node31:/disk4
1           │ chk_b2c4d7   │ node8:/disk3, node22:/disk1, node14:/disk2
...         │ ...          │ ...
31          │ chk_f1a2b3   │ node11:/disk2, node25:/disk1, node7:/disk3
```

This metadata is small (few KB per file), kept in memory for fast lookups.

#### 2. How a Video Gets Fetched (Full Playback)

```
Client                    Metadata Server              Chunk Servers
  │                            │                            │
  │  1. GET video abc123       │                            │
  │───────────────────────────>│                            │
  │                            │                            │
  │  2. Chunk map:             │                            │
  │     Chunk 0: node5,node12  │                            │
  │     Chunk 1: node8,node22  │                            │
  │<───────────────────────────│                            │
  │                            │                            │
  │  3. Give me Chunk 0        │                            │
  │────────────────────────────────────────────────────────>│ (node5)
  │  4. Here's 64MB of data    │                            │
  │<────────────────────────────────────────────────────────│
  │  5. Give me Chunk 1 (pipelined while playing Chunk 0)   │
  │────────────────────────────────────────────────────────>│ (node8)
```

Client **pipelines** requests -- requests Chunk 1 while still receiving Chunk 0, so no gap in playback. Replica selection picks the closest/fastest node based on network topology or latency.

#### 3. How Seeking to Any Minute Works

When a user drags the slider to minute 45:

**Step 1: Calculate byte offset via video index**

Videos use container formats (MP4, WebM) with an **index table** (`moov atom` in MP4, `cues` in WebM) mapping timestamps to byte positions:

```
MP4 Index (moov atom):
  Time 0:00  -> byte 0
  Time 0:05  -> byte 2,341,888
  Time 45:00 -> byte 1,428,357,120
```

Client reads this index first (it's small, at start or end of file).

**Step 2: Calculate which chunk**

```
Target byte: 1,428,357,120
Chunk size:  67,108,864 (64MB)

Chunk number = 1,428,357,120 / 67,108,864 = Chunk 21
Offset within chunk = 1,428,357,120 % 67,108,864 = 17,571,456 bytes in
```

**Step 3: Fetch from that chunk with an offset**

```
Client to Metadata Server: "Where is Chunk 21 of video abc123?"
Server: "node19, node27, node7"

Client to node19: "Give me Chunk 21 starting at byte 17,571,456"
                   (HTTP Range Request: Range: bytes=17571456-)
```

Chunk server does a **disk seek** directly to that position. No need to read chunks 0-20. This is why seeking is nearly instant.

#### 4. How Resumable Uploads Work

If connection drops at 60% of a 2GB upload:

```
Before disconnect:
  Chunk 0-18:  ✅ uploaded + acknowledged
  Chunk 19:    ❌ partially uploaded (connection died)
  Chunk 20-31: not started

On reconnect:
  Client: "What chunks do you have for upload session xyz?"
  Server: "Chunks 0-18 complete, Chunk 19 incomplete"
  Client: "OK, re-uploading from Chunk 19"
```

Only ~64MB re-uploaded, not the 1.2GB already transferred. Each chunk has a **checksum** (MD5/SHA) -- server verifies integrity before acknowledging.

#### 5. How Replication and Consistency Work

**Write path (chain replication):**

```
Client writes Chunk 0:
  Client ──> Primary (node5)
              ├──> Secondary (node12)     [primary forwards]
              │       └──> Tertiary (node31)  [secondary forwards]
              └── All 3 ACK back ──> client gets success
```

Write only acknowledged when all replicas confirm. Ensures durability.

**Read path:** Pick any replica directly. Since chunks are immutable (never modified after write), any replica is always correct. No consistency problems.

**Failure recovery:**

```
node12 disk dies
  → Metadata server detects: "Chunk 0 has only 2 replicas"
  → Triggers re-replication: read from node5, write new copy to node40
  → Update metadata: replicas = node5, node31, node40
```

Happens automatically in the background. System self-heals.

#### 6. How It Scales

```
Adding capacity = adding nodes:
  Before: 100 nodes, 500TB total
  After:  120 nodes, 600TB total
  New uploads land on new nodes (least-loaded placement)
  Existing data optionally rebalanced in background
```

**No single bottleneck:**
- Metadata server: chunk map in memory (~100 bytes per chunk, billions fit in RAM)
- Chunk servers: each independently serves reads/writes from local disks
- Client talks directly to chunk servers for data -- metadata server only consulted for lookups

#### Complete Picture Summary

```
UPLOAD:  2GB file → split 32 × 64MB chunks → each replicated 3x
         → metadata registered → checksum verified

PLAY:    Get chunk map → fetch chunks sequentially from nearest replicas
         → pipeline requests (fetch next while playing current)

SEEK:    45:00 → MP4 index → byte 1.4GB → Chunk 21 offset 17MB
         → fetch directly → instant seek, no wasted transfer

FAILURE: Node dies → detect under-replicated → re-replicate from survivors
         → self-heals, no manual intervention

SCALE:   Add nodes → new data flows automatically → optional rebalance
```

---

## Streaming Protocols for Video Delivery

**Source:** dacast.com/blog/streaming-protocols/ (2026 Update)

### What is a Streaming Protocol?

A set of rules that moves video/audio across the internet -- from encoder/camera to platform, CDN, and player. Determines **how media is transported**, latency behavior, and playback reliability at scale.

**Key distinctions:**
- **Codec** = compress/decompress (H.264, HEVC, AV1)
- **Protocol** = transport rules (HLS, DASH, WebRTC, SRT)
- **Format/Container** = package holding compressed video + audio + metadata (MP4, MPEG-TS)

### TL;DR -- Most 2026 Workflows Are Hybrid

- **RTMP or SRT** for ingest/contribution (encoder -> platform)
- **HLS or DASH** for large-scale delivery (platform -> viewers via CDN)
- **WebRTC** for ultra-low latency interactivity (sub-second)
- **LL-HLS/CMAF** sits in the middle (near-real-time without WebRTC complexity)

### The 7 Protocols

#### 1. HLS (HTTP Live Streaming)

| Aspect | Detail |
|---|---|
| **Developed by** | Apple |
| **How it works** | Splits video into small segments, delivers over HTTP. Player downloads M3U8 playlist listing available segments. Supports adaptive bitrate (ABR) |
| **Latency** | High (15-30s traditional) or ~2s with LL-HLS |
| **Compatibility** | Excellent -- iOS, macOS, smart TVs, all major browsers |
| **Codecs** | H.264, H.265/HEVC; AAC, MP3 |
| **Security** | Good (HTTPS, AES-128, FairPlay/Widevine/PlayReady DRM) |
| **Best for** | Large-scale live events, OTT delivery, VOD |
| **Weakness** | True sub-second real-time still needs WebRTC. LL-HLS requires full chain support (player + CDN + origin) |

#### 2. RTMP (Real-Time Messaging Protocol)

| Aspect | Detail |
|---|---|
| **Developed by** | Macromedia/Adobe |
| **How it works** | Persistent TCP connection between encoder and server. Originally for Flash Player (dead), now lives on as **ingest protocol** |
| **Latency** | Low (~2-5s) |
| **Compatibility** | Limited for playback (Flash dead), universally supported for **ingest** (OBS, hardware encoders) |
| **Codecs** | H.264, x264; AAC |
| **Security** | Basic (RTMPS adds TLS) |
| **Best for** | Encoder -> platform ingest. Most common pattern: **RTMP ingest + HLS delivery** |
| **Weakness** | Cannot be used for modern playback. Vulnerable to hijacking without TLS |

#### 3. SRT (Secure Reliable Transport)

| Aspect | Detail |
|---|---|
| **Developed by** | Haivision (open-source) |
| **How it works** | UDP-based with adaptive retransmission and forward error correction (FEC). Handles jitter, packet loss, bandwidth fluctuations |
| **Latency** | Very low (~1-2s) |
| **Compatibility** | Growing but not universal. Requires SRT-compatible software/hardware |
| **Codecs** | Codec-agnostic (any video/audio codec) |
| **Security** | Excellent (built-in AES 128/256-bit encryption) |
| **Best for** | Remote production, field contribution over public internet |
| **Weakness** | Ecosystem still catching up. Not all encoders/platforms support natively |

#### 4. MSS (Microsoft Smooth Streaming)

| Aspect | Detail |
|---|---|
| **Developed by** | Microsoft (2008) |
| **How it works** | ABR streaming using MP4 fragments over HTTP |
| **Latency** | Medium (~2-4s) |
| **Status** | **Obsolete.** Died with Silverlight (discontinued 2021) |
| **Historical note** | Powered NBC's 2008 Olympics. Case study of how proprietary dependencies kill protocols |

#### 5. MPEG-DASH (Dynamic Adaptive Streaming over HTTP)

| Aspect | Detail |
|---|---|
| **Developed by** | MPEG (open standard) |
| **How it works** | ABR streaming over HTTP using MPD manifest. Codec-agnostic and DRM-flexible |
| **Latency** | Medium to high (~5-20s) |
| **Compatibility** | Excellent everywhere **except iOS Safari**. Android, smart TVs, YouTube, Netflix |
| **Codecs** | H.264, H.265, VP9/VP10, AV1; AAC, MP3 |
| **Security** | Good (Widevine, PlayReady DRM) |
| **Best for** | OTT distribution, smart TV ecosystems, multi-DRM delivery |
| **Weakness** | No native iOS Safari support. Many stacks run **HLS + DASH** for full reach |

#### 6. WebRTC (Web Real-Time Communication)

| Aspect | Detail |
|---|---|
| **Developed by** | Google (open standard, W3C/IETF) |
| **How it works** | Peer-to-peer (or via SFU) using UDP. Built into browsers. STUN/TURN for NAT traversal |
| **Latency** | Ultra-low (<0.5s) |
| **Compatibility** | All modern browsers, Android, iOS |
| **Codecs** | H.264, VP8/VP9; Opus |
| **Security** | Strong (DTLS + SRTP built-in) |
| **Best for** | Video calls, live auctions, betting, live shopping, two-way classrooms |
| **Weakness** | Complex (signaling servers, STUN/TURN). Scaling to large audiences harder than HLS/DASH |
| **2026 update** | **WHIP** (ingest) now an RFC; **WHEP** (egress) IETF draft -- standardize WebRTC over HTTP |

#### 7. RTSP (Real-Time Streaming Protocol)

| Aspect | Detail |
|---|---|
| **How it works** | Session control protocol, paired with RTP for media transport |
| **Latency** | Low (~2-10s) |
| **Compatibility** | VLC, QuickTime, embedded systems, IP cameras |
| **Codecs** | H.264, H.265, MJPEG; AAC, G.711 |
| **Best for** | IP cameras, surveillance, private monitoring |
| **Weakness** | Frequently misconfigured (default passwords, exposed ports). High vulnerability |

### Protocol Matching by Role

| Workflow Stage | Best Protocols |
|---|---|
| **Capture/Ingest** | RTMP, SRT, RTSP |
| **Transcoding** | MPEG-TS, CMAF |
| **Delivery** | HLS, MPEG-DASH, WebRTC |
| **Playback** | HTML5 (HLS/DASH), Native (WebRTC), Media Players (RTSP) |

### Common Hybrid Workflows

**A -- Classic scalable live:**
```
Encoder (RTMP) → Platform → HLS/DASH via CDN → HTML5 player
```

**B -- Resilient contribution + real-time viewing:**
```
Camera (SRT) → Media server → WebRTC (or LL-HLS) → viewers
```

**C -- OTT delivery:**
```
Contribution → Packaging (DASH + DRM, HLS for iOS) → CDN → device apps/TVs
```

### 2026 Protocol Innovations

**LL-CMAF (Low-Latency Common Media Application Format):**
- Smaller chunks streamed before segment fully encoded
- Reduces latency to 3-7s (vs. 10-30s traditional)
- Works with existing CDNs and HTML5 players
- Single media files for both HLS and DASH

**WHIP/WHEP (WebRTC over HTTP/3):**
- Standardizes WebRTC ingest (WHIP) and egress (WHEP) over HTTP
- Built on QUIC/HTTP/3
- Sub-second latency, easier integration than raw WebRTC

**HESP (High-Efficiency Streaming Protocol):**
- Dual-stream approach (low-latency + high-quality)
- 1-2s latency with ABR support, scales to millions
- Supports DRM, SSAI (server-side ad insertion)
- Bridges real-time interactivity and broadcast scale

### Security Comparison

| Protocol | Encryption | DRM | Vulnerabilities |
|---|---|---|---|
| **HLS** | HTTPS, AES-128 | FairPlay, Widevine, PlayReady | Low |
| **RTMP** | Partial (RTMPS) | No | Medium |
| **SRT** | Built-in AES | No | Low |
| **MPEG-DASH** | HTTPS | Widevine, PlayReady | Low |
| **WebRTC** | DTLS + SRTP | No | Low (most secure) |
| **RTSP** | Optional (RTSPS) | No | High |

### How This Connects to YouTube/Netflix Design

In the YouTube system design above:
- **Upload/Ingest:** RTMP or SRT from encoder to platform
- **Encoding:** Transcode to multiple formats/resolutions (360p, 720p, 1080p) stored in BLOB storage
- **Delivery:** HLS or DASH segments served via CDN to viewers
- **Seeking:** Works because HLS/DASH segments are small (2-10s each) with playlist manifests mapping time -> segment. Player requests the right segment directly
- **Adaptive bitrate:** Player monitors bandwidth and switches between quality levels mid-stream using the manifest

---
