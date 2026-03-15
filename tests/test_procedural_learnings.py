"""Tests for procedural learning extraction from session traces.

Covers:
  - _detect_procedural_patterns: recovery and stuck pattern detection
  - _extract_procedural_learnings: full extraction with mocked coordination
"""

from unittest.mock import MagicMock, patch, call
import pytest

from omega.server.hook_server.session import (
    _detect_procedural_patterns,
    _extract_procedural_learnings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rows(specs: list[tuple[str, str, int, str]]) -> list[dict]:
    """Build audit rows from (tool_name, result_status, call_index, result_summary) tuples."""
    return [
        {
            "tool_name": tool,
            "result_status": status,
            "call_index": idx,
            "result_summary": summary,
        }
        for tool, status, idx, summary in specs
    ]


def _make_minimal_rows(n: int = 20) -> list[dict]:
    """Return n alternating ok rows to satisfy the gate without triggering patterns."""
    return [
        {"tool_name": "omega_query", "result_status": "ok", "call_index": i, "result_summary": ""}
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# 1. Recovery pattern detection
# ---------------------------------------------------------------------------

class TestRecoveryPatternDetection:
    def test_detects_basic_recovery(self):
        """Error on a tool followed by success on the same tool within 10 calls."""
        rows = _make_minimal_rows()  # 20 baseline rows (call_index 0–19)
        # Append error then success on same tool
        rows += _make_rows([
            ("omega_store", "error", 20, "disk full"),
            ("omega_store", "ok",    25, "stored ok"),
        ])
        # Re-sort by call_index
        rows = sorted(rows, key=lambda r: r["call_index"])

        recoveries, stuck = _detect_procedural_patterns(rows)

        assert len(recoveries) == 1
        r = recoveries[0]
        assert r["tool_name"] == "omega_store"
        assert r["error_count"] == 1
        assert r["first_error"] == "disk full"
        assert r["success_summary"] == "stored ok"

    def test_recovery_within_10_calls_boundary(self):
        """Success exactly 10 calls after first error is still a recovery."""
        rows = _make_minimal_rows()
        rows += _make_rows([
            ("tool_a", "error", 20, "err"),
            ("tool_a", "ok",    30, "win"),  # diff = 10
        ])
        rows = sorted(rows, key=lambda r: r["call_index"])
        recoveries, stuck = _detect_procedural_patterns(rows)
        assert any(r["tool_name"] == "tool_a" for r in recoveries)

    def test_no_recovery_when_success_too_far(self):
        """Success > 10 calls after first error should NOT be a recovery."""
        rows = _make_minimal_rows()
        rows += _make_rows([
            ("tool_b", "error", 20, "err"),
            ("tool_b", "ok",    32, "late"),  # diff = 12 > 10
        ])
        rows = sorted(rows, key=lambda r: r["call_index"])
        recoveries, _ = _detect_procedural_patterns(rows)
        assert not any(r["tool_name"] == "tool_b" for r in recoveries)

    def test_multiple_errors_before_recovery(self):
        """Multiple errors before success: error_count reflects all pre-success errors."""
        rows = _make_minimal_rows()
        rows += _make_rows([
            ("tool_c", "error", 20, "err1"),
            ("tool_c", "error", 21, "err2"),
            ("tool_c", "error", 22, "err3"),
            ("tool_c", "ok",    25, "success"),
        ])
        rows = sorted(rows, key=lambda r: r["call_index"])
        recoveries, _ = _detect_procedural_patterns(rows)
        assert len(recoveries) == 1
        assert recoveries[0]["error_count"] == 3
        assert recoveries[0]["first_error"] == "err1"

    def test_recovery_deduplicated_per_tool(self):
        """Same tool should only generate one recovery entry."""
        rows = _make_minimal_rows()
        rows += _make_rows([
            ("tool_d", "error", 20, "e1"),
            ("tool_d", "ok",    22, "s1"),
            ("tool_d", "error", 25, "e2"),
            ("tool_d", "ok",    27, "s2"),
        ])
        rows = sorted(rows, key=lambda r: r["call_index"])
        recoveries, _ = _detect_procedural_patterns(rows)
        tool_d_recoveries = [r for r in recoveries if r["tool_name"] == "tool_d"]
        assert len(tool_d_recoveries) == 1


# ---------------------------------------------------------------------------
# 2. Stuck pattern detection
# ---------------------------------------------------------------------------

class TestStuckPatternDetection:
    def test_detects_stuck_pattern(self):
        """5+ consecutive errors with no resolution → stuck pattern."""
        rows = _make_minimal_rows()
        rows += _make_rows([
            ("flaky_tool", "error", 20, f"err{i}") for i in range(5)
        ])
        rows = sorted(rows, key=lambda r: r["call_index"])
        _, stuck = _detect_procedural_patterns(rows)

        assert len(stuck) == 1
        s = stuck[0]
        assert s["tool_name"] == "flaky_tool"
        assert s["consecutive_errors"] == 5
        assert s["last_error"] == "err4"

    def test_stuck_only_at_five_errors(self):
        """4 consecutive errors should NOT trigger stuck pattern."""
        rows = _make_minimal_rows()
        rows += _make_rows([
            ("almost_stuck", "error", 20 + i, f"err{i}") for i in range(4)
        ])
        rows = sorted(rows, key=lambda r: r["call_index"])
        _, stuck = _detect_procedural_patterns(rows)
        assert not any(s["tool_name"] == "almost_stuck" for s in stuck)

    def test_stuck_uses_last_error_summary(self):
        """last_error should be from the final error row."""
        rows = _make_minimal_rows()
        rows += _make_rows([
            ("s_tool", "error", 20 + i, f"err{i}") for i in range(6)
        ])
        rows = sorted(rows, key=lambda r: r["call_index"])
        _, stuck = _detect_procedural_patterns(rows)
        assert stuck[0]["last_error"] == "err5"


# ---------------------------------------------------------------------------
# 3. Gate: fewer than 20 rows → no output
# ---------------------------------------------------------------------------

class TestGate:
    def test_gate_below_20_rows_returns_empty(self):
        """Sessions with < 20 audit rows should return empty lists."""
        rows = _make_rows([
            ("omega_store", "error", i, "err") for i in range(10)
        ] + [
            ("omega_store", "ok", 15, "ok")
        ])
        recoveries, stuck = _detect_procedural_patterns(rows)
        assert recoveries == []
        assert stuck == []

    def test_gate_exactly_19_rows(self):
        """19 rows — still below gate."""
        rows = _make_minimal_rows(19)
        recoveries, stuck = _detect_procedural_patterns(rows)
        assert recoveries == []
        assert stuck == []

    def test_gate_exactly_20_rows(self):
        """Exactly 20 rows satisfies the gate."""
        rows = _make_minimal_rows(20)
        # Add a recovery on top (rows already at 20 so gate passes)
        rows += _make_rows([
            ("t", "error", 20, "e"),
            ("t", "ok",    21, "s"),
        ])
        rows = sorted(rows, key=lambda r: r["call_index"])
        # 22 total rows — gate should pass and recovery detected
        recoveries, _ = _detect_procedural_patterns(rows)
        assert any(r["tool_name"] == "t" for r in recoveries)


# ---------------------------------------------------------------------------
# 4. Cap: max 3 learnings total
# ---------------------------------------------------------------------------

class TestCap:
    def test_cap_at_three_total(self):
        """No more than 3 combined patterns should be returned."""
        rows = _make_minimal_rows()
        # Create 4 distinct recovery patterns
        for i in range(4):
            tool = f"tool_{i}"
            rows += _make_rows([
                (tool, "error", 100 + i * 20,      f"err_{i}"),
                (tool, "ok",    100 + i * 20 + 5,  f"ok_{i}"),
            ])
        rows = sorted(rows, key=lambda r: r["call_index"])
        recoveries, stuck = _detect_procedural_patterns(rows)
        assert len(recoveries) + len(stuck) <= 3

    def test_recoveries_fill_cap_first(self):
        """Recoveries should be included before stuck patterns."""
        rows = _make_minimal_rows()
        # 3 recoveries
        for i in range(3):
            tool = f"rec_{i}"
            rows += _make_rows([
                (tool, "error", 100 + i * 20,      f"err_{i}"),
                (tool, "ok",    100 + i * 20 + 5,  f"ok_{i}"),
            ])
        # 1 stuck pattern
        rows += _make_rows([
            ("stuck_tool", "error", 200 + j, f"se{j}") for j in range(5)
        ])
        rows = sorted(rows, key=lambda r: r["call_index"])
        recoveries, stuck = _detect_procedural_patterns(rows)
        assert len(recoveries) == 3
        assert len(stuck) == 0  # cap exhausted by recoveries


# ---------------------------------------------------------------------------
# 5. Full extraction — recovery stored as lesson_learned with source=auto_procedural
# ---------------------------------------------------------------------------

class TestFullExtractionRecovery:
    def test_stores_recovery_as_lesson_learned(self):
        """Full extraction stores a recovery pattern as lesson_learned with positive polarity."""
        rows = _make_minimal_rows()
        rows += _make_rows([
            ("omega_store", "error", 20, "bucket error"),
            ("omega_store", "ok",    22, "bucket created"),
        ])
        rows = sorted(rows, key=lambda r: r["call_index"])

        mock_mgr = MagicMock()
        mock_mgr.query_audit.return_value = rows

        # get_manager and auto_capture are imported locally inside _extract_procedural_learnings,
        # so we patch them at their source modules.
        with patch("omega.coordination.get_manager", return_value=mock_mgr), \
             patch("omega.bridge.auto_capture") as mock_ac:
            _extract_procedural_learnings("sess-001")

        mock_ac.assert_called()
        call_kwargs = mock_ac.call_args_list[0].kwargs
        assert call_kwargs["event_type"] == "lesson_learned"
        assert call_kwargs["metadata"]["source"] == "auto_procedural"
        assert call_kwargs["metadata"]["polarity"] == "positive"
        assert call_kwargs["metadata"]["memory_type"] == "procedural"
        assert "omega_store" in call_kwargs["content"]
        assert call_kwargs["session_id"] == "sess-001"


# ---------------------------------------------------------------------------
# 6. Full extraction — stuck stored as lesson_learned with polarity=negative
# ---------------------------------------------------------------------------

class TestFullExtractionStuck:
    def test_stores_stuck_as_lesson_learned_negative(self):
        """Full extraction stores a stuck pattern as lesson_learned with negative polarity."""
        rows = _make_minimal_rows()
        rows += _make_rows([
            ("bad_tool", "error", 20 + i, f"fail{i}") for i in range(5)
        ])
        rows = sorted(rows, key=lambda r: r["call_index"])

        mock_mgr = MagicMock()
        mock_mgr.query_audit.return_value = rows

        with patch("omega.coordination.get_manager", return_value=mock_mgr), \
             patch("omega.bridge.auto_capture") as mock_ac:
            _extract_procedural_learnings("sess-002")

        mock_ac.assert_called()
        call_kwargs = mock_ac.call_args_list[0].kwargs
        assert call_kwargs["event_type"] == "lesson_learned"
        assert call_kwargs["metadata"]["polarity"] == "negative"
        assert call_kwargs["metadata"]["source"] == "auto_procedural"
        assert "bad_tool" in call_kwargs["content"]
        assert "Anti-pattern" in call_kwargs["content"]


# ---------------------------------------------------------------------------
# 7. Short sessions produce no stores
# ---------------------------------------------------------------------------

class TestShortSession:
    def test_empty_session_id_returns_early(self):
        """Empty session_id should return immediately without querying."""
        with patch("omega.coordination.get_manager") as mock_gm, \
             patch("omega.bridge.auto_capture") as mock_ac:
            _extract_procedural_learnings("")

        mock_gm.assert_not_called()
        mock_ac.assert_not_called()

    def test_short_session_no_stores(self):
        """A session with < 20 audit rows should produce no stores."""
        rows = _make_minimal_rows(15)  # only 15 rows, below gate

        mock_mgr = MagicMock()
        mock_mgr.query_audit.return_value = rows

        with patch("omega.coordination.get_manager", return_value=mock_mgr), \
             patch("omega.bridge.auto_capture") as mock_ac:
            _extract_procedural_learnings("sess-short")

        mock_ac.assert_not_called()

    def test_no_patterns_means_no_stores(self):
        """20+ rows but no error patterns → nothing stored."""
        rows = _make_minimal_rows(25)

        mock_mgr = MagicMock()
        mock_mgr.query_audit.return_value = rows

        with patch("omega.coordination.get_manager", return_value=mock_mgr), \
             patch("omega.bridge.auto_capture") as mock_ac:
            _extract_procedural_learnings("sess-clean")

        mock_ac.assert_not_called()

    def test_extraction_caps_stores_at_three(self):
        """Even with many patterns, only 3 stores should be made."""
        rows = _make_minimal_rows()
        # 5 recovery patterns
        for i in range(5):
            tool = f"cap_tool_{i}"
            rows += _make_rows([
                (tool, "error", 100 + i * 20,      f"e{i}"),
                (tool, "ok",    100 + i * 20 + 5,  f"s{i}"),
            ])
        rows = sorted(rows, key=lambda r: r["call_index"])

        mock_mgr = MagicMock()
        mock_mgr.query_audit.return_value = rows

        with patch("omega.coordination.get_manager", return_value=mock_mgr), \
             patch("omega.bridge.auto_capture") as mock_ac:
            _extract_procedural_learnings("sess-cap")

        assert mock_ac.call_count <= 3
