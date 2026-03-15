"""Tests for OMEGA security hardening measures."""

import json
import stat
import time
from pathlib import Path

import pytest

from omega.exceptions import StorageError


# ---------------------------------------------------------------------------
# Phase 1: secure_connect
# ---------------------------------------------------------------------------


class TestSecureConnect:
    """Test secure_connect() DB file permissions."""

    def test_creates_db_with_600_permissions(self, tmp_path):
        from omega.crypto import secure_connect

        db_path = tmp_path / "test.db"
        conn = secure_connect(db_path)
        conn.close()

        mode = db_path.stat().st_mode
        # Owner read/write only, no group/other
        assert mode & stat.S_IRWXG == 0, f"Group perms should be 0, got {oct(mode)}"
        assert mode & stat.S_IRWXO == 0, f"Other perms should be 0, got {oct(mode)}"
        assert mode & stat.S_IRUSR, "Owner should have read"
        assert mode & stat.S_IWUSR, "Owner should have write"

    def test_fixes_existing_permissive_db(self, tmp_path):
        from omega.crypto import secure_connect

        db_path = tmp_path / "test.db"
        # Create with permissive mode
        db_path.touch(mode=0o644)
        assert db_path.stat().st_mode & stat.S_IROTH  # world-readable

        conn = secure_connect(db_path)
        conn.close()

        mode = db_path.stat().st_mode
        assert mode & stat.S_IRWXG == 0, f"Group perms should be fixed, got {oct(mode)}"
        assert mode & stat.S_IRWXO == 0, f"Other perms should be fixed, got {oct(mode)}"

    def test_returns_working_connection(self, tmp_path):
        from omega.crypto import secure_connect

        db_path = tmp_path / "test.db"
        conn = secure_connect(db_path)
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.execute("INSERT INTO test VALUES (1)")
        result = conn.execute("SELECT id FROM test").fetchone()
        assert result[0] == 1
        conn.close()

    def test_passes_kwargs_through(self, tmp_path):
        from omega.crypto import secure_connect

        db_path = tmp_path / "test.db"
        conn = secure_connect(db_path, timeout=10, check_same_thread=False)
        conn.execute("CREATE TABLE test (id INTEGER)")
        conn.close()


# ---------------------------------------------------------------------------
# Phase 2: Export security
# ---------------------------------------------------------------------------


class TestExportSecurity:
    """Test export file permissions and encryption warnings."""

    def test_export_file_has_600_permissions(self, tmp_path):
        from omega.sqlite_store import SQLiteStore

        store = SQLiteStore(db_path=tmp_path / "test.db")
        store.store(content="test memory", session_id="s1")

        export_path = tmp_path / "export.json"
        store.export_to_file(export_path)

        mode = export_path.stat().st_mode
        assert mode & stat.S_IRWXG == 0, f"Group perms should be 0, got {oct(mode)}"
        assert mode & stat.S_IRWXO == 0, f"Other perms should be 0, got {oct(mode)}"

    def test_export_content_is_valid_json(self, tmp_path, monkeypatch):
        from omega.sqlite_store import SQLiteStore

        # Disable encryption so the export file is plain JSON
        monkeypatch.setenv("OMEGA_ENCRYPT", "0")

        store = SQLiteStore(db_path=tmp_path / "test.db")
        store.store(content="test memory", session_id="s1")

        export_path = tmp_path / "export.json"
        result = store.export_to_file(export_path)

        data = json.loads(export_path.read_text())
        assert data["node_count"] == 1
        assert result["node_count"] == 1


# ---------------------------------------------------------------------------
# Phase 4: Rate limiting
# ---------------------------------------------------------------------------


class TestRateLimiting:
    """Test MCP server rate limiting."""

    def test_normal_usage_allowed(self):
        from omega.server.mcp_server import _check_rate_limit, _global_timestamps, _write_timestamps

        # Clear state
        _global_timestamps.clear()
        _write_timestamps.clear()

        # Normal call should pass
        result = _check_rate_limit("omega_query")
        assert result is None

    def test_global_rate_limit_exceeded(self):
        from omega.server.mcp_server import (
            _check_rate_limit,
            _global_timestamps,
            _write_timestamps,
            _GLOBAL_RATE_LIMIT,
        )

        _global_timestamps.clear()
        _write_timestamps.clear()

        # Fill up the global bucket
        now = time.monotonic()
        for _ in range(_GLOBAL_RATE_LIMIT):
            _global_timestamps.append(now)

        result = _check_rate_limit("omega_query")
        assert result is not None
        assert "Rate limit exceeded" in result

        # Clean up
        _global_timestamps.clear()

    def test_write_rate_limit_exceeded(self):
        from omega.server.mcp_server import (
            _check_rate_limit,
            _global_timestamps,
            _write_timestamps,
            _WRITE_RATE_LIMIT,
        )

        _global_timestamps.clear()
        _write_timestamps.clear()

        # Fill up the write bucket
        now = time.monotonic()
        for _ in range(_WRITE_RATE_LIMIT):
            _write_timestamps.append(now)

        result = _check_rate_limit("omega_store")
        assert result is not None
        assert "write calls" in result

        # Clean up
        _global_timestamps.clear()
        _write_timestamps.clear()

    def test_read_tool_not_affected_by_write_limit(self):
        from omega.server.mcp_server import (
            _check_rate_limit,
            _global_timestamps,
            _write_timestamps,
            _WRITE_RATE_LIMIT,
        )

        _global_timestamps.clear()
        _write_timestamps.clear()

        # Fill up write bucket
        now = time.monotonic()
        for _ in range(_WRITE_RATE_LIMIT):
            _write_timestamps.append(now)

        # Read tool should still pass (not a write tool)
        result = _check_rate_limit("omega_query")
        assert result is None

        # Clean up
        _global_timestamps.clear()
        _write_timestamps.clear()

    def test_all_write_tools_are_rate_limited(self):
        """Every mutation tool must be in _WRITE_TOOLS. Prevents drift."""
        from omega.server.mcp_server import _WRITE_TOOLS

        # Exhaustive list of read-only tools (safe to exclude from write limiting)
        READ_ONLY_TOOLS = frozenset({
            # Core read tools
            "omega_query", "omega_welcome", "omega_protocol",
            "omega_resume_task", "omega_stats", "omega_profile",
            # Consultation tools (external API calls, no OMEGA state writes)
            "omega_consult_gpt", "omega_consult_claude",
            # Coord read tools
            "omega_sessions_list", "omega_file_check", "omega_intent_check",
            "omega_coord_status", "omega_session_recover", "omega_task_next",
            "omega_tasks_list", "omega_audit", "omega_inbox",
            "omega_find_agents", "omega_git_events", "omega_branch_check",
            "omega_coord_metrics", "omega_action_check", "omega_drift_check",
            "omega_smart_route", "omega_decision_query",
        })

        # Get all registered tool names
        from omega.server.tool_schemas import TOOL_SCHEMAS
        from omega.server.coord_schemas import COORD_TOOL_SCHEMAS
        all_tool_names = {t["name"] for t in TOOL_SCHEMAS} | {t["name"] for t in COORD_TOOL_SCHEMAS}

        # Every tool must be classified as either read-only or write
        unclassified = all_tool_names - _WRITE_TOOLS - READ_ONLY_TOOLS
        assert not unclassified, (
            f"Tools not classified as read or write (add to _WRITE_TOOLS or READ_ONLY_TOOLS): "
            f"{sorted(unclassified)}"
        )


# ---------------------------------------------------------------------------
# Phase 5: Input size limits
# ---------------------------------------------------------------------------


class TestNodeCountLimit:
    """Test store() rejects at node capacity."""

    def test_store_rejects_at_capacity(self, tmp_path):
        from omega.sqlite_store import SQLiteStore

        store = SQLiteStore(db_path=tmp_path / "test.db")
        # Set a very low limit for testing
        store._MAX_NODES = 2
        store.store(content="memory one", session_id="s1", skip_inference=True)
        store.store(content="memory two", session_id="s1", skip_inference=True)

        with pytest.raises(StorageError, match="Node count.*limit"):
            store.store(content="memory three", session_id="s1", skip_inference=True)


class TestContentSizeLimit:
    """Test store() rejects oversized content."""

    def test_oversized_content_rejected(self, tmp_path):
        from omega.sqlite_store import SQLiteStore

        store = SQLiteStore(db_path=tmp_path / "test.db")
        store._MAX_CONTENT_SIZE = 100  # Very low limit for testing

        with pytest.raises(StorageError, match="Content size.*exceeds limit"):
            store.store(content="x" * 101, session_id="s1", skip_inference=True)

    def test_content_within_limit_accepted(self, tmp_path):
        from omega.sqlite_store import SQLiteStore

        store = SQLiteStore(db_path=tmp_path / "test.db")
        store._MAX_CONTENT_SIZE = 100

        node_id = store.store(content="x" * 99, session_id="s1", skip_inference=True)
        assert node_id


class TestDocumentSizeLimit:
    """Test knowledge engine document size limit."""

    def test_oversized_document_rejected(self, tmp_path):
        from omega.knowledge.engine import KnowledgeBase

        kb = KnowledgeBase(db_path=tmp_path / "test.db")
        kb.MAX_DOCUMENT_SIZE_MB = 0  # 0 MB = reject everything

        # Create a small text file
        doc_path = tmp_path / "test.txt"
        doc_path.write_text("Some content that exceeds 0 MB limit")

        result = kb.ingest(str(doc_path))
        assert "exceeds limit" in result


# ---------------------------------------------------------------------------
# Phase 6: Log file permissions
# ---------------------------------------------------------------------------


class TestLogFilePermissions:
    """Test that log files are created with 0o600."""

    def test_hook_server_log_permissions(self, tmp_path):
        """Test _secure_append creates files with 0o600."""
        from omega.server.hook_server import _secure_append

        log_path = tmp_path / "test.log"
        _secure_append(log_path, "test log entry\n")

        assert log_path.exists()
        mode = log_path.stat().st_mode
        assert mode & stat.S_IRWXG == 0, f"Group perms should be 0, got {oct(mode)}"
        assert mode & stat.S_IRWXO == 0, f"Other perms should be 0, got {oct(mode)}"

    def test_secure_append_appends(self, tmp_path):
        """Test _secure_append actually appends (doesn't truncate)."""
        from omega.server.hook_server import _secure_append

        log_path = tmp_path / "test.log"
        _secure_append(log_path, "line 1\n")
        _secure_append(log_path, "line 2\n")

        content = log_path.read_text()
        assert "line 1" in content
        assert "line 2" in content


# ---------------------------------------------------------------------------
# Phase 3: Supabase URL removal (static check)
# ---------------------------------------------------------------------------


class TestSupabaseUrlRemoved:
    """Verify hardcoded Supabase URL was removed."""

    def test_no_hardcoded_url_in_supabase_ts(self):
        supabase_ts = Path(__file__).parent.parent / "web" / "src" / "supabase.ts"
        if not supabase_ts.exists():
            pytest.skip("web/src/supabase.ts not found")
        content = supabase_ts.read_text()
        assert "eczfuktgqqejtwwabihc" not in content, "Hardcoded Supabase URL should be removed"

    def test_env_example_has_placeholder(self):
        env_example = Path(__file__).parent.parent / "web" / ".env.example"
        if not env_example.exists():
            pytest.skip("web/.env.example not found")
        content = env_example.read_text()
        assert "your-project-id" in content, ".env.example should have placeholder URL"
        assert "eczfuktgqqejtwwabihc" not in content, "Real project ID should be removed"


# ---------------------------------------------------------------------------
# Phase 7: Coordination handler input validation
# ---------------------------------------------------------------------------


class TestCoordHandlerValidation:
    """Test that coord handlers reject malicious session_ids."""

    @pytest.mark.asyncio
    async def test_session_register_rejects_path_traversal(self):
        from omega.server.coord_handlers import handle_session_register

        result = await handle_session_register({"session_id": "../../../etc/passwd"})
        assert result.get("isError"), f"Should reject path traversal, got: {result}"

    @pytest.mark.asyncio
    async def test_file_claim_rejects_path_traversal(self):
        from omega.server.coord_handlers import handle_file_claim

        result = await handle_file_claim({
            "session_id": "../../etc/shadow",
            "file_path": "/tmp/test.py",
        })
        assert result.get("isError"), f"Should reject path traversal, got: {result}"

    @pytest.mark.asyncio
    async def test_send_message_rejects_invalid_session(self):
        from omega.server.coord_handlers import handle_send_message

        result = await handle_send_message({
            "session_id": "valid-session",
            "to_session_id": "$(whoami)",
            "content": "hello",
        })
        assert result.get("isError"), f"Should reject shell metachar, got: {result}"

    @pytest.mark.asyncio
    async def test_task_create_rejects_null_byte(self):
        from omega.server.coord_handlers import handle_task_create

        result = await handle_task_create({
            "session_id": "/etc/passwd\x00",
            "title": "test",
        })
        assert result.get("isError"), f"Should reject null byte, got: {result}"

    @pytest.mark.asyncio
    async def test_valid_session_id_not_rejected_by_validation(self):
        from omega.server.coord_handlers import handle_session_register

        result = await handle_session_register({"session_id": "abc-123.test_session"})
        # Should either succeed or fail for non-validation reasons
        if result.get("isError"):
            text = result["content"][0]["text"].lower()
            assert "invalid session_id" not in text, "Valid session_id should not be rejected by validation"
