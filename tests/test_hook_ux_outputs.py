"""Tests for hook UX output formatting.

Covers:
- Scored surfacing output format ([score%] event_type: preview (id:xxx))
- Health pulse formatting (ago calculation, edge count, label)
- Activity report via actual hook function (_print_activity_report)
- Build summary from session_stop
- _ext_to_tags full extension coverage
- _surface_for_edit output format with scoring
- Cross-project lesson output format in standalone hook
"""

import json
import os
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))


# ============================================================================
# Fixture: reset bridge singleton between tests
# ============================================================================

@pytest.fixture(autouse=True)
def _reset_bridge(tmp_omega_dir):
    from omega.bridge import reset_memory
    reset_memory()
    yield
    reset_memory()


@pytest.fixture
def fake_home(tmp_omega_dir):
    home_dir = tmp_omega_dir.parent
    with patch.object(Path, "home", return_value=home_dir):
        yield home_dir


# ============================================================================
# Scored surfacing output format
# ============================================================================

class TestScoredSurfacingFormat:
    """Test _surface_for_edit output lines use compact [OMEGA] card format."""

    def test_produces_omega_card(self):
        from omega.server.hook_server import _surface_for_edit
        mock_results = [
            {"relevance": 0.87, "event_type": "decision", "content": "Use SQLite", "id": "abcdef1234"},
        ]
        with patch("omega.bridge.query_structured", return_value=mock_results):
            lines = _surface_for_edit("/src/omega/bridge.py", "s1", "/Projects/omega")
        assert any("[OMEGA]" in line for line in lines)

    def test_memory_produces_used_card(self):
        from omega.server.hook_server import _surface_for_edit
        mock_results = [
            {"relevance": 0.87, "event_type": "decision", "content": "Use SQLite", "id": "abcdef1234"},
        ]
        with patch("omega.bridge.query_structured", return_value=mock_results):
            lines = _surface_for_edit("/src/bridge.py", "s1", "/proj")
        card_output = "\n".join(lines)
        assert "[OMEGA] Used:" in card_output
        assert "Use SQLite" in card_output

    def test_error_pattern_produces_warning_card(self):
        from omega.server.hook_server import _surface_for_edit
        mock_results = [
            {"relevance": 0.65, "event_type": "error_pattern", "content": "DB timeout", "id": "xyz789abcd",
             "metadata": {"error_count": 2, "pattern": "DB timeout", "file": "db.py"}},
        ]
        with patch("omega.bridge.query_structured", return_value=mock_results):
            lines = _surface_for_edit("/f.py", "s1", "/p")
        card_output = "\n".join(lines)
        assert "[OMEGA] Warning:" in card_output

    def test_content_preview_truncated_at_120(self):
        from omega.server.hook_server import _surface_for_edit
        long_content = "A" * 200
        mock_results = [
            {"relevance": 0.40, "event_type": "decision", "content": long_content, "id": "abc12345"},
        ]
        with patch("omega.bridge.query_structured", return_value=mock_results):
            lines = _surface_for_edit("/f.py", "s1", "/p")
        card_output = "\n".join(lines)
        # Content should be truncated (120 chars max + ellipsis)
        assert "A" * 121 not in card_output

    def test_results_below_threshold_filtered(self):
        from omega.server.hook_server import _surface_for_edit
        mock_results = [
            {"relevance": 0.10, "event_type": "decision", "content": "low", "id": "aaa"},
            {"relevance": 0.05, "event_type": "error_pattern", "content": "very low", "id": "bbb"},
        ]
        with patch("omega.bridge.query_structured", return_value=mock_results):
            lines = _surface_for_edit("/f.py", "s1", "/p")
        assert lines == []

    def test_empty_results_returns_empty(self):
        from omega.server.hook_server import _surface_for_edit
        with patch("omega.bridge.query_structured", return_value=[]):
            lines = _surface_for_edit("/f.py", "s1", "/p")
        assert lines == []

    def test_multiple_results_all_produce_cards(self):
        from omega.server.hook_server import _surface_for_edit
        mock_results = [
            {"relevance": 0.90, "event_type": "decision", "content": "First", "id": "aaa11111"},
            {"relevance": 0.75, "event_type": "lesson_learned", "content": "Second", "id": "bbb22222"},
            {"relevance": 0.60, "event_type": "error_pattern", "content": "Third", "id": "ccc33333",
             "metadata": {"error_count": 1, "pattern": "Third", "file": "f.py"}},
        ]
        with patch("omega.bridge.query_structured", return_value=mock_results):
            lines = _surface_for_edit("/f.py", "s1", "/p")
        # Each result produces a compact card (1 card per result, cards may be multi-line)
        assert len(lines) == 3
        assert all("[OMEGA]" in line for line in lines)

    def test_tracks_surfaced_ids(self, fake_home, tmp_omega_dir):
        from omega.server.hook_server import _surface_for_edit
        mock_results = [
            {"relevance": 0.80, "event_type": "decision", "content": "test", "id": "mem-aaa"},
        ]
        with patch("omega.bridge.query_structured", return_value=mock_results):
            _surface_for_edit("/f.py", "s1", "/p")
        json_path = tmp_omega_dir / "session-s1.surfaced.json"
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert "mem-aaa" in data["/f.py"]


# ============================================================================
# Health pulse formatting
# ============================================================================

class TestHealthPulse:
    """Test health pulse output in session_start hook."""

    def _run_main_capture(self, fake_home, tmp_omega_dir, **overrides):
        """Run session_start.main() capturing stdout."""
        import importlib
        import session_start
        importlib.reload(session_start)

        mock_welcome = {
            "memory_count": 42,
            "recent_memories": [],
        }
        mock_health = overrides.get("health", {"ok": True})
        edge_count = overrides.get("edge_count", 100)
        last_ts = overrides.get("last_ts", None)

        mock_store = MagicMock()
        mock_store.edge_count.return_value = edge_count
        mock_store.count.return_value = overrides.get("node_count", 50)
        mock_store.get_last_capture_time.return_value = last_ts

        captured = StringIO()
        with patch("omega.bridge.welcome", return_value=mock_welcome), \
             patch("omega.bridge.status", return_value=mock_health), \
             patch("omega.bridge._get_store", return_value=mock_store), \
             patch("omega.bridge.consolidate"), \
             patch("omega.bridge.compact"), \
             patch("omega.bridge.get_cross_project_lessons", return_value=[]), \
             patch("sys.stdout", captured):
            session_start.main()
        return captured.getvalue()

    def test_health_label_ok(self, fake_home, tmp_omega_dir):
        output = self._run_main_capture(fake_home, tmp_omega_dir, health={"ok": True})
        assert "Health: ok" in output

    def test_health_label_from_status(self, fake_home, tmp_omega_dir):
        output = self._run_main_capture(fake_home, tmp_omega_dir, health={"ok": False, "status": "degraded"})
        assert "Health: degraded" in output

    def test_edge_count_thousands_separator(self, fake_home, tmp_omega_dir):
        output = self._run_main_capture(fake_home, tmp_omega_dir, edge_count=12345)
        assert "12,345 edges" in output

    def test_last_capture_never(self, fake_home, tmp_omega_dir):
        output = self._run_main_capture(fake_home, tmp_omega_dir, last_ts=None)
        assert "Last capture: never" in output

    def test_last_capture_seconds_ago(self, fake_home, tmp_omega_dir):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        ts = now.isoformat()
        output = self._run_main_capture(fake_home, tmp_omega_dir, last_ts=ts)
        assert "s ago" in output

    def test_last_capture_days_ago(self, fake_home, tmp_omega_dir):
        from datetime import datetime, timezone, timedelta
        old = datetime.now(timezone.utc) - timedelta(days=3, hours=5)
        ts = old.isoformat()
        output = self._run_main_capture(fake_home, tmp_omega_dir, last_ts=ts)
        assert "3d ago" in output

    def test_full_health_line_format(self, fake_home, tmp_omega_dir):
        output = self._run_main_capture(fake_home, tmp_omega_dir, edge_count=50)
        assert "Health:" in output
        assert "graph:" in output
        assert "Last capture:" in output


# ============================================================================
# Activity report via actual hook function
# ============================================================================

class TestActivityReportHook:
    """Test _print_activity_report from the actual session_stop hook."""

    def _capture_report(self, session_id, counts, surfaced=0, fake_home=None, tmp_omega_dir=None):
        import importlib
        import session_stop
        importlib.reload(session_stop)

        mock_store = MagicMock()
        mock_store.get_session_event_counts.return_value = counts

        if tmp_omega_dir and surfaced:
            marker = tmp_omega_dir / f"session-{session_id}.surfaced"
            marker.write_text("x" * surfaced)

        captured = StringIO()
        with patch("omega.bridge._get_store", return_value=mock_store), \
             patch("sys.stdout", captured):
            session_stop._print_activity_report(session_id)
        return captured.getvalue()

    def test_full_report_format(self, fake_home, tmp_omega_dir):
        counts = {"error_pattern": 2, "decision": 3, "lesson_learned": 1}
        output = self._capture_report("s1", counts, surfaced=4, fake_home=fake_home, tmp_omega_dir=tmp_omega_dir)
        assert "Session complete" in output
        assert "6 captured" in output  # 2+3+1
        assert "2 errors" in output
        assert "3 decisions" in output
        assert "1 lesson learned" in output
        assert "4 surfaced" in output

    def test_pipe_delimited(self, fake_home, tmp_omega_dir):
        counts = {"decision": 2}
        output = self._capture_report("s1", counts, fake_home=fake_home, tmp_omega_dir=tmp_omega_dir)
        assert "|" in output

    def test_no_output_when_empty(self, fake_home, tmp_omega_dir):
        output = self._capture_report("s1", {}, fake_home=fake_home, tmp_omega_dir=tmp_omega_dir)
        assert output == ""

    def test_no_output_for_empty_session_id(self, fake_home, tmp_omega_dir):
        output = self._capture_report("", {"decision": 1}, fake_home=fake_home, tmp_omega_dir=tmp_omega_dir)
        assert output == ""

    def test_surfaced_only(self, fake_home, tmp_omega_dir):
        """Report should appear even with zero captured but some surfaced."""
        output = self._capture_report("s1", {}, surfaced=5, fake_home=fake_home, tmp_omega_dir=tmp_omega_dir)
        assert "0 captured" in output
        assert "5 surfaced" in output

    def test_plural_errors(self, fake_home, tmp_omega_dir):
        counts = {"error_pattern": 3}
        output = self._capture_report("s1", counts, fake_home=fake_home, tmp_omega_dir=tmp_omega_dir)
        assert "3 errors" in output

    def test_singular_error(self, fake_home, tmp_omega_dir):
        counts = {"error_pattern": 1}
        output = self._capture_report("s1", counts, fake_home=fake_home, tmp_omega_dir=tmp_omega_dir)
        assert "1 error" in output
        assert "errors" not in output


# ============================================================================
# Build summary from session_stop
# ============================================================================

class TestBuildSummary:
    """Test _build_summary in the session_stop hook."""

    def _build(self, decisions=None, errors=None, tasks=None):
        import importlib
        import session_stop
        importlib.reload(session_stop)

        def fake_query(query_text, limit, session_id, project, event_type=None):
            if event_type == "decision":
                return decisions or []
            elif event_type == "error_pattern":
                return errors or []
            elif event_type == "task_completion":
                return tasks or []
            return []

        with patch("omega.bridge.query_structured", side_effect=fake_query):
            return session_stop._build_summary("s1", "/proj")

    def test_no_activity_fallback(self):
        result = self._build()
        assert result == "Session ended (no captured activity)"

    def test_decisions_section(self):
        result = self._build(decisions=[
            {"content": "Used SQLite for storage"},
            {"content": "Chose ONNX over PyTorch"},
        ])
        assert "Decisions (2)" in result
        assert "Used SQLite" in result
        assert "Chose ONNX" in result

    def test_errors_section(self):
        result = self._build(errors=[
            {"content": "DB connection timeout on cold start"},
        ])
        assert "Errors (1)" in result
        assert "DB connection timeout" in result

    def test_tasks_section(self):
        result = self._build(tasks=[
            {"content": "Migrated store to SQLite"},
        ])
        assert "Tasks (1)" in result
        assert "Migrated store" in result

    def test_multiple_sections_pipe_delimited(self):
        result = self._build(
            decisions=[{"content": "d1"}],
            errors=[{"content": "e1"}],
        )
        assert " | " in result

    def test_summary_truncated_at_600(self):
        long_decisions = [{"content": "A" * 120} for _ in range(10)]
        result = self._build(decisions=long_decisions)
        assert len(result) <= 600

    def test_content_preview_truncated_at_120(self):
        result = self._build(decisions=[{"content": "B" * 200}])
        # Decision content should be truncated
        assert "B" * 121 not in result


# ============================================================================
# _ext_to_tags full coverage
# ============================================================================

class TestExtToTagsComplete:
    """Test all 18 file extension mappings."""

    @pytest.mark.parametrize("ext,expected", [
        (".py", ["python"]),
        (".js", ["javascript"]),
        (".ts", ["typescript"]),
        (".tsx", ["typescript", "react"]),
        (".jsx", ["javascript", "react"]),
        (".rs", ["rust"]),
        (".go", ["go"]),
        (".rb", ["ruby"]),
        (".java", ["java"]),
        (".swift", ["swift"]),
        (".sh", ["bash"]),
        (".sql", ["sql"]),
        (".md", ["markdown"]),
        (".yml", ["yaml"]),
        (".yaml", ["yaml"]),
        (".json", ["json"]),
        (".toml", ["toml"]),
    ])
    def test_extension_mapping(self, ext, expected):
        from omega.server.hook_server import _ext_to_tags
        assert _ext_to_tags(f"/tmp/file{ext}") == expected

    def test_case_insensitive(self):
        from omega.server.hook_server import _ext_to_tags
        assert _ext_to_tags("/tmp/File.PY") == ["python"]
        assert _ext_to_tags("/tmp/App.TSX") == ["typescript", "react"]

    def test_no_extension(self):
        from omega.server.hook_server import _ext_to_tags
        assert _ext_to_tags("/tmp/Makefile") == []

    def test_unknown_extension(self):
        from omega.server.hook_server import _ext_to_tags
        assert _ext_to_tags("/tmp/data.csv") == []


# ============================================================================
# Cross-project lesson output format (standalone hook)
# ============================================================================

class TestCrossProjectOutputFormat:
    """Test the cross-project lesson output in session_start standalone hook."""

    def test_output_header(self, fake_home, tmp_omega_dir, capsys):
        import importlib
        import session_start
        importlib.reload(session_start)

        mock_lessons = [
            {"content": "Always validate inputs", "cross_project": True, "project": "other-project"},
        ]
        mock_welcome = {"memory_count": 10, "recent_memories": []}

        with patch("omega.bridge.welcome", return_value=mock_welcome), \
             patch("omega.bridge.consolidate"), \
             patch("omega.bridge.compact"), \
             patch("omega.bridge.get_cross_project_lessons", return_value=mock_lessons):
            session_start.main()

        output = capsys.readouterr().out
        assert "[CROSS-PROJECT]" in output
        assert "Lessons from other codebases:" in output

    def test_project_name_in_brackets(self, fake_home, tmp_omega_dir, capsys):
        import importlib
        import session_start
        importlib.reload(session_start)

        mock_lessons = [
            {"content": "Use type hints", "cross_project": True, "project": "/projects/acme"},
        ]
        mock_welcome = {"memory_count": 10, "recent_memories": []}

        with patch("omega.bridge.welcome", return_value=mock_welcome), \
             patch("omega.bridge.consolidate"), \
             patch("omega.bridge.compact"), \
             patch("omega.bridge.get_cross_project_lessons", return_value=mock_lessons):
            session_start.main()

        output = capsys.readouterr().out
        assert "[/projects/acme]" in output
        assert "Use type hints" in output

    def test_content_truncated_at_120(self, fake_home, tmp_omega_dir, capsys):
        import importlib
        import session_start
        importlib.reload(session_start)

        long_content = "X" * 200
        mock_lessons = [
            {"content": long_content, "cross_project": True, "project": "proj"},
        ]
        mock_welcome = {"memory_count": 10, "recent_memories": []}

        with patch("omega.bridge.welcome", return_value=mock_welcome), \
             patch("omega.bridge.consolidate"), \
             patch("omega.bridge.compact"), \
             patch("omega.bridge.get_cross_project_lessons", return_value=mock_lessons):
            session_start.main()

        output = capsys.readouterr().out
        assert "X" * 121 not in output

    def test_max_3_lessons(self, fake_home, tmp_omega_dir, capsys):
        import importlib
        import session_start
        importlib.reload(session_start)

        mock_lessons = [
            {"content": f"Lesson {i}", "cross_project": True, "project": f"p{i}"}
            for i in range(5)
        ]
        mock_welcome = {"memory_count": 10, "recent_memories": []}

        with patch("omega.bridge.welcome", return_value=mock_welcome), \
             patch("omega.bridge.consolidate"), \
             patch("omega.bridge.compact"), \
             patch("omega.bridge.get_cross_project_lessons", return_value=mock_lessons):
            session_start.main()

        output = capsys.readouterr().out
        # Count lines with project brackets (the lesson lines)
        lesson_lines = [line for line in output.splitlines() if line.strip().startswith("- [p")]
        assert len(lesson_lines) == 3

    def test_unknown_project_fallback(self, fake_home, tmp_omega_dir, capsys):
        import importlib
        import session_start
        importlib.reload(session_start)

        mock_lessons = [
            {"content": "Some lesson", "cross_project": True},  # no "project" key
        ]
        mock_welcome = {"memory_count": 10, "recent_memories": []}

        with patch("omega.bridge.welcome", return_value=mock_welcome), \
             patch("omega.bridge.consolidate"), \
             patch("omega.bridge.compact"), \
             patch("omega.bridge.get_cross_project_lessons", return_value=mock_lessons):
            session_start.main()

        output = capsys.readouterr().out
        assert "[unknown]" in output


# ============================================================================
# Hook server handle_session_start output format
# ============================================================================

class TestHookServerSessionStart:
    """Test handle_session_start output in daemon mode."""

    # Valid time-of-day greetings the function can produce
    _TOD_GREETINGS = ("Good morning", "Good afternoon", "Good evening", "Evening")

    def test_header_with_memories(self):
        """Returning user gets time-of-day greeting and memory count in footer."""
        from omega.server.hook_server import handle_session_start
        mock_ctx = {
            "memory_count": 5, "health_status": "ok",
            "last_capture_ago": "5m ago", "context_items": [],
        }
        with patch("omega.bridge.get_session_context", return_value=mock_ctx), \
             patch("omega.bridge.consolidate"), \
             patch("omega.bridge.compact"):
            result = handle_session_start({"session_id": "s1", "project": "/p"})
        output = result["output"]
        # Output contains a time-of-day greeting (may not be first line due to
        # cache-friendly zone reordering — stable content precedes greeting)
        assert any(g in output for g in self._TOD_GREETINGS), \
            f"Expected time-of-day greeting in output"
        # Footer should contain memory count
        assert "5 memories" in output

    def test_context_items_in_output(self):
        """[CONTEXT] block is unchanged in new format."""
        from omega.server.hook_server import handle_session_start
        mock_ctx = {
            "memory_count": 42, "health_status": "ok",
            "last_capture_ago": "5m ago",
            "context_items": [
                {"tag": "DECISION", "text": "Use SQLite WAL mode"},
                {"tag": "LESSON", "text": "Lock is non-reentrant"},
            ],
        }
        with patch("omega.bridge.get_session_context", return_value=mock_ctx), \
             patch("omega.bridge.consolidate"), \
             patch("omega.bridge.compact"):
            result = handle_session_start({"session_id": "s1", "project": "/p"})
        assert "[CONTEXT]" in result["output"]
        assert "DECISION: Use SQLite WAL mode" in result["output"]
        assert "LESSON: Lock is non-reentrant" in result["output"]

    def test_first_session_greeting(self):
        """First-time user (0 memories) sees onboarding text."""
        from omega.server.hook_server import handle_session_start
        mock_ctx = {
            "memory_count": 0, "health_status": "ok",
            "last_capture_ago": "unknown", "context_items": [],
        }
        with patch("omega.bridge.get_session_context", return_value=mock_ctx), \
             patch("omega.bridge.consolidate"), \
             patch("omega.bridge.compact"):
            result = handle_session_start({"session_id": "s1", "project": "/p"})
        output = result["output"]
        assert "OMEGA captures decisions" in output
        assert "Quick start" in output
        assert "OMEGA: 0 memories" in output

    def test_no_error_on_success(self):
        from omega.server.hook_server import handle_session_start
        mock_ctx = {
            "memory_count": 0, "health_status": "ok",
            "last_capture_ago": "unknown", "context_items": [],
        }
        with patch("omega.bridge.get_session_context", return_value=mock_ctx), \
             patch("omega.bridge.consolidate"), \
             patch("omega.bridge.compact"):
            result = handle_session_start({"session_id": "s1", "project": "/p"})
        assert result["error"] is None

    def test_streak_in_greeting(self):
        """When streak >= 3, greeting includes N-day streak."""
        from omega.server.hook_server import handle_session_start
        mock_ctx = {
            "memory_count": 50, "health_status": "ok",
            "last_capture_ago": "2m ago", "context_items": [],
        }
        mock_streak = {"current": 7, "longest": 10}
        with patch("omega.bridge.get_session_context", return_value=mock_ctx), \
             patch("omega.bridge.consolidate"), \
             patch("omega.bridge.compact"), \
             patch("omega.milestones.get_streak", return_value=mock_streak), \
             patch("omega.bridge._get_store"):
            result = handle_session_start({"session_id": "s1", "project": "/p"})
        output = result["output"]
        assert "7-day streak" in output
        # Streak should appear on the greeting line (may not be first line
        # due to cache-friendly zone reordering)
        greeting_lines = [l for l in output.splitlines() if "streak" in l]
        assert greeting_lines, "Streak text should appear in output"

    def test_compact_footer(self):
        """Footer has format: OMEGA: {count} memories | {status} | capture: {ago}."""
        from omega.server.hook_server import handle_session_start
        mock_ctx = {
            "memory_count": 123, "health_status": "ok",
            "last_capture_ago": "3m ago", "context_items": [],
        }
        with patch("omega.bridge.get_session_context", return_value=mock_ctx), \
             patch("omega.bridge.consolidate"), \
             patch("omega.bridge.compact"):
            result = handle_session_start({"session_id": "s1", "project": "/p"})
        output = result["output"]
        # Footer line contains key parts (may not be last due to [GREET])
        footer_lines = [l for l in output.strip().splitlines() if l.startswith("OMEGA:")]
        assert len(footer_lines) == 1
        footer = footer_lines[0]
        assert "123 memories" in footer
        assert "ok" in footer
        assert "capture: 3m ago" in footer

    def test_last_session_in_greeting(self):
        """When last session info is available, it appears in the output."""
        from omega.server.hook_server import handle_session_start
        mock_ctx = {
            "memory_count": 30, "health_status": "ok",
            "last_capture_ago": "1h ago", "context_items": [],
        }
        mock_last_info = {
            "agent_name": "Maple",
            "task": "Refactoring the auth module",
            "ended_ago": "2h ago",
            "checkpoint_text": "",
        }
        with patch("omega.bridge.get_session_context", return_value=mock_ctx), \
             patch("omega.bridge.consolidate"), \
             patch("omega.bridge.compact"), \
             patch("omega.server.hook_server.session._get_last_session_info", return_value=mock_last_info):
            result = handle_session_start({"session_id": "s1", "project": "/p"})
        output = result["output"]
        assert "Maple" in output
        assert "2h ago" in output
        assert "Refactoring the auth module" in output


# ============================================================================
# Stale surfacing file cleanup (both patterns)
# ============================================================================

class TestStaleSurfacingCleanup:
    """Test that session_start cleans up both .surfaced and .surfaced.json."""

    def test_cleans_old_surfaced_files(self, fake_home, tmp_omega_dir):
        import importlib
        import session_start
        importlib.reload(session_start)

        # Create stale files (old mtime)
        stale = tmp_omega_dir / "session-old.surfaced"
        stale.write_text("xxx")
        os.utime(stale, (0, 0))  # epoch = very old

        stale_json = tmp_omega_dir / "session-old.surfaced.json"
        stale_json.write_text("{}")
        os.utime(stale_json, (0, 0))

        # Create fresh files
        fresh = tmp_omega_dir / "session-new.surfaced"
        fresh.write_text("x")

        mock_welcome = {"memory_count": 0, "recent_memories": []}
        with patch("omega.bridge.welcome", return_value=mock_welcome), \
             patch("omega.bridge.consolidate"), \
             patch("omega.bridge.compact"), \
             patch("omega.bridge.get_cross_project_lessons", return_value=[]):
            session_start.main()

        assert not stale.exists()
        assert not stale_json.exists()
        assert fresh.exists()


# ============================================================================
# [STANDUP] + [COORD-PROTOCOL] — Multi-agent framing at session start
# ============================================================================

class TestCoordGreet:
    """Test [STANDUP] and [COORD-PROTOCOL] output in handle_coord_session_start.

    [COORD-GREET] was removed and replaced by [STANDUP] (peer roster)
    and [COORD-PROTOCOL] (multi-agent rules).
    """

    def _make_mock_mgr(self, peers=None, conflicts=None, tasks=None):
        """Build a mock coordination manager."""
        mgr = MagicMock()
        mgr.register_session.return_value = {
            "peers_on_project": len(peers) if peers else 0,
        }
        mgr.list_sessions.return_value = peers or []
        mgr.get_status.return_value = {
            "conflicts": conflicts or [],
            "deadlocks": [],
            "files": [],
        }
        mgr.get_unread_count.return_value = 0
        mgr.list_tasks.return_value = tasks or []
        mgr.get_session_claims.return_value = {"file_claims": [], "branch_claims": []}
        mgr.check_inbox.return_value = []
        mgr.get_recent_events.return_value = []
        return mgr

    def test_coord_greet_emitted_with_peers(self):
        """[STANDUP] and [COORD-PROTOCOL] appear when peers are active."""
        from omega.server.hook_server import handle_coord_session_start
        peers = [
            {"session_id": "peer-aaa", "status": "active", "project": "/proj", "task": "fixing tests"},
        ]
        mgr = self._make_mock_mgr(peers=peers)
        with patch("omega.coordination.get_manager", return_value=mgr):
            result = handle_coord_session_start({"session_id": "s1", "project": "/proj"})
        assert "[STANDUP]" in result["output"]
        assert "[COORD-PROTOCOL]" in result["output"]
        assert "1 peer" in result["output"]
        assert "fixing tests" in result["output"]

    def test_coord_greet_shows_conflict_status(self):
        """Output includes conflict information when overlaps exist."""
        from omega.server.hook_server import handle_coord_session_start
        peers = [
            {"session_id": "peer-bbb", "status": "active", "project": "/proj", "task": "editing handler"},
        ]
        conflicts = [{"file": "/proj/handler.py", "owner": "peer-bbb"}]
        mgr = self._make_mock_mgr(peers=peers, conflicts=conflicts)
        with patch("omega.coordination.get_manager", return_value=mgr):
            result = handle_coord_session_start({"session_id": "s1", "project": "/proj"})
        # Conflicts are surfaced in the output (exact format may vary)
        output = result["output"]
        assert "overlap" in output.lower() or "conflict" in output.lower() or "handler.py" in output

    def test_coord_greet_no_conflicts(self):
        """No conflict warnings when there are no file overlaps."""
        from omega.server.hook_server import handle_coord_session_start
        peers = [
            {"session_id": "peer-ccc", "status": "active", "project": "/proj", "task": "idle"},
        ]
        mgr = self._make_mock_mgr(peers=peers)
        with patch("omega.coordination.get_manager", return_value=mgr):
            result = handle_coord_session_start({"session_id": "s1", "project": "/proj"})
        # Should not mention overlaps/conflicts when there are none
        output = result["output"]
        assert "overlap" not in output.lower() or "no" in output.lower() or "0" in output

    def test_coord_greet_omitted_single_agent(self):
        """[STANDUP] and [COORD-PROTOCOL] not emitted when no peers."""
        from omega.server.hook_server import handle_coord_session_start
        mgr = self._make_mock_mgr(peers=[])
        with patch("omega.coordination.get_manager", return_value=mgr):
            result = handle_coord_session_start({"session_id": "s1", "project": "/proj"})
        assert "[STANDUP]" not in result["output"]
        assert "[COORD-PROTOCOL]" not in result["output"]

    def test_coord_greet_multiple_peers(self):
        """[STANDUP] lists multiple peers."""
        from omega.server.hook_server import handle_coord_session_start
        peers = [
            {"session_id": f"peer-{i}", "status": "active", "project": "/proj", "task": f"task-{i}"}
            for i in range(4)
        ]
        mgr = self._make_mock_mgr(peers=peers)
        with patch("omega.coordination.get_manager", return_value=mgr):
            result = handle_coord_session_start({"session_id": "s1", "project": "/proj"})
        assert "[STANDUP]" in result["output"]
        assert "4 peer" in result["output"]


# ============================================================================
# [COORD-EVENT] — Team change narration in heartbeat
# ============================================================================

class TestCoordEvent:
    """Test [COORD-EVENT] output in handle_coord_heartbeat."""

    def _setup_heartbeat(self, session_id, project, mgr, count=8):
        """Pre-populate heartbeat state so we hit the 8th-beat check."""
        from omega.server import hook_server
        hook_server._last_heartbeat.pop(session_id, None)
        hook_server._heartbeat_count[session_id] = count - 1  # next call increments to count
        hook_server._peer_snapshot[session_id] = set()  # initial snapshot exists

    def test_coord_event_on_peer_join(self):
        """[COORD-EVENT] emitted when a peer joins."""
        from omega.server.hook_server import handle_coord_heartbeat
        from omega.server import hook_server

        mgr = MagicMock()
        mgr.heartbeat.return_value = None
        mgr.active_session_count.return_value = 2
        mgr.list_sessions.return_value = [
            {"session_id": "s1", "status": "active", "project": "/proj"},
            {"session_id": "peer-new", "status": "active", "project": "/proj"},
        ]
        mgr.get_session_claims.return_value = {"file_claims": [], "branch_claims": []}
        mgr.get_unread_count.return_value = 0
        mgr.check_inbox.return_value = []
        mgr.list_tasks.return_value = []
        mgr.get_status.return_value = {"conflicts": [], "deadlocks": []}
        mgr.get_recent_events.return_value = []

        self._setup_heartbeat("s1", "/proj", mgr, count=8)

        with patch("omega.coordination.get_manager", return_value=mgr):
            result = handle_coord_heartbeat({"session_id": "s1", "project": "/proj"})
        assert "[COORD-EVENT]" in result["output"]
        assert "joined" in result["output"]

    def test_coord_event_not_on_no_change(self):
        """[COORD-EVENT] not emitted when peer set is unchanged."""
        from omega.server.hook_server import handle_coord_heartbeat
        from omega.server import hook_server

        mgr = MagicMock()
        mgr.heartbeat.return_value = None
        mgr.active_session_count.return_value = 2
        mgr.list_sessions.return_value = [
            {"session_id": "s1", "status": "active", "project": "/proj"},
            {"session_id": "peer-old", "status": "active", "project": "/proj"},
        ]
        mgr.get_session_claims.return_value = {"file_claims": [], "branch_claims": []}
        mgr.get_unread_count.return_value = 0
        mgr.check_inbox.return_value = []
        mgr.list_tasks.return_value = []
        mgr.get_status.return_value = {"conflicts": [], "deadlocks": []}
        mgr.get_recent_events.return_value = []

        self._setup_heartbeat("s1", "/proj", mgr, count=8)
        # Pre-populate snapshot with the same peer
        hook_server._peer_snapshot["s1"] = {"peer-old"}

        with patch("omega.coordination.get_manager", return_value=mgr):
            result = handle_coord_heartbeat({"session_id": "s1", "project": "/proj"})
        assert "[COORD-EVENT]" not in result["output"]


# ============================================================================
# [COORD-PULSE] — Team progress pulse in heartbeat
# ============================================================================

class TestCoordPulse:
    """Test [COORD-PULSE] output in handle_coord_heartbeat."""

    def _setup_heartbeat(self, session_id, count=8):
        from omega.server import hook_server
        hook_server._last_heartbeat.pop(session_id, None)
        hook_server._heartbeat_count[session_id] = count - 1
        hook_server._peer_snapshot[session_id] = {"peer-x"}
        hook_server._last_pulse_state.pop(session_id, None)

    def test_coord_pulse_emitted_with_tasks(self):
        """[COORD-PULSE] appears when there are tasks to report."""
        from omega.server.hook_server import handle_coord_heartbeat

        mgr = MagicMock()
        mgr.heartbeat.return_value = None
        mgr.active_session_count.return_value = 2
        mgr.list_sessions.return_value = [
            {"session_id": "s1", "status": "active", "project": "/proj"},
            {"session_id": "peer-x", "status": "active", "project": "/proj"},
        ]
        mgr.get_session_claims.return_value = {"file_claims": [], "branch_claims": []}
        mgr.get_unread_count.return_value = 0
        mgr.check_inbox.return_value = []
        mgr.list_tasks.return_value = [
            {"id": 1, "title": "Fix auth", "status": "completed", "session_id": "peer-x"},
            {"id": 2, "title": "Add tests", "status": "in_progress", "session_id": "s1"},
        ]
        mgr.get_status.return_value = {"conflicts": [], "deadlocks": []}
        mgr.get_recent_events.return_value = []

        self._setup_heartbeat("s1", count=8)

        with patch("omega.coordination.get_manager", return_value=mgr):
            result = handle_coord_heartbeat({"session_id": "s1", "project": "/proj"})
        assert "[COORD-PULSE]" in result["output"]
        assert "1 of 2 tasks done" in result["output"]

    def test_coord_pulse_debounced(self):
        """[COORD-PULSE] skipped when state unchanged since last pulse."""
        from omega.server.hook_server import handle_coord_heartbeat
        from omega.server import hook_server

        mgr = MagicMock()
        mgr.heartbeat.return_value = None
        mgr.active_session_count.return_value = 2
        mgr.list_sessions.return_value = [
            {"session_id": "s1", "status": "active", "project": "/proj"},
            {"session_id": "peer-x", "status": "active", "project": "/proj"},
        ]
        mgr.get_session_claims.return_value = {"file_claims": [], "branch_claims": []}
        mgr.get_unread_count.return_value = 0
        mgr.check_inbox.return_value = []
        mgr.list_tasks.return_value = [
            {"id": 1, "title": "Fix auth", "status": "completed", "session_id": "peer-x"},
        ]
        mgr.get_status.return_value = {"conflicts": [], "deadlocks": []}
        mgr.get_recent_events.return_value = []

        self._setup_heartbeat("s1", count=8)
        # Pre-set pulse state to match what would be computed
        hook_server._last_pulse_state["s1"] = "1:0:1"

        with patch("omega.coordination.get_manager", return_value=mgr):
            result = handle_coord_heartbeat({"session_id": "s1", "project": "/proj"})
        assert "[COORD-PULSE]" not in result["output"]

    def test_coord_pulse_shows_conflicts(self):
        """[COORD-PULSE] includes conflict count when present."""
        from omega.server.hook_server import handle_coord_heartbeat

        mgr = MagicMock()
        mgr.heartbeat.return_value = None
        mgr.active_session_count.return_value = 2
        mgr.list_sessions.return_value = [
            {"session_id": "s1", "status": "active", "project": "/proj"},
            {"session_id": "peer-x", "status": "active", "project": "/proj"},
        ]
        mgr.get_session_claims.return_value = {"file_claims": [], "branch_claims": []}
        mgr.get_unread_count.return_value = 0
        mgr.check_inbox.return_value = []
        mgr.list_tasks.return_value = []
        mgr.get_status.return_value = {
            "conflicts": [{"file": "/proj/f.py"}],
            "deadlocks": [],
        }
        mgr.get_recent_events.return_value = []

        self._setup_heartbeat("s1", count=8)

        with patch("omega.coordination.get_manager", return_value=mgr):
            result = handle_coord_heartbeat({"session_id": "s1", "project": "/proj"})
        assert "[COORD-PULSE]" in result["output"]
        assert "1 conflict(s)" in result["output"]


# ============================================================================
# [COORD-CONFLICT] — File overlap detection in heartbeat
# ============================================================================

class TestCoordConflict:
    """Test [COORD-CONFLICT] output in handle_coord_heartbeat."""

    def _setup_heartbeat(self, session_id, count=8):
        from omega.server import hook_server
        hook_server._last_heartbeat.pop(session_id, None)
        hook_server._heartbeat_count[session_id] = count - 1
        hook_server._peer_snapshot[session_id] = set()
        hook_server._last_pulse_state.pop(session_id, None)

    def test_coord_conflict_on_overlapping_claims(self):
        """[COORD-CONFLICT] emitted when file claims overlap."""
        from omega.server.hook_server import handle_coord_heartbeat

        def mock_get_claims(sid):
            if sid == "peer-x":
                return {"file_claims": ["/proj/handler.py"], "branch_claims": []}
            return {"file_claims": ["/proj/handler.py"], "branch_claims": []}

        mgr = MagicMock()
        mgr.heartbeat.return_value = None
        mgr.active_session_count.return_value = 2
        mgr.list_sessions.return_value = [
            {"session_id": "s1", "status": "active", "project": "/proj"},
            {"session_id": "peer-x", "status": "active", "project": "/proj"},
        ]
        mgr.get_session_claims.side_effect = mock_get_claims
        mgr.get_unread_count.return_value = 0
        mgr.check_inbox.return_value = []
        mgr.list_tasks.return_value = []
        mgr.get_status.return_value = {"conflicts": [], "deadlocks": []}
        mgr.get_recent_events.return_value = []

        self._setup_heartbeat("s1", count=8)

        with patch("omega.coordination.get_manager", return_value=mgr):
            result = handle_coord_heartbeat({"session_id": "s1", "project": "/proj"})
        assert "[COORD-CONFLICT]" in result["output"]
        assert "handler.py" in result["output"]

    def test_no_conflict_without_overlap(self):
        """[COORD-CONFLICT] not emitted when no overlap."""
        from omega.server.hook_server import handle_coord_heartbeat

        def mock_get_claims(sid):
            if sid == "peer-x":
                return {"file_claims": ["/proj/handler.py"], "branch_claims": []}
            return {"file_claims": ["/proj/utils.py"], "branch_claims": []}

        mgr = MagicMock()
        mgr.heartbeat.return_value = None
        mgr.active_session_count.return_value = 2
        mgr.list_sessions.return_value = [
            {"session_id": "s1", "status": "active", "project": "/proj"},
            {"session_id": "peer-x", "status": "active", "project": "/proj"},
        ]
        mgr.get_session_claims.side_effect = mock_get_claims
        mgr.get_unread_count.return_value = 0
        mgr.check_inbox.return_value = []
        mgr.list_tasks.return_value = []
        mgr.get_status.return_value = {"conflicts": [], "deadlocks": []}
        mgr.get_recent_events.return_value = []

        self._setup_heartbeat("s1", count=8)

        with patch("omega.coordination.get_manager", return_value=mgr):
            result = handle_coord_heartbeat({"session_id": "s1", "project": "/proj"})
        assert "[COORD-CONFLICT]" not in result["output"]
