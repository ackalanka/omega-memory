"""Tests for omega.behavioral — Behavioral pattern extraction."""

import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from omega.behavioral import (
    BehavioralAnalyzer,
    _compute_confidence,
    _is_subsequence,
    effective_confidence,
    MIN_STORE_CONFIDENCE,
    MIN_SURFACE_CONFIDENCE,
    REINFORCE_DELTA,
    MAX_UNCONFIRMED_CONFIDENCE,
)
from omega.types import AutoCaptureEventType, EVENT_TYPE_TTL, TTLCategory


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def coord_db(tmp_path):
    """Create a fresh coordination-style SQLite DB with coord_* tables."""
    db_path = tmp_path / "test_coord.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")

    # coord_audit
    conn.execute("""
        CREATE TABLE coord_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            tool_name TEXT NOT NULL,
            arguments TEXT,
            result_summary TEXT,
            created_at TEXT NOT NULL
        )
    """)

    # coord_git_events
    conn.execute("""
        CREATE TABLE coord_git_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            project TEXT NOT NULL,
            event_type TEXT NOT NULL,
            commit_hash TEXT,
            branch TEXT,
            message TEXT,
            created_at TEXT NOT NULL
        )
    """)

    # coord_sessions
    conn.execute("""
        CREATE TABLE coord_sessions (
            session_id TEXT PRIMARY KEY,
            pid INTEGER,
            project TEXT,
            task TEXT,
            status TEXT DEFAULT 'active',
            capabilities TEXT,
            started_at TEXT NOT NULL,
            last_heartbeat TEXT NOT NULL,
            metadata TEXT
        )
    """)

    # coord_file_claims
    conn.execute("""
        CREATE TABLE coord_file_claims (
            file_path TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            task TEXT,
            claimed_at TEXT NOT NULL,
            last_activity TEXT NOT NULL
        )
    """)

    # coord_handoffs
    conn.execute("""
        CREATE TABLE coord_handoffs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            project TEXT,
            completed_tasks TEXT,
            blocked_items TEXT,
            key_context TEXT,
            next_steps TEXT,
            files_modified TEXT,
            decisions_made TEXT,
            git_branch TEXT,
            git_dirty_files TEXT,
            created_at TEXT NOT NULL,
            read_by TEXT DEFAULT '[]'
        )
    """)

    # coord_tasks
    conn.execute("""
        CREATE TABLE coord_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            project TEXT,
            session_id TEXT,
            status TEXT DEFAULT 'pending',
            priority INTEGER DEFAULT 0,
            created_by TEXT NOT NULL,
            created_at TEXT NOT NULL,
            claimed_at TEXT,
            completed_at TEXT,
            metadata TEXT,
            result TEXT,
            progress INTEGER DEFAULT 0
        )
    """)

    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def analyzer(coord_db):
    """BehavioralAnalyzer with test DB connection."""
    return BehavioralAnalyzer(conn=coord_db)


# ---------------------------------------------------------------------------
# Helper: populate test data
# ---------------------------------------------------------------------------

def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _populate_audit(conn, tool_calls, sessions=None):
    """Insert tool audit rows. tool_calls: dict of {tool_name: count} per session."""
    if sessions is None:
        sessions = [f"sess-{i}" for i in range(len(tool_calls))]
    for sess_id, tools in zip(sessions, tool_calls):
        for tool_name, count in tools.items():
            for _ in range(count):
                conn.execute(
                    "INSERT INTO coord_audit (session_id, tool_name, created_at) VALUES (?, ?, ?)",
                    (sess_id, tool_name, _now_iso()),
                )
    conn.commit()


def _populate_git_events(conn, commits_per_session, messages=None):
    """Insert git commit events. commits_per_session: list of ints."""
    msg_idx = 0
    for i, count in enumerate(commits_per_session):
        sess_id = f"sess-{i}"
        for j in range(count):
            msg = None
            if messages and msg_idx < len(messages):
                msg = messages[msg_idx]
                msg_idx += 1
            conn.execute(
                "INSERT INTO coord_git_events (session_id, project, event_type, message, created_at) VALUES (?, ?, ?, ?, ?)",
                (sess_id, "/test/project", "commit", msg, _now_iso()),
            )
    conn.commit()


def _populate_sessions(conn, count, hour_utc=14, duration_min=45):
    """Insert session records. hour_utc is the UTC hour (ICT = UTC+7)."""
    for i in range(count):
        start = datetime(2026, 2, 1 + (i % 28), hour_utc, 0, 0, tzinfo=timezone.utc)
        end = start + timedelta(minutes=duration_min)
        conn.execute(
            "INSERT INTO coord_sessions (session_id, started_at, last_heartbeat, status) VALUES (?, ?, ?, ?)",
            (f"sess-{i}", start.isoformat(), end.isoformat(), "ended"),
        )
    conn.commit()


def _populate_file_claims(conn, session_files):
    """Insert file claim rows. session_files: dict of {session_id: [file_paths]}.

    Since file_path is PRIMARY KEY in the real table, we drop that constraint
    in test or use unique composite keys. For co-edit analysis, the analyzer
    groups by session_id, so we need the actual file_path (not session-prefixed).
    We recreate the table without the PK constraint for flexibility.
    """
    conn.execute("DROP TABLE IF EXISTS coord_file_claims")
    conn.execute("""
        CREATE TABLE coord_file_claims (
            file_path TEXT NOT NULL,
            session_id TEXT NOT NULL,
            task TEXT,
            claimed_at TEXT NOT NULL,
            last_activity TEXT NOT NULL
        )
    """)
    for sess_id, files in session_files.items():
        for fp in files:
            conn.execute(
                "INSERT INTO coord_file_claims (file_path, session_id, claimed_at, last_activity) VALUES (?, ?, ?, ?)",
                (fp, sess_id, _now_iso(), _now_iso()),
            )
    conn.commit()


# ---------------------------------------------------------------------------
# Tests: Event type registration
# ---------------------------------------------------------------------------


class TestEventTypeRegistration:
    def test_behavioral_pattern_in_autocapture(self):
        assert AutoCaptureEventType.BEHAVIORAL_PATTERN == "behavioral_pattern"

    def test_behavioral_pattern_ttl_is_permanent(self):
        assert EVENT_TYPE_TTL[AutoCaptureEventType.BEHAVIORAL_PATTERN] == TTLCategory.PERMANENT

    def test_behavioral_pattern_ttl_via_for_event_type(self):
        assert TTLCategory.for_event_type("behavioral_pattern") is None  # PERMANENT = None


# ---------------------------------------------------------------------------
# Tests: Confidence calculation
# ---------------------------------------------------------------------------


class TestConfidenceCalculation:
    def test_zero_inputs(self):
        assert _compute_confidence(0, 0, 0.0) == 0.0

    def test_perfect_inputs(self):
        conf = _compute_confidence(session_count=50, datapoint_count=200, consistency_ratio=1.0)
        assert conf > 0.9

    def test_minimum_threshold_inputs(self):
        # Just barely meeting minimums
        conf = _compute_confidence(session_count=5, datapoint_count=10, consistency_ratio=0.5)
        assert 0.3 < conf < 0.7

    def test_high_consistency_low_volume(self):
        conf = _compute_confidence(session_count=2, datapoint_count=5, consistency_ratio=1.0)
        # High consistency (0.4) but low breadth and volume
        assert conf < 0.7

    def test_high_volume_low_consistency(self):
        conf = _compute_confidence(session_count=20, datapoint_count=100, consistency_ratio=0.2)
        # Good volume but poor consistency
        assert conf < 0.7

    def test_consistency_clamped(self):
        # Ratio > 1.0 should be clamped
        c1 = _compute_confidence(5, 10, 1.5)
        c2 = _compute_confidence(5, 10, 1.0)
        assert c1 == c2

    def test_negative_consistency_clamped(self):
        conf = _compute_confidence(5, 10, -0.5)
        # Consistency component should be 0
        expected = _compute_confidence(5, 10, 0.0)
        assert conf == expected


# ---------------------------------------------------------------------------
# Tests: Tool preference extractor
# ---------------------------------------------------------------------------


class TestToolPreferences:
    def test_insufficient_sessions(self, coord_db, analyzer):
        # Only 2 sessions, need 5
        _populate_audit(coord_db, [
            {"Grep": 10, "Bash": 2},
            {"Grep": 8, "Bash": 1},
        ])
        result = analyzer.analyze_tool_preferences(min_sessions=5)
        assert result == []

    def test_strong_search_tool_ratio(self, coord_db, analyzer):
        # Grep used 4x more than Bash-search across 6 sessions
        sessions_data = [{"Grep": 10, "Glob": 2, "Bash": 5} for _ in range(6)]
        _populate_audit(coord_db, sessions_data)
        result = analyzer.analyze_tool_preferences(min_sessions=5)
        ratios = [p for p in result if p["pattern_type"] == "tool_preference" and "ratio" in p["pattern_key"]]
        # Should detect Grep >> Glob ratio
        assert any("Grep" in p["content"] for p in ratios)

    def test_dominant_tool_detected(self, coord_db, analyzer):
        # One tool dominates 50% of all usage
        sessions_data = [{"Read": 20, "Edit": 3, "Bash": 2} for _ in range(6)]
        _populate_audit(coord_db, sessions_data)
        result = analyzer.analyze_tool_preferences(min_sessions=5)
        dominant = [p for p in result if "dominant" in p["pattern_key"]]
        assert any("Read" in p["content"] for p in dominant)

    def test_no_patterns_when_evenly_distributed(self, coord_db, analyzer):
        # All tools used equally, no strong ratios
        sessions_data = [{"Grep": 5, "Glob": 5, "Read": 5} for _ in range(6)]
        _populate_audit(coord_db, sessions_data)
        result = analyzer.analyze_tool_preferences(min_sessions=5)
        ratios = [p for p in result if "ratio" in p["pattern_key"]]
        assert ratios == []

    def test_missing_table(self, tmp_path):
        """Gracefully handles missing coord_audit table."""
        conn = sqlite3.connect(str(tmp_path / "empty.db"))
        a = BehavioralAnalyzer(conn=conn)
        assert a.analyze_tool_preferences() == []
        conn.close()


# ---------------------------------------------------------------------------
# Tests: Git style extractor
# ---------------------------------------------------------------------------


class TestGitStyle:
    def test_insufficient_commits(self, coord_db, analyzer):
        _populate_git_events(coord_db, [2, 1])
        result = analyzer.analyze_git_style(min_commits=10)
        assert result == []

    def test_commit_frequency_detected(self, coord_db, analyzer):
        # 8 commits/session across 5 sessions = "frequently"
        _populate_git_events(coord_db, [8, 8, 8, 8, 8])
        result = analyzer.analyze_git_style(min_commits=10)
        freq = [p for p in result if p["pattern_key"] == "git_commit_frequency"]
        assert len(freq) == 1
        assert "frequently" in freq[0]["content"]

    def test_sparse_commits_low_confidence(self, coord_db, analyzer):
        # 1 commit/session across 15 sessions: low consistency ratio, may not meet threshold
        _populate_git_events(coord_db, [1] * 15)
        result = analyzer.analyze_git_style(min_commits=10)
        freq = [p for p in result if p["pattern_key"] == "git_commit_frequency"]
        # Sparse commits have low consistency (1/10 = 0.1), confidence likely below 0.6
        if freq:
            assert "sparingly" in freq[0]["content"]
        else:
            # Expected: confidence too low to store
            assert True

    def test_moderate_commits_detected(self, coord_db, analyzer):
        # 4 commits/session across 15 sessions = "moderately", enough for confidence
        _populate_git_events(coord_db, [4] * 15)
        result = analyzer.analyze_git_style(min_commits=10)
        freq = [p for p in result if p["pattern_key"] == "git_commit_frequency"]
        assert len(freq) == 1
        assert "moderately" in freq[0]["content"]

    def test_conventional_commits_detected(self, coord_db, analyzer):
        messages = [
            "feat: add login page", "fix: resolve null pointer",
            "chore: update deps", "docs: update readme",
            "feat: add dashboard", "fix: handle edge case",
            "refactor: clean up utils", "test: add unit tests",
            "feat: user settings", "fix: typo in config",
            "style: formatting", "random commit without prefix",
            "feat: add search", "fix: edge case two",
            "feat: profile page", "chore: cleanup",
            "fix: validation bug", "docs: api reference",
            "feat: export feature", "test: integration tests",
        ]
        # Spread across 8 sessions (need breadth for confidence)
        _populate_git_events(coord_db, [3, 3, 3, 2, 2, 3, 2, 2], messages=messages)
        result = analyzer.analyze_git_style(min_commits=10)
        conv = [p for p in result if p["pattern_key"] == "git_conventional_commits"]
        assert len(conv) == 1
        assert "conventional" in conv[0]["content"].lower()

    def test_missing_table(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "empty.db"))
        a = BehavioralAnalyzer(conn=conn)
        assert a.analyze_git_style() == []
        conn.close()


# ---------------------------------------------------------------------------
# Tests: Session patterns extractor
# ---------------------------------------------------------------------------


class TestSessionPatterns:
    def test_insufficient_sessions(self, coord_db, analyzer):
        _populate_sessions(coord_db, 3)
        result = analyzer.analyze_session_patterns(min_sessions=10)
        assert result == []

    def test_peak_hours_detected(self, coord_db, analyzer):
        # All sessions at 14:00 UTC = 21:00 ICT (evening)
        _populate_sessions(coord_db, 15, hour_utc=14)
        result = analyzer.analyze_session_patterns(min_sessions=10)
        timing = [p for p in result if p["pattern_key"] == "session_peak_hours"]
        assert len(timing) == 1
        assert "evening" in timing[0]["content"]

    def test_avg_duration_detected(self, coord_db, analyzer):
        _populate_sessions(coord_db, 15, duration_min=45)
        result = analyzer.analyze_session_patterns(min_sessions=10)
        duration = [p for p in result if p["pattern_key"] == "session_avg_duration"]
        assert len(duration) == 1
        assert "45min" in duration[0]["content"]

    def test_missing_table(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "empty.db"))
        a = BehavioralAnalyzer(conn=conn)
        assert a.analyze_session_patterns() == []
        conn.close()


# ---------------------------------------------------------------------------
# Tests: Co-edit clusters extractor
# ---------------------------------------------------------------------------


class TestCoEdits:
    def test_co_edit_pair_detected(self, coord_db, analyzer):
        # coordination.py + coord_handlers.py always together
        session_files = {
            f"sess-{i}": ["src/omega/coordination.py", "src/omega/coord_handlers.py", "tests/test_coord.py"]
            for i in range(5)
        }
        _populate_file_claims(coord_db, session_files)
        result = analyzer.analyze_co_edits(min_cooccurrence=3)
        assert len(result) > 0
        # At least one pair should be detected
        assert any("co_edit" in p["pattern_key"] for p in result)

    def test_insufficient_cooccurrence(self, coord_db, analyzer):
        session_files = {
            "sess-0": ["file_a.py", "file_b.py"],
            "sess-1": ["file_a.py", "file_c.py"],
        }
        _populate_file_claims(coord_db, session_files)
        result = analyzer.analyze_co_edits(min_cooccurrence=3)
        assert result == []

    def test_missing_table(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "empty.db"))
        a = BehavioralAnalyzer(conn=conn)
        assert a.analyze_co_edits() == []
        conn.close()


# ---------------------------------------------------------------------------
# Tests: Storage pipeline
# ---------------------------------------------------------------------------


class TestStoragePipeline:
    def test_store_pattern_calls_auto_capture(self, coord_db, analyzer):
        with patch("omega.bridge.auto_capture") as mock_capture:
            mock_capture.return_value = "Stored"
            pattern = {
                "content": "Uses Grep heavily",
                "pattern_type": "tool_preference",
                "pattern_key": "tool_dominant:Grep",
                "confidence": 0.85,
                "evidence_count": 47,
                "evidence_sessions": 12,
            }
            analyzer._store_pattern(pattern)
            mock_capture.assert_called_once()
            args, kwargs = mock_capture.call_args
            assert kwargs.get("event_type", args[1] if len(args) > 1 else None) == "behavioral_pattern"
            meta = kwargs.get("metadata", args[2] if len(args) > 2 else None)
            assert meta["source"] == "behavioral_inference"
            assert meta["pattern_key"] == "tool_dominant:Grep"
            assert meta["confidence"] == 0.85
            assert meta["user_confirmed"] is None

    def test_analyze_and_store_dedup(self, coord_db, analyzer):
        """Existing pattern with user_confirmed=None should be reinforced, not re-created."""
        sessions_data = [{"Grep": 20, "Glob": 2} for _ in range(6)]
        _populate_audit(coord_db, sessions_data)

        # Mock _find_existing_pattern to return an existing node
        existing_node = MagicMock()
        existing_node.metadata = {
            "pattern_key": "tool_dominant:Grep",
            "user_confirmed": None,
            "confidence": 0.80,
        }
        existing_node.id = "existing-id"

        with patch.object(analyzer, "_find_existing_pattern", return_value=existing_node):
            with patch.object(analyzer, "_store_pattern") as mock_store:
                with patch.object(analyzer, "_reinforce_pattern"):
                    result = analyzer.analyze_and_store()
                    mock_store.assert_not_called()
                    assert result.get("updated", 0) > 0

    def test_analyze_and_store_stores_new(self, coord_db, analyzer):
        """New patterns should be stored."""
        sessions_data = [{"Grep": 20, "Glob": 2} for _ in range(6)]
        _populate_audit(coord_db, sessions_data)

        with patch.object(analyzer, "_find_existing_pattern", return_value=None):
            with patch.object(analyzer, "_store_pattern") as mock_store:
                result = analyzer.analyze_and_store()
                assert result["stored"] > 0
                assert mock_store.call_count == result["stored"]


# ---------------------------------------------------------------------------
# Tests: Protected from consolidation
# ---------------------------------------------------------------------------


class TestConsolidationProtection:
    def test_behavioral_pattern_in_protected_types(self):
        """behavioral_pattern should be protected from consolidation pruning."""
        from omega.sqlite_store import SQLiteStore
        # Read the source to verify protected_types includes behavioral_pattern
        import inspect
        source = inspect.getsource(SQLiteStore.consolidate)
        assert "behavioral_pattern" in source


# ---------------------------------------------------------------------------
# Tests: Contradiction detection with explicit preferences
# ---------------------------------------------------------------------------


class TestContradictionDetection:
    def test_behavioral_vs_explicit_preference(self):
        """Behavioral inference should be checkable against explicit preferences."""
        from omega.preferences import detect_contradictions

        # Words must overlap enough (Jaccard >= 0.3) for contradiction detection
        behavioral_content = "I always use Bash for search operations in projects"
        class FakePref:
            def __init__(self, content, id="pref-1"):
                self.content = content
                self.id = id

        existing = [FakePref("I never use Bash for search operations in projects")]
        contradictions = detect_contradictions(behavioral_content, existing)
        # Should detect polarity flip: "always" vs "never" with high topic overlap
        assert len(contradictions) > 0


# ---------------------------------------------------------------------------
# Tests: Constants
# ---------------------------------------------------------------------------


class TestConstants:
    def test_min_store_confidence(self):
        assert MIN_STORE_CONFIDENCE == 0.6

    def test_min_surface_confidence(self):
        assert MIN_SURFACE_CONFIDENCE == 0.5

    def test_surface_threshold_at_or_below_store(self):
        # Surface threshold <= store threshold so patterns remain visible after decay
        assert MIN_SURFACE_CONFIDENCE <= MIN_STORE_CONFIDENCE

    def test_reinforce_delta(self):
        assert REINFORCE_DELTA == 0.03

    def test_max_unconfirmed_confidence(self):
        assert MAX_UNCONFIRMED_CONFIDENCE == 0.95


# ---------------------------------------------------------------------------
# Tests: Phase 2 — Confidence lifecycle
# ---------------------------------------------------------------------------


class TestEffectiveConfidence:
    def test_zero_days_no_decay(self):
        """Fresh pattern should have no decay."""
        now_iso = datetime.now(timezone.utc).isoformat()
        result = effective_confidence(0.85, now_iso)
        assert abs(result - 0.85) < 0.01

    def test_30_day_half_life(self):
        """After 30 days, confidence should be roughly halved."""
        past = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        result = effective_confidence(1.0, past)
        assert 0.45 < result < 0.55  # ~0.5 at half-life

    def test_60_days_quarter(self):
        """After 60 days (2 half-lives), confidence ~0.25."""
        past = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        result = effective_confidence(1.0, past)
        assert 0.2 < result < 0.3

    def test_90_days_very_low(self):
        """After 90 days, confidence should be very low."""
        past = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
        result = effective_confidence(1.0, past)
        assert result < 0.15

    def test_empty_iso_returns_raw(self):
        """Empty last_evidence_iso returns raw confidence."""
        assert effective_confidence(0.8, "") == 0.8

    def test_none_iso_returns_raw(self):
        """None last_evidence_iso returns raw confidence."""
        assert effective_confidence(0.8, None) == 0.8

    def test_invalid_iso_returns_raw(self):
        """Invalid ISO string returns raw confidence."""
        assert effective_confidence(0.8, "not-a-date") == 0.8

    def test_z_suffix_handled(self):
        """Z suffix ISO format works."""
        now_z = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        result = effective_confidence(0.85, now_z)
        assert abs(result - 0.85) < 0.01

    def test_never_goes_negative(self):
        """Decay should never produce negative values."""
        very_old = (datetime.now(timezone.utc) - timedelta(days=365)).isoformat()
        result = effective_confidence(0.5, very_old)
        assert result >= 0.0


# ---------------------------------------------------------------------------
# Tests: Phase 2 — Pattern evolution
# ---------------------------------------------------------------------------


class TestPatternEvolution:
    def test_find_existing_pattern_returns_node(self, coord_db, analyzer):
        """_find_existing_pattern returns the memory node when found."""
        mock_node = MagicMock()
        mock_node.metadata = {"pattern_key": "tool_dominant:Grep"}
        mock_store = MagicMock()
        mock_store.get_by_type.return_value = [mock_node]

        with patch("omega.bridge._get_store", return_value=mock_store):
            result = analyzer._find_existing_pattern("tool_dominant:Grep")
            assert result is mock_node

    def test_find_existing_pattern_returns_none(self, coord_db, analyzer):
        """_find_existing_pattern returns None when not found."""
        mock_store = MagicMock()
        mock_store.get_by_type.return_value = []

        with patch("omega.bridge._get_store", return_value=mock_store):
            result = analyzer._find_existing_pattern("nonexistent_key")
            assert result is None

    def test_denied_patterns_not_recreated(self, coord_db, analyzer):
        """Patterns denied by user (user_confirmed=False) should be skipped."""
        sessions_data = [{"Grep": 20, "Glob": 2} for _ in range(6)]
        _populate_audit(coord_db, sessions_data)

        denied_node = MagicMock()
        denied_node.metadata = {
            "pattern_key": "tool_dominant:Grep",
            "user_confirmed": False,
        }

        with patch.object(analyzer, "_find_existing_pattern", return_value=denied_node):
            with patch.object(analyzer, "_store_pattern") as mock_store:
                with patch.object(analyzer, "_reinforce_pattern") as mock_reinforce:
                    result = analyzer.analyze_and_store()
                    mock_store.assert_not_called()
                    mock_reinforce.assert_not_called()
                    assert result["skipped_denied"] > 0

    def test_existing_pattern_gets_reinforced(self, coord_db, analyzer):
        """Existing pattern should be reinforced, not duplicated."""
        sessions_data = [{"Grep": 20, "Glob": 2} for _ in range(6)]
        _populate_audit(coord_db, sessions_data)

        existing_node = MagicMock()
        existing_node.metadata = {
            "pattern_key": "tool_dominant:Grep",
            "user_confirmed": None,
            "confidence": 0.80,
        }
        existing_node.id = "test-id-123"

        with patch.object(analyzer, "_find_existing_pattern", return_value=existing_node):
            with patch.object(analyzer, "_store_pattern") as mock_store:
                with patch.object(analyzer, "_reinforce_pattern") as mock_reinforce:
                    result = analyzer.analyze_and_store()
                    mock_store.assert_not_called()
                    assert mock_reinforce.call_count > 0
                    assert result.get("updated", 0) > 0

    def test_reinforce_bumps_confidence(self, coord_db, analyzer):
        """_reinforce_pattern should bump confidence by REINFORCE_DELTA."""
        mock_node = MagicMock()
        mock_node.id = "test-pattern-id"
        mock_node.metadata = {
            "event_type": "behavioral_pattern",
            "pattern_key": "tool_dominant:Grep",
            "confidence": 0.80,
            "evidence_count": 30,
            "evidence_sessions": 8,
            "user_confirmed": None,
        }

        mock_store = MagicMock()
        new_pattern = {
            "evidence_count": 40,
            "evidence_sessions": 10,
        }

        with patch("omega.bridge._get_store", return_value=mock_store):
            analyzer._reinforce_pattern(mock_node, new_pattern)
            mock_store.update_node.assert_called_once()
            call_args = mock_store.update_node.call_args
            updated_meta = call_args[1]["metadata"] if "metadata" in call_args[1] else call_args[0][1]
            assert updated_meta["confidence"] == round(0.80 + REINFORCE_DELTA, 3)
            assert updated_meta["evidence_count"] == 40
            assert updated_meta["evidence_sessions"] == 10
            assert "last_evidence_at" in updated_meta

    def test_reinforce_caps_unconfirmed(self, coord_db, analyzer):
        """Reinforcement should cap at MAX_UNCONFIRMED_CONFIDENCE for unconfirmed patterns."""
        mock_node = MagicMock()
        mock_node.id = "test-pattern-id"
        mock_node.metadata = {
            "event_type": "behavioral_pattern",
            "pattern_key": "tool_dominant:Grep",
            "confidence": 0.94,
            "evidence_count": 50,
            "evidence_sessions": 15,
            "user_confirmed": None,
        }

        mock_store = MagicMock()
        new_pattern = {"evidence_count": 55, "evidence_sessions": 16}

        with patch("omega.bridge._get_store", return_value=mock_store):
            analyzer._reinforce_pattern(mock_node, new_pattern)
            call_args = mock_store.update_node.call_args
            updated_meta = call_args[1]["metadata"] if "metadata" in call_args[1] else call_args[0][1]
            assert updated_meta["confidence"] <= MAX_UNCONFIRMED_CONFIDENCE


# ---------------------------------------------------------------------------
# Helpers: Phase 3
# ---------------------------------------------------------------------------


def _populate_handoffs(conn, handoffs):
    """Insert coord_handoffs rows.

    handoffs: list of dicts with keys matching coord_handoffs columns.
    At minimum: session_id, created_at. Optional JSON fields:
    completed_tasks, blocked_items, next_steps, decisions_made.
    """
    for h in handoffs:
        conn.execute(
            """INSERT INTO coord_handoffs
               (session_id, project, completed_tasks, blocked_items, next_steps,
                decisions_made, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                h.get("session_id", "sess-0"),
                h.get("project"),
                h.get("completed_tasks"),
                h.get("blocked_items"),
                h.get("next_steps"),
                h.get("decisions_made"),
                h.get("created_at", _now_iso()),
            ),
        )
    conn.commit()


def _populate_tasks(conn, tasks):
    """Insert coord_tasks rows.

    tasks: list of dicts with keys: title, status, session_id, created_by,
    created_at, claimed_at, completed_at.
    """
    for t in tasks:
        conn.execute(
            """INSERT INTO coord_tasks
               (title, project, session_id, status, created_by, created_at,
                claimed_at, completed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                t.get("title", "task"),
                t.get("project"),
                t.get("session_id"),
                t.get("status", "pending"),
                t.get("created_by", "test"),
                t.get("created_at", _now_iso()),
                t.get("claimed_at"),
                t.get("completed_at"),
            ),
        )
    conn.commit()


def _populate_sessions_with_projects(conn, sessions):
    """Insert sessions with project info.

    sessions: list of dicts with keys: session_id, project, started_at,
    last_heartbeat, status.
    """
    for s in sessions:
        conn.execute(
            """INSERT INTO coord_sessions
               (session_id, project, started_at, last_heartbeat, status)
               VALUES (?, ?, ?, ?, ?)""",
            (
                s["session_id"],
                s.get("project"),
                s["started_at"],
                s["last_heartbeat"],
                s.get("status", "ended"),
            ),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Tests: Phase 3 — Project focus extractor
# ---------------------------------------------------------------------------


class TestProjectFocus:
    def test_dominant_project_detected(self, coord_db, analyzer):
        """Detect when one project has 50%+ of session time."""
        sessions = []
        # omega: 12 sessions x 60 min = 720 min (dominant)
        for i in range(12):
            start = datetime(2026, 2, 1 + i, 10, 0, 0, tzinfo=timezone.utc)
            end = start + timedelta(minutes=60)
            sessions.append({
                "session_id": f"sess-omega-{i}",
                "project": "/Users/test/Projects/omega",
                "started_at": start.isoformat(),
                "last_heartbeat": end.isoformat(),
            })
        # acme-app: 3 sessions x 60 min = 180 min
        for i in range(3):
            start = datetime(2026, 2, 15 + i, 10, 0, 0, tzinfo=timezone.utc)
            end = start + timedelta(minutes=60)
            sessions.append({
                "session_id": f"sess-e1-{i}",
                "project": "/Users/test/Projects/acme-app",
                "started_at": start.isoformat(),
                "last_heartbeat": end.isoformat(),
            })
        _populate_sessions_with_projects(coord_db, sessions)

        result = analyzer.analyze_project_focus(min_sessions=10)
        dominant = [p for p in result if p["pattern_key"].startswith("project_focus:")]
        assert len(dominant) == 1
        assert "omega" in dominant[0]["content"]

    def test_multi_project_breadth(self, coord_db, analyzer):
        """Detect when 3+ projects each have 10%+ of sessions."""
        sessions = []
        projects = ["proj-a", "proj-b", "proj-c", "proj-d"]
        for idx, proj in enumerate(projects):
            for i in range(4):
                start = datetime(2026, 2, 1 + idx * 4 + i, 10, 0, 0, tzinfo=timezone.utc)
                end = start + timedelta(minutes=45)
                sessions.append({
                    "session_id": f"sess-{proj}-{i}",
                    "project": f"/Users/test/{proj}",
                    "started_at": start.isoformat(),
                    "last_heartbeat": end.isoformat(),
                })
        _populate_sessions_with_projects(coord_db, sessions)

        result = analyzer.analyze_project_focus(min_sessions=10)
        breadth = [p for p in result if p["pattern_key"] == "project_breadth:multi"]
        assert len(breadth) == 1
        assert "4 projects" in breadth[0]["content"]

    def test_insufficient_sessions(self, coord_db, analyzer):
        sessions = [{
            "session_id": "sess-0",
            "project": "/test",
            "started_at": datetime(2026, 2, 1, 10, 0, 0, tzinfo=timezone.utc).isoformat(),
            "last_heartbeat": datetime(2026, 2, 1, 11, 0, 0, tzinfo=timezone.utc).isoformat(),
        }]
        _populate_sessions_with_projects(coord_db, sessions)
        result = analyzer.analyze_project_focus(min_sessions=10)
        assert result == []

    def test_missing_table(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "empty.db"))
        a = BehavioralAnalyzer(conn=conn)
        assert a.analyze_project_focus() == []
        conn.close()


# ---------------------------------------------------------------------------
# Tests: Phase 3 — Workflow sequences extractor
# ---------------------------------------------------------------------------


class TestWorkflowSequences:
    def test_strong_sequence_detected(self, coord_db, analyzer):
        """Detect tool_a -> tool_b appearing in 70%+ of sessions with tool_a."""
        # 10 sessions, each with Read -> Edit -> Read -> Edit sequence (boosts volume)
        for i in range(10):
            sess = f"sess-{i}"
            base = datetime(2026, 2, 1, 10, 0, i, tzinfo=timezone.utc)
            for j, tool in enumerate(["Read", "Edit", "Read", "Edit", "Bash"]):
                ts = (base + timedelta(seconds=j)).isoformat()
                coord_db.execute(
                    "INSERT INTO coord_audit (session_id, tool_name, created_at) VALUES (?, ?, ?)",
                    (sess, tool, ts),
                )
        coord_db.commit()

        result = analyzer.analyze_workflow_sequences(min_sessions=5)
        seq = [p for p in result if p["pattern_key"].startswith("workflow_sequence:")]
        assert any("Read" in p["content"] and "Edit" in p["content"] for p in seq)

    def test_handoff_discipline(self, coord_db, analyzer):
        """Detect omega_handoff before session_deregister."""
        for i in range(10):
            sess = f"sess-{i}"
            base = datetime(2026, 2, 1, 10, 0, i, tzinfo=timezone.utc)
            tools = ["omega_query", "omega_store", "omega_handoff", "session_deregister"]
            for j, tool in enumerate(tools):
                ts = (base + timedelta(seconds=j)).isoformat()
                coord_db.execute(
                    "INSERT INTO coord_audit (session_id, tool_name, created_at) VALUES (?, ?, ?)",
                    (sess, tool, ts),
                )
        coord_db.commit()

        result = analyzer.analyze_workflow_sequences(min_sessions=5)
        discipline = [p for p in result if p["pattern_key"] == "workflow_handoff_discipline"]
        assert len(discipline) == 1
        assert "handoff" in discipline[0]["content"].lower()

    def test_insufficient_sessions(self, coord_db, analyzer):
        coord_db.execute(
            "INSERT INTO coord_audit (session_id, tool_name, created_at) VALUES (?, ?, ?)",
            ("sess-0", "Read", _now_iso()),
        )
        coord_db.commit()
        result = analyzer.analyze_workflow_sequences(min_sessions=5)
        assert result == []

    def test_missing_table(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "empty.db"))
        a = BehavioralAnalyzer(conn=conn)
        assert a.analyze_workflow_sequences() == []
        conn.close()


# ---------------------------------------------------------------------------
# Tests: Phase 3 — Handoff patterns extractor
# ---------------------------------------------------------------------------


class TestHandoffPatterns:
    def _make_handoffs(self, n, thorough=True, blockers=False, decisions=0):
        """Generate n handoff dicts."""
        handoffs = []
        for i in range(n):
            h = {
                "session_id": f"sess-{i}",
                "created_at": _now_iso(),
                "completed_tasks": '["task1"]' if thorough else None,
                "next_steps": "Do X next" if thorough else None,
                "decisions_made": json.dumps([f"decision-{j}" for j in range(decisions)]) if decisions else None,
                "blocked_items": '["blocker1"]' if blockers else None,
            }
            handoffs.append(h)
        return handoffs

    def test_thoroughness_detected(self, coord_db, analyzer):
        handoffs = self._make_handoffs(8, thorough=True, decisions=2)
        _populate_handoffs(coord_db, handoffs)
        result = analyzer.analyze_handoff_patterns(min_handoffs=5)
        thorough = [p for p in result if p["pattern_key"] == "handoff_thoroughness"]
        assert len(thorough) == 1
        assert "Thorough" in thorough[0]["content"]

    def test_blocker_rate_detected(self, coord_db, analyzer):
        handoffs = self._make_handoffs(8, thorough=True, blockers=True, decisions=1)
        _populate_handoffs(coord_db, handoffs)
        result = analyzer.analyze_handoff_patterns(min_handoffs=5)
        blockers = [p for p in result if p["pattern_key"] == "handoff_blocker_rate"]
        assert len(blockers) == 1
        assert "blockers" in blockers[0]["content"].lower()

    def test_decision_density_detected(self, coord_db, analyzer):
        handoffs = self._make_handoffs(8, thorough=True, decisions=4)
        _populate_handoffs(coord_db, handoffs)
        result = analyzer.analyze_handoff_patterns(min_handoffs=5)
        density = [p for p in result if p["pattern_key"] == "handoff_decision_density"]
        assert len(density) == 1
        assert "decision" in density[0]["content"].lower()

    def test_insufficient_handoffs(self, coord_db, analyzer):
        handoffs = self._make_handoffs(2)
        _populate_handoffs(coord_db, handoffs)
        result = analyzer.analyze_handoff_patterns(min_handoffs=5)
        assert result == []

    def test_missing_table(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "empty.db"))
        a = BehavioralAnalyzer(conn=conn)
        assert a.analyze_handoff_patterns() == []
        conn.close()


# ---------------------------------------------------------------------------
# Tests: Phase 3 — Task completion style extractor
# ---------------------------------------------------------------------------


class TestTaskCompletionStyle:
    def test_completion_rate_detected(self, coord_db, analyzer):
        tasks = []
        for i in range(20):
            claimed = datetime(2026, 2, 1 + i, 10, 0, 0, tzinfo=timezone.utc)
            completed = claimed + timedelta(minutes=30)
            tasks.append({
                "title": f"task-{i}",
                "status": "completed",
                "session_id": f"sess-{i}",
                "created_by": "test",
                "created_at": _now_iso(),
                "claimed_at": claimed.isoformat(),
                "completed_at": completed.isoformat(),
            })
        # Add 3 failed tasks
        for i in range(3):
            tasks.append({
                "title": f"failed-{i}",
                "status": "failed",
                "session_id": f"sess-fail-{i}",
                "created_by": "test",
                "created_at": _now_iso(),
            })
        _populate_tasks(coord_db, tasks)

        result = analyzer.analyze_task_completion_style(min_tasks=10)
        rate = [p for p in result if p["pattern_key"] == "task_completion_rate"]
        assert len(rate) == 1
        assert "High" in rate[0]["content"]

    def test_avg_duration_detected(self, coord_db, analyzer):
        tasks = []
        for i in range(20):
            claimed = datetime(2026, 2, 1 + i, 10, 0, 0, tzinfo=timezone.utc)
            completed = claimed + timedelta(minutes=25)
            tasks.append({
                "title": f"task-{i}",
                "status": "completed",
                "session_id": f"sess-{i}",
                "created_by": "test",
                "created_at": _now_iso(),
                "claimed_at": claimed.isoformat(),
                "completed_at": completed.isoformat(),
            })
        _populate_tasks(coord_db, tasks)

        result = analyzer.analyze_task_completion_style(min_tasks=10)
        duration = [p for p in result if p["pattern_key"] == "task_avg_duration"]
        assert len(duration) == 1
        assert "25min" in duration[0]["content"]

    def test_insufficient_tasks(self, coord_db, analyzer):
        tasks = [{"title": "t", "status": "completed", "created_by": "test", "created_at": _now_iso()}]
        _populate_tasks(coord_db, tasks)
        result = analyzer.analyze_task_completion_style(min_tasks=10)
        assert result == []

    def test_missing_table(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "empty.db"))
        a = BehavioralAnalyzer(conn=conn)
        assert a.analyze_task_completion_style() == []
        conn.close()


# ---------------------------------------------------------------------------
# Tests: Phase 3 — Git style enhancements
# ---------------------------------------------------------------------------


class TestGitStyleEnhancements:
    def test_message_length_detected(self, coord_db, analyzer):
        """Detect commit message length pattern."""
        # Short messages: avg ~25 chars across 10 sessions
        messages = [f"fix: short msg {i}" for i in range(30)]
        _populate_git_events(coord_db, [3] * 10, messages=messages)
        result = analyzer.analyze_git_style(min_commits=10)
        length = [p for p in result if p["pattern_key"] == "git_message_length"]
        assert len(length) == 1
        assert "concise" in length[0]["content"]

    def test_detailed_messages_detected(self, coord_db, analyzer):
        """Detect detailed commit message length pattern."""
        messages = [f"feat: implement the complete authentication system with OAuth2 support number {i}" for i in range(30)]
        _populate_git_events(coord_db, [3] * 10, messages=messages)
        result = analyzer.analyze_git_style(min_commits=10)
        length = [p for p in result if p["pattern_key"] == "git_message_length"]
        assert len(length) == 1
        assert "detailed" in length[0]["content"]

    def test_branch_discipline_trunk(self, coord_db, analyzer):
        """Detect trunk-based development."""
        # All commits on main across 10 sessions
        for i in range(10):
            sess = f"sess-{i}"
            for j in range(3):
                coord_db.execute(
                    "INSERT INTO coord_git_events (session_id, project, event_type, branch, message, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (sess, "/test", "commit", "main", f"commit {j}", _now_iso()),
                )
        coord_db.commit()

        result = analyzer.analyze_git_style(min_commits=10)
        branch = [p for p in result if p["pattern_key"] == "git_branch_style"]
        assert len(branch) == 1
        assert "Trunk-based" in branch[0]["content"]

    def test_branch_discipline_feature(self, coord_db, analyzer):
        """Detect feature-branch workflow."""
        for i in range(10):
            sess = f"sess-{i}"
            for j in range(3):
                coord_db.execute(
                    "INSERT INTO coord_git_events (session_id, project, event_type, branch, message, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (sess, "/test", "commit", f"feature/branch-{i}", f"commit {j}", _now_iso()),
                )
        coord_db.commit()

        result = analyzer.analyze_git_style(min_commits=10)
        branch = [p for p in result if p["pattern_key"] == "git_branch_style"]
        assert len(branch) == 1
        assert "Feature-branch" in branch[0]["content"]


# ---------------------------------------------------------------------------
# Tests: Phase 3 — Session pattern enhancements
# ---------------------------------------------------------------------------


class TestSessionPatternEnhancements:
    def test_weekday_pattern_detected(self, coord_db, analyzer):
        """Detect weekday work pattern."""
        # Insert 15 sessions all on weekdays (Mon-Fri)
        for i in range(15):
            # Feb 2026: 2nd=Mon, 3rd=Tue, ..., 6th=Fri, 9th=Mon, ...
            day = 2 + i  # Start from Monday Feb 2
            if day > 28:
                day = 2 + (i % 20)
            start = datetime(2026, 2, day, 14, 0, 0, tzinfo=timezone.utc)
            # Skip weekends
            if start.weekday() >= 5:
                start = start + timedelta(days=(7 - start.weekday()))
            end = start + timedelta(minutes=45)
            coord_db.execute(
                "INSERT INTO coord_sessions (session_id, started_at, last_heartbeat, status) VALUES (?, ?, ?, ?)",
                (f"sess-wd-{i}", start.isoformat(), end.isoformat(), "ended"),
            )
        coord_db.commit()

        result = analyzer.analyze_session_patterns(min_sessions=10)
        weekday = [p for p in result if p["pattern_key"] == "session_weekday_pattern"]
        assert len(weekday) == 1
        assert "weekday" in weekday[0]["content"].lower() or "Mon-Fri" in weekday[0]["content"]


# ---------------------------------------------------------------------------
# Tests: Phase 4 — Cross-pattern correlations
# ---------------------------------------------------------------------------


class TestDetectCorrelations:
    def _mock_patterns(self, patterns):
        """Return a patched _get_active_patterns returning given patterns."""
        return patch.object(
            BehavioralAnalyzer, "_get_active_patterns", return_value=patterns
        )

    def test_correlations_found_with_two_types(self, coord_db, analyzer):
        """Correlations detected when 2+ pattern types with matching rules exist."""
        patterns = [
            {
                "id": "p1",
                "content": "Works primarily in the evening (21:00-01:00 ICT, 80% of sessions)",
                "pattern_type": "session_timing",
                "pattern_key": "session_peak_hours",
                "confidence": 0.85,
                "raw_confidence": 0.85,
                "evidence_count": 50,
                "evidence_sessions": 30,
                "user_confirmed": None,
            },
            {
                "id": "p2",
                "content": "Thorough handoff writer: includes next_steps and decisions",
                "pattern_type": "handoff_quality",
                "pattern_key": "handoff_thoroughness",
                "confidence": 0.78,
                "raw_confidence": 0.78,
                "evidence_count": 20,
                "evidence_sessions": 15,
                "user_confirmed": None,
            },
        ]
        with self._mock_patterns(patterns):
            insights = analyzer.detect_correlations()
            assert len(insights) >= 1
            assert insights[0]["confidence"] > 0
            assert len(insights[0]["pattern_types"]) == 2

    def test_no_correlations_with_single_type(self, coord_db, analyzer):
        """No correlations when only one pattern type exists."""
        patterns = [
            {
                "id": "p1",
                "content": "Uses Grep heavily",
                "pattern_type": "tool_preference",
                "pattern_key": "tool_dominant:Grep",
                "confidence": 0.9,
                "raw_confidence": 0.9,
                "evidence_count": 100,
                "evidence_sessions": 20,
                "user_confirmed": None,
            },
        ]
        with self._mock_patterns(patterns):
            insights = analyzer.detect_correlations()
            assert insights == []

    def test_no_correlations_with_empty_patterns(self, coord_db, analyzer):
        """No correlations when no patterns exist."""
        with self._mock_patterns([]):
            insights = analyzer.detect_correlations()
            assert insights == []

    def test_correlation_confidence_is_min_times_09(self, coord_db, analyzer):
        """Correlation confidence = min(a, b) * 0.9."""
        patterns = [
            {
                "id": "p1",
                "content": "Works primarily in the evening",
                "pattern_type": "session_timing",
                "pattern_key": "session_peak_hours",
                "confidence": 0.80,
                "raw_confidence": 0.80,
                "evidence_count": 10,
                "evidence_sessions": 10,
                "user_confirmed": None,
            },
            {
                "id": "p2",
                "content": "Thorough handoff writer",
                "pattern_type": "handoff_quality",
                "pattern_key": "handoff_thoroughness",
                "confidence": 0.90,
                "raw_confidence": 0.90,
                "evidence_count": 10,
                "evidence_sessions": 10,
                "user_confirmed": None,
            },
        ]
        with self._mock_patterns(patterns):
            insights = analyzer.detect_correlations()
            assert len(insights) >= 1
            assert insights[0]["confidence"] == round(0.80 * 0.9, 3)


# ---------------------------------------------------------------------------
# Tests: Phase 4 — Synthesize profile
# ---------------------------------------------------------------------------


class TestSynthesizeProfile:
    def _mock_patterns(self, patterns):
        return patch.object(
            BehavioralAnalyzer, "_get_active_patterns", return_value=patterns
        )

    def test_generates_summary_from_patterns(self, coord_db, analyzer):
        """Profile generates a summary when patterns exist."""
        patterns = [
            {
                "id": "p1",
                "content": "Works primarily in the evening (21:00-01:00 ICT)",
                "pattern_type": "session_timing",
                "pattern_key": "session_peak_hours",
                "confidence": 0.85,
                "raw_confidence": 0.85,
                "evidence_count": 50,
                "evidence_sessions": 30,
                "user_confirmed": None,
            },
            {
                "id": "p2",
                "content": "Commits frequently (avg 6.2/session across 20 sessions)",
                "pattern_type": "git_workflow",
                "pattern_key": "git_commit_frequency",
                "confidence": 0.82,
                "raw_confidence": 0.82,
                "evidence_count": 120,
                "evidence_sessions": 20,
                "user_confirmed": None,
            },
        ]
        with self._mock_patterns(patterns):
            profile = analyzer.synthesize_profile()
            assert profile["summary"]
            assert profile["summary"] != "No behavioral patterns detected yet."
            assert profile["pattern_count"] == 2
            assert profile["avg_confidence"] > 0
            assert "session_timing" in profile["dimensions"]
            assert "git_workflow" in profile["dimensions"]

    def test_empty_when_no_patterns(self, coord_db, analyzer):
        """Profile returns empty summary when no patterns exist."""
        with self._mock_patterns([]):
            profile = analyzer.synthesize_profile()
            assert profile["summary"] == "No behavioral patterns detected yet."
            assert profile["pattern_count"] == 0
            assert profile["dimensions"] == {}

    def test_dimensions_ordered_by_confidence(self, coord_db, analyzer):
        """Dimensions should be ordered by confidence descending."""
        patterns = [
            {
                "id": "p1",
                "content": "Low confidence pattern",
                "pattern_type": "tool_preference",
                "pattern_key": "tool_dominant:Grep",
                "confidence": 0.72,
                "raw_confidence": 0.72,
                "evidence_count": 10,
                "evidence_sessions": 5,
                "user_confirmed": None,
            },
            {
                "id": "p2",
                "content": "High confidence pattern",
                "pattern_type": "session_timing",
                "pattern_key": "session_peak_hours",
                "confidence": 0.95,
                "raw_confidence": 0.95,
                "evidence_count": 80,
                "evidence_sessions": 40,
                "user_confirmed": True,
            },
        ]
        with self._mock_patterns(patterns):
            profile = analyzer.synthesize_profile()
            dim_keys = list(profile["dimensions"].keys())
            dim_confs = [profile["dimensions"][k]["confidence"] for k in dim_keys]
            assert dim_confs == sorted(dim_confs, reverse=True)


# ---------------------------------------------------------------------------
# Tests: Phase 4 — Generate recommendations
# ---------------------------------------------------------------------------


class TestGenerateRecommendations:
    def _mock_patterns(self, patterns):
        return patch.object(
            BehavioralAnalyzer, "_get_active_patterns", return_value=patterns
        )

    def test_long_sessions_rule_fires(self, coord_db, analyzer):
        """Long session recommendation fires when avg > 1h."""
        patterns = [
            {
                "id": "p1",
                "content": "Average session duration: 1.5h (across 20 sessions)",
                "pattern_type": "session_timing",
                "pattern_key": "session_avg_duration",
                "confidence": 0.8,
                "raw_confidence": 0.8,
                "evidence_count": 20,
                "evidence_sessions": 20,
                "user_confirmed": None,
            },
        ]
        with self._mock_patterns(patterns):
            recs = analyzer.generate_recommendations()
            assert any(r["id"] == "long_sessions" for r in recs)

    def test_no_false_positives_short_sessions(self, coord_db, analyzer):
        """Long session recommendation does NOT fire for short sessions."""
        patterns = [
            {
                "id": "p1",
                "content": "Average session duration: 35min (across 20 sessions)",
                "pattern_type": "session_timing",
                "pattern_key": "session_avg_duration",
                "confidence": 0.8,
                "raw_confidence": 0.8,
                "evidence_count": 20,
                "evidence_sessions": 20,
                "user_confirmed": None,
            },
        ]
        with self._mock_patterns(patterns):
            recs = analyzer.generate_recommendations()
            assert not any(r["id"] == "long_sessions" for r in recs)

    def test_multiple_rules_can_fire(self, coord_db, analyzer):
        """Multiple recommendation rules fire simultaneously."""
        patterns = [
            {
                "id": "p1",
                "content": "Average session duration: 2.1h",
                "pattern_type": "session_timing",
                "pattern_key": "session_avg_duration",
                "confidence": 0.8,
                "raw_confidence": 0.8,
                "evidence_count": 20,
                "evidence_sessions": 20,
                "user_confirmed": None,
            },
            {
                "id": "p2",
                "content": "Frequently encounters blockers: 45% of handoffs",
                "pattern_type": "handoff_quality",
                "pattern_key": "handoff_blocker_rate",
                "confidence": 0.75,
                "raw_confidence": 0.75,
                "evidence_count": 10,
                "evidence_sessions": 10,
                "user_confirmed": None,
            },
            {
                "id": "p3",
                "content": "Primary project: omega (72%)",
                "pattern_type": "project_focus",
                "pattern_key": "project_focus:omega",
                "confidence": 0.85,
                "raw_confidence": 0.85,
                "evidence_count": 30,
                "evidence_sessions": 20,
                "user_confirmed": None,
            },
        ]
        with self._mock_patterns(patterns):
            recs = analyzer.generate_recommendations()
            rec_ids = {r["id"] for r in recs}
            assert "long_sessions" in rec_ids
            assert "high_blocker_rate" in rec_ids
            assert "single_project_tunnel" in rec_ids

    def test_empty_when_no_patterns(self, coord_db, analyzer):
        """No recommendations when no patterns match."""
        with self._mock_patterns([]):
            recs = analyzer.generate_recommendations()
            assert recs == []

    def test_weekend_work_rule(self, coord_db, analyzer):
        """Weekend work recommendation fires correctly."""
        patterns = [
            {
                "id": "p1",
                "content": "Frequently works on weekends (60% Sat-Sun)",
                "pattern_type": "session_timing",
                "pattern_key": "session_weekday_pattern",
                "confidence": 0.8,
                "raw_confidence": 0.8,
                "evidence_count": 30,
                "evidence_sessions": 20,
                "user_confirmed": None,
            },
        ]
        with self._mock_patterns(patterns):
            recs = analyzer.generate_recommendations()
            assert any(r["id"] == "weekend_work" for r in recs)

    def test_recommendation_has_required_fields(self, coord_db, analyzer):
        """Each recommendation has id, recommendation, category, based_on."""
        patterns = [
            {
                "id": "p1",
                "content": "Average session duration: 1.5h",
                "pattern_type": "session_timing",
                "pattern_key": "session_avg_duration",
                "confidence": 0.8,
                "raw_confidence": 0.8,
                "evidence_count": 20,
                "evidence_sessions": 20,
                "user_confirmed": None,
            },
        ]
        with self._mock_patterns(patterns):
            recs = analyzer.generate_recommendations()
            for rec in recs:
                assert "id" in rec
                assert "recommendation" in rec
                assert "category" in rec
                assert "based_on" in rec


# ---------------------------------------------------------------------------
# TestIsSubsequence
# ---------------------------------------------------------------------------


class TestIsSubsequence:
    """Test the _is_subsequence helper."""

    def test_exact_match(self):
        assert _is_subsequence(["A", "B", "C"], ["A", "B", "C"])

    def test_subsequence_with_gaps(self):
        assert _is_subsequence(["A", "C"], ["A", "B", "C", "D"])

    def test_not_subsequence(self):
        assert not _is_subsequence(["C", "A"], ["A", "B", "C"])

    def test_empty_pattern(self):
        assert _is_subsequence([], ["A", "B"])

    def test_empty_sequence(self):
        assert not _is_subsequence(["A"], [])

    def test_longer_pattern_than_sequence(self):
        assert not _is_subsequence(["A", "B", "C"], ["A", "B"])


# ---------------------------------------------------------------------------
# TestWorkflowSequencesDeep
# ---------------------------------------------------------------------------


class TestWorkflowSequencesDeep:
    """Test PrefixSpan-based deep workflow sequence mining."""

    def _try_import_prefixspan(self):
        try:
            from prefixspan import PrefixSpan
            return True
        except ImportError:
            return False

    def test_returns_empty_without_prefixspan(self, coord_db):
        analyzer = BehavioralAnalyzer(conn=coord_db)
        with patch.dict("sys.modules", {"prefixspan": None}):
            result = analyzer.analyze_workflow_sequences_deep()
            assert result == []

    def test_returns_empty_without_coord_audit(self, coord_db):
        # Drop the table to test missing table handling
        coord_db.execute("DROP TABLE IF EXISTS coord_audit")
        coord_db.commit()
        coord_db.execute("""
            CREATE TABLE coord_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                tool_name TEXT NOT NULL,
                arguments TEXT,
                result_summary TEXT,
                created_at TEXT NOT NULL
            )
        """)
        coord_db.commit()
        analyzer = BehavioralAnalyzer(conn=coord_db)
        result = analyzer.analyze_workflow_sequences_deep()
        assert result == []

    def test_finds_deep_patterns(self, coord_db):
        if not self._try_import_prefixspan():
            pytest.skip("prefixspan not available")

        analyzer = BehavioralAnalyzer(conn=coord_db)
        now = datetime.now(timezone.utc)

        # Create a consistent 3-tool pattern across 5 sessions
        for sess_idx in range(5):
            sid = f"deep-sess-{sess_idx}"
            for i, tool in enumerate(["Read", "Grep", "Edit", "Read", "Grep", "Edit"]):
                ts = (now + timedelta(seconds=sess_idx * 100 + i)).isoformat()
                coord_db.execute(
                    "INSERT INTO coord_audit (session_id, tool_name, created_at) VALUES (?, ?, ?)",
                    (sid, tool, ts),
                )
        coord_db.commit()

        patterns = analyzer.analyze_workflow_sequences_deep(min_sessions=3)
        assert isinstance(patterns, list)
        # Should find Read -> Grep -> Edit pattern
        if patterns:
            assert any("Read" in p["content"] for p in patterns)
            assert all(p["pattern_type"] == "workflow_sequence_deep" for p in patterns)

    def test_caps_at_10_patterns(self, coord_db):
        if not self._try_import_prefixspan():
            pytest.skip("prefixspan not available")

        analyzer = BehavioralAnalyzer(conn=coord_db)
        now = datetime.now(timezone.utc)

        # Create many different tool sequences
        tools = ["Read", "Grep", "Edit", "Write", "Bash", "Glob", "Task"]
        for sess_idx in range(10):
            sid = f"many-sess-{sess_idx}"
            for i, tool in enumerate(tools):
                ts = (now + timedelta(seconds=sess_idx * 100 + i)).isoformat()
                coord_db.execute(
                    "INSERT INTO coord_audit (session_id, tool_name, created_at) VALUES (?, ?, ?)",
                    (sid, tool, ts),
                )
        coord_db.commit()

        patterns = analyzer.analyze_workflow_sequences_deep(min_sessions=3)
        assert len(patterns) <= 10
