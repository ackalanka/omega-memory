"""
OMEGA Thompson Sampling -- Outcome-Correlated Learning

Treats memory event types and clusters as multi-armed bandit "arms."
Tracks success/failure when memories are surfaced and learns which
types to prioritize using Thompson Sampling with Beta distributions.

Zero new dependencies: uses random.betavariate (stdlib).
"""

import json as _json
import logging
import random
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("omega.thompson")

# Default prior: Beta(1, 1) = uniform
DEFAULT_ALPHA = 1.0
DEFAULT_BETA = 1.0

# Boost range applied to query scores
MIN_BOOST = 0.8
MAX_BOOST = 1.2

# Minimum trials before arm influences scoring
MIN_TRIALS_FOR_BOOST = 5


class ThompsonBandit:
    """Multi-armed bandit using Thompson Sampling for memory prioritization."""

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

    def _locked_execute_and_commit(self, *statements):
        """Execute SQL statements under the store's lock, then commit."""
        store = self._get_store()
        with store._lock:
            for sql, params in statements:
                store._conn.execute(sql, params)
            store._conn.commit()

    def _ensure_arm(self, arm_id: str, arm_type: str, context: Optional[str] = None) -> None:
        """Create arm if it doesn't exist."""
        now = datetime.now(timezone.utc).isoformat()
        self._locked_execute_and_commit(
            ("""INSERT OR IGNORE INTO thompson_arms
               (arm_id, arm_type, alpha, beta, total_trials, total_successes,
                last_updated, context)
               VALUES (?, ?, ?, ?, 0, 0, ?, ?)""",
             (arm_id, arm_type, DEFAULT_ALPHA, DEFAULT_BETA, now, context)),
        )

    def record_outcome(
        self,
        arm_id: str,
        arm_type: str,
        success: bool,
        context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record a success or failure for an arm.

        Args:
            arm_id: Unique identifier (e.g., "event_type:decision", "cluster:3")
            arm_type: Category ("event_type", "cluster", "pattern_type")
            success: Whether the surfaced memory was helpful
            context: Optional JSON context (project, entity_id)
        """
        self._ensure_arm(arm_id, arm_type, context)

        now = datetime.now(timezone.utc).isoformat()

        if success:
            sql = """UPDATE thompson_arms
                     SET alpha = alpha + 1, total_trials = total_trials + 1,
                         total_successes = total_successes + 1, last_updated = ?
                     WHERE arm_id = ?"""
        else:
            sql = """UPDATE thompson_arms
                     SET beta = beta + 1, total_trials = total_trials + 1,
                         last_updated = ?
                     WHERE arm_id = ?"""

        self._locked_execute_and_commit((sql, (now, arm_id)))

        # Read back (reads are safe without lock in WAL mode)
        conn = self._get_conn()
        row = conn.execute(
            "SELECT alpha, beta, total_trials, total_successes FROM thompson_arms WHERE arm_id = ?",
            (arm_id,),
        ).fetchone()

        if row:
            return {
                "arm_id": arm_id,
                "alpha": row[0],
                "beta": row[1],
                "total_trials": row[2],
                "total_successes": row[3],
                "success_rate": row[3] / max(row[2], 1),
            }
        return {"arm_id": arm_id, "error": "arm not found after update"}

    def sample_priorities(self, arm_ids: List[str]) -> Dict[str, float]:
        """Sample from Beta distributions to get priority scores.

        Returns {arm_id: sampled_score} where score is in [0, 1].
        Arms not in the database get the default uniform prior.
        """
        conn = self._get_conn()

        if not arm_ids:
            return {}

        # Fetch all requested arms in one query
        placeholders = ",".join("?" for _ in arm_ids)
        rows = conn.execute(
            f"SELECT arm_id, alpha, beta FROM thompson_arms WHERE arm_id IN ({placeholders})",
            arm_ids,
        ).fetchall()

        arm_params = {row[0]: (row[1], row[2]) for row in rows}

        result = {}
        for arm_id in arm_ids:
            alpha, beta = arm_params.get(arm_id, (DEFAULT_ALPHA, DEFAULT_BETA))
            # Thompson sampling: draw from Beta(alpha, beta)
            result[arm_id] = random.betavariate(alpha, beta)

        return result

    def get_boost_factor(self, arm_id: str) -> float:
        """Get a deterministic boost factor for query scoring.

        Maps the arm's estimated success rate to [MIN_BOOST, MAX_BOOST].
        Arms with fewer than MIN_TRIALS_FOR_BOOST trials return 1.0 (neutral).
        """
        conn = self._get_conn()
        row = conn.execute(
            "SELECT alpha, beta, total_trials FROM thompson_arms WHERE arm_id = ?",
            (arm_id,),
        ).fetchone()

        if not row or row[2] < MIN_TRIALS_FOR_BOOST:
            return 1.0

        alpha, beta_val, _ = row
        # Expected value of Beta distribution = alpha / (alpha + beta)
        expected = alpha / (alpha + beta_val)

        # Map [0, 1] -> [MIN_BOOST, MAX_BOOST]
        return MIN_BOOST + expected * (MAX_BOOST - MIN_BOOST)

    def get_rankings(self) -> List[dict]:
        """Get all arms ranked by estimated success rate.

        Returns list of dicts sorted by expected success rate descending.
        """
        conn = self._get_conn()
        rows = conn.execute(
            """SELECT arm_id, arm_type, alpha, beta,
                      total_trials, total_successes, last_updated, context
               FROM thompson_arms
               ORDER BY (CAST(alpha AS REAL) / (alpha + beta)) DESC"""
        ).fetchall()

        rankings = []
        for arm_id, arm_type, alpha, beta_val, trials, successes, updated, ctx in rows:
            expected = alpha / (alpha + beta_val)
            rankings.append({
                "arm_id": arm_id,
                "arm_type": arm_type,
                "alpha": alpha,
                "beta": beta_val,
                "total_trials": trials,
                "total_successes": successes,
                "expected_rate": round(expected, 3),
                "boost_factor": round(MIN_BOOST + expected * (MAX_BOOST - MIN_BOOST), 3),
                "last_updated": updated,
                "context": _json.loads(ctx) if ctx else None,
            })

        return rankings

    def decay_arms(self, factor: float = 0.99) -> int:
        """Apply decay to all arms, pulling them toward the prior.

        Multiplies alpha and beta by factor, keeping a minimum of 1.0.
        This prevents stale arms from dominating indefinitely.
        Returns count of arms decayed.
        """
        conn = self._get_conn()
        now = datetime.now(timezone.utc).isoformat()

        rows = conn.execute(
            "SELECT arm_id, alpha, beta FROM thompson_arms"
        ).fetchall()

        updates = []
        for arm_id, alpha, beta_val in rows:
            new_alpha = max(DEFAULT_ALPHA, alpha * factor)
            new_beta = max(DEFAULT_BETA, beta_val * factor)

            if new_alpha != alpha or new_beta != beta_val:
                updates.append((
                    """UPDATE thompson_arms SET alpha = ?, beta = ?, last_updated = ?
                       WHERE arm_id = ?""",
                    (new_alpha, new_beta, now, arm_id),
                ))

        if updates:
            self._locked_execute_and_commit(*updates)
        return len(updates)

    def get_arm(self, arm_id: str) -> Optional[dict]:
        """Get a single arm's state."""
        conn = self._get_conn()
        row = conn.execute(
            """SELECT arm_id, arm_type, alpha, beta,
                      total_trials, total_successes, last_updated, context
               FROM thompson_arms WHERE arm_id = ?""",
            (arm_id,),
        ).fetchone()

        if not row:
            return None

        alpha, beta_val = row[2], row[3]
        expected = alpha / (alpha + beta_val)
        return {
            "arm_id": row[0],
            "arm_type": row[1],
            "alpha": alpha,
            "beta": beta_val,
            "total_trials": row[4],
            "total_successes": row[5],
            "expected_rate": round(expected, 3),
            "last_updated": row[6],
            "context": _json.loads(row[7]) if row[7] else None,
        }
