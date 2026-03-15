"""
OMEGA Pattern Learner -- Memory Content Clustering & Drift Detection

Discovers emergent thematic patterns from memory embeddings using HDBSCAN
clustering and c-TF-IDF labeling. Generates behavioral_pattern memories
with pattern_type values: memory_theme, knowledge_concentration, topic_drift,
behavioral_drift.

Requires: scikit-learn>=1.3.0 (optional dep, graceful fallback).
Data source: memories table + memories_vec (384-dim bge-small-en-v1.5 embeddings).
"""

import json as _json
import logging
import math
import struct
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("omega.pattern_learner")

EMBEDDING_DIM = 384

# Minimum cluster members to generate a pattern
MIN_CLUSTER_SIZE_FOR_PATTERN = 5
# Maximum clusters to generate patterns for (avoid spam)
MAX_CLUSTER_PATTERNS = 20
# Minimum confidence to store a cluster pattern
MIN_STORE_CONFIDENCE = 0.6
# Noise ratio threshold: skip pattern generation if >80% noise
MAX_NOISE_RATIO = 0.80
# CUSUM drift detection threshold
CUSUM_THRESHOLD = 3.0
# EWMA smoothing factor
EWMA_ALPHA = 0.3


def _deserialize_f32(data: bytes, dim: int = EMBEDDING_DIM) -> List[float]:
    """Deserialize bytes to a float32 vector."""
    return list(struct.unpack(f"{dim}f", data))


def _serialize_f32(vector: List[float]) -> bytes:
    """Serialize a float32 vector to bytes."""
    return struct.pack(f"{len(vector)}f", *vector)


class PatternLearner:
    """Discover thematic patterns from memory embeddings."""

    def __init__(self, store=None):
        """Initialize with an optional OmegaSQLiteStore instance.

        If store is None, gets the singleton store via bridge.
        """
        self._store = store

    def _get_store(self):
        if self._store is not None:
            return self._store
        from omega.bridge import _get_store
        return _get_store()

    def _get_conn(self):
        store = self._get_store()
        return store._conn

    def load_memory_embeddings(
        self,
        event_types: Optional[List[str]] = None,
        limit: int = 2000,
    ) -> Tuple[List[str], Any, List[dict]]:
        """Load embeddings from memories_vec joined with memories table.

        Returns (node_ids, embeddings_array, metadata_list).
        Skips memories with hash-fallback embeddings (all near-zero variance).
        """
        import numpy as np

        conn = self._get_conn()

        # Build query with optional event_type filter
        query = """
            SELECT m.node_id, m.content, m.metadata, m.session_id,
                   m.event_type, m.extracted_keywords, v.embedding
            FROM memories m
            JOIN memories_vec v ON v.rowid = m.id
        """
        params: list = []
        if event_types:
            placeholders = ",".join("?" for _ in event_types)
            query += f" WHERE m.event_type IN ({placeholders})"
            params.extend(event_types)

        query += " ORDER BY m.created_at DESC LIMIT ?"
        params.append(limit)

        rows = conn.execute(query, params).fetchall()

        node_ids: List[str] = []
        embeddings: List[List[float]] = []
        metadata_list: List[dict] = []

        for node_id, content, meta_json, session_id, event_type, keywords, emb_bytes in rows:
            if emb_bytes is None:
                continue

            vec = _deserialize_f32(emb_bytes)

            # Skip hash-fallback embeddings (near-zero variance = meaningless)
            arr = np.array(vec)
            if np.var(arr) < 1e-6:
                continue

            meta = _json.loads(meta_json) if meta_json else {}

            node_ids.append(node_id)
            embeddings.append(vec)
            metadata_list.append({
                "content": content or "",
                "session_id": session_id or "",
                "event_type": event_type or "",
                "keywords": keywords or "",
                **meta,
            })

        if not embeddings:
            return [], np.array([]), []

        return node_ids, np.array(embeddings, dtype=np.float32), metadata_list

    def cluster_memories(
        self,
        embeddings: Any,
        min_cluster_size: int = 3,
    ) -> List[int]:
        """Cluster embeddings using HDBSCAN from scikit-learn.

        Returns label array where -1 = noise.
        """
        from sklearn.cluster import HDBSCAN

        clusterer = HDBSCAN(
            min_cluster_size=min_cluster_size,
            metric="cosine",
            cluster_selection_method="eom",
            n_jobs=1,
        )
        labels = clusterer.fit_predict(embeddings)
        return list(labels)

    def label_clusters(
        self,
        node_ids: List[str],
        labels: List[int],
        metadata_list: List[dict],
    ) -> Dict[int, dict]:
        """Label each cluster using c-TF-IDF over keywords and content.

        Returns {cluster_id: {"label": str, "keywords": [...], "member_count": int,
                              "member_node_ids": [...], "session_ids": set}}.
        """
        # Group members by cluster
        cluster_members: Dict[int, List[int]] = {}
        for idx, label in enumerate(labels):
            if label == -1:
                continue
            cluster_members.setdefault(label, []).append(idx)

        # Build per-cluster text and compute c-TF-IDF
        cluster_texts: Dict[int, str] = {}
        for cid, member_indices in cluster_members.items():
            texts = []
            for idx in member_indices:
                meta = metadata_list[idx]
                kw = meta.get("keywords", "")
                content = meta.get("content", "")
                # Prefer keywords, fallback to first 200 chars of content
                text = kw if kw else content[:200]
                texts.append(text)
            cluster_texts[cid] = " ".join(texts)

        ctfidf_scores = self._compute_ctfidf(cluster_texts)

        # Build cluster info
        cluster_info: Dict[int, dict] = {}
        for cid, member_indices in cluster_members.items():
            top_terms = ctfidf_scores.get(cid, [])
            label_parts = [term for term, _ in top_terms[:4]]
            label = " & ".join(label_parts) if label_parts else f"cluster-{cid}"

            session_ids = set()
            member_nids = []
            for idx in member_indices:
                member_nids.append(node_ids[idx])
                sid = metadata_list[idx].get("session_id", "")
                if sid:
                    session_ids.add(sid)

            cluster_info[cid] = {
                "label": label,
                "keywords": [term for term, _ in top_terms[:8]],
                "member_count": len(member_indices),
                "member_node_ids": member_nids[:5],  # Representative sample
                "all_member_node_ids": member_nids,
                "session_ids": session_ids,
            }

        return cluster_info

    def _compute_ctfidf(
        self,
        cluster_texts: Dict[int, str],
    ) -> Dict[int, List[Tuple[str, float]]]:
        """Compute c-TF-IDF scores for cluster labeling.

        Pure Python: Counter for TF, log(N/df) for IDF.
        Returns {cluster_id: [(term, score), ...]} sorted descending.
        """
        n_clusters = len(cluster_texts)
        if n_clusters == 0:
            return {}

        # Tokenize each cluster text
        cluster_tokens: Dict[int, Counter] = {}
        all_df: Counter = Counter()  # document frequency across clusters

        stopwords = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "shall", "can",
            "to", "of", "in", "for", "on", "with", "at", "by", "from",
            "as", "into", "about", "between", "through", "after", "before",
            "above", "below", "and", "or", "but", "not", "no", "nor",
            "so", "if", "then", "than", "that", "this", "these", "those",
            "it", "its", "i", "my", "we", "our", "you", "your", "he",
            "she", "they", "them", "their", "what", "which", "who",
            "when", "where", "how", "all", "each", "every", "both",
            "few", "more", "most", "other", "some", "such", "only",
            "same", "also", "just", "very", "too", "up", "out",
        }

        for cid, text in cluster_texts.items():
            # Simple tokenization: lowercase, split on non-alpha, filter short/stop
            tokens = []
            for word in text.lower().split():
                clean = "".join(c for c in word if c.isalnum() or c == "_")
                if len(clean) >= 3 and clean not in stopwords:
                    tokens.append(clean)

            tf = Counter(tokens)
            cluster_tokens[cid] = tf

            # Document frequency: count clusters containing each term
            for term in set(tokens):
                all_df[term] += 1

        # Compute c-TF-IDF
        result: Dict[int, List[Tuple[str, float]]] = {}
        for cid, tf in cluster_tokens.items():
            total_tokens = sum(tf.values()) or 1
            scores = []
            for term, count in tf.items():
                tf_score = count / total_tokens
                df = all_df.get(term, 1)
                idf = math.log(n_clusters / df) if df < n_clusters else 0.1
                scores.append((term, tf_score * idf))

            scores.sort(key=lambda x: x[1], reverse=True)
            result[cid] = scores

        return result

    def compute_cluster_centroids(
        self,
        embeddings: Any,
        labels: List[int],
    ) -> Dict[int, Any]:
        """Compute mean embedding (centroid) for each cluster."""
        import numpy as np

        centroids: Dict[int, Any] = {}
        cluster_indices: Dict[int, List[int]] = {}

        for idx, label in enumerate(labels):
            if label == -1:
                continue
            cluster_indices.setdefault(label, []).append(idx)

        for cid, indices in cluster_indices.items():
            cluster_embs = embeddings[indices]
            centroids[cid] = np.mean(cluster_embs, axis=0)

        return centroids

    def store_clusters(
        self,
        cluster_info: Dict[int, dict],
        centroids: Dict[int, Any],
    ) -> int:
        """Store cluster state in memory_clusters table.

        Supersedes previous cluster runs. Returns count stored.
        """
        conn = self._get_conn()

        # Supersede old clusters
        conn.execute("UPDATE memory_clusters SET superseded = 1 WHERE superseded = 0")

        now = datetime.now(timezone.utc).isoformat()
        stored = 0

        for cid, info in cluster_info.items():
            centroid_bytes = None
            if cid in centroids:
                centroid_bytes = _serialize_f32(list(centroids[cid].astype(float)))

            conn.execute(
                """INSERT INTO memory_clusters
                   (cluster_id, label, member_count, centroid,
                    representative_keywords, representative_memory_ids,
                    created_at, updated_at, superseded)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)""",
                (
                    cid,
                    info["label"],
                    info["member_count"],
                    centroid_bytes,
                    ", ".join(info.get("keywords", [])),
                    _json.dumps(info.get("all_member_node_ids", info.get("member_node_ids", []))),
                    now,
                    now,
                ),
            )
            stored += 1

        conn.commit()
        return stored

    def generate_cluster_patterns(
        self,
        cluster_info: Dict[int, dict],
        embeddings: Any,
        labels: List[int],
    ) -> List[dict]:
        """Generate behavioral_pattern dicts for significant clusters."""
        total_members = sum(info["member_count"] for info in cluster_info.values())
        if total_members == 0:
            return []

        patterns = []
        for cid, info in sorted(cluster_info.items(), key=lambda x: x[1]["member_count"], reverse=True):
            if len(patterns) >= MAX_CLUSTER_PATTERNS:
                break

            member_count = info["member_count"]
            if member_count < MIN_CLUSTER_SIZE_FOR_PATTERN:
                continue

            # Confidence model
            size_factor = min(member_count / max(total_members * 0.2, 1), 1.0)
            density_factor = self._compute_density(embeddings, labels, cid)
            breadth_factor = min(len(info.get("session_ids", set())) / 10.0, 1.0)

            confidence = round(
                0.3 * size_factor + 0.4 * density_factor + 0.3 * breadth_factor,
                3,
            )

            if confidence < MIN_STORE_CONFIDENCE:
                continue

            session_count = len(info.get("session_ids", set()))
            label = info["label"]
            keywords_str = ", ".join(info.get("keywords", [])[:5])

            patterns.append({
                "content": (
                    f"Knowledge theme: '{label}' "
                    f"({member_count} memories across {session_count} sessions)"
                ),
                "pattern_type": "memory_theme",
                "pattern_key": f"theme:{label.lower().replace(' & ', '-').replace(' ', '-')}",
                "confidence": confidence,
                "evidence_count": int(member_count),
                "evidence_sessions": int(session_count),
                "cluster_id": int(cid),
                "keywords": keywords_str,
                "representative_memory_ids": info.get("member_node_ids", []),
            })

        return patterns

    def _compute_density(
        self,
        embeddings: Any,
        labels: List[int],
        cluster_id: int,
    ) -> float:
        """Compute average intra-cluster cosine similarity (density factor)."""
        import numpy as np

        indices = [i for i, l in enumerate(labels) if l == cluster_id]
        if len(indices) < 2:
            return 0.5

        cluster_embs = embeddings[indices]

        # Normalize for cosine similarity
        norms = np.linalg.norm(cluster_embs, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)
        normed = cluster_embs / norms

        # Average pairwise cosine similarity (sample if large)
        if len(indices) > 50:
            rng = np.random.default_rng(42)
            sample_idx = rng.choice(len(indices), 50, replace=False)
            normed = normed[sample_idx]

        sim_matrix = normed @ normed.T
        # Exclude diagonal
        n = sim_matrix.shape[0]
        mask = ~np.eye(n, dtype=bool)
        avg_sim = float(sim_matrix[mask].mean())

        # Map from cosine sim range [0, 1] to density factor [0, 1]
        return max(0.0, min(avg_sim, 1.0))

    def analyze_and_store(self) -> dict:
        """Main entry point: cluster memories and store patterns.

        Returns summary dict. Gracefully handles missing scikit-learn.
        """
        try:
            import importlib.util
            if importlib.util.find_spec("numpy") is None:
                return {"skipped": "numpy not available"}
        except (ImportError, ValueError):
            return {"skipped": "numpy not available"}

        try:
            from sklearn.cluster import HDBSCAN  # noqa: F401
        except ImportError:
            return {"skipped": "scikit-learn not available"}

        # Load embeddings (outside lock for thread safety)
        node_ids, embeddings, metadata_list = self.load_memory_embeddings()

        if len(node_ids) < 10:
            return {"skipped": "insufficient memories", "count": len(node_ids)}

        # Cluster
        labels = self.cluster_memories(embeddings)

        # Check noise ratio
        noise_count = sum(1 for l in labels if l == -1)
        noise_ratio = noise_count / len(labels)
        if noise_ratio > MAX_NOISE_RATIO:
            logger.warning(
                "HDBSCAN assigned %.0f%% to noise (%d/%d), skipping pattern generation",
                noise_ratio * 100, noise_count, len(labels),
            )
            return {
                "skipped": "high_noise_ratio",
                "noise_ratio": round(noise_ratio, 2),
                "total": len(labels),
            }

        # Label clusters
        cluster_info = self.label_clusters(node_ids, labels, metadata_list)
        clusters_found = len(cluster_info)

        # Compute centroids
        centroids = self.compute_cluster_centroids(embeddings, labels)

        # Store cluster state (inside lock via store)
        stored_clusters = self.store_clusters(cluster_info, centroids)

        # Generate patterns
        patterns = self.generate_cluster_patterns(cluster_info, embeddings, labels)

        # Store patterns through behavioral pipeline
        stored = 0
        for pattern in patterns:
            try:
                self._store_or_reinforce_pattern(pattern)
                stored += 1
            except Exception as e:
                logger.warning("Failed to store cluster pattern: %s", e)

        # Generate effectiveness patterns from Thompson data
        effectiveness_stored = 0
        try:
            eff_patterns = self.generate_effectiveness_patterns()
            for pat in eff_patterns:
                try:
                    self._store_or_reinforce_pattern(pat)
                    effectiveness_stored += 1
                except Exception as e:
                    logger.warning("Failed to store effectiveness pattern: %s", e)
        except Exception as e:
            logger.warning("Failed to generate effectiveness patterns: %s", e)

        result = {
            "total_memories": len(node_ids),
            "clusters_found": clusters_found,
            "noise_ratio": round(noise_ratio, 2),
            "stored_clusters": stored_clusters,
            "patterns_generated": len(patterns),
            "stored": stored,
            "effectiveness_stored": effectiveness_stored,
        }
        logger.info("Pattern learning complete: %s", result)
        return result

    def generate_effectiveness_patterns(self) -> List[dict]:
        """Generate behavioral_patterns capturing Thompson effectiveness rankings.

        Reads current Thompson arms and stores the top-ranked memory types
        so the data is available in Supabase for the admin UI.
        """
        try:
            from omega.thompson import ThompsonBandit
        except ImportError:
            return []

        bandit = ThompsonBandit(store=self._get_store())
        rankings = bandit.get_rankings()

        if not rankings:
            return []

        # Only include event_type arms with meaningful data
        event_type_arms = [
            r for r in rankings
            if r.get("arm_type") == "event_type" and r.get("total_trials", 0) >= 3
        ]

        if not event_type_arms:
            return []

        # Map expected rates to verbal labels
        def _verbal(rate: float, trials: int) -> str:
            if trials < 5:
                return "Needs data"
            if rate >= 0.70:
                return "Very helpful"
            if rate >= 0.50:
                return "Helpful"
            if rate >= 0.30:
                return "Mixed"
            return "Needs data"

        arms_data = []
        for arm in event_type_arms:
            arm_id = arm["arm_id"]
            type_name = arm_id.replace("event_type:", "")
            expected = arm.get("expected_rate", 0)
            trials = arm.get("total_trials", 0)
            successes = arm.get("total_successes", 0)
            verbal = _verbal(expected, trials)
            arms_data.append({
                "type": type_name,
                "trials": trials,
                "successes": successes,
                "expected_rate": round(expected, 3),
                "verbal": verbal,
            })

        content = (
            f"Memory effectiveness ranking: "
            f"{arms_data[0]['type']} is most effective "
            f"({arms_data[0]['verbal']}, {arms_data[0]['trials']} trials)"
        )

        return [{
            "content": content,
            "pattern_type": "effectiveness_ranking",
            "pattern_key": "effectiveness:memory_types",
            "confidence": 0.80,
            "evidence_count": sum(a["trials"] for a in arms_data),
            "evidence_sessions": 0,
            "arms": arms_data,
        }]

    def _store_or_reinforce_pattern(self, pattern: dict) -> None:
        """Store a new pattern or reinforce an existing one."""
        from omega.bridge import auto_capture, _get_store

        store = _get_store()

        # Check for existing pattern with same key
        existing = store.get_by_type("behavioral_pattern", limit=100)
        for mem in existing:
            meta = mem.metadata or {}
            if meta.get("pattern_key") == pattern["pattern_key"]:
                # Reinforce: bump confidence and update evidence
                meta["evidence_count"] = max(
                    meta.get("evidence_count", 0), pattern["evidence_count"],
                )
                meta["evidence_sessions"] = max(
                    meta.get("evidence_sessions", 0), pattern["evidence_sessions"],
                )
                meta["last_evidence_at"] = datetime.now(timezone.utc).isoformat()
                old_conf = meta.get("confidence", 0)
                new_conf = min(old_conf + 0.03, 0.95)
                if meta.get("user_confirmed"):
                    new_conf = min(old_conf + 0.03, 1.0)
                meta["confidence"] = round(new_conf, 3)
                store.update_node(mem.id, metadata=meta)
                return

        # New pattern
        metadata = {
            "source": "pattern_learner",
            "pattern_type": pattern["pattern_type"],
            "confidence": pattern["confidence"],
            "evidence_count": pattern["evidence_count"],
            "evidence_sessions": pattern["evidence_sessions"],
            "pattern_key": pattern["pattern_key"],
            "user_confirmed": None,
        }
        if "cluster_id" in pattern:
            metadata["cluster_id"] = pattern["cluster_id"]
        if "keywords" in pattern:
            metadata["keywords"] = pattern["keywords"]
        if "representative_memory_ids" in pattern:
            metadata["representative_memory_ids"] = pattern["representative_memory_ids"]
        if "arms" in pattern:
            metadata["arms"] = pattern["arms"]

        auto_capture(
            content=pattern["content"],
            event_type="behavioral_pattern",
            metadata=metadata,
        )

    def get_active_clusters(self) -> List[dict]:
        """Get current (non-superseded) clusters."""
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT cluster_id, label, member_count, representative_keywords,
                      representative_memory_ids, created_at
               FROM memory_clusters
               WHERE superseded = 0
               ORDER BY member_count DESC"""
        ).fetchall()

        clusters = []
        for cid, label, count, keywords, member_ids_json, created in rows:
            clusters.append({
                "cluster_id": cid,
                "label": label,
                "member_count": count,
                "keywords": keywords,
                "representative_memory_ids": _json.loads(member_ids_json) if member_ids_json else [],
                "created_at": created,
            })

        return clusters

    def get_clusters_for_retrieval(self) -> List[dict]:
        """Get active clusters with deserialized centroids for retrieval boosting.

        Returns list of dicts with cluster_id, centroid (as list of floats),
        and member_node_ids. Skips clusters without centroids.
        """
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT cluster_id, centroid, representative_memory_ids
               FROM memory_clusters
               WHERE superseded = 0 AND centroid IS NOT NULL"""
        ).fetchall()

        clusters = []
        for cid, centroid_bytes, member_ids_json in rows:
            if centroid_bytes is None:
                continue
            try:
                centroid = _deserialize_f32(centroid_bytes)
            except Exception as e:
                logger.debug("Centroid deserialization failed for cluster %s: %s", cid, e)
                continue
            member_ids = _json.loads(member_ids_json) if member_ids_json else []
            clusters.append({
                "cluster_id": cid,
                "centroid": centroid,
                "member_node_ids": member_ids,
            })

        return clusters

    def generate_welcome_patterns(self, limit: int = 3) -> List[str]:
        """Generate plain-text pattern lines for session start welcome briefing.

        Reads memory_clusters (non-superseded) and thompson_arms to produce
        human-readable lines summarizing top themes, most effective memory type,
        and any active drift signals.

        Slot allocation prioritizes drift (time-sensitive) over static info:
        - limit=3: themes + effectiveness + drift
        - limit=2 with drift: themes + drift
        - limit=2 no drift: themes + effectiveness
        - limit=1 with drift: drift
        - limit=1 no drift: themes

        Returns empty list if no pattern data exists (graceful fallback).
        """
        # --- Collect all categories independently ---
        theme_line: Optional[str] = None
        effectiveness_line: Optional[str] = None
        drift_lines: List[str] = []

        # Top theme clusters
        try:
            clusters = self.get_active_clusters()
            if clusters:
                theme_parts = []
                for c in clusters[:limit]:
                    label = c.get("label", "unknown")
                    count = c.get("member_count", 0)
                    theme_parts.append(f"'{label}' ({count} memories)")
                if theme_parts:
                    theme_line = f"Top themes: {', '.join(theme_parts)}"
        except Exception as e:
            logger.debug("Welcome patterns: cluster read failed: %s", e)

        # Most effective memory type from Thompson rankings
        try:
            from omega.thompson import ThompsonBandit
            bandit = ThompsonBandit(store=self._get_store())
            rankings = bandit.get_rankings()
            event_type_arms = [
                r for r in rankings
                if r.get("arm_type") == "event_type" and r.get("total_trials", 0) >= 3
            ]
            if event_type_arms:
                best = event_type_arms[0]
                arm_id = best["arm_id"]
                type_name = arm_id.replace("event_type:", "")
                trials = best.get("total_trials", 0)
                expected = best.get("expected_rate", 0)
                if trials < 5:
                    verbal = "Needs data"
                elif expected >= 0.70:
                    verbal = "Very helpful"
                elif expected >= 0.50:
                    verbal = "Helpful"
                elif expected >= 0.30:
                    verbal = "Mixed"
                else:
                    verbal = "Needs data"
                pct = int(expected * 100)
                effectiveness_line = (
                    f"Most effective type: {type_name} ({verbal}, {pct}% over {trials} trials)"
                )
        except ImportError:
            pass  # Thompson module not available
        except Exception as e:
            logger.debug("Welcome patterns: Thompson read failed: %s", e)

        # Drift signals (from stored behavioral_pattern memories)
        try:
            conn = self._get_conn()
            drift_rows = conn.execute(
                """SELECT content FROM memories
                   WHERE event_type = 'behavioral_pattern'
                   AND json_extract(metadata, '$.pattern_type') = 'topic_drift'
                   ORDER BY created_at DESC LIMIT 2"""
            ).fetchall()
            for (content,) in drift_rows:
                if content:
                    drift_lines.append(content.replace("Topic drift: ", "Drift: "))
        except Exception as e:
            logger.debug("Welcome patterns: drift read failed: %s", e)

        # --- Merge with priority-based slot allocation ---
        # Drift is time-sensitive (something changed), so it gets guaranteed
        # slots over static info when space is constrained.
        lines: List[str] = []
        has_drift = len(drift_lines) > 0

        if has_drift:
            # Reserve at least 1 slot for drift
            drift_slots = max(1, limit - 2) if limit >= 2 else limit
            non_drift_slots = limit - min(drift_slots, len(drift_lines))
            # Fill non-drift: themes first, then effectiveness
            if non_drift_slots >= 1 and theme_line:
                lines.append(theme_line)
                non_drift_slots -= 1
            if non_drift_slots >= 1 and effectiveness_line:
                lines.append(effectiveness_line)
            # Then drift
            for dl in drift_lines[:drift_slots]:
                if len(lines) < limit:
                    lines.append(dl)
        else:
            # No drift: themes first, then effectiveness
            if theme_line:
                lines.append(theme_line)
            if effectiveness_line and len(lines) < limit:
                lines.append(effectiveness_line)

        return lines[:limit]

    # ------------------------------------------------------------------
    # Phase 3: Drift Detection
    # ------------------------------------------------------------------

    def detect_topic_drift(
        self,
        window_days: int = 30,
        min_windows: int = 3,
    ) -> List[dict]:
        """Detect topic emergence/decline using CUSUM on cluster sizes over time.

        Compares cluster membership counts across time windows to detect
        significant shifts in topic interest.
        """
        import numpy as np

        conn = self._get_conn()

        # Get all non-superseded cluster snapshots with timestamps
        rows = conn.execute(
            """SELECT cluster_id, label, member_count, created_at
               FROM memory_clusters
               ORDER BY created_at ASC"""
        ).fetchall()

        if len(rows) < min_windows:
            return []

        # Group by creation timestamp (each analyze_and_store run is a snapshot)
        snapshots: Dict[str, Dict[int, int]] = {}
        snapshot_labels: Dict[int, str] = {}
        for cid, label, count, created in rows:
            # Use date portion as window key
            window_key = created[:10] if created else "unknown"
            snapshots.setdefault(window_key, {})[cid] = count
            snapshot_labels[cid] = label

        if len(snapshots) < min_windows:
            return []

        # CUSUM per cluster across snapshots
        patterns = []
        sorted_windows = sorted(snapshots.keys())

        # Track all cluster_ids seen
        all_cids = set()
        for window_data in snapshots.values():
            all_cids.update(window_data.keys())

        for cid in all_cids:
            sizes = [snapshots[w].get(cid, 0) for w in sorted_windows]

            if len(sizes) < min_windows:
                continue

            arr = np.array(sizes, dtype=float)
            mean_size = float(np.mean(arr))
            if mean_size == 0:
                continue

            # CUSUM: cumulative sum of deviations from mean
            deviations = arr - mean_size
            cusum_pos = np.zeros(len(deviations))
            cusum_neg = np.zeros(len(deviations))

            for i in range(1, len(deviations)):
                cusum_pos[i] = max(0, cusum_pos[i - 1] + deviations[i])
                cusum_neg[i] = min(0, cusum_neg[i - 1] + deviations[i])

            max_pos = float(np.max(cusum_pos))
            max_neg = float(np.min(cusum_neg))

            label = snapshot_labels.get(cid, f"cluster-{cid}")

            # Emergence: significant positive CUSUM
            if max_pos > CUSUM_THRESHOLD * mean_size and mean_size > 0:
                trend = "growing"
                latest = sizes[-1]
                earliest = sizes[0]
                pct_change = ((latest - earliest) / max(earliest, 1)) * 100

                patterns.append({
                    "content": (
                        f"Topic drift: '{label}' is {trend} "
                        f"({earliest} -> {latest} memories, "
                        f"{pct_change:+.0f}% over {len(sorted_windows)} snapshots)"
                    ),
                    "pattern_type": "topic_drift",
                    "pattern_key": f"drift:topic:{label.lower().replace(' & ', '-').replace(' ', '-')}",
                    "confidence": min(0.5 + max_pos / (CUSUM_THRESHOLD * mean_size * 3), 0.95),
                    "evidence_count": sum(sizes),
                    "evidence_sessions": len(sorted_windows),
                    "direction": trend,
                    "cluster_id": cid,
                })

            # Decline: significant negative CUSUM
            if abs(max_neg) > CUSUM_THRESHOLD * mean_size and mean_size > 0:
                trend = "declining"
                latest = sizes[-1]
                earliest = sizes[0]
                pct_change = ((latest - earliest) / max(earliest, 1)) * 100

                patterns.append({
                    "content": (
                        f"Topic drift: '{label}' is {trend} "
                        f"({earliest} -> {latest} memories, "
                        f"{pct_change:+.0f}% over {len(sorted_windows)} snapshots)"
                    ),
                    "pattern_type": "topic_drift",
                    "pattern_key": f"drift:topic:{label.lower().replace(' & ', '-').replace(' ', '-')}:decline",
                    "confidence": min(0.5 + abs(max_neg) / (CUSUM_THRESHOLD * mean_size * 3), 0.95),
                    "evidence_count": sum(sizes),
                    "evidence_sessions": len(sorted_windows),
                    "direction": trend,
                    "cluster_id": cid,
                })

        return patterns

    def detect_behavioral_drift(
        self,
        window_days: int = 7,
        min_windows: int = 4,
    ) -> List[dict]:
        """Detect behavioral drift using EWMA on session metrics.

        Monitors: avg session length, tool diversity, memory creation rate.
        Pure NumPy, no new deps.
        """
        import numpy as np

        conn = self._get_conn()

        # Check if coord_sessions exists
        has_sessions = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='coord_sessions'"
        ).fetchone()
        if not has_sessions:
            return []

        rows = conn.execute(
            """SELECT session_id, started_at, ended_at
               FROM coord_sessions
               WHERE started_at IS NOT NULL
               ORDER BY started_at ASC"""
        ).fetchall()

        if len(rows) < min_windows * 3:
            return []

        # Compute per-session duration in minutes
        durations = []
        session_dates = []
        for sid, started, ended in rows:
            if not started or not ended:
                continue
            try:
                s = datetime.fromisoformat(started.replace("Z", "+00:00"))
                e = datetime.fromisoformat(ended.replace("Z", "+00:00"))
                dur = (e - s).total_seconds() / 60.0
                if 0 < dur < 1440:  # Filter unreasonable durations
                    durations.append(dur)
                    session_dates.append(s)
            except (ValueError, TypeError):
                continue

        if len(durations) < min_windows * 3:
            return []

        arr = np.array(durations)

        # EWMA smoothing
        ewma = np.zeros(len(arr))
        ewma[0] = arr[0]
        for i in range(1, len(arr)):
            ewma[i] = EWMA_ALPHA * arr[i] + (1 - EWMA_ALPHA) * ewma[i - 1]

        # Detect drift: compare recent EWMA to historical mean
        if len(ewma) < 10:
            return []

        recent = ewma[-5:]
        historical = ewma[:-5]
        recent_mean = float(np.mean(recent))
        hist_mean = float(np.mean(historical))
        hist_std = float(np.std(historical))

        if hist_std == 0:
            return []

        z_score = (recent_mean - hist_mean) / hist_std

        patterns = []
        if abs(z_score) > 2.0:
            direction = "longer" if z_score > 0 else "shorter"
            pct_change = ((recent_mean - hist_mean) / hist_mean) * 100

            patterns.append({
                "content": (
                    f"Behavioral drift: sessions are {pct_change:+.0f}% {direction} recently "
                    f"({recent_mean:.0f}min avg vs {hist_mean:.0f}min historical)"
                ),
                "pattern_type": "behavioral_drift",
                "pattern_key": f"drift:session_duration:{direction}",
                "confidence": min(0.5 + abs(z_score) / 6.0, 0.95),
                "evidence_count": len(durations),
                "evidence_sessions": len(durations),
                "z_score": round(z_score, 2),
                "direction": direction,
            })

        return patterns

    # ------------------------------------------------------------------
    # Phase 3: Meta-Memory Synthesis
    # ------------------------------------------------------------------

    def synthesize_meta_memories(
        self,
        cluster_info: Optional[Dict[int, dict]] = None,
        min_members: int = 8,
    ) -> List[dict]:
        """Generate template-based summary memories for significant clusters.

        Creates knowledge_concentration patterns that synthesize cluster themes.
        """
        if cluster_info is None:
            # Load from stored clusters
            active = self.get_active_clusters()
            cluster_info = {}
            for c in active:
                cluster_info[c["cluster_id"]] = {
                    "label": c["label"],
                    "member_count": c["member_count"],
                    "keywords": c.get("keywords", "").split(", ") if c.get("keywords") else [],
                    "member_node_ids": c.get("representative_memory_ids", []),
                    "session_ids": set(),  # Not available from stored clusters
                }

        patterns = []
        for cid, info in cluster_info.items():
            if info["member_count"] < min_members:
                continue

            label = info["label"]
            n = info["member_count"]
            session_count = len(info.get("session_ids", set())) or "multiple"
            keywords = info.get("keywords", [])
            kw_str = ", ".join(keywords[:5]) if keywords else label

            content = (
                f"Recurring theme: {label}. "
                f"Based on {n} memories across {session_count} sessions. "
                f"Key topics: {kw_str}."
            )

            patterns.append({
                "content": content,
                "pattern_type": "knowledge_concentration",
                "pattern_key": f"concentration:{label.lower().replace(' & ', '-').replace(' ', '-')}",
                "confidence": min(0.6 + (n / 100.0), 0.95),
                "evidence_count": n,
                "evidence_sessions": len(info.get("session_ids", set())) if isinstance(info.get("session_ids"), set) else 0,
                "cluster_id": cid,
                "keywords": kw_str,
                "member_node_ids": info.get("member_node_ids", []),
            })

        return patterns
