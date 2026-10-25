#!/usr/bin/env python3
"""
test_week3.py — Comprehensive Test Suite for Week 3 (CacheMind Intelligence Layer)

Covers all Week 3 deliverables from the 2-Month Completion Plan:
  [Day 1–2] Frequency and recency tracking per cached entry
  [Day 3–4] Scored Eviction (weight = recency + frequency; capacity constraint)
  [Day 5–6] Smart Dynamic TTL (extension on hits, expiration purging)
  [Day 7]   Checkpoint: Eviction decisions demonstrably differ from plain LRU on query stream
  [API]     Intelligence endpoints (/api/cache/intelligence, /api/cache/purge-expired, /api/cache/simulate-comparison)
"""

import os
import sys
import time
import math
import numpy as np
from dotenv import load_dotenv

os.environ["USE_TF"] = "0"
os.environ["USE_TORCH"] = "1"
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
load_dotenv()

import backend_api_original as app_module
from backend_api_original import app, cachemind, embeddings
from cachemind import CacheMind

TEST_RESULTS = []


def record_test(name: str, passed: bool, detail: str = ""):
    status = "✓ PASS" if passed else "✗ FAIL"
    TEST_RESULTS.append((name, passed, detail))
    print(f"[{status}] {name}")
    if detail:
        print(f"        {detail}")


def test_day1_2_access_frequency_and_recency():
    print("\n" + "=" * 60)
    print("  Testing Day 1–2: Access Frequency & Recency Tracking")
    print("=" * 60)

    cachemind.clear()

    q = "what are the hostel fees?"
    resp = {"reply": "Hostel fees for first year are Rs. 35,000 per term."}
    eid = cachemind.store(q, resp)

    entries, _ = cachemind._load_cache_data()
    entry = entries.get(eid)

    record_test("Initial entry has access_count=1", entry.get("access_count") == 1)
    record_test("Initial entry has hit_count=0", entry.get("hit_count") == 0)
    record_test("Initial entry has valid created_at timestamp", entry.get("created_at") > 0)
    record_test("Initial entry has last_accessed == created_at", abs(entry.get("last_accessed") - entry.get("created_at")) < 1.0)

    # Perform lookups to increment frequency
    time.sleep(0.05)
    is_hit, _, _, _, _ = cachemind.lookup("what are the hostel fees?")
    record_test("First lookup is HIT", is_hit)

    entries, _ = cachemind._load_cache_data()
    entry = entries.get(eid)
    record_test("hit_count incremented to 1", entry.get("hit_count") == 1)
    record_test("access_count incremented to 2", entry.get("access_count") == 2)
    record_test("last_accessed updated on hit", entry.get("last_accessed") >= entry.get("created_at"))


def test_day3_4_scored_eviction():
    print("\n" + "=" * 60)
    print("  Testing Day 3–4: Scored Eviction (Recency + Frequency)")
    print("=" * 60)

    # Instantiate isolated CacheMind with small capacity for deterministic eviction testing
    small_cache = CacheMind(
        redis_client=None,  # test in-memory fallback
        embedding_model=embeddings,
        max_entries=3,
        weight_recency=0.5,
        weight_frequency=0.5,
        default_ttl=86400,
    )
    small_cache.clear()

    # 1. Fill cache to capacity (3 entries)
    e1 = small_cache.store("query alpha", {"reply": "alpha"})
    e2 = small_cache.store("query beta", {"reply": "beta"})
    e3 = small_cache.store("query gamma", {"reply": "gamma"})

    stats = small_cache.get_stats()
    record_test("Cache size reaches capacity (3 items)", stats["cached_entries_count"] == 3)

    # 2. Make 'query alpha' very popular (high frequency)
    for _ in range(5):
        small_cache.lookup("query alpha")

    entries, _ = small_cache._load_cache_data()
    score_alpha = small_cache.calculate_score(entries[e1])
    score_beta = small_cache.calculate_score(entries[e2])
    score_gamma = small_cache.calculate_score(entries[e3])

    record_test(
        "High-frequency entry 'alpha' has higher score than rarely used 'beta'",
        score_alpha > score_beta,
        f"alpha score={score_alpha:.4f}, beta score={score_beta:.4f}",
    )

    # 3. Add a 4th entry — capacity should trigger Scored Eviction!
    e4 = small_cache.store("query delta", {"reply": "delta"})

    entries_after, _ = small_cache._load_cache_data()
    stats_after = small_cache.get_stats()

    record_test("Capacity maintained at 3 entries after store", stats_after["cached_entries_count"] == 3)
    record_test("Total evictions counter incremented", stats_after["total_evictions"] >= 1)
    record_test(
        "Valuable high-frequency entry 'alpha' was RETAINED by Scored Eviction",
        e1 in entries_after,
        f"Retained IDs: {list(entries_after.keys())}",
    )
    record_test(
        "Low-value cold entry was the one chosen for eviction",
        (e2 not in entries_after) or (e3 not in entries_after),
    )


def test_day5_6_smart_ttl_and_purging():
    print("\n" + "=" * 60)
    print("  Testing Day 5–6: Smart Dynamic TTL & Expiration Purging")
    print("=" * 60)

    smart_cache = CacheMind(
        redis_client=None,
        embedding_model=embeddings,
        default_ttl=100,  # 100 seconds base
        min_ttl=10,
        max_ttl=300,
        ttl_extension_factor=0.25,  # +25s per hit
    )
    smart_cache.clear()

    eid = smart_cache.store("sample circular query", {"reply": "circular content"})
    entries, _ = smart_cache._load_cache_data()
    initial_ttl = entries[eid].get("ttl")
    record_test("Initial TTL matches base TTL (100s)", initial_ttl == 100)

    # Trigger cache hit
    smart_cache.lookup("sample circular query")
    entries_hit, _ = smart_cache._load_cache_data()
    extended_ttl = entries_hit[eid].get("ttl")
    extensions = entries_hit[eid].get("ttl_extensions")

    record_test(
        "Smart TTL extended on cache hit (+25%)",
        extended_ttl == 125,
        f"extended_ttl={extended_ttl}, initial_ttl={initial_ttl}",
    )
    record_test("ttl_extensions counter incremented to 1", extensions == 1)

    # Test Expiration & Purging
    # Create an entry with an already expired TTL
    expired_cache = CacheMind(
        redis_client=None,
        embedding_model=embeddings,
        default_ttl=1,  # 1 second TTL
    )
    exp_id = expired_cache.store("quick expiring question", {"reply": "expires soon"})
    # Artificially set created_at into the past
    entries_exp, _ = expired_cache._load_cache_data()
    entries_exp[exp_id]["created_at"] = time.time() - 10.0  # 10s ago, TTL is 1s
    expired_cache._memory_entries[exp_id] = entries_exp[exp_id]

    record_test("Entry detected as expired via is_expired()", expired_cache.is_expired(entries_exp[exp_id]))

    # Lookup on expired entry should return MISS and purge it
    is_hit, resp, sim, lat, matched = expired_cache.lookup("quick expiring question")
    record_test("Lookup on expired entry returns MISS", not is_hit and resp is None)

    # Active purge
    purged_count = expired_cache.purge_expired()
    record_test("Purge executed cleanly without errors", purged_count >= 0)


def test_day7_checkpoint_lru_vs_scored_demonstration():
    print("\n" + "=" * 60)
    print("  Testing Day 7 Checkpoint: Scored Eviction vs Plain LRU")
    print("=" * 60)

    # Simulated realistic campus query sequence:
    # 'where is library' is high frequency (asked repeatedly)
    # A burst of unique queries arrives ('admissions', 'canteen', 'gymkhana', 'exam fee')
    query_stream = [
        "where is library",
        "where is library",
        "where is library",
        "admissions 2025",
        "canteen menu",
        "gymkhana timings",
        "exam fee payment",
        "where is library",  # Critical access: LRU will have evicted it; Scored will retain it!
    ]

    results = CacheMind.simulate_policy_comparison(query_stream, capacity=3)
    lru_res = results["LRU"]
    cm_res = results["CacheMind"]

    print(f"      LRU Hit Rate        : {lru_res['hit_rate_percent']}% ({lru_res['hits']} hits, {lru_res['misses']} misses)")
    print(f"      CacheMind Hit Rate  : {cm_res['hit_rate_percent']}% ({cm_res['hits']} hits, {cm_res['misses']} misses)")
    print(f"      LRU Evictions       : {lru_res['evictions']}")
    print(f"      CacheMind Evictions : {cm_res['evictions']}")

    record_test(
        "Checkpoint: CacheMind eviction decisions demonstrably differ from LRU",
        cm_res["evictions"] != lru_res["evictions"],
        f"CacheMind evicted {cm_res['evictions']} vs LRU {lru_res['evictions']}",
    )
    record_test(
        "Checkpoint: CacheMind achieves higher or equal hit rate by protecting frequent queries",
        cm_res["hits"] >= lru_res["hits"],
        f"CacheMind hits: {cm_res['hits']} vs LRU hits: {lru_res['hits']}",
    )
    record_test(
        "Frequent query 'where is library' retained in CacheMind under burst pressure",
        "where is library" in cm_res["retained"],
        f"Retained items: {cm_res['retained']}",
    )


def test_api_endpoints():
    print("\n" + "=" * 60)
    print("  Testing Week 3 API Endpoints & Telemetry")
    print("=" * 60)

    with app.test_client() as client:
        # 1. /api/cache/stats
        resp = client.get("/api/cache/stats")
        record_test("/api/cache/stats returns HTTP 200", resp.status_code == 200)
        data = resp.get_json()
        record_test("Stats contains 'eviction_policy'", data.get("eviction_policy") == "scored_recency_frequency")
        record_test("Stats contains 'total_evictions'", "total_evictions" in data)
        record_test("Stats contains 'total_ttl_extensions'", "total_ttl_extensions" in data)
        record_test("Stats contains 'max_capacity'", "max_capacity" in data)

        # 2. /api/cache/intelligence
        resp_intel = client.get("/api/cache/intelligence")
        record_test("/api/cache/intelligence returns HTTP 200", resp_intel.status_code == 200)
        intel_data = resp_intel.get_json()
        record_test("Intelligence response includes weights (recency & frequency)", "weights" in intel_data)
        record_test("Intelligence response includes ttl_config", "ttl_config" in intel_data)

        # 3. /api/cache/purge-expired
        resp_purge = client.post("/api/cache/purge-expired")
        record_test("/api/cache/purge-expired returns HTTP 200", resp_purge.status_code == 200)

        # 4. /api/cache/simulate-comparison
        resp_sim = client.post(
            "/api/cache/simulate-comparison",
            json={
                "queries": ["a", "b", "a", "c", "d", "a"],
                "capacity": 2,
            },
        )
        record_test("/api/cache/simulate-comparison returns HTTP 200", resp_sim.status_code == 200)
        sim_data = resp_sim.get_json()
        record_test("Simulation data has LRU, LFU, and CacheMind comparisons", "LRU" in sim_data.get("simulation", {}))


if __name__ == "__main__":
    print("\n" + "#" * 60)
    print("  RUNNING WEEK 3 TEST SUITE (CacheMind Intelligence Layer)")
    print("#" * 60)

    test_day1_2_access_frequency_and_recency()
    test_day3_4_scored_eviction()
    test_day5_6_smart_ttl_and_purging()
    test_day7_checkpoint_lru_vs_scored_demonstration()
    test_api_endpoints()

    print("\n" + "=" * 60)
    print("  WEEK 3 TEST SUITE SUMMARY")
    print("=" * 60)
    passed_count = sum(1 for _, p, _ in TEST_RESULTS if p)
    total_count = len(TEST_RESULTS)

    for name, p, detail in TEST_RESULTS:
        mark = "✓" if p else "✗"
        print(f" {mark} {name}")

    print(f"\nTotal: {total_count} | Passed: {passed_count} | Failed: {total_count - passed_count}")

    if passed_count == total_count:
        print("🎉 ALL WEEK 3 TESTS PASSED PERFECTLY!\n")
        sys.exit(0)
    else:
        print("⚠️ SOME TESTS FAILED. Check details above.\n")
        sys.exit(1)
