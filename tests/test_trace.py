"""Tests for session tracing: schema, capture, and query."""

import os
from pathlib import Path

import pytest
from omega.coordination import CoordinationManager
from omega.server.hook_server.trace import (
    handle_trace_capture,
    _classify_result_status,
    _call_counters,
    _next_call_index,
)


@pytest.fixture
def mgr(tmp_path):
    return CoordinationManager(str(tmp_path / "coord.db"), cloud_sync=False)


class TestTraceSchema:
    def test_coord_audit_has_trace_columns(self, mgr):
        """coord_audit should have latency_ms, call_index, result_status, input_size."""
        cursor = mgr._conn.execute("PRAGMA table_info(coord_audit)")
        columns = {row[1] for row in cursor.fetchall()}
        assert "latency_ms" in columns
        assert "call_index" in columns
        assert "result_status" in columns
        assert "input_size" in columns


class TestTraceLogAudit:
    def test_log_audit_with_trace_fields(self, mgr):
        """log_audit should accept and store trace fields."""
        mgr.log_audit(
            session_id="sess-1",
            tool_name="Edit",
            arguments={"file_path": "/tmp/test.py"},
            result_summary="ok",
            latency_ms=42,
            call_index=1,
            result_status="ok",
            input_size=256,
        )

        rows = mgr.query_audit(session_id="sess-1")  # query_audit flushes buffer
        assert len(rows) == 1
        assert rows[0]["latency_ms"] == 42
        assert rows[0]["call_index"] == 1
        assert rows[0]["result_status"] == "ok"
        assert rows[0]["input_size"] == 256

    def test_log_audit_without_trace_fields(self, mgr):
        """Existing callers that omit trace fields should still work."""
        mgr.log_audit(
            session_id="sess-2",
            tool_name="Read",
            arguments=None,
            result_summary="read ok",
        )

        rows = mgr.query_audit(session_id="sess-2")  # query_audit flushes buffer
        assert len(rows) == 1
        assert rows[0]["latency_ms"] is None
        assert rows[0]["call_index"] is None
        assert rows[0]["result_status"] == "ok"
        assert rows[0]["input_size"] is None


class TestTraceCaptureHandler:
    def test_basic_trace_capture(self):
        """handle_trace_capture should return a dict with no output (silent)."""
        payload = {
            "tool_name": "Edit",
            "tool_input": '{"file_path": "/tmp/test.py", "old_string": "a", "new_string": "b"}',
            "tool_output": "File edited successfully",
            "session_id": "sess-trace-1",
            "project": "/tmp/test-project",
        }
        result = handle_trace_capture(payload)
        assert isinstance(result, dict)

    def test_classifies_error_status(self):
        """Should detect error from Traceback in output."""
        assert _classify_result_status("Traceback (most recent call last):\n  ...") == "error"
        assert _classify_result_status("Error: file not found") == "error"
        assert _classify_result_status("exit code 1") == "error"
        assert _classify_result_status("Command timed out after 120s") == "timeout"
        assert _classify_result_status("File edited successfully") == "ok"
        assert _classify_result_status("") == "ok"

    def test_increments_call_index(self):
        """Sequential calls in the same session should increment call_index."""
        _call_counters.clear()
        assert _next_call_index("sess-a") == 1
        assert _next_call_index("sess-a") == 2
        assert _next_call_index("sess-b") == 1
        assert _next_call_index("sess-a") == 3


class TestTraceWiring:
    def test_trace_capture_in_dispatch_table(self):
        """trace_capture should be in the hook dispatch table."""
        from omega.server.hook_server.core import HOOK_HANDLERS

        assert "trace_capture" in HOOK_HANDLERS

    def test_trace_capture_in_fallback_scripts(self):
        """trace_capture should be in fast_hook.py fallback map."""
        import importlib
        import sys

        hooks_dir = str(Path(__file__).parent.parent / "hooks")
        if hooks_dir not in sys.path:
            sys.path.insert(0, hooks_dir)
        import fast_hook

        importlib.reload(fast_hook)
        assert "trace_capture" in fast_hook._FALLBACK_SCRIPTS


class TestTraceQuery:
    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path):
        """Set up a fresh store and coordination manager."""
        import omega.coordination as _coord

        os.environ["OMEGA_HOME"] = str(tmp_path / ".omega")
        (tmp_path / ".omega").mkdir()
        os.environ["OMEGA_ENCRYPT"] = "0"
        from omega.bridge import reset_memory
        reset_memory()
        # Reset coordination singleton so get_instance() creates a fresh one
        _coord.close_manager()
        yield
        _coord.close_manager()
        reset_memory()
        os.environ.pop("OMEGA_HOME", None)
        os.environ.pop("OMEGA_ENCRYPT", None)

    @pytest.mark.asyncio
    async def test_trace_mode_returns_timeline(self):
        """omega_query mode=trace should return formatted session timeline."""
        from omega.server.handlers import HANDLERS

        # Insert some trace rows
        from omega.coordination import CoordinationManager
        mgr = CoordinationManager.get_instance()
        mgr.log_audit(session_id="sess-t", tool_name="Read", call_index=1, result_status="ok", input_size=100)
        mgr.log_audit(session_id="sess-t", tool_name="Edit", call_index=2, result_status="ok", input_size=500)
        mgr.log_audit(session_id="sess-t", tool_name="Bash", call_index=3, result_status="error", input_size=50)

        result = await HANDLERS["omega_query"]({"mode": "trace", "session_id": "sess-t"})
        text = result["content"][0]["text"]
        assert "3 tool calls" in text
        assert "Read" in text
        assert "Edit" in text
        assert "Bash" in text
        assert "error" in text

    @pytest.mark.asyncio
    async def test_trace_mode_requires_session_id(self):
        """mode=trace without session_id should return an error."""
        from omega.server.handlers import HANDLERS

        result = await HANDLERS["omega_query"]({"mode": "trace"})
        assert result.get("isError", False)


class TestTraceIntegration:
    """End-to-end: capture via hook handler -> query back via audit -> verify."""

    def test_full_trace_pipeline(self, mgr):
        """Trace capture -> query_audit -> verify ordering and status."""
        from unittest.mock import patch

        _call_counters.clear()

        # Mock the singleton so trace handler writes to our test mgr
        with patch("omega.coordination.CoordinationManager.get_instance", return_value=mgr):

            for tool, output in [
                ("Read", "file contents here"),
                ("Edit", "File edited successfully"),
                ("Bash", "Traceback (most recent call last):\n  Error"),
            ]:
                handle_trace_capture({
                    "tool_name": tool,
                    "tool_input": f'{{"arg": "value"}}',
                    "tool_output": output,
                    "session_id": "sess-integ",
                    "project": "/tmp/test",
                })

        rows = mgr.query_audit(session_id="sess-integ")
        assert len(rows) == 3

        # query_audit returns DESC order, reverse for chronological
        rows.sort(key=lambda r: r.get("call_index") or 0)

        assert rows[0]["tool_name"] == "Read"
        assert rows[0]["call_index"] == 1
        assert rows[0]["result_status"] == "ok"

        assert rows[1]["tool_name"] == "Edit"
        assert rows[1]["call_index"] == 2
        assert rows[1]["result_status"] == "ok"

        assert rows[2]["tool_name"] == "Bash"
        assert rows[2]["call_index"] == 3
        assert rows[2]["result_status"] == "error"
