# Week 3 Implementation Report — CacheMind Intelligence Layer

> **Project:** Campus Chat  
> **Milestone:** Week 3 Checkpoint Completed (Days 1–7)  
> **Final Status:** CacheMind Intelligence Layer operational with Scored Eviction (Recency + Frequency), Smart Dynamic TTL, Capacity Enforcement, and LRU/LFU comparison verified end-to-end.

---

## 1. Executive Summary

During Week 3, we implemented the **Intelligence Layer** of CacheMind, transforming the semantic cache from a basic store-and-lookup mechanism into a self-tuning, capacity-aware cache:
- **Frequency & Recency Tracking:** Every cached query entry actively records `access_count`, `hit_count`, `created_at`, `last_accessed`, and `ttl_extensions`.
- **Scored Eviction Policy:** Replaced standard LRU eviction with a weighted multi-factor scoring formula:
  $$\text{Score} = w_r \cdot \text{Recency} + w_f \cdot \text{Frequency}$$
  Entries with the lowest utility score are evicted when cache capacity (`CACHE_MAX_ENTRIES`) is reached. High-value, frequently accessed queries are actively protected from burst evictions.
- **Smart Dynamic TTL:** Frequently accessed entries have their time-to-live extended on every cache hit (+25% base TTL per hit, up to a configurable ceiling of 7 days). Cold and rarely accessed queries decay naturally.
- **Expiration Purging:** Implemented both passive expiration detection on lookup and active sweeping (`purge_expired`).
- **Policy Comparison Simulation:** Added a comparative benchmarking engine testing CacheMind Scored Eviction vs. Plain LRU vs. Plain LFU on simulated query logs.
- **REST Endpoints Added:** Added `/api/cache/intelligence`, `/api/cache/purge-expired`, and `/api/cache/simulate-comparison`, while expanding `/api/cache/stats` with Week 3 telemetry.

---

## 2. Mathematical Formulation & Architecture

### Scored Eviction Formula
For any cached entry $e$ at time $t_{\text{now}}$:

1. **Recency Factor ($R \in (0, 1]$)**:
   Modeled with a continuous half-life decay function (1 hour half-life scale):
   $$R(e) = \frac{1}{1 + \frac{t_{\text{now}} - t_{\text{last\_accessed}}}{3600}}$$

2. **Frequency Factor ($F \in [0, 1]$)**:
   Modeled with sub-linear logarithmic scaling to reward high frequency without letting runaway items permanently monopolize the cache:
   $$F(e) = \frac{\ln(1 + \text{access\_count})}{\ln(1 + \max(\text{max\_access}, 10))}$$

3. **Combined CacheMind Score**:
   $$\text{Score}(e) = \left(\frac{w_r}{w_r + w_f}\right) \cdot R(e) + \left(\frac{w_f}{w_r + w_f}\right) \cdot F(e)$$
   *Default configuration:* $w_r = 0.5$, $w_f = 0.5$ (configurable via `CACHE_WEIGHT_RECENCY` and `CACHE_WEIGHT_FREQUENCY`).

### Smart Dynamic TTL Formula
When a cache hit occurs for entry $e$:
$$\text{TTL}_{\text{new}}(e) = \min\left(\text{TTL}_{\text{max}}, \; \text{TTL}_{\text{current}} + \lfloor \text{TTL}_{\text{base}} \times f_{\text{ext}} \rfloor\right)$$
*Parameters:*
- $\text{TTL}_{\text{base}}$ = 86,400s (24 hours)
- $\text{TTL}_{\text{max}}$ = 604,800s (7 days)
- $f_{\text{ext}}$ = 0.25 (+25% per hit)

---

## 3. Checkpoint Verification: CacheMind vs Plain LRU

To satisfy the **Week 3 Checkpoint** (*"eviction and TTL decisions demonstrably differ from plain LRU on the same query log"*), we simulated a realistic campus query sequence:
1. High-frequency baseline query: `"where is library"` accessed repeatedly.
2. Burst of four novel queries: `"admissions 2025"`, `"canteen menu"`, `"gymkhana timings"`, `"exam fee payment"`.
3. Re-access of the critical query: `"where is library"`.
4. Cache capacity constraint: 3 entries.

### Comparative Results:
| Policy | Total Hits | Total Misses | Hit Rate | Evicted Queries | Retained Queries |
|---|:---:|:---:|:---:|---|---|
| **Plain LRU** | 2 | 6 | **25.0%** | `where is library`, `admissions 2025`, `canteen menu` | `gymkhana timings`, `exam fee payment`, `where is library` (reloaded) |
| **Plain LFU** | 2 | 6 | **25.0%** | `where is library`, `admissions 2025`, `canteen menu` | `gymkhana timings`, `exam fee payment`, `where is library` (reloaded) |
| **CacheMind (Scored)** | **3** | **5** | **37.5%** | `admissions 2025`, `canteen menu` | **`where is library`**, `gymkhana timings`, `exam fee payment` |

**Key Finding:** Plain LRU evicted `"where is library"` as soon as the 3 burst queries arrived because its recency timestamp was older. CacheMind correctly computed a high retention score ($S \approx 0.9058$) due to its high frequency weight, protecting it from eviction and yielding a **+12.5% higher cache hit rate**.

---

## 4. API Endpoints

| Endpoint | Method | Description |
|---|:---:|---|
| `/api/cache/stats` | `GET` | Telemetry including hits, misses, `total_evictions`, `total_ttl_extensions`, `total_expired_purges`, and `eviction_policy`. |
| `/api/cache/intelligence` | `GET` | Policy metadata, recency/frequency weights, TTL config, and capacity limits. |
| `/api/cache/purge-expired` | `POST` | Triggers active sweep and removal of expired cache entries. |
| `/api/cache/simulate-comparison` | `POST` | Replays query streams through LRU, LFU, and CacheMind to compare hit rates and eviction choices. |

---

## 5. Automated Test Suite Results

### Week 3 Test Suite (`test_week3.py`):
```text
============================================================
  WEEK 3 TEST SUITE SUMMARY
============================================================
 ✓ Initial entry has access_count=1
 ✓ Initial entry has hit_count=0
 ✓ Initial entry has valid created_at timestamp
 ✓ Initial entry has last_accessed == created_at
 ✓ First lookup is HIT
 ✓ hit_count incremented to 1
 ✓ access_count incremented to 2
 ✓ last_accessed updated on hit
 ✓ Cache size reaches capacity (3 items)
 ✓ High-frequency entry 'alpha' has higher score than rarely used 'beta'
 ✓ Capacity maintained at 3 entries after store
 ✓ Total evictions counter incremented
 ✓ Valuable high-frequency entry 'alpha' was RETAINED by Scored Eviction
 ✓ Low-value cold entry was the one chosen for eviction
 ✓ Initial TTL matches base TTL (100s)
 ✓ Smart TTL extended on cache hit (+25%)
 ✓ ttl_extensions counter incremented to 1
 ✓ Entry detected as expired via is_expired()
 ✓ Lookup on expired entry returns MISS
 ✓ Purge executed cleanly without errors
 ✓ Checkpoint: CacheMind eviction decisions demonstrably differ from LRU
 ✓ Checkpoint: CacheMind achieves higher or equal hit rate by protecting frequent queries
 ✓ Frequent query 'where is library' retained in CacheMind under burst pressure
 ✓ /api/cache/stats returns HTTP 200
 ✓ Stats contains 'eviction_policy'
 ✓ Stats contains 'total_evictions'
 ✓ Stats contains 'total_ttl_extensions'
 ✓ Stats contains 'max_capacity'
 ✓ /api/cache/intelligence returns HTTP 200
 ✓ Intelligence response includes weights (recency & frequency)
 ✓ Intelligence response includes ttl_config
 ✓ /api/cache/purge-expired returns HTTP 200
 ✓ /api/cache/simulate-comparison returns HTTP 200
 ✓ Simulation data has LRU, LFU, and CacheMind comparisons

Total: 34 | Passed: 34 | Failed: 0
🎉 ALL WEEK 3 TESTS PASSED PERFECTLY!
```

### Week 2 Regression Suite (`test_week2.py`):
```text
Total: 28 | Passed: 28 | Failed: 0
🎉 ALL WEEK 2 TESTS PASSED PERFECTLY!
```
