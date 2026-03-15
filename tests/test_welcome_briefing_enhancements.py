"""Tests for welcome briefing enhancements (Tasks 3, 4, 4b).

Covers:
- Task 3: Pattern display includes node_id, status, and action prompt for 3+ unconfirmed
- Task 4: Dead memories (never accessed, 14+ days old) surfaced in welcome
- Task 4b: Stale memory insights (auto_reflect_stale) surfaced in welcome
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def _reset_bridge(tmp_omega_dir):
    from omega.bridge import reset_memory
    reset_memory()
    yield
    reset_memory()


class _NoopResult:
    """Fake pipeline result that returns empty strings for all stages."""
    def get_output(self, key):
        return ""

    def format_footer(self):
        return ""


class _NoopPipeline:
    """Fake maintenance pipeline that does nothing (no GC, no consolidation)."""
    def run(self):
        return _NoopResult()


def _noop_pipeline_factory():
    return _NoopPipeline()


# ============================================================================
# Task 3: Pattern display with node_id, status, action prompt
# ============================================================================

class TestPatternDisplayEnhancements:
    """Test behavioral_pattern display includes node_id and status."""

    def _insert_pattern(self, store, node_id: str, content: str,
                        status: str | None = None, access_count: int = 0):
        meta = json.dumps({"status": status}) if status else "{}"
        store._conn.execute(
            "INSERT INTO memories (node_id, content, event_type, metadata, access_count, created_at) "
            "VALUES (?, ?, 'behavioral_pattern', ?, ?, datetime('now'))",
            (node_id, content, meta, access_count),
        )
        store._conn.commit()

    def test_pattern_shows_node_id_in_output(self, tmp_omega_dir):
        """Pattern lines should include the node_id."""
        from omega.bridge import _get_store
        from omega.server.hook_server import handle_session_start

        store = _get_store()
        self._insert_pattern(store, "pat-abc123", "User prefers short commits", "confirmed")

        result = handle_session_start({"session_id": "test-session", "project": "/tmp"})
        output = result.get("output", "")
        assert "pat-abc123" in output

    def test_pattern_shows_status_in_output(self, tmp_omega_dir):
        """Pattern lines should include the status tag."""
        from omega.bridge import _get_store
        from omega.server.hook_server import handle_session_start

        store = _get_store()
        self._insert_pattern(store, "pat-conf1", "Always run tests before commit", "confirmed")
        self._insert_pattern(store, "pat-pend1", "User avoids large PRs", None)

        result = handle_session_start({"session_id": "test-session", "project": "/tmp"})
        output = result.get("output", "")
        assert "[confirmed]" in output
        assert "[unconfirmed]" in output

    def test_pattern_truncates_content_to_100(self, tmp_omega_dir):
        """Pattern content first line should be truncated to 100 characters."""
        from omega.bridge import _get_store
        from omega.server.hook_server import handle_session_start

        store = _get_store()
        long_content = "X" * 150 + "\nSecond line should not appear"
        self._insert_pattern(store, "pat-long1", long_content, "confirmed")

        result = handle_session_start({"session_id": "test-session", "project": "/tmp"})
        output = result.get("output", "")
        # The truncated content (100 chars of X) should appear, but not 150 Xs
        assert "X" * 100 in output
        assert "X" * 101 not in output
        assert "Second line should not appear" not in output

    def test_action_prompt_shown_when_3_or_more_unconfirmed(self, tmp_omega_dir):
        """Action prompt should appear when 3+ patterns are unconfirmed."""
        from omega.bridge import _get_store
        from omega.server.hook_server import handle_session_start

        store = _get_store()
        for i in range(3):
            self._insert_pattern(store, f"pat-unc{i}", f"Unconfirmed pattern {i}", None)

        result = handle_session_start({"session_id": "test-session", "project": "/tmp"})
        output = result.get("output", "")
        assert "Action needed" in output
        assert "habits_confirm" in output
        assert "habits_deny" in output

    def test_action_prompt_not_shown_when_fewer_than_3_unconfirmed(self, tmp_omega_dir):
        """Action prompt should NOT appear when fewer than 3 unconfirmed."""
        from omega.bridge import _get_store
        from omega.server.hook_server import handle_session_start

        store = _get_store()
        self._insert_pattern(store, "pat-c1", "Confirmed pattern", "confirmed")
        self._insert_pattern(store, "pat-u1", "One unconfirmed", None)
        self._insert_pattern(store, "pat-u2", "Two unconfirmed", None)

        result = handle_session_start({"session_id": "test-session", "project": "/tmp"})
        output = result.get("output", "")
        assert "habits_confirm" not in output

    def test_action_prompt_shown_when_exactly_3_unconfirmed(self, tmp_omega_dir):
        """Boundary: exactly 3 unconfirmed should trigger the action prompt."""
        from omega.bridge import _get_store
        from omega.server.hook_server import handle_session_start

        store = _get_store()
        self._insert_pattern(store, "pat-e1", "Pattern 1", None)
        self._insert_pattern(store, "pat-e2", "Pattern 2", None)
        self._insert_pattern(store, "pat-e3", "Pattern 3", None)

        result = handle_session_start({"session_id": "test-session", "project": "/tmp"})
        output = result.get("output", "")
        assert "habits_confirm" in output

    def test_no_patterns_no_section(self, tmp_omega_dir):
        """When no patterns exist, [PATTERNS] section should not appear."""
        from omega.server.hook_server import handle_session_start

        result = handle_session_start({"session_id": "test-session", "project": "/tmp"})
        output = result.get("output", "")
        assert "[PATTERNS]" not in output

    def test_limit_5_patterns(self, tmp_omega_dir):
        """At most 5 patterns should be displayed (LIMIT 5)."""
        from omega.bridge import _get_store
        from omega.server.hook_server import handle_session_start

        store = _get_store()
        for i in range(7):
            self._insert_pattern(store, f"pat-lim{i}", f"Pattern number {i}",
                                 "confirmed", access_count=i)

        result = handle_session_start({"session_id": "test-session", "project": "/tmp"})
        output = result.get("output", "")
        # Count how many pattern IDs appear
        count = sum(1 for i in range(7) if f"pat-lim{i}" in output)
        assert count <= 5


# ============================================================================
# Task 4: Dead memories surfaced in welcome
#
# Strategy: The maintenance pipeline GCs old zero-access-count memories, so
# tests mock it out. The tests verify the SQL query and output formatting.
# ============================================================================

class TestDeadMemoriesSurfacing:
    """Test dead memories (access_count=0, 14+ days old) appear in welcome."""

    def _insert_old_memory(self, store, node_id: str, content: str,
                           event_type: str = "decision",
                           days_old: int = 20, access_count: int = 0):
        created_at = (datetime.now(timezone.utc) - timedelta(days=days_old)).isoformat()
        store._conn.execute(
            "INSERT INTO memories (node_id, content, event_type, access_count, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (node_id, content, event_type, access_count, created_at),
        )
        store._conn.commit()

    def test_dead_memory_appears_in_output(self, tmp_omega_dir):
        """A dead memory (never accessed, 20 days old) should appear in welcome."""
        from omega.bridge import _get_store
        from omega.server.hook_server import handle_session_start

        store = _get_store()
        self._insert_old_memory(store, "dead-mem-001", "Old decision nobody cares about")

        with patch(
            "omega.server.hook_server.maintenance.build_session_start_pipeline",
            return_value=_NoopPipeline(),
        ):
            result = handle_session_start({"session_id": "test-session", "project": "/tmp"})

        output = result.get("output", "")
        assert "dead-mem-001" in output
        assert "Dead memories" in output

    def test_dead_memory_shows_content_preview(self, tmp_omega_dir):
        """Dead memory should show the first 80 characters of content."""
        from omega.bridge import _get_store
        from omega.server.hook_server import handle_session_start

        store = _get_store()
        content = "This is a dead memory with specific identifiable content for testing purposes"
        self._insert_old_memory(store, "dead-preview-001", content)

        with patch(
            "omega.server.hook_server.maintenance.build_session_start_pipeline",
            return_value=_NoopPipeline(),
        ):
            result = handle_session_start({"session_id": "test-session", "project": "/tmp"})

        output = result.get("output", "")
        assert content[:80] in output

    def test_dead_memory_total_count_shown(self, tmp_omega_dir):
        """The total count of dead memories should appear in the header."""
        from omega.bridge import _get_store
        from omega.server.hook_server import handle_session_start

        store = _get_store()
        for i in range(5):
            self._insert_old_memory(store, f"dead-count-{i}", f"Dead memory {i}")

        with patch(
            "omega.server.hook_server.maintenance.build_session_start_pipeline",
            return_value=_NoopPipeline(),
        ):
            result = handle_session_start({"session_id": "test-session", "project": "/tmp"})

        output = result.get("output", "")
        assert "5 never accessed" in output

    def test_recently_created_memory_not_shown(self, tmp_omega_dir):
        """Memory created less than 14 days ago should NOT appear as dead."""
        from omega.bridge import _get_store
        from omega.server.hook_server import handle_session_start

        store = _get_store()
        # Insert a "returning user" anchor so we get past the new-user path
        self._insert_old_memory(
            store, "anchor-001", "Anchor memory", days_old=20, access_count=5
        )
        self._insert_old_memory(
            store, "fresh-mem-001", "Recently created memory", days_old=5
        )

        with patch(
            "omega.server.hook_server.maintenance.build_session_start_pipeline",
            return_value=_NoopPipeline(),
        ):
            result = handle_session_start({"session_id": "test-session", "project": "/tmp"})

        output = result.get("output", "")
        assert "fresh-mem-001" not in output

    def test_accessed_memory_not_shown(self, tmp_omega_dir):
        """Memory with access_count > 0 should NOT appear even if old."""
        from omega.bridge import _get_store
        from omega.server.hook_server import handle_session_start

        store = _get_store()
        # This memory is old but accessed — should not show as dead
        self._insert_old_memory(
            store, "accessed-mem-001", "Accessed old memory", access_count=3
        )

        with patch(
            "omega.server.hook_server.maintenance.build_session_start_pipeline",
            return_value=_NoopPipeline(),
        ):
            result = handle_session_start({"session_id": "test-session", "project": "/tmp"})

        output = result.get("output", "")
        assert "accessed-mem-001" not in output

    def test_session_summary_excluded(self, tmp_omega_dir):
        """session_summary event_type should be excluded from dead memory list."""
        from omega.bridge import _get_store
        from omega.server.hook_server import handle_session_start

        store = _get_store()
        self._insert_old_memory(
            store, "dead-anchor", "Returning user anchor", days_old=20, access_count=5
        )
        self._insert_old_memory(
            store, "sess-sum-001", "Old session summary", event_type="session_summary"
        )

        with patch(
            "omega.server.hook_server.maintenance.build_session_start_pipeline",
            return_value=_NoopPipeline(),
        ):
            result = handle_session_start({"session_id": "test-session", "project": "/tmp"})

        output = result.get("output", "")
        assert "sess-sum-001" not in output

    def test_checkpoint_excluded(self, tmp_omega_dir):
        """checkpoint event_type should be excluded from dead memory list."""
        from omega.bridge import _get_store
        from omega.server.hook_server import handle_session_start

        store = _get_store()
        self._insert_old_memory(
            store, "dead-anchor2", "Returning user anchor", days_old=20, access_count=5
        )
        self._insert_old_memory(
            store, "chkpt-001", "Old checkpoint", event_type="checkpoint"
        )

        with patch(
            "omega.server.hook_server.maintenance.build_session_start_pipeline",
            return_value=_NoopPipeline(),
        ):
            result = handle_session_start({"session_id": "test-session", "project": "/tmp"})

        output = result.get("output", "")
        assert "chkpt-001" not in output

    def test_no_dead_memories_no_section(self, tmp_omega_dir):
        """When no dead memories exist, the section should not appear."""
        from omega.bridge import _get_store
        from omega.server.hook_server import handle_session_start

        store = _get_store()
        # Only insert accessed memories — no dead ones
        self._insert_old_memory(
            store, "live-mem-001", "Accessed memory", days_old=20, access_count=5
        )

        with patch(
            "omega.server.hook_server.maintenance.build_session_start_pipeline",
            return_value=_NoopPipeline(),
        ):
            result = handle_session_start({"session_id": "test-session", "project": "/tmp"})

        output = result.get("output", "")
        assert "Dead memories" not in output

    def test_max_3_dead_memories_shown(self, tmp_omega_dir):
        """At most 3 dead memories should be shown in the briefing."""
        from omega.bridge import _get_store
        from omega.server.hook_server import handle_session_start

        store = _get_store()
        for i in range(6):
            self._insert_old_memory(store, f"dead-max-{i}", f"Dead memory item {i}")

        with patch(
            "omega.server.hook_server.maintenance.build_session_start_pipeline",
            return_value=_NoopPipeline(),
        ):
            result = handle_session_start({"session_id": "test-session", "project": "/tmp"})

        output = result.get("output", "")
        count = sum(1 for i in range(6) if f"dead-max-{i}" in output)
        assert count <= 3

    def test_dead_memory_sql_query_logic(self, tmp_omega_dir):
        """Directly verify the dead memory SQL query returns expected rows."""
        from omega.bridge import _get_store

        store = _get_store()
        # Dead: old + access_count=0 + eligible type
        old_date = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
        recent_date = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()

        store._conn.executemany(
            "INSERT INTO memories (node_id, content, event_type, access_count, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                ("dead-eligible", "Should appear", "decision", 0, old_date),
                ("dead-fresh", "Too fresh", "decision", 0, recent_date),
                ("dead-accessed", "Has accesses", "decision", 3, old_date),
                ("dead-sess-sum", "Session summary", "session_summary", 0, old_date),
                ("dead-checkpoint", "Checkpoint", "checkpoint", 0, old_date),
                ("dead-bpat", "Behavioral pattern", "behavioral_pattern", 0, old_date),
            ],
        )
        store._conn.commit()

        rows = store._conn.execute(
            "SELECT node_id FROM memories "
            "WHERE access_count = 0 "
            "AND created_at < datetime('now', '-14 days') "
            "AND event_type NOT IN ('session_summary', 'checkpoint', 'behavioral_pattern') "
            "ORDER BY created_at ASC LIMIT 3"
        ).fetchall()

        node_ids = [r[0] for r in rows]
        assert "dead-eligible" in node_ids
        assert "dead-fresh" not in node_ids
        assert "dead-accessed" not in node_ids
        assert "dead-sess-sum" not in node_ids
        assert "dead-checkpoint" not in node_ids
        assert "dead-bpat" not in node_ids


# ============================================================================
# Task 4b: Stale memory insights from auto_reflect_stale
# ============================================================================

class TestStaleInsightsSurfacing:
    """Test stale memory insights (auto_reflect_stale) surfaced in welcome."""

    def _insert_stale_insight(self, store, node_id: str, content: str,
                              source: str = "auto_reflect_stale"):
        meta = json.dumps({"source": source, "category": "system_insight"})
        store._conn.execute(
            "INSERT INTO memories (node_id, content, event_type, metadata, created_at) "
            "VALUES (?, ?, 'advisor_insight', ?, datetime('now'))",
            (node_id, content, meta),
        )
        store._conn.commit()

    def _insert_anchor(self, store):
        """Insert a returning-user anchor memory so we get past the new-user path."""
        from datetime import datetime, timezone, timedelta
        old = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        store._conn.execute(
            "INSERT INTO memories (node_id, content, event_type, access_count, created_at) "
            "VALUES ('anchor-stale', 'Anchor', 'decision', 5, ?)",
            (old,),
        )
        store._conn.commit()

    def test_stale_insight_appears_in_output(self, tmp_omega_dir):
        """An auto_reflect_stale insight should appear in the welcome briefing."""
        from omega.bridge import _get_store
        from omega.server.hook_server import handle_session_start

        store = _get_store()
        self._insert_stale_insight(
            store, "insight-001",
            "Stale memories detected:\n- mem-abc: Old note about deployment\n- mem-xyz: Unused rule",
        )

        with patch(
            "omega.server.hook_server.maintenance.build_session_start_pipeline",
            return_value=_NoopPipeline(),
        ):
            result = handle_session_start({"session_id": "test-session", "project": "/tmp"})

        output = result.get("output", "")
        assert "Stale memories to review" in output
        assert "auto-reflect" in output

    def test_stale_insight_shows_content_preview(self, tmp_omega_dir):
        """Stale insight should show the content lines."""
        from omega.bridge import _get_store
        from omega.server.hook_server import handle_session_start

        store = _get_store()
        self._insert_stale_insight(
            store, "insight-preview-001",
            "Line 1 of stale insight\nLine 2 of stale insight\nLine 3 of stale insight",
        )

        with patch(
            "omega.server.hook_server.maintenance.build_session_start_pipeline",
            return_value=_NoopPipeline(),
        ):
            result = handle_session_start({"session_id": "test-session", "project": "/tmp"})

        output = result.get("output", "")
        assert "Line 1 of stale insight" in output

    def test_non_stale_insight_not_shown(self, tmp_omega_dir):
        """An advisor_insight without auto_reflect_stale source should NOT appear."""
        from omega.bridge import _get_store
        from omega.server.hook_server import handle_session_start

        store = _get_store()
        self._insert_anchor(store)
        self._insert_stale_insight(
            store, "insight-other-001",
            "Some other insight content",
            source="manual",
        )

        with patch(
            "omega.server.hook_server.maintenance.build_session_start_pipeline",
            return_value=_NoopPipeline(),
        ):
            result = handle_session_start({"session_id": "test-session", "project": "/tmp"})

        output = result.get("output", "")
        assert "Stale memories to review" not in output

    def test_no_stale_insights_no_section(self, tmp_omega_dir):
        """When no stale insights exist, the section should not appear."""
        from omega.bridge import _get_store
        from omega.server.hook_server import handle_session_start

        store = _get_store()
        self._insert_anchor(store)

        with patch(
            "omega.server.hook_server.maintenance.build_session_start_pipeline",
            return_value=_NoopPipeline(),
        ):
            result = handle_session_start({"session_id": "test-session", "project": "/tmp"})

        output = result.get("output", "")
        assert "Stale memories to review" not in output

    def test_only_latest_insight_shown(self, tmp_omega_dir):
        """Only the most recent stale insight should be shown (LIMIT 1)."""
        from omega.bridge import _get_store
        from omega.server.hook_server import handle_session_start

        store = _get_store()
        self._insert_stale_insight(store, "insight-old-001", "Old stale insight content")
        self._insert_stale_insight(store, "insight-new-001", "New stale insight content")

        with patch(
            "omega.server.hook_server.maintenance.build_session_start_pipeline",
            return_value=_NoopPipeline(),
        ):
            result = handle_session_start({"session_id": "test-session", "project": "/tmp"})

        output = result.get("output", "")
        assert "Stale memories to review" in output
        # Section header should appear exactly once
        assert output.count("Stale memories to review") == 1

    def test_stale_insight_max_5_preview_lines(self, tmp_omega_dir):
        """Preview should be capped at 5 lines."""
        from omega.bridge import _get_store
        from omega.server.hook_server import handle_session_start

        store = _get_store()
        long_content = "\n".join(f"Line {i} of stale content" for i in range(10))
        self._insert_stale_insight(store, "insight-long-001", long_content)

        with patch(
            "omega.server.hook_server.maintenance.build_session_start_pipeline",
            return_value=_NoopPipeline(),
        ):
            result = handle_session_start({"session_id": "test-session", "project": "/tmp"})

        output = result.get("output", "")
        assert "Line 0 of stale content" in output
        assert "Line 4 of stale content" in output
        assert "Line 5 of stale content" not in output

    def test_stale_insight_sql_query_logic(self, tmp_omega_dir):
        """Directly verify the stale insight SQL query returns expected rows."""
        from omega.bridge import _get_store

        store = _get_store()
        for source, node_id in [
            ("auto_reflect_stale", "correct-source"),
            ("manual", "wrong-source"),
            ("weekly_reflect", "another-wrong"),
        ]:
            meta = json.dumps({"source": source})
            store._conn.execute(
                "INSERT INTO memories (node_id, content, event_type, metadata, created_at) "
                "VALUES (?, ?, 'advisor_insight', ?, datetime('now'))",
                (node_id, f"Content for {node_id}", meta),
            )
        store._conn.commit()

        rows = store._conn.execute(
            "SELECT node_id FROM memories "
            "WHERE event_type = 'advisor_insight' "
            "AND json_extract(metadata, '$.source') = 'auto_reflect_stale' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchall()

        node_ids = [r[0] for r in rows]
        assert "correct-source" in node_ids
        assert "wrong-source" not in node_ids
        assert "another-wrong" not in node_ids
