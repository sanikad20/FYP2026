"""
cachemind.py — CacheMind Semantic Cache Core (Week 2)

An intelligent semantic caching engine that intercepts incoming user queries,
computes their embedding, and searches against cached query embeddings in Redis
using cosine similarity. A similarity threshold determines whether to return a
cached response (hit) or fall through to the LLM/RAG pipeline (miss).

Features:
- Reuses ChromaDB's HuggingFace 'all-MiniLM-L6-v2' (384-dimensional) embeddings.
- Vectorized NumPy cosine similarity search over cached Redis vectors.
- Sub-50ms cache hits bypassing LLM, SQL, and vector database retrieval.
- Comprehensive hit/miss logging and real-time metrics tracking for Week 8 analysis.
- Access frequency and recency tracking per entry (foundational for Week 3).
- Resilient design: transparent in-memory fallback if Redis is unavailable.
"""

import os
import json
import time
import uuid
import hashlib
from datetime import datetime
from typing import Tuple, Optional, Dict, Any, List
import numpy as np


class CacheMind:
    """
    Semantic Cache Engine backed by Redis with cosine similarity matching.
    """

    def __init__(
        self,
        redis_client=None,
        embedding_model=None,
        threshold: float = 0.85,
        default_ttl: Optional[int] = 86400,
        model_name: str = "all-MiniLM-L6-v2",
    ):
        self.redis = redis_client
        self.embedding_model = embedding_model
        self.threshold = float(os.environ.get("CACHE_SIMILARITY_THRESHOLD", threshold))
        self.default_ttl = default_ttl
        self.model_name = model_name

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
        }

        # Redis key prefixes
        self.KEY_ENTRIES = "campus_chat:cache:entries"
        self.KEY_VECTORS = "campus_chat:cache:vectors"
        self.KEY_LOGS = "campus_chat:cache:logs"
        self.KEY_STATS = "campus_chat:cache:stats"

        print(
            f"🧠 CacheMind Core initialized (threshold={self.threshold}, "
            f"embedding_model={self.model_name}, "
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
        
        # embed_query from LangChain HuggingFaceEmbeddings
        vec = self.embedding_model.embed_query(query)
        arr = np.array(vec, dtype=np.float32)
        norm = np.linalg.norm(arr)
        if norm > 1e-9:
            arr = arr / norm
        return arr

    def lookup(self, query: str) -> Tuple[bool, Optional[Dict[str, Any]], float, float, Optional[str]]:
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
        entry_ids = list(vectors_map.keys())
        matrix = np.array([vectors_map[eid] for eid in entry_ids], dtype=np.float32)

        # Dot product with normalized vector gives cosine similarity
        similarities = np.dot(matrix, query_vec)
        best_idx = int(np.argmax(similarities))
        best_score = float(similarities[best_idx])
        best_id = entry_ids[best_idx]
        best_entry = entries_map.get(best_id, {})
        matched_query = best_entry.get("query", "")

        latency_ms = (time.perf_counter() - start_time) * 1000.0

        # 4. Apply similarity threshold
        if best_score >= self.threshold:
            # CACHE HIT
            self._update_hit_metadata(best_id, best_entry)
            self._record_event(
                event_type="HIT",
                query=query_str,
                matched_query=matched_query,
                similarity=best_score,
                latency_ms=latency_ms,
            )
            return True, best_entry.get("response"), best_score, latency_ms, matched_query
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
        """
        query_str = query.strip()
        if not query_str or not response:
            return ""

        if query_vec is None:
            query_vec = self.embed_query(query_str)
        elif not isinstance(query_vec, np.ndarray):
            query_vec = np.array(query_vec, dtype=np.float32)

        # Normalize vector for cosine similarity
        norm = np.linalg.norm(query_vec)
        if norm > 1e-9:
            query_vec = query_vec / norm

        now = time.time()
        entry_id = hashlib.sha256(query_str.lower().encode("utf-8")).hexdigest()[:16]

        entry_data = {
            "id": entry_id,
            "query": query_str,
            "response": response,
            "created_at": now,
            "last_accessed": now,
            "access_count": 1,
            "hit_count": 0,
            "ttl": ttl or self.default_ttl,
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

    def _load_cache_data(self) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, List[float]]]:
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
                    val = json.loads(v.decode("utf-8") if isinstance(v, bytes) else str(v))
                    entries[eid] = val

                for k, v in raw_vectors.items():
                    eid = k.decode("utf-8") if isinstance(k, bytes) else str(k)
                    vec = json.loads(v.decode("utf-8") if isinstance(v, bytes) else str(v))
                    vectors[eid] = vec

                return entries, vectors
            except Exception as e:
                print(f"⚠️ Redis load error ({e}), falling back to in-memory cache.")

        # Fallback to memory
        return dict(self._memory_entries), dict(self._memory_vectors)

    def _update_hit_metadata(self, entry_id: str, entry_data: Dict[str, Any]) -> None:
        """
        Update hit statistics and access recency on the cache entry (for Week 3).
        """
        entry_data["hit_count"] = entry_data.get("hit_count", 0) + 1
        entry_data["access_count"] = entry_data.get("access_count", 0) + 1
        entry_data["last_accessed"] = time.time()

        if self._is_redis_alive():
            try:
                self.redis.hset(self.KEY_ENTRIES, entry_id, json.dumps(entry_data))
            except Exception:
                pass
        else:
            self._memory_entries[entry_id] = entry_data

    def _record_event(
        self,
        event_type: str,
        query: str,
        matched_query: Optional[str],
        similarity: float,
        latency_ms: float,
    ) -> None:
        """
        Record hit/miss event in structured log and update aggregate statistics.
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

        # Update stats
        if self._is_redis_alive():
            try:
                pipe = self.redis.pipeline()
                pipe.lpush(self.KEY_LOGS, json.dumps(event))
                pipe.ltrim(self.KEY_LOGS, 0, 999)  # Keep recent 1000 logs
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
        total_time_ms = 0.0
        cached_entries_count = 0

        if self._is_redis_alive():
            try:
                stats_raw = self.redis.hgetall(self.KEY_STATS)
                total = int(stats_raw.get(b"total_lookups", 0))
                hits = int(stats_raw.get(b"hits", 0))
                misses = int(stats_raw.get(b"misses", 0))
                stores = int(stats_raw.get(b"total_stores", 0))
                total_time_ms = float(stats_raw.get(b"total_lookup_time_ms", 0.0))
                cached_entries_count = self.redis.hlen(self.KEY_ENTRIES)
            except Exception:
                pass
        else:
            total = self._memory_stats["total_lookups"]
            hits = self._memory_stats["hits"]
            misses = self._memory_stats["misses"]
            stores = self._memory_stats["total_stores"]
            total_time_ms = self._memory_stats["total_lookup_time_ms"]
            cached_entries_count = len(self._memory_entries)

        hit_rate = (hits / total * 100.0) if total > 0 else 0.0
        avg_latency = (total_time_ms / total) if total > 0 else 0.0

        return {
            "total_lookups": total,
            "hits": hits,
            "misses": misses,
            "total_stores": stores,
            "hit_rate_percent": round(hit_rate, 2),
            "cached_entries_count": cached_entries_count,
            "avg_lookup_latency_ms": round(avg_latency, 2),
            "similarity_threshold": self.threshold,
            "embedding_model": self.model_name,
            "storage_backend": "redis" if self._is_redis_alive() else "memory",
        }

    def get_logs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Return the most recent cache lookup events.
        """
        limit = max(1, min(limit, 500))
        if self._is_redis_alive():
            try:
                raw_logs = self.redis.lrange(self.KEY_LOGS, 0, limit - 1)
                return [
                    json.loads(log.decode("utf-8") if isinstance(log, bytes) else str(log))
                    for log in raw_logs
                ]
            except Exception:
                pass
        return self._memory_logs[:limit]

    def clear(self) -> bool:
        """
        Flush all cached entries, vectors, and reset statistics.
        """
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
        }
        return True
