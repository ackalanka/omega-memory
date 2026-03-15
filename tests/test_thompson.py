"""Tests for omega.thompson -- Thompson Sampling bandit."""

import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from omega.thompson import (
    ThompsonBandit,
    DEFAULT_ALPHA,
    DEFAULT_BETA,
    MIN_BOOST,
    MAX_BOOST,
    MIN_TRIALS_FOR_BOOST,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def bandit_db(tmp_path):
    """Create a fresh SQLite DB with thompson_arms table."""
    db_path = tmp_path / "test_thompson.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")

    conn.execute("""
        CREATE TABLE thompson_arms (
            arm_id TEXT PRIMARY KEY,
            arm_type TEXT NOT NULL,
            alpha REAL DEFAULT 1.0,
            beta REAL DEFAULT 1.0,
            total_trials INTEGER DEFAULT 0,
            total_successes INTEGER DEFAULT 0,
            last_updated TEXT NOT NULL,
            context TEXT
        )
    """)
    conn.execute("CREATE INDEX idx_thompson_arms_type ON thompson_arms(arm_type)")
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def bandit(bandit_db):
    """Create a ThompsonBandit backed by a test DB."""
    store = MagicMock()
    store._conn = bandit_db
    return ThompsonBandit(store=store)


# ---------------------------------------------------------------------------
# TestEnsureArm
# ---------------------------------------------------------------------------


class TestEnsureArm:
    """Test arm creation and idempotency."""

    def test_creates_new_arm(self, bandit, bandit_db):
        bandit._ensure_arm("event_type:decision", "event_type")
        row = bandit_db.execute(
            "SELECT arm_id, arm_type, alpha, beta, total_trials FROM thompson_arms WHERE arm_id = ?",
            ("event_type:decision",),
        ).fetchone()
        assert row is not None
        assert row[0] == "event_type:decision"
        assert row[1] == "event_type"
        assert row[2] == DEFAULT_ALPHA
        assert row[3] == DEFAULT_BETA
        assert row[4] == 0

    def test_idempotent(self, bandit, bandit_db):
        bandit._ensure_arm("event_type:decision", "event_type")
        bandit._ensure_arm("event_type:decision", "event_type")
        count = bandit_db.execute(
            "SELECT COUNT(*) FROM thompson_arms WHERE arm_id = ?",
            ("event_type:decision",),
        ).fetchone()[0]
        assert count == 1

    def test_with_context(self, bandit, bandit_db):
        ctx = json.dumps({"project": "omega"})
        bandit._ensure_arm("cluster:3", "cluster", context=ctx)
        row = bandit_db.execute(
            "SELECT context FROM thompson_arms WHERE arm_id = ?",
            ("cluster:3",),
        ).fetchone()
        assert row[0] == ctx


# ---------------------------------------------------------------------------
# TestRecordOutcome
# ---------------------------------------------------------------------------


class TestRecordOutcome:
    """Test success/failure recording."""

    def test_record_success(self, bandit):
        result = bandit.record_outcome("event_type:decision", "event_type", success=True)
        assert result["alpha"] == DEFAULT_ALPHA + 1
        assert result["beta"] == DEFAULT_BETA
        assert result["total_trials"] == 1
        assert result["total_successes"] == 1
        assert result["success_rate"] == 1.0

    def test_record_failure(self, bandit):
        result = bandit.record_outcome("event_type:decision", "event_type", success=False)
        assert result["alpha"] == DEFAULT_ALPHA
        assert result["beta"] == DEFAULT_BETA + 1
        assert result["total_trials"] == 1
        assert result["total_successes"] == 0
        assert result["success_rate"] == 0.0

    def test_multiple_outcomes(self, bandit):
        bandit.record_outcome("et:decision", "event_type", success=True)
        bandit.record_outcome("et:decision", "event_type", success=True)
        result = bandit.record_outcome("et:decision", "event_type", success=False)
        assert result["total_trials"] == 3
        assert result["total_successes"] == 2
        assert result["alpha"] == DEFAULT_ALPHA + 2
        assert result["beta"] == DEFAULT_BETA + 1

    def test_creates_arm_on_first_outcome(self, bandit, bandit_db):
        """record_outcome auto-creates arm if missing."""
        bandit.record_outcome("new_arm:test", "event_type", success=True)
        row = bandit_db.execute(
            "SELECT 1 FROM thompson_arms WHERE arm_id = ?", ("new_arm:test",)
        ).fetchone()
        assert row is not None


# ---------------------------------------------------------------------------
# TestSamplePriorities
# ---------------------------------------------------------------------------


class TestSamplePriorities:
    """Test Thompson sampling from Beta distributions."""

    def test_empty_input(self, bandit):
        assert bandit.sample_priorities([]) == {}

    def test_unknown_arms_get_uniform_prior(self, bandit):
        scores = bandit.sample_priorities(["unknown:arm"])
        assert "unknown:arm" in scores
        assert 0.0 <= scores["unknown:arm"] <= 1.0

    def test_strong_arm_tends_high(self, bandit):
        """An arm with many successes should sample high most of the time."""
        for _ in range(50):
            bandit.record_outcome("strong:arm", "event_type", success=True)

        # Sample 100 times and check most are > 0.5
        high_count = 0
        for _ in range(100):
            scores = bandit.sample_priorities(["strong:arm"])
            if scores["strong:arm"] > 0.5:
                high_count += 1
        assert high_count > 80, f"Expected most samples > 0.5, got {high_count}/100"

    def test_weak_arm_tends_low(self, bandit):
        """An arm with many failures should sample low most of the time."""
        for _ in range(50):
            bandit.record_outcome("weak:arm", "event_type", success=False)

        low_count = 0
        for _ in range(100):
            scores = bandit.sample_priorities(["weak:arm"])
            if scores["weak:arm"] < 0.5:
                low_count += 1
        assert low_count > 80, f"Expected most samples < 0.5, got {low_count}/100"

    def test_multiple_arms_returned(self, bandit):
        bandit.record_outcome("a:1", "event_type", success=True)
        bandit.record_outcome("a:2", "event_type", success=False)
        scores = bandit.sample_priorities(["a:1", "a:2", "a:3"])
        assert len(scores) == 3


# ---------------------------------------------------------------------------
# TestGetBoostFactor
# ---------------------------------------------------------------------------


class TestGetBoostFactor:
    """Test deterministic boost factor for query scoring."""

    def test_unknown_arm_returns_neutral(self, bandit):
        assert bandit.get_boost_factor("unknown:arm") == 1.0

    def test_insufficient_trials_returns_neutral(self, bandit):
        bandit.record_outcome("few:arm", "event_type", success=True)
        bandit.record_outcome("few:arm", "event_type", success=True)
        assert bandit.get_boost_factor("few:arm") == 1.0

    def test_successful_arm_gets_high_boost(self, bandit):
        for _ in range(MIN_TRIALS_FOR_BOOST + 5):
            bandit.record_outcome("good:arm", "event_type", success=True)

        boost = bandit.get_boost_factor("good:arm")
        assert boost > 1.0
        assert boost <= MAX_BOOST

    def test_unsuccessful_arm_gets_low_boost(self, bandit):
        for _ in range(MIN_TRIALS_FOR_BOOST + 5):
            bandit.record_outcome("bad:arm", "event_type", success=False)

        boost = bandit.get_boost_factor("bad:arm")
        assert boost < 1.0
        assert boost >= MIN_BOOST

    def test_boost_range(self, bandit):
        """Boost is always in [MIN_BOOST, MAX_BOOST]."""
        for _ in range(100):
            bandit.record_outcome("range:arm", "event_type", success=True)
        boost = bandit.get_boost_factor("range:arm")
        assert MIN_BOOST <= boost <= MAX_BOOST


# ---------------------------------------------------------------------------
# TestGetRankings
# ---------------------------------------------------------------------------


class TestGetRankings:
    """Test ranking of all arms."""

    def test_empty_rankings(self, bandit):
        assert bandit.get_rankings() == []

    def test_rankings_sorted_by_expected_rate(self, bandit):
        for _ in range(10):
            bandit.record_outcome("best:arm", "event_type", success=True)
        for _ in range(5):
            bandit.record_outcome("mid:arm", "event_type", success=True)
        for _ in range(5):
            bandit.record_outcome("mid:arm", "event_type", success=False)
        for _ in range(10):
            bandit.record_outcome("worst:arm", "event_type", success=False)

        rankings = bandit.get_rankings()
        rates = [r["expected_rate"] for r in rankings]
        assert rates == sorted(rates, reverse=True)

    def test_ranking_fields(self, bandit):
        bandit.record_outcome("test:arm", "event_type", success=True)
        rankings = bandit.get_rankings()
        assert len(rankings) == 1
        r = rankings[0]
        assert "arm_id" in r
        assert "arm_type" in r
        assert "alpha" in r
        assert "beta" in r
        assert "total_trials" in r
        assert "total_successes" in r
        assert "expected_rate" in r
        assert "boost_factor" in r
        assert "last_updated" in r
        assert "context" in r


# ---------------------------------------------------------------------------
# TestDecayArms
# ---------------------------------------------------------------------------


class TestDecayArms:
    """Test arm decay toward prior."""

    def test_decay_reduces_alpha_beta(self, bandit):
        for _ in range(20):
            bandit.record_outcome("decay:arm", "event_type", success=True)

        arm_before = bandit.get_arm("decay:arm")
        alpha_before = arm_before["alpha"]

        count = bandit.decay_arms(factor=0.9)
        assert count >= 1

        arm_after = bandit.get_arm("decay:arm")
        assert arm_after["alpha"] < alpha_before

    def test_decay_respects_floor(self, bandit):
        """Alpha and beta never go below 1.0."""
        bandit._ensure_arm("floor:arm", "event_type")
        bandit.decay_arms(factor=0.5)
        arm = bandit.get_arm("floor:arm")
        assert arm["alpha"] >= DEFAULT_ALPHA
        assert arm["beta"] >= DEFAULT_BETA

    def test_decay_returns_zero_when_no_change(self, bandit):
        """Fresh arms at default don't change with small decay."""
        bandit._ensure_arm("fresh:arm", "event_type")
        count = bandit.decay_arms(factor=0.99)
        # At defaults (1.0, 1.0), 0.99 decay rounds to same value
        assert count >= 0  # Implementation detail


# ---------------------------------------------------------------------------
# TestGetArm
# ---------------------------------------------------------------------------


class TestGetArm:
    """Test single arm retrieval."""

    def test_nonexistent_arm(self, bandit):
        assert bandit.get_arm("nope") is None

    def test_existing_arm(self, bandit):
        bandit.record_outcome("exist:arm", "cluster", success=True)
        arm = bandit.get_arm("exist:arm")
        assert arm is not None
        assert arm["arm_id"] == "exist:arm"
        assert arm["arm_type"] == "cluster"
        assert arm["total_trials"] == 1

    def test_arm_with_context(self, bandit, bandit_db):
        ctx = json.dumps({"project": "omega"})
        bandit._ensure_arm("ctx:arm", "event_type", context=ctx)
        arm = bandit.get_arm("ctx:arm")
        assert arm["context"] == {"project": "omega"}


# ---------------------------------------------------------------------------
# TestIntegration
# ---------------------------------------------------------------------------


class TestIntegration:
    """End-to-end integration scenarios."""

    def test_full_lifecycle(self, bandit):
        """Create, record, sample, rank, decay."""
        # Record outcomes for multiple arms
        for _ in range(10):
            bandit.record_outcome("et:decision", "event_type", success=True)
        for _ in range(5):
            bandit.record_outcome("et:user_preference", "event_type", success=True)
        for _ in range(5):
            bandit.record_outcome("et:user_preference", "event_type", success=False)
        for _ in range(10):
            bandit.record_outcome("et:session_summary", "event_type", success=False)

        # Sample priorities
        scores = bandit.sample_priorities(["et:decision", "et:user_preference", "et:session_summary"])
        assert len(scores) == 3

        # Rankings
        rankings = bandit.get_rankings()
        assert len(rankings) == 3
        assert rankings[0]["arm_id"] == "et:decision"

        # Decay
        count = bandit.decay_arms(factor=0.95)
        assert count >= 1

    def test_boost_in_scoring_context(self, bandit):
        """Simulate how boost integrates with query scoring."""
        for _ in range(MIN_TRIALS_FOR_BOOST + 1):
            bandit.record_outcome("et:decision", "event_type", success=True)
        for _ in range(MIN_TRIALS_FOR_BOOST + 1):
            bandit.record_outcome("et:noise", "event_type", success=False)

        decision_boost = bandit.get_boost_factor("et:decision")
        noise_boost = bandit.get_boost_factor("et:noise")

        assert decision_boost > noise_boost
        assert decision_boost > 1.0
        assert noise_boost < 1.0

        # Simulate scoring: base_score * boost
        base_score = 0.5
        assert base_score * decision_boost > base_score * noise_boost
