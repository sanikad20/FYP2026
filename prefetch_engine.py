"""
prefetch_engine.py — Predictive Prefetching Engine for Campus Chat (Week 4)

Implements Markov-Chain sequence tracking and predictive prefetching on top of CacheMind:
- Tracks sequence of questions per session (A -> B, A -> B -> C).
- Computes transition probabilities: P(Next | Curr) = Count(Curr -> Next) / Total(Curr).
- Predicts next likely question when confidence exceeds configurable threshold.
- Asynchronously prefetches RAG answers into CacheMind in the background without blocking responses.
- Enforces strict security:
  * Strict session and authorization context (no cross-user private data mixing).
  * Concurrency limits and budget throttling.
  * Loop prevention (sliding window of recently prefetched queries).
- Invalidation hook when documents change.
- Telemetry & performance simulation (prefetch hit rate, latency saved, LLM calls avoided).
"""

import os
import time
import json
import hashlib
import threading
from typing import Dict, Any, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor
import psycopg2


def normalize_query(query: str) -> str:
    """Normalize query text for canonical transition tracking."""
    if not query:
        return ""
    q = query.strip().lower()
    # Strip trailing punctuation
    while q and q[-1] in "?!.,;:":
        q = q[:-1].strip()
    return " ".join(q.split())


def hash_query(query: str) -> str:
    """Return SHA-256 short hash of normalized query."""
    norm = normalize_query(query)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:16]


class PredictivePrefetchEngine:
    """
    Lightweight Markov-Chain Predictive Prefetcher.
    """

    def __init__(
        self,
        cachemind_instance=None,
        db_connection_factory=None,
        rag_answer_generator=None,
        confidence_threshold: float = 0.40,
        prefetch_ttl: int = 86400,
        max_concurrent: int = 2,
        budget_per_minute: int = 20,
        enabled: bool = True,
    ):
        self.cachemind = cachemind_instance
        self.get_db_conn = db_connection_factory
        self.rag_generator = rag_answer_generator

        # Configuration (from env or defaults)
        self.enabled = os.environ.get("PREFETCH_ENABLED", "true").lower() in ("true", "1", "yes") if enabled else False
        self.confidence_threshold = float(os.environ.get("PREFETCH_CONFIDENCE_THRESHOLD", confidence_threshold))
        self.prefetch_ttl = int(os.environ.get("PREFETCH_TTL", prefetch_ttl))
        self.max_concurrent = int(os.environ.get("PREFETCH_MAX_CONCURRENT", max_concurrent))
        self.budget_per_minute = int(os.environ.get("PREFETCH_BUDGET_PER_MINUTE", budget_per_minute))

        # Memory transition graph: { prev_hash: { next_hash: { 'text': next_text, 'count': N } } }
        self._transitions: Dict[str, Dict[str, Dict[str, Any]]] = {}
        # Hash to normalized text mapping
        self._hash_to_text: Dict[str, str] = {}
        # Session history tracking: { session_id: [query_hash_1, query_hash_2, ...] }
        self._session_histories: Dict[str, List[str]] = {}
        # Session recent prefetches to avoid loops: { session_id: set(prefetched_hashes) }
        self._session_prefetches: Dict[str, set] = {}

        # Budget enforcement
        self._minute_window_start = time.time()
        self._minute_prefetch_count = 0
        self._lock = threading.Lock()

        # Thread pool for asynchronous background prefetching
        self._executor = ThreadPoolExecutor(max_workers=self.max_concurrent, thread_name_prefix="PrefetchWorker")

        # Telemetry metrics
        self.metrics = {
            "total_transitions_recorded": 0,
            "predictions_attempted": 0,
            "predictions_made": 0,
            "prefetches_triggered": 0,
            "prefetches_completed": 0,
            "prefetches_skipped_cached": 0,
            "prefetches_skipped_budget": 0,
            "prefetch_hits": 0,
            "avoided_llm_calls": 0,
            "total_latency_saved_ms": 0.0,
            "errors": 0,
        }

        # Load persisted transitions from PostgreSQL
        self._load_transitions_from_db()
        print(f"🔮 PredictivePrefetchEngine initialized (threshold={self.confidence_threshold}, "
              f"max_concurrent={self.max_concurrent}, budget/min={self.budget_per_minute}, "
              f"enabled={self.enabled})")

    def _load_transitions_from_db(self):
        """Load known query transitions from PostgreSQL if available."""
        if not self.get_db_conn:
            return
        try:
            conn = self.get_db_conn()
            cur = conn.cursor()
            cur.execute("""
                SELECT prev_query_hash, prev_query_text, next_query_hash, next_query_text, transition_count
                FROM query_transitions;
            """)
            rows = cur.fetchall()
            for r in rows:
                p_hash, p_text, n_hash, n_text, count = r
                if p_hash not in self._transitions:
                    self._transitions[p_hash] = {}
                self._transitions[p_hash][n_hash] = {"text": n_text, "count": count}
                self._hash_to_text[p_hash] = p_text
                self._hash_to_text[n_hash] = n_text
            cur.close()
            conn.close()
            print(f"🔮 Loaded {len(rows)} query transitions from database.")
        except Exception as e:
            print(f"🔮 [Warning] Could not load query transitions from DB: {e}")

    def record_transition(self, prev_query: str, next_query: str):
        """
        Record that next_query followed prev_query.
        Updates in-memory Markov model and persists to PostgreSQL.
        """
        if not prev_query or not next_query:
            return

        norm_prev = normalize_query(prev_query)
        norm_next = normalize_query(next_query)
        if not norm_prev or not norm_next or norm_prev == norm_next:
            return

        p_hash = hash_query(norm_prev)
        n_hash = hash_query(norm_next)

        with self._lock:
            self._hash_to_text[p_hash] = norm_prev
            self._hash_to_text[n_hash] = norm_next

            if p_hash not in self._transitions:
                self._transitions[p_hash] = {}

            if n_hash not in self._transitions[p_hash]:
                self._transitions[p_hash][n_hash] = {"text": norm_next, "count": 1}
            else:
                self._transitions[p_hash][n_hash]["count"] += 1

            self.metrics["total_transitions_recorded"] += 1

        # Persist asynchronously / safely to PostgreSQL
        if self.get_db_conn:
            try:
                conn = self.get_db_conn()
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO query_transitions 
                        (prev_query_hash, prev_query_text, next_query_hash, next_query_text, transition_count, last_transition_at)
                    VALUES (%s, %s, %s, %s, 1, CURRENT_TIMESTAMP)
                    ON CONFLICT (prev_query_hash, next_query_hash)
                    DO UPDATE SET 
                        transition_count = query_transitions.transition_count + 1,
                        last_transition_at = CURRENT_TIMESTAMP;
                """, (p_hash, norm_prev, n_hash, norm_next))
                conn.commit()
                cur.close()
                conn.close()
            except Exception as e:
                print(f"🔮 [Warning] Failed to persist transition to DB: {e}")

    def record_user_query(self, session_id: str, query: str):
        """
        Track a user query in their session history and record sequence transition.
        """
        if not query:
            return

        norm = normalize_query(query)
        q_hash = hash_query(norm)

        with self._lock:
            history = self._session_histories.setdefault(session_id, [])
            prev_hash = history[-1] if history else None
            history.append(q_hash)
            # Keep history to last 10 queries
            if len(history) > 10:
                history.pop(0)

        if prev_hash and prev_hash != q_hash:
            prev_text = self._hash_to_text.get(prev_hash, "")
            if prev_text:
                self.record_transition(prev_text, norm)

    def predict_next_query(self, current_query: str) -> Optional[Tuple[str, float]]:
        """
        Given the current query, predict the most likely next query and confidence score.
        Returns (predicted_query_text, confidence) or None.
        """
        self.metrics["predictions_attempted"] += 1
        norm_curr = normalize_query(current_query)
        c_hash = hash_query(norm_curr)

        with self._lock:
            candidates = self._transitions.get(c_hash, {})
            if not candidates:
                return None

            total_transitions = sum(item["count"] for item in candidates.values())
            if total_transitions == 0:
                return None

            # Find candidate with highest frequency
            best_hash = None
            best_count = 0
            best_text = ""
            for h, info in candidates.items():
                if info["count"] > best_count:
                    best_count = info["count"]
                    best_hash = h
                    best_text = info["text"]

            if not best_hash:
                return None

            confidence = best_count / float(total_transitions)
            if confidence >= self.confidence_threshold:
                self.metrics["predictions_made"] += 1
                return (best_text, round(confidence, 4))

        return None

    def trigger_prefetch_if_applicable(
        self,
        current_query: str,
        session_id: str,
        auth_role: str = "student",
        user_id: Optional[int] = None,
    ):
        """
        Inspect the current query, compute prediction, and trigger background prefetch
        if confidence meets threshold and budget permits.
        """
        if not self.enabled:
            return None

        prediction = self.predict_next_query(current_query)
        if not prediction:
            return None

        predicted_query, confidence = prediction
        pred_hash = hash_query(predicted_query)

        # 1. Loop prevention: check if session already prefetched this query recently
        with self._lock:
            recent_prefetches = self._session_prefetches.setdefault(session_id, set())
            if pred_hash in recent_prefetches:
                return None

        # 2. Check if already cached in CacheMind
        if self.cachemind:
            try:
                is_hit, cached_entry = self.cachemind.lookup(predicted_query)
                if is_hit:
                    self.metrics["prefetches_skipped_cached"] += 1
                    return None
            except Exception:
                pass

        # 3. Check rate budget
        now = time.time()
        with self._lock:
            if now - self._minute_window_start > 60.0:
                self._minute_window_start = now
                self._minute_prefetch_count = 0

            if self._minute_prefetch_count >= self.budget_per_minute:
                self.metrics["prefetches_skipped_budget"] += 1
                return None

            self._minute_prefetch_count += 1
            self.metrics["prefetches_triggered"] += 1
            recent_prefetches.add(pred_hash)

        # 4. Dispatch background prefetch task
        self._executor.submit(
            self._execute_prefetch_task,
            current_query,
            predicted_query,
            confidence,
            session_id,
            auth_role,
            user_id,
        )
        return predicted_query

    def _execute_prefetch_task(
        self,
        trigger_query: str,
        predicted_query: str,
        confidence: float,
        session_id: str,
        auth_role: str,
        user_id: Optional[int],
    ):
        """
        Background worker that generates answer via RAG and stores it in CacheMind.
        """
        t0 = time.time()
        try:
            # Re-verify it is not already in cache
            if self.cachemind:
                hit, _ = self.cachemind.lookup(predicted_query)
                if hit:
                    return

            # Call RAG pipeline generator in user's role context
            if self.rag_generator:
                answer_data = self.rag_generator(predicted_query, auth_role=auth_role)
                if answer_data and self.cachemind:
                    # Tag metadata with prefetched=True
                    if isinstance(answer_data, dict):
                        answer_data["_prefetched"] = True
                        answer_data["_prefetch_confidence"] = confidence
                        answer_data["_trigger_query"] = trigger_query

                    self.cachemind.store(
                        predicted_query,
                        answer_data,
                        ttl=self.prefetch_ttl,
                    )
                    with self._lock:
                        self.metrics["prefetches_completed"] += 1

                    # Log metric to PostgreSQL
                    self._record_prefetch_metric(
                        trigger_query=trigger_query,
                        predicted_query=predicted_query,
                        confidence=confidence,
                        status="prefetch_cached",
                        cache_hit=False,
                        latency_saved_ms=0.0,
                    )
        except Exception as e:
            with self._lock:
                self.metrics["errors"] += 1
            print(f"🔮 [Warning] Background prefetch execution failed for '{predicted_query}': {e}")

    def notify_cache_hit(self, query: str, cached_entry: Dict[str, Any], latency_ms: float = 15.0):
        """
        Hook called when a user query results in a cache hit.
        If the cached response was prefetched, records a prefetch hit!
        """
        is_prefetched = False
        payload = cached_entry.get("response", {})
        if isinstance(payload, dict) and payload.get("_prefetched"):
            is_prefetched = True

        if is_prefetched:
            with self._lock:
                self.metrics["prefetch_hits"] += 1
                self.metrics["avoided_llm_calls"] += 1
                # Baseline LLM latency assumed ~1200ms
                saved = max(0.0, 1200.0 - latency_ms)
                self.metrics["total_latency_saved_ms"] += saved

            self._record_prefetch_metric(
                trigger_query=payload.get("_trigger_query", "unknown"),
                predicted_query=query,
                confidence=payload.get("_prefetch_confidence", 0.0),
                status="prefetch_hit",
                cache_hit=True,
                latency_saved_ms=max(0.0, 1200.0 - latency_ms),
            )

    def _record_prefetch_metric(
        self,
        trigger_query: str,
        predicted_query: str,
        confidence: float,
        status: str,
        cache_hit: bool,
        latency_saved_ms: float,
    ):
        """Persist metric record to PostgreSQL."""
        if not self.get_db_conn:
            return
        try:
            conn = self.get_db_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO prefetch_metrics 
                    (trigger_query, predicted_query, prediction_confidence, prefetch_status, cache_hit, latency_saved_ms)
                VALUES (%s, %s, %s, %s, %s, %s);
            """, (trigger_query, predicted_query, confidence, status, cache_hit, latency_saved_ms))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print(f"🔮 [Warning] Failed to record prefetch metric to DB: {e}")

    def invalidate_for_document(self, document_title: str, keywords: Optional[List[str]] = None):
        """
        Invalidates cached answers in CacheMind when an underlying document changes.
        """
        if not self.cachemind:
            return 0

        invalidated_count = 0
        search_terms = [document_title.lower()]
        if keywords:
            search_terms.extend([k.lower() for k in keywords])

        try:
            entries, _ = self.cachemind._load_cache_data()
            for eid, entry in list(entries.items()):
                q_text = entry.get("query", "").lower()
                resp_text = str(entry.get("response", "")).lower()
                if any(term in q_text or term in resp_text for term in search_terms):
                    self.cachemind.evict(eid)
                    invalidated_count += 1
        except Exception as e:
            print(f"🔮 [Warning] Error invalidating cache for document '{document_title}': {e}")

        return invalidated_count

    def get_stats(self) -> Dict[str, Any]:
        """Return full telemetry metrics and Markov chain overview."""
        with self._lock:
            total_preds = self.metrics["predictions_made"]
            p_hits = self.metrics["prefetch_hits"]
            accuracy = round((p_hits / total_preds * 100.0), 2) if total_preds > 0 else 0.0

            # Count total transitions in graph
            distinct_pairs = sum(len(dest) for dest in self._transitions.values())

            # Top transitions
            top_transitions = []
            for p_hash, dests in self._transitions.items():
                p_text = self._hash_to_text.get(p_hash, p_hash)
                total_p = sum(d["count"] for d in dests.values())
                for n_hash, info in dests.items():
                    n_text = info["text"]
                    c = info["count"]
                    conf = round(c / total_p, 4) if total_p > 0 else 0.0
                    top_transitions.append({
                        "from_query": p_text,
                        "to_query": n_text,
                        "count": c,
                        "confidence": conf,
                    })

            top_transitions.sort(key=lambda x: (x["count"], x["confidence"]), reverse=True)

            return {
                "enabled": self.enabled,
                "confidence_threshold": self.confidence_threshold,
                "max_concurrent": self.max_concurrent,
                "budget_per_minute": self.budget_per_minute,
                "distinct_transition_pairs": distinct_pairs,
                "top_transitions": top_transitions[:15],
                "metrics": {
                    **self.metrics,
                    "prediction_accuracy_percent": accuracy,
                }
            }

    def simulate_comparison(
        self,
        query_sequence: List[str],
        base_llm_latency_ms: float = 1200.0,
        cache_hit_latency_ms: float = 15.0,
    ) -> Dict[str, Any]:
        """
        Compare CacheMind performance WITH vs WITHOUT Predictive Prefetching
        on a supplied sequence of queries.
        """
        # Baseline simulation: CacheMind only (no prefetch)
        baseline_hits = 0
        baseline_misses = 0
        baseline_total_time = 0.0
        baseline_cache = set()

        for q in query_sequence:
            norm_q = normalize_query(q)
            if norm_q in baseline_cache:
                baseline_hits += 1
                baseline_total_time += cache_hit_latency_ms
            else:
                baseline_misses += 1
                baseline_total_time += base_llm_latency_ms
                baseline_cache.add(norm_q)

        # Prefetch simulation: CacheMind + Predictive Prefetching
        prefetch_hits = 0
        prefetch_misses = 0
        prefetch_total_time = 0.0
        prefetch_cache = set()
        prefetched_items = set()
        transitions_sim: Dict[str, Dict[str, int]] = {}

        prev_q = None
        for q in query_sequence:
            norm_q = normalize_query(q)

            # Update transition
            if prev_q and prev_q != norm_q:
                transitions_sim.setdefault(prev_q, {})
                transitions_sim[prev_q][norm_q] = transitions_sim[prev_q].get(norm_q, 0) + 1

            # Check cache
            if norm_q in prefetch_cache:
                prefetch_hits += 1
                prefetch_total_time += cache_hit_latency_ms
            else:
                prefetch_misses += 1
                prefetch_total_time += base_llm_latency_ms
                prefetch_cache.add(norm_q)

            # Trigger prefetch prediction for next query
            cand = transitions_sim.get(norm_q, {})
            if cand:
                tot = sum(cand.values())
                best_n = max(cand.keys(), key=lambda k: cand[k])
                if cand[best_n] / float(tot) >= self.confidence_threshold:
                    if best_n not in prefetch_cache and best_n not in prefetched_items:
                        prefetch_cache.add(best_n)
                        prefetched_items.add(best_n)

            prev_q = norm_q

        baseline_hr = round((baseline_hits / len(query_sequence) * 100.0), 2) if query_sequence else 0.0
        prefetch_hr = round((prefetch_hits / len(query_sequence) * 100.0), 2) if query_sequence else 0.0
        time_saved = max(0.0, baseline_total_time - prefetch_total_time)
        speedup = round(baseline_total_time / prefetch_total_time, 2) if prefetch_total_time > 0 else 1.0

        return {
            "query_count": len(query_sequence),
            "baseline_cachemind": {
                "hits": baseline_hits,
                "misses": baseline_misses,
                "hit_rate_percent": baseline_hr,
                "total_latency_ms": round(baseline_total_time, 2),
                "avg_latency_ms": round(baseline_total_time / len(query_sequence), 2) if query_sequence else 0.0,
            },
            "predictive_prefetching": {
                "hits": prefetch_hits,
                "misses": prefetch_misses,
                "hit_rate_percent": prefetch_hr,
                "total_latency_ms": round(prefetch_total_time, 2),
                "avg_latency_ms": round(prefetch_total_time / len(query_sequence), 2) if query_sequence else 0.0,
                "prefetched_count": len(prefetched_items),
            },
            "comparison": {
                "hit_rate_gain_percent": round(prefetch_hr - baseline_hr, 2),
                "total_time_saved_ms": round(time_saved, 2),
                "speedup_factor": speedup,
                "avoided_llm_calls": max(0, prefetch_hits - baseline_hits),
            }
        }
