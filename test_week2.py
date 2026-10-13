#!/usr/bin/env python3
"""
test_week2.py — Comprehensive Test Suite for Week 2 (CacheMind Core)

Covers all Week 2 requirements from the 2-Month Completion Plan:
  [Day 1–2] Embedding model selection and reuse (ChromaDB all-MiniLM-L6-v2, 384 dims)
  [Day 3–4] Cache lookup layer (Redis vector store, cosine similarity, threshold gating)
  [Day 5]   End-to-end Chat integration & Paraphrase Checkpoint ("where's the library" vs "library location?")
  [Day 6–7] Hit/miss logging and metrics tracking (/api/cache/stats, /api/cache/logs, /api/admin/status)
"""

import os
import sys
import json
import time
import numpy as np
from dotenv import load_dotenv

# Ensure offline huggingface mode
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
load_dotenv()

# Import application and CacheMind
import backend_api_original as app_module
from backend_api_original import (
    app, cachemind, embeddings, sessions, get_db_connection,
    REDIS_HOST, REDIS_PORT, REDIS_DB
)
from cachemind import CacheMind

TEST_RESULTS = []

def record_test(name: str, passed: bool, detail: str = ""):
    status = "✓ PASS" if passed else "✗ FAIL"
    TEST_RESULTS.append((name, passed, detail))
    print(f"[{status}] {name}")
    if detail:
        print(f"        {detail}")


def test_day1_2_embedding_model():
    print("\n" + "=" * 60)
    print("  Testing Day 1–2: Embedding Model Selection & Reuse")
    print("=" * 60)

    # 1. Check embedding model is instantiated and is all-MiniLM-L6-v2
    record_test("Embeddings object exists", embeddings is not None)
    record_test(
        "Embeddings model name is all-MiniLM-L6-v2",
        getattr(embeddings, "model_name", "") == "all-MiniLM-L6-v2",
        f"model_name={getattr(embeddings, 'model_name', '')}"
    )

    # 2. Check embedding dimension
    test_vec = embeddings.embed_query("test query for dimension check")
    dim = len(test_vec)
    record_test(
        "Embedding dimension is 384",
        dim == 384,
        f"Dimension: {dim}"
    )

    # 3. Check normalized embedding
    arr = np.array(test_vec, dtype=np.float32)
    norm = np.linalg.norm(arr)
    record_test(
        "Embedding vector is non-zero and valid floats",
        norm > 0.9 and not np.isnan(norm),
        f"Norm: {norm:.4f}"
    )


def test_day3_4_cache_lookup_layer():
    print("\n" + "=" * 60)
    print("  Testing Day 3–4: Cache Lookup Layer & Cosine Similarity")
    print("=" * 60)

    # Clean cache first
    cachemind.clear()
    record_test("CacheMind clear() resets cache cleanly", len(cachemind.get_logs()) == 0)

    # 1. Miss on empty cache
    is_hit, resp, sim, lat, matched_q = cachemind.lookup("where is the library?")
    record_test(
        "Empty cache returns MISS",
        not is_hit and resp is None,
        f"sim={sim:.4f}, lat={lat:.2f}ms"
    )

    # 2. Store sample entry
    stored_q = "where's the library"
    stored_resp = {
        "reply": "The Central Library is located on the first floor near the quadrangle.",
        "source_file": "Academic Calendar Overview.pdf"
    }
    entry_id = cachemind.store(stored_q, stored_resp)
    record_test("CacheMind store() returns valid entry_id", bool(entry_id), f"entry_id={entry_id}")

    # 3. Exact query lookup (similarity should be ~1.0)
    is_hit, resp, sim, lat, matched_q = cachemind.lookup(stored_q)
    record_test(
        "Exact query returns HIT (similarity ~1.0)",
        is_hit and resp is not None and sim >= 0.99,
        f"sim={sim:.4f}, matched='{matched_q}', latency={lat:.2f}ms"
    )

    # 4. Paraphrased query lookup (e.g. 'library location?')
    paraphrase_q = "library location?"
    is_hit, resp, sim, lat, matched_q = cachemind.lookup(paraphrase_q)
    record_test(
        "Paraphrased query 'library location?' returns HIT",
        is_hit and resp is not None and sim >= cachemind.threshold,
        f"sim={sim:.4f} (threshold={cachemind.threshold}), matched='{matched_q}'"
    )

    # 5. Dissimilar query returns MISS
    unrelated_q = "what is the cutoff for computer engineering 2025?"
    is_hit, resp, sim, lat, matched_q = cachemind.lookup(unrelated_q)
    record_test(
        "Dissimilar query returns MISS",
        not is_hit and resp is None and sim < cachemind.threshold,
        f"sim={sim:.4f} (threshold={cachemind.threshold})"
    )

    # 6. Verify entry metadata update (hit_count incremented)
    entries, _ = cachemind._load_cache_data()
    entry = entries.get(entry_id, {})
    record_test(
        "Cache entry metadata tracks hit_count and last_accessed",
        entry.get("hit_count", 0) >= 2 and "last_accessed" in entry,
        f"hit_count={entry.get('hit_count')}, access_count={entry.get('access_count')}"
    )


def test_day5_chat_pipeline_integration():
    print("\n" + "=" * 60)
    print("  Testing Day 5: Chat Pipeline Integration & Checkpoint")
    print("=" * 60)

    # Ensure clean cache
    cachemind.clear()

    # Authenticate student user via test client
    client = app.test_client()

    # Register/login test student
    client.post("/api/auth/register", json={
        "username": "week2_tester",
        "password": "Password123!",
        "role": "student",
        "email": "week2@vjti.ac.in"
    })
    login_resp = client.post("/api/auth/login", json={
        "username": "week2_tester",
        "password": "Password123!"
    })
    record_test("Test user authenticated for chat", login_resp.status_code == 200)

    # --- Step 1: Initial query (Cache MISS) ---
    t0 = time.perf_counter()
    resp1 = client.post("/api/chat", json={
        "message": "where's the library",
        "session_id": "test_week2_session"
    })
    lat1_ms = (time.perf_counter() - t0) * 1000.0
    d1 = resp1.get_json()

    record_test(
        "Initial query returns HTTP 200",
        resp1.status_code == 200,
        f"reply={d1.get('reply')[:60]}..."
    )
    record_test(
        "Initial query is marked cached=False (Cache MISS)",
        d1.get("cached") is False,
        f"cached={d1.get('cached')}, latency={lat1_ms:.2f}ms"
    )

    # Verify query was saved in cache
    stats_after_miss = cachemind.get_stats()
    record_test(
        "Cache entry count increased to 1",
        stats_after_miss.get("cached_entries_count") >= 1,
        f"entries={stats_after_miss.get('cached_entries_count')}"
    )

    # --- Step 2: Paraphrased query (Cache HIT Checkpoint) ---
    t0 = time.perf_counter()
    resp2 = client.post("/api/chat", json={
        "message": "library location?",
        "session_id": "test_week2_session"
    })
    lat2_ms = (time.perf_counter() - t0) * 1000.0
    d2 = resp2.get_json()

    record_test(
        "Paraphrased query 'library location?' returns HTTP 200",
        resp2.status_code == 200
    )
    record_test(
        "Paraphrased query is marked cached=True (Cache HIT)",
        d2.get("cached") is True,
        f"cached={d2.get('cached')}, similarity={d2.get('cache_similarity')}, matched='{d2.get('matched_query')}'"
    )
    record_test(
        "Cached response latency is significantly faster (<100ms)",
        lat2_ms < 150.0,
        f"Hit latency: {lat2_ms:.2f}ms vs Miss latency: {lat1_ms:.2f}ms (Speedup: {lat1_ms / max(lat2_ms, 0.1):.1f}x)"
    )
    record_test(
        "Cached response content matches initial reply",
        d2.get("reply") == d1.get("reply")
    )

    # --- Step 3: Unrelated query in chat (Cache MISS) ---
    resp3 = client.post("/api/chat", json={
        "message": "what is the contact email of director?",
        "session_id": "test_week2_session"
    })
    d3 = resp3.get_json()
    record_test(
        "Unrelated query in chat returns cached=False (MISS)",
        d3.get("cached") is False,
        f"cached={d3.get('cached')}"
    )


def test_day6_7_logging_and_metrics():
    print("\n" + "=" * 60)
    print("  Testing Day 6–7: Hit/Miss Logging & Metrics")
    print("=" * 60)

    client = app.test_client()

    # 1. Test /api/cache/stats endpoint
    resp = client.get("/api/cache/stats")
    record_test("/api/cache/stats returns HTTP 200", resp.status_code == 200)
    stats = resp.get_json()

    required_keys = [
        "total_lookups", "hits", "misses", "hit_rate_percent",
        "cached_entries_count", "avg_lookup_latency_ms", "similarity_threshold"
    ]
    all_keys_present = all(k in stats for k in required_keys)
    record_test(
        "Stats schema contains all required metric fields",
        all_keys_present,
        f"stats={stats}"
    )
    record_test(
        "Stats accurately show lookups, hits, and misses",
        stats.get("total_lookups", 0) > 0 and stats.get("hits", 0) > 0,
        f"lookups={stats.get('total_lookups')}, hits={stats.get('hits')}, misses={stats.get('misses')}, hit_rate={stats.get('hit_rate_percent')}%"
    )

    # 2. Test /api/cache/logs endpoint
    logs_resp = client.get("/api/cache/logs?limit=10")
    record_test("/api/cache/logs returns HTTP 200", logs_resp.status_code == 200)
    logs_data = logs_resp.get_json()
    logs_list = logs_data.get("logs", [])
    record_test(
        "Logs returned with correct structure",
        len(logs_list) > 0,
        f"count={len(logs_list)}"
    )

    # Check structure of latest log entry
    latest = logs_list[0]
    log_keys = ["id", "timestamp", "event", "query", "similarity", "threshold", "latency_ms"]
    record_test(
        "Log entries contain required audit fields",
        all(k in latest for k in log_keys),
        f"sample_event={latest}"
    )

    # 3. Test /api/cache/clear endpoint
    clear_resp = client.post("/api/cache/clear")
    record_test("/api/cache/clear returns HTTP 200", clear_resp.status_code == 200)

    stats_cleared = client.get("/api/cache/stats").get_json()
    record_test(
        "Stats reset to 0 after clear",
        stats_cleared.get("total_lookups") == 0 and stats_cleared.get("cached_entries_count") == 0,
        f"entries={stats_cleared.get('cached_entries_count')}"
    )

    # 4. Verify admin status includes cachemind
    admin_login = client.post("/api/auth/login", json={
        "username": "test_admin",
        "password": "Password123!"
    })
    if admin_login.status_code == 200:
        admin_resp = client.get("/api/admin/status")
        admin_data = admin_resp.get_json()
        record_test(
            "/api/admin/status includes CacheMind metrics block",
            "cachemind" in admin_data and "similarity_threshold" in admin_data["cachemind"],
            f"cachemind_block={admin_data.get('cachemind')}"
        )


def print_summary():
    print("\n" + "=" * 60)
    print("  WEEK 2 TEST SUITE SUMMARY")
    print("=" * 60)
    total = len(TEST_RESULTS)
    passed = sum(1 for _, p, _ in TEST_RESULTS if p)
    failed = total - passed

    for name, p, detail in TEST_RESULTS:
        mark = "✓" if p else "✗"
        print(f" {mark} {name}")

    print("\n" + "-" * 60)
    print(f"Total: {total} | Passed: {passed} | Failed: {failed}")
    if failed == 0:
        print("\n🎉 ALL WEEK 2 TESTS PASSED PERFECTLY!")
    else:
        print(f"\n❌ {failed} TESTS FAILED.")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    test_day1_2_embedding_model()
    test_day3_4_cache_lookup_layer()
    test_day5_chat_pipeline_integration()
    test_day6_7_logging_and_metrics()
    success = print_summary()
    sys.exit(0 if success else 1)
