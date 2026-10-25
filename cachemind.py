"""
cachemind.py — CacheMind Semantic Cache & Intelligence Layer (Week 2 & Week 3)

An intelligent semantic caching engine that intercepts incoming user queries,
computes their embedding, and searches against cached query embeddings in Redis
(or memory fallback) using cosine similarity.

Features:
- Week 2: Local ChromaDB 'all-MiniLM-L6-v2' (384-dimensional) embeddings.
- Week 2: Vectorized NumPy cosine similarity matching with configurable threshold.
- Week 2: Transparent in-memory fallback when Redis is offline.
- Week 2: Structured hit/miss logging and telemetry endpoints.
- Week 3: Multi-factor Scored Eviction (Score = w_recency * Recency + w_frequency * Frequency).
- Week 3: Smart Dynamic TTL (popular items receive lifetime extensions; cold items decay).
- Week 3: Configurable capacity limits (CACHE_MAX_ENTRIES) with automatic eviction.
- Week 3: Active and passive expired-entry purging.
- Week 3: Policy comparison benchmarking utility (CacheMind Scored vs. plain LRU vs. LFU).
"""

import os
import json
import time
import uuid
import math
import hashlib
from datetime import datetime
from typing import Tuple, Optional, Dict, Any, List
import numpy as np


class CacheMind:
    """
    Intelligent Semantic Cache Engine with Scored Eviction and Smart Dynamic TTL.
    """

    def __init__(
        self,
        redis_client=None,
        embedding_model=None,
        threshold: float = 0.85,
        default_ttl: Optional[int] = 86400,
        model_name: str = "all-MiniLM-L6-v2",
        max_entries: Optional[int] = None,
        weight_recency: Optional[float] = None,
        weight_frequency: Optional[float] = None,
        min_ttl: Optional[int] = None,
        max_ttl: Optional[int] = None,
        ttl_extension_factor: Optional[float] = None,
    ):
        self.redis = redis_client
        self.embedding_model = embedding_model
        self.threshold = float(os.environ.get("CACHE_SIMILARITY_THRESHOLD", threshold))
        self.default_ttl = int(default_ttl or 86400)
        self.model_name = model_name

        # Week 3 — Intelligence Layer Parameters
        self.max_entries = int(
            max_entries
            if max_entries is not None
            else os.environ.get("CACHE_MAX_ENTRIES", 1000)
        )
        self.weight_recency = float(
            weight_recency
            if weight_recency is not None
            else os.environ.get("CACHE_WEIGHT_RECENCY", 0.5)
        )
        self.weight_frequency = float(
            weight_frequency
            if weight_frequency is not None
            else os.environ.get("CACHE_WEIGHT_FREQUENCY", 0.5)
        )
        self.min_ttl = int(
            min_ttl if min_ttl is not None else os.environ.get("CACHE_MIN_TTL", 3600)
        )
        self.max_ttl = int(
            max_ttl if max_ttl is not None else os.environ.get("CACHE_MAX_TTL", 604800)
        )  # 7 days max
        self.ttl_extension_factor = float(
            ttl_extension_factor
            if ttl_extension_factor is not None
            else os.environ.get("CACHE_TTL_EXTENSION_FACTOR", 0.25)
        )  # +25% base TTL per hit

        # In-memory fallbacks when Redis is offline
        self._memory_entries: Dict[str, Dict[str, Any]] = {}
        self._memory_vectors: Dict[str, List[float]] = {}
        self._memory_logs: List[Dict[str, Any]] = []
        self._memory_stats = {
            "total_lookups": 0,
            "hits": 0,
            "misses": 0,
            "total_stores": 0,
            "total_lookup_time_ms": 0.0,
            "total_evictions": 0,
            "total_ttl_extensions": 0,
            "total_expired_purges": 0,
        }

        # Redis key prefixes
        self.KEY_ENTRIES = "campus_chat:cache:entries"
        self.KEY_VECTORS = "campus_chat:cache:vectors"
        self.KEY_LOGS = "campus_chat:cache:logs"
        self.KEY_STATS = "campus_chat:cache:stats"

        print(
            f"🧠 CacheMind Core & Intelligence Layer initialized "
            f"(threshold={self.threshold}, max_entries={self.max_entries}, "
            f"weights=[R:{self.weight_recency:.2f}, F:{self.weight_frequency:.2f}], "
            f"redis={'connected' if self._is_redis_alive() else 'in-memory fallback'})"
        )

    def _is_redis_alive(self) -> bool:
        if self.redis is None:
            return False
        try:
            return bool(self.redis.ping())
        except Exception:
            return False

    def embed_query(self, query: str) -> np.ndarray:
        """
        Embed a query string into a normalized numpy vector.
        """
        if self.embedding_model is None:
            raise RuntimeError("CacheMind embedding model is not configured.")

        vec = self.embedding_model.embed_query(query)
        arr = np.array(vec, dtype=np.float32)
        norm = np.linalg.norm(arr)
        if norm > 1e-9:
            arr = arr / norm
        return arr

    # ─────────────────────────────────────────────────────────────────────────
    # Week 3: Scoring & Eviction Engine
    # ─────────────────────────────────────────────────────────────────────────

    def calculate_score(
        self,
        entry: Dict[str, Any],
        now: Optional[float] = None,
        max_access_in_cache: int = 1,
    ) -> float:
        """
        Calculate intelligence score combining Recency and Frequency.
        Score = w_recency * Recency_Score + w_frequency * Frequency_Score

        - Recency: Half-life decay based on elapsed seconds since last_accessed.
                   R = 1.0 / (1.0 + (delta_seconds / 3600.0))
        - Frequency: Logarithmically scaled access frequency normalized to [0, 1].
        """
        if now is None:
            now = time.time()

        last_accessed = float(entry.get("last_accessed", now))
        delta_sec = max(0.0, now - last_accessed)

        # 1. Recency Score (1.0 when just accessed, decays smoothly toward 0.0)
        # Half-life scale: 1 hour (3600 seconds)
        recency_score = 1.0 / (1.0 + (delta_sec / 3600.0))

        # 2. Frequency Score (scaled logarithmically to prevent runaway dominance)
        access_count = max(1, int(entry.get("access_count", 1)))
        max_access = max(max_access_in_cache, access_count, 10)
        frequency_score = math.log1p(access_count) / math.log1p(max_access)
        frequency_score = min(1.0, max(0.0, frequency_score))

        # 3. Weighted Combination
        w_total = self.weight_recency + self.weight_frequency
        w_r = self.weight_recency / w_total if w_total > 0 else 0.5
        w_f = self.weight_frequency / w_total if w_total > 0 else 0.5

        final_score = (w_r * recency_score) + (w_f * frequency_score)
        return round(float(final_score), 5)

    def is_expired(self, entry: Dict[str, Any], now: Optional[float] = None) -> bool:
        """
        Check if a cache entry has exceeded its dynamic TTL.
        """
        if now is None:
            now = time.time()

        created_at = float(entry.get("created_at", now))
        ttl = float(entry.get("ttl", self.default_ttl))

        # Entry expires if elapsed time since creation exceeds the dynamic TTL
        return now > (created_at + ttl)

    def purge_expired(self) -> int:
        """
        Actively sweep and remove expired entries from cache.
        Returns the count of purged entries.
        """
        now = time.time()
        entries_map, _ = self._load_cache_data()
        expired_ids = [
            eid for eid, entry in entries_map.items() if self.is_expired(entry, now)
        ]

        if not expired_ids:
            return 0

        for eid in expired_ids:
            self._delete_entry(eid)

        purged_count = len(expired_ids)
        self._increment_stat("total_expired_purges", purged_count)
        return purged_count

    def evict(self, count: int = 1) -> List[str]:
        """
        Evict 'count' entries using CacheMind's Scored Eviction policy.
        The entries with the LOWEST score (lowest recency + frequency) are evicted.
        Returns list of evicted entry IDs.
        """
        entries_map, _ = self._load_cache_data()
        if not entries_map:
            return []

        now = time.time()
        max_acc = max(
            (int(e.get("access_count", 1)) for e in entries_map.values()), default=1
        )

        # Score every entry
        scored_entries = []
        for eid, entry in entries_map.items():
            # If already expired, prioritize it for immediate eviction
            if self.is_expired(entry, now):
                score = -1.0
            else:
                score = self.calculate_score(entry, now, max_acc)
            scored_entries.append((score, eid, entry.get("query", "")))

        # Sort ascending: lowest score first (least valuable to retain)
        scored_entries.sort(key=lambda x: x[0])

        to_evict = scored_entries[: max(1, count)]
        evicted_ids = []

        for score, eid, query in to_evict:
            self._delete_entry(eid)
            evicted_ids.append(eid)
            self._record_event(
                event_type="EVICT",
                query=query,
                matched_query=f"score={score:.4f}",
                similarity=score,
                latency_ms=0.0,
            )

        self._increment_stat("total_evictions", len(evicted_ids))
        return evicted_ids

    def _delete_entry(self, entry_id: str) -> None:
        """Remove single entry and its vector from Redis and in-memory store."""
        if self._is_redis_alive():
            try:
                pipe = self.redis.pipeline()
                pipe.hdel(self.KEY_ENTRIES, entry_id)
                pipe.hdel(self.KEY_VECTORS, entry_id)
                pipe.execute()
            except Exception:
                pass

        self._memory_entries.pop(entry_id, None)
        self._memory_vectors.pop(entry_id, None)

    # ─────────────────────────────────────────────────────────────────────────
    # Lookup & Store Core Workflow
    # ─────────────────────────────────────────────────────────────────────────

    def lookup(
        self, query: str
    ) -> Tuple[bool, Optional[Dict[str, Any]], float, float, Optional[str]]:
        """
        Look up a query in the semantic cache.

        Returns:
            (is_hit, cached_response, similarity_score, latency_ms, matched_query)
        """
        start_time = time.perf_counter()
        query_str = query.strip()
        if not query_str:
            return False, None, 0.0, 0.0, None

        # 1. Embed incoming query
        query_vec = self.embed_query(query_str)

        # 2. Retrieve cached vectors and entries
        entries_map, vectors_map = self._load_cache_data()

        if not entries_map or not vectors_map:
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            self._record_event(
                event_type="MISS",
                query=query_str,
                matched_query=None,
                similarity=0.0,
                latency_ms=latency_ms,
            )
            return False, None, 0.0, latency_ms, None

        # 3. Compute cosine similarity across all cached vectors (vectorized)
        now = time.time()
        entry_ids = list(vectors_map.keys())
        matrix = np.array([vectors_map[eid] for eid in entry_ids], dtype=np.float32)

        # Dot product with normalized query vector gives cosine similarity
        similarities = np.dot(matrix, query_vec)
        best_idx = int(np.argmax(similarities))
        best_score = float(similarities[best_idx])
        best_id = entry_ids[best_idx]
        best_entry = entries_map.get(best_id, {})
        matched_query = best_entry.get("query", "")

        # Week 3 Check: Is the matched entry expired?
        if self.is_expired(best_entry, now):
            self._delete_entry(best_id)
            self._increment_stat("total_expired_purges", 1)
            latency_ms = (time.perf_counter() - start_time) * 1000.0
            self._record_event(
                event_type="MISS",
                query=query_str,
                matched_query=f"{matched_query} (expired)",
                similarity=best_score,
                latency_ms=latency_ms,
            )
            return False, None, best_score, latency_ms, matched_query

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        # 4. Apply similarity threshold
        if best_score >= self.threshold:
            # CACHE HIT — Update frequency, recency, and apply Smart TTL extension
            self._update_hit_metadata(best_id, best_entry)
            self._record_event(
                event_type="HIT",
                query=query_str,
                matched_query=matched_query,
                similarity=best_score,
                latency_ms=latency_ms,
            )
            return (
                True,
                best_entry.get("response"),
                best_score,
                latency_ms,
                matched_query,
            )
        else:
            # CACHE MISS
            self._record_event(
                event_type="MISS",
                query=query_str,
                matched_query=matched_query if best_score > 0.4 else None,
                similarity=best_score,
                latency_ms=latency_ms,
            )
            return False, None, best_score, latency_ms, matched_query

    def store(
        self,
        query: str,
        response: Dict[str, Any],
        query_vec: Optional[np.ndarray] = None,
        ttl: Optional[int] = None,
    ) -> str:
        """
        Store a query, its embedding, and the generated response in the cache.
        Enforces maximum capacity (CACHE_MAX_ENTRIES) with Scored Eviction.
        """
        query_str = query.strip()
        if not query_str or not response:
            return ""

        now = time.time()
        entry_id = hashlib.sha256(query_str.lower().encode("utf-8")).hexdigest()[:16]

        # Load active cache size
        entries_map, _ = self._load_cache_data()

        # Week 3: Enforce Capacity Limit via Scored Eviction
        # If entry is new and current size >= max_entries, evict lowest scored item
        if entry_id not in entries_map and len(entries_map) >= self.max_entries:
            self.evict(count=1)

        if query_vec is None:
            query_vec = self.embed_query(query_str)
        elif not isinstance(query_vec, np.ndarray):
            query_vec = np.array(query_vec, dtype=np.float32)

        norm = np.linalg.norm(query_vec)
        if norm > 1e-9:
            query_vec = query_vec / norm

        assigned_ttl = ttl or self.default_ttl
        entry_data = {
            "id": entry_id,
            "query": query_str,
            "response": response,
            "created_at": now,
            "last_accessed": now,
            "access_count": 1,
            "hit_count": 0,
            "ttl": assigned_ttl,
            "base_ttl": assigned_ttl,
            "ttl_extensions": 0,
        }

        vec_list = query_vec.tolist()

        if self._is_redis_alive():
            try:
                pipeline = self.redis.pipeline()
                pipeline.hset(self.KEY_ENTRIES, entry_id, json.dumps(entry_data))
                pipeline.hset(self.KEY_VECTORS, entry_id, json.dumps(vec_list))
                pipeline.hincrby(self.KEY_STATS, "total_stores", 1)
                pipeline.execute()
            except Exception as e:
                print(f"⚠️ Redis error in store ({e}), saving to in-memory fallback.")
                self._memory_entries[entry_id] = entry_data
                self._memory_vectors[entry_id] = vec_list
                self._memory_stats["total_stores"] += 1
        else:
            self._memory_entries[entry_id] = entry_data
            self._memory_vectors[entry_id] = vec_list
            self._memory_stats["total_stores"] += 1

        return entry_id

    def _load_cache_data(
        self,
    ) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, List[float]]]:
        """
        Load active entries and vector embeddings from Redis or memory fallback.
        """
        entries: Dict[str, Dict[str, Any]] = {}
        vectors: Dict[str, List[float]] = {}

        if self._is_redis_alive():
            try:
                raw_entries = self.redis.hgetall(self.KEY_ENTRIES)
                raw_vectors = self.redis.hgetall(self.KEY_VECTORS)

                for k, v in raw_entries.items():
                    eid = k.decode("utf-8") if isinstance(k, bytes) else str(k)
                    val = json.loads(
                        v.decode("utf-8") if isinstance(v, bytes) else str(v)
                    )
                    entries[eid] = val

                for k, v in raw_vectors.items():
                    eid = k.decode("utf-8") if isinstance(k, bytes) else str(k)
                    vec = json.loads(
                        v.decode("utf-8") if isinstance(v, bytes) else str(v)
                    )
                    vectors[eid] = vec

                return entries, vectors
            except Exception as e:
                print(f"⚠️ Redis load error ({e}), falling back to in-memory cache.")

        return dict(self._memory_entries), dict(self._memory_vectors)

    def _update_hit_metadata(
        self, entry_id: str, entry_data: Dict[str, Any]
    ) -> None:
        """
        Week 3: Update access metrics and apply Smart Dynamic TTL Extension.
        Frequently hit entries get their TTL extended; cold entries decay faster.
        """
        now = time.time()
        hit_count = entry_data.get("hit_count", 0) + 1
        access_count = entry_data.get("access_count", 0) + 1

        entry_data["hit_count"] = hit_count
        entry_data["access_count"] = access_count
        entry_data["last_accessed"] = now

        # Smart Dynamic TTL Extension
        base_ttl = entry_data.get("base_ttl", self.default_ttl)
        current_ttl = entry_data.get("ttl", base_ttl)
        bonus_seconds = int(base_ttl * self.ttl_extension_factor)
        new_ttl = min(self.max_ttl, current_ttl + bonus_seconds)

        if new_ttl > current_ttl:
            entry_data["ttl"] = new_ttl
            entry_data["ttl_extensions"] = entry_data.get("ttl_extensions", 0) + 1
            self._increment_stat("total_ttl_extensions", 1)

        if self._is_redis_alive():
            try:
                self.redis.hset(self.KEY_ENTRIES, entry_id, json.dumps(entry_data))
            except Exception:
                pass
        else:
            self._memory_entries[entry_id] = entry_data

    def _increment_stat(self, field: str, amount: int = 1) -> None:
        """Increment telemetry counter in Redis and in-memory stats."""
        if self._is_redis_alive():
            try:
                self.redis.hincrby(self.KEY_STATS, field, amount)
            except Exception:
                pass
        self._memory_stats[field] = self._memory_stats.get(field, 0) + amount

    def _record_event(
        self,
        event_type: str,
        query: str,
        matched_query: Optional[str],
        similarity: float,
        latency_ms: float,
    ) -> None:
        """
        Record hit/miss/evict event in structured log and update aggregate statistics.
        """
        event = {
            "id": uuid.uuid4().hex[:12],
            "timestamp": datetime.now().isoformat(),
            "event": event_type,
            "query": query,
            "matched_query": matched_query,
            "similarity": round(similarity, 4),
            "threshold": self.threshold,
            "latency_ms": round(latency_ms, 2),
        }

        if self._is_redis_alive():
            try:
                pipe = self.redis.pipeline()
                pipe.lpush(self.KEY_LOGS, json.dumps(event))
                pipe.ltrim(self.KEY_LOGS, 0, 999)  # Keep recent 1000 logs
                if event_type in ("HIT", "MISS"):
                    pipe.hincrby(self.KEY_STATS, "total_lookups", 1)
                    if event_type == "HIT":
                        pipe.hincrby(self.KEY_STATS, "hits", 1)
                    else:
                        pipe.hincrby(self.KEY_STATS, "misses", 1)
                    pipe.hincrbyfloat(self.KEY_STATS, "total_lookup_time_ms", latency_ms)
                pipe.execute()
            except Exception:
                pass
        else:
            self._memory_logs.insert(0, event)
            if len(self._memory_logs) > 1000:
                self._memory_logs = self._memory_logs[:1000]

            if event_type in ("HIT", "MISS"):
                self._memory_stats["total_lookups"] += 1
                if event_type == "HIT":
                    self._memory_stats["hits"] += 1
                else:
                    self._memory_stats["misses"] += 1
                self._memory_stats["total_lookup_time_ms"] += latency_ms

    def get_stats(self) -> Dict[str, Any]:
        """
        Return real-time cache metrics and performance statistics.
        """
        total = 0
        hits = 0
        misses = 0
        stores = 0
        evictions = 0
        ttl_extensions = 0
        expired_purges = 0
        total_time_ms = 0.0
        cached_entries_count = 0

        if self._is_redis_alive():
            try:
                stats_raw = self.redis.hgetall(self.KEY_STATS)
                total = int(stats_raw.get(b"total_lookups", 0))
                hits = int(stats_raw.get(b"hits", 0))
                misses = int(stats_raw.get(b"misses", 0))
                stores = int(stats_raw.get(b"total_stores", 0))
                evictions = int(stats_raw.get(b"total_evictions", 0))
                ttl_extensions = int(stats_raw.get(b"total_ttl_extensions", 0))
                expired_purges = int(stats_raw.get(b"total_expired_purges", 0))
                total_time_ms = float(stats_raw.get(b"total_lookup_time_ms", 0.0))
                cached_entries_count = self.redis.hlen(self.KEY_ENTRIES)
            except Exception:
                pass
        else:
            total = self._memory_stats.get("total_lookups", 0)
            hits = self._memory_stats.get("hits", 0)
            misses = self._memory_stats.get("misses", 0)
            stores = self._memory_stats.get("total_stores", 0)
            evictions = self._memory_stats.get("total_evictions", 0)
            ttl_extensions = self._memory_stats.get("total_ttl_extensions", 0)
            expired_purges = self._memory_stats.get("total_expired_purges", 0)
            total_time_ms = self._memory_stats.get("total_lookup_time_ms", 0.0)
            cached_entries_count = len(self._memory_entries)

        hit_rate = (hits / total * 100.0) if total > 0 else 0.0
        avg_latency = (total_time_ms / total) if total > 0 else 0.0

        return {
            "total_lookups": total,
            "hits": hits,
            "misses": misses,
            "total_stores": stores,
            "total_evictions": evictions,
            "total_ttl_extensions": ttl_extensions,
            "total_expired_purges": expired_purges,
            "hit_rate_percent": round(hit_rate, 2),
            "cached_entries_count": cached_entries_count,
            "avg_lookup_latency_ms": round(avg_latency, 2),
            "max_capacity": self.max_entries,
            "similarity_threshold": self.threshold,
            "eviction_policy": "scored_recency_frequency",
            "weight_recency": self.weight_recency,
            "weight_frequency": self.weight_frequency,
            "default_ttl_seconds": self.default_ttl,
            "max_ttl_seconds": self.max_ttl,
            "embedding_model": self.model_name,
            "storage_backend": "redis" if self._is_redis_alive() else "memory",
        }

    def get_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return the most recent cache lookup events."""
        limit = max(1, min(limit, 500))
        if self._is_redis_alive():
            try:
                raw_logs = self.redis.lrange(self.KEY_LOGS, 0, limit - 1)
                return [
                    json.loads(
                        log.decode("utf-8") if isinstance(log, bytes) else str(log)
                    )
                    for log in raw_logs
                ]
            except Exception:
                pass
        return self._memory_logs[:limit]

    def clear(self) -> bool:
        """Flush all cached entries, vectors, and reset statistics."""
        if self._is_redis_alive():
            try:
                self.redis.delete(
                    self.KEY_ENTRIES,
                    self.KEY_VECTORS,
                    self.KEY_LOGS,
                    self.KEY_STATS,
                )
            except Exception:
                pass

        self._memory_entries.clear()
        self._memory_vectors.clear()
        self._memory_logs.clear()
        self._memory_stats = {
            "total_lookups": 0,
            "hits": 0,
            "misses": 0,
            "total_stores": 0,
            "total_lookup_time_ms": 0.0,
            "total_evictions": 0,
            "total_ttl_extensions": 0,
            "total_expired_purges": 0,
        }
        return True

    # ─────────────────────────────────────────────────────────────────────────
    # Week 3 Checkpoint Utility: Policy Comparison Simulation
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def simulate_policy_comparison(
        queries: List[str], capacity: int = 3
    ) -> Dict[str, Any]:
        """
        Simulate the exact same query stream on:
          1. Plain LRU (Evicts strictly based on oldest last_accessed)
          2. Plain LFU (Evicts strictly based on lowest access count)
          3. CacheMind Scored (Combines Recency + Frequency)

        Demonstrates that CacheMind decisions differ from plain LRU and retain
        high-frequency queries even under temporary bursts of novel queries.
        """
        # 1. Plain LRU Simulator
        lru_cache: Dict[str, float] = {}  # key -> last_accessed
        lru_hits = 0
        lru_misses = 0
        lru_evictions: List[str] = []

        # 2. Plain LFU Simulator
        lfu_cache: Dict[str, int] = {}  # key -> access_count
        lfu_hits = 0
        lfu_misses = 0
        lfu_evictions: List[str] = []

        # 3. CacheMind Scored Simulator
        cm_cache: Dict[str, Dict[str, Any]] = {}  # key -> {last_accessed, count, created}
        cm_hits = 0
        cm_misses = 0
        cm_evictions: List[str] = []

        now = 1000.0
        for q in queries:
            now += 10.0  # Simulated step time

            # --- LRU ---
            if q in lru_cache:
                lru_hits += 1
                lru_cache[q] = now
            else:
                lru_misses += 1
                if len(lru_cache) >= capacity:
                    oldest_q = min(lru_cache.keys(), key=lambda k: lru_cache[k])
                    del lru_cache[oldest_q]
                    lru_evictions.append(oldest_q)
                lru_cache[q] = now

            # --- LFU ---
            if q in lfu_cache:
                lfu_hits += 1
                lfu_cache[q] += 1
            else:
                lfu_misses += 1
                if len(lfu_cache) >= capacity:
                    lowest_q = min(lfu_cache.keys(), key=lambda k: lfu_cache[k])
                    del lfu_cache[lowest_q]
                    lfu_evictions.append(lowest_q)
                lfu_cache[q] = 1

            # --- CacheMind Scored ---
            if q in cm_cache:
                cm_hits += 1
                cm_cache[q]["access_count"] += 1
                cm_cache[q]["last_accessed"] = now
            else:
                cm_misses += 1
                if len(cm_cache) >= capacity:
                    # Score all items
                    def calc_sim_score(e):
                        rec = 1.0 / (1.0 + (now - e["last_accessed"]) / 60.0)
                        freq = min(1.0, math.log1p(e["access_count"]) / math.log1p(10))
                        return 0.5 * rec + 0.5 * freq

                    victim_q = min(cm_cache.keys(), key=lambda k: calc_sim_score(cm_cache[k]))
                    del cm_cache[victim_q]
                    cm_evictions.append(victim_q)

                cm_cache[q] = {
                    "last_accessed": now,
                    "access_count": 1,
                    "created_at": now,
                }

        total_queries = len(queries)
        return {
            "capacity": capacity,
            "total_queries": total_queries,
            "LRU": {
                "hits": lru_hits,
                "misses": lru_misses,
                "hit_rate_percent": round(lru_hits / total_queries * 100.0, 2),
                "evictions": lru_evictions,
                "retained": list(lru_cache.keys()),
            },
            "LFU": {
                "hits": lfu_hits,
                "misses": lfu_misses,
                "hit_rate_percent": round(lfu_hits / total_queries * 100.0, 2),
                "evictions": lfu_evictions,
                "retained": list(lfu_cache.keys()),
            },
            "CacheMind": {
                "hits": cm_hits,
                "misses": cm_misses,
                "hit_rate_percent": round(cm_hits / total_queries * 100.0, 2),
                "evictions": cm_evictions,
                "retained": list(cm_cache.keys()),
            },
        }
