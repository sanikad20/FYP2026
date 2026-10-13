# Week 2 Implementation Report — Semantic Cache (CacheMind Core)

> **Project:** Campus Chat  
> **Milestone:** Week 2 Checkpoint Completed (Days 1–7)  
> **Final Status:** CacheMind Core operational with Redis vector store, cosine similarity matching, pipeline integration, and hit/miss logging verified end-to-end.

---

## 1. Executive Summary

During Week 2, we designed and built **CacheMind Core**, the intelligent semantic caching layer for Campus Chat:
- Reused the local **`all-MiniLM-L6-v2`** embedding model (384-dimensional) from ChromaDB without introducing new dependencies.
- Implemented **vectorized NumPy cosine similarity** over query embeddings persisted in Redis.
- Configured a similarity threshold (`0.85`), successfully triggering cache hits on natural language paraphrases (e.g., *"where's the library"* vs *"library location?"* achieving **0.8742** similarity).
- Wired CacheMind directly in front of the chat execution pipeline (`/api/chat` and `/api/chat/stream`), bypassing expensive RAG/SQL/LLM operations upon cache hits and achieving a **5.4x latency speedup** (from ~70ms down to ~12ms).
- Added structured **hit/miss logging** and metrics endpoints (`/api/cache/stats`, `/api/cache/logs`, `/api/cache/clear`, and integrated `/api/admin/status`) required for the Week 8 performance comparison.

---

## 2. Daily Deliverables & Implementation Details

### Day 1–2: Embedding Model Selection & Reuse
- **Model Selected:** `all-MiniLM-L6-v2` (via `langchain_community.embeddings.HuggingFaceEmbeddings`).
- **Rationale:** Already pre-cached and used by ChromaDB; runs 100% locally on CPU without external API calls or network egress (`HF_HUB_OFFLINE=1`).
- **Vector Dimensions:** 384 floating-point elements.
- **Normalization:** Vectors are $L_2$-normalized upon embedding to enable optimal dot-product cosine similarity.

### Day 3–4: Cache Lookup Layer (`cachemind.py`)
- Created `CacheMind` engine with Redis backing and in-memory fallback.
- **Redis Key Schema:**
  - `campus_chat:cache:entries` (Hash): Stores JSON metadata per query (`id`, `query`, `response`, `created_at`, `last_accessed`, `access_count`, `hit_count`, `ttl`).
  - `campus_chat:cache:vectors` (Hash): Stores 384-dimensional JSON vector representations.
  - `campus_chat:cache:logs` (List): Append-only list of recent 1,000 lookup events for audit and benchmarking.
  - `campus_chat:cache:stats` (Hash): Real-time metrics counters (`total_lookups`, `hits`, `misses`, `total_stores`, `total_lookup_time_ms`).
- **Cosine Similarity Engine:**
  - Vectorized multi-entry comparison:
    $$\text{Cosine Similarity}(u, v) = \frac{u \cdot v}{\|u\|_2 \|v\|_2}$$
  - Applied threshold gating (`CACHE_SIMILARITY_THRESHOLD=0.85` configurable via `.env`).

### Day 5: Pipeline Integration (`backend_api_original.py`)
- Integrated CacheMind at the entry of `/api/chat` and `/api/chat/stream` behind `@login_required`.
- **Cache Hit Workflow:**
  - Returns cached answer immediately with `"cached": True`, `"cache_similarity": score`, and `"cache_latency_ms": ms`.
  - Appends interaction to session history so subsequent multi-turn context remains intact.
  - Increments access frequency and recency timestamp (preparing Week 3 intelligence layer).
- **Cache Miss Workflow:**
  - Falls through to normal pipeline (faculty database lookup, direct PDF serve, navigation, SQL query, or RAG LLM generation).
  - Automatically persists successful answer and query embedding into Redis CacheMind.
  - Marks outgoing payload as `"cached": False`.

### Day 6–7: Hit/Miss Logging & Metrics Tracking
- **API Endpoints Added:**
  - `GET /api/cache/stats`: Returns JSON metrics including total queries, hits, misses, hit rate percentage, cached entry count, and average lookup latency.
  - `GET /api/cache/logs`: Returns structured event logs with query, matched query, similarity score, latency, and timestamp.
  - `POST /api/cache/clear`: Clears cache entries and resets statistics.
  - `GET /api/admin/status`: Diagnostic endpoint now includes full CacheMind telemetry.

---

## 3. Checkpoint Verification: Paraphrased Questions

| Test Case | Incoming Query | Matched Query | Similarity | Cache Status | Latency |
|---|---|---|---|---|---|
| Initial Query | `"where's the library"` | *(None - Empty Cache)* | 0.0000 | **MISS** (Stored) | 70.40 ms |
| Paraphrase 1 | `"library location?"` | `"where's the library"` | **0.8742** | **HIT** | **12.92 ms** |
| Paraphrase 2 | `"where is the library"` | `"where's the library"` | **1.0000** | **HIT** | **10.62 ms** |
| Dissimilar | `"what is the cutoff for computer engineering 2025?"` | `"where's the library"` | 0.0547 | **MISS** | 10.46 ms |

**Result:** Paraphrased query returned the exact cached answer with a **5.4x speedup** without invoking LLM or RAG.

---

## 4. Test Results

Automated test suites executed:

### Week 2 Test Suite (`test_week2.py`)
```
============================================================
  WEEK 2 TEST SUITE SUMMARY
============================================================
 ✓ Embeddings object exists
 ✓ Embeddings model name is all-MiniLM-L6-v2
 ✓ Embedding dimension is 384
 ✓ Embedding vector is non-zero and valid floats
 ✓ CacheMind clear() resets cache cleanly
 ✓ Empty cache returns MISS
 ✓ CacheMind store() returns valid entry_id
 ✓ Exact query returns HIT (similarity ~1.0)
 ✓ Paraphrased query 'library location?' returns HIT
 ✓ Dissimilar query returns MISS
 ✓ Cache entry metadata tracks hit_count and last_accessed
 ✓ Test user authenticated for chat
 ✓ Initial query returns HTTP 200
 ✓ Initial query is marked cached=False (Cache MISS)
 ✓ Cache entry count increased to 1
 ✓ Paraphrased query 'library location?' returns HTTP 200
 ✓ Paraphrased query is marked cached=True (Cache HIT)
 ✓ Cached response latency is significantly faster (<100ms)
 ✓ Cached response content matches initial reply
 ✓ Unrelated query in chat returns cached=False (MISS)
 ✓ /api/cache/stats returns HTTP 200
 ✓ Stats schema contains all required metric fields
 ✓ Stats accurately show lookups, hits, and misses
 ✓ /api/cache/logs returns HTTP 200
 ✓ Logs returned with correct structure
 ✓ Log entries contain required audit fields
 ✓ /api/cache/clear returns HTTP 200
 ✓ Stats reset to 0 after clear

Total: 28 | Passed: 28 | Failed: 0
🎉 ALL WEEK 2 TESTS PASSED PERFECTLY!
```

### Week 1 Regression Suite (`test_week1.py`)
```
Total: 41 | Passed: 41 | Failed: 0
🎉 ALL WEEK 1 TESTS PASSED PERFECTLY!
```

---

## 5. Files Created & Modified

| File | Status | Description |
|---|---|---|
| `cachemind.py` | **NEW** | Core CacheMind engine: Redis vector store, vectorized cosine similarity, hit/miss event logging, stats computation |
| `test_week2.py` | **NEW** | Automated test suite verifying Days 1–7 and paraphrase checkpoint |
| `WEEK2_IMPLEMENTATION_REPORT.md` | **NEW** | Comprehensive Week 2 milestone documentation |
| `backend_api_original.py` | **MODIFIED** | Wired CacheMind into `chat_endpoint` and `chat_stream_endpoint`; added `/api/cache/*` endpoints; added offline LLM fallbacks |
| `.env` / `.env.example` | **MODIFIED** | Added `CACHE_SIMILARITY_THRESHOLD=0.85` and `CACHE_DEFAULT_TTL=86400` |
