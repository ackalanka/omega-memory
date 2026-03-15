"""Tests for OMEGA Pre-File Guard — real enforcement of file claims.

Covers: blocking, self-claim, TTL expiry, force-claim, fail-open, cleanup.
"""
import pytest
from datetime import datetime, timedelta, timezone


class TestCheckFileTTL:
    """check_file() should be TTL-aware."""

    def test_active_claim_is_visible(self, coord_mgr):
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.claim_file("sess-A", "/proj/foo.py")
        info = coord_mgr.check_file("/proj/foo.py")
        assert info["claimed"] is True
        assert info["session_id"] == "sess-A"

    def test_unclaimed_file(self, coord_mgr):
        info = coord_mgr.check_file("/proj/bar.py")
        assert info["claimed"] is False

    def test_expired_claim_treated_as_unclaimed(self, coord_mgr):
        """A claim with last_activity older than CLAIM_TTL_SECONDS should auto-expire."""
        from omega.coordination import CLAIM_TTL_SECONDS
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.claim_file("sess-A", "/proj/foo.py")

        # Backdate the last_activity to simulate expiry
        expired_time = (datetime.now(timezone.utc) - timedelta(seconds=CLAIM_TTL_SECONDS + 60)).isoformat()
        coord_mgr._conn.execute(
            "UPDATE coord_file_claims SET last_activity = ? WHERE file_path = ?",
            (expired_time, "/proj/foo.py")
        )
        coord_mgr._conn.commit()

        info = coord_mgr.check_file("/proj/foo.py")
        assert info["claimed"] is False
        assert info.get("expired_claim") is True

    def test_claim_refresh_resets_ttl(self, coord_mgr):
        """Re-claiming (refresh) should reset last_activity, keeping claim alive."""
        from omega.coordination import CLAIM_TTL_SECONDS
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.claim_file("sess-A", "/proj/foo.py")

        # Backdate to near-expiry
        near_expiry = (datetime.now(timezone.utc) - timedelta(seconds=CLAIM_TTL_SECONDS - 30)).isoformat()
        coord_mgr._conn.execute(
            "UPDATE coord_file_claims SET last_activity = ? WHERE file_path = ?",
            (near_expiry, "/proj/foo.py")
        )
        coord_mgr._conn.commit()

        # Refresh the claim
        result = coord_mgr.claim_file("sess-A", "/proj/foo.py", task="still editing")
        assert result["success"] is True
        assert result.get("refreshed") is True

        # Now check — should still be claimed (refreshed last_activity)
        info = coord_mgr.check_file("/proj/foo.py")
        assert info["claimed"] is True


class TestClaimFileForce:
    """claim_file(force=True) should override existing claims."""

    def test_force_claim_overrides(self, coord_mgr):
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.register_session("sess-B", pid=2, project="/proj")
        coord_mgr.claim_file("sess-A", "/proj/foo.py", task="editing")

        result = coord_mgr.claim_file("sess-B", "/proj/foo.py", task="urgent fix", force=True)
        assert result["success"] is True
        assert result["force_override"] is True
        assert result["previous_owner"] == "sess-A"

        # Verify ownership transferred
        info = coord_mgr.check_file("/proj/foo.py")
        assert info["session_id"] == "sess-B"

    def test_force_claim_is_audited(self, coord_mgr):
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.register_session("sess-B", pid=2, project="/proj")
        coord_mgr.claim_file("sess-A", "/proj/foo.py")
        coord_mgr.claim_file("sess-B", "/proj/foo.py", force=True)

        # Check audit log
        entries = coord_mgr.query_audit(tool_name="file_claim_force")
        assert len(entries) >= 1
        assert entries[0]["session_id"] == "sess-B"
        assert "foo.py" in entries[0].get("result_summary", "")

    def test_no_force_returns_conflict(self, coord_mgr):
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.register_session("sess-B", pid=2, project="/proj")
        coord_mgr.claim_file("sess-A", "/proj/foo.py")

        result = coord_mgr.claim_file("sess-B", "/proj/foo.py")
        assert result["success"] is False
        assert result["conflict"] is True
        assert result["claimed_by"] == "sess-A"

    def test_claim_file_expired_claim_auto_replaced(self, coord_mgr):
        """An expired claim should be silently replaced without force."""
        from omega.coordination import CLAIM_TTL_SECONDS
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.register_session("sess-B", pid=2, project="/proj")
        coord_mgr.claim_file("sess-A", "/proj/foo.py")

        # Backdate to expired
        expired_time = (datetime.now(timezone.utc) - timedelta(seconds=CLAIM_TTL_SECONDS + 60)).isoformat()
        coord_mgr._conn.execute(
            "UPDATE coord_file_claims SET last_activity = ? WHERE file_path = ?",
            (expired_time, "/proj/foo.py")
        )
        coord_mgr._conn.commit()

        result = coord_mgr.claim_file("sess-B", "/proj/foo.py", task="new work")
        assert result["success"] is True
        assert result.get("expired_claim_replaced") is True

        info = coord_mgr.check_file("/proj/foo.py")
        assert info["session_id"] == "sess-B"


class TestCleanExpiredClaims:
    """_clean_expired_claims() should remove old claims in periodic cleanup."""

    def test_clean_removes_expired(self, coord_mgr):
        from omega.coordination import CLAIM_TTL_SECONDS
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.claim_file("sess-A", "/proj/a.py")
        coord_mgr.claim_file("sess-A", "/proj/b.py")

        # Expire one claim
        expired_time = (datetime.now(timezone.utc) - timedelta(seconds=CLAIM_TTL_SECONDS + 60)).isoformat()
        coord_mgr._conn.execute(
            "UPDATE coord_file_claims SET last_activity = ? WHERE file_path = ?",
            (expired_time, "/proj/a.py")
        )
        coord_mgr._conn.commit()

        with coord_mgr._lock:
            removed = coord_mgr._clean_expired_claims()
            coord_mgr._conn.commit()

        assert len(removed) == 1
        # a.py should be gone, b.py should remain
        assert coord_mgr.check_file("/proj/a.py")["claimed"] is False
        assert coord_mgr.check_file("/proj/b.py")["claimed"] is True

    def test_clean_preserves_active(self, coord_mgr):
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.claim_file("sess-A", "/proj/active.py")

        with coord_mgr._lock:
            removed = coord_mgr._clean_expired_claims()
            coord_mgr._conn.commit()

        assert len(removed) == 0
        assert coord_mgr.check_file("/proj/active.py")["claimed"] is True


class TestPreFileGuardHook:
    """Tests for the hook_server daemon handler handle_pre_file_guard."""

    def test_blocks_when_claimed_by_other(self, coord_mgr, monkeypatch):
        """Should return exit_code=2 when file is claimed by another session."""
        from omega.server.hook_server import handle_pre_file_guard
        import omega.coordination as coord_mod

        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.claim_file("sess-A", "/proj/foo.py", task="editing")

        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        payload = {
            "tool_name": "Edit",
            "session_id": "sess-B",
            "tool_input": '{"file_path": "/proj/foo.py"}',
        }
        result = handle_pre_file_guard(payload)
        assert result.get("exit_code") == 2
        assert "[FILE-GUARD] BLOCKED" in result.get("output", "")

    def test_allows_self_claimed_file(self, coord_mgr, monkeypatch):
        """Should allow if I own the claim."""
        from omega.server.hook_server import handle_pre_file_guard
        import omega.coordination as coord_mod

        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.claim_file("sess-A", "/proj/foo.py")

        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        payload = {
            "tool_name": "Edit",
            "session_id": "sess-A",
            "tool_input": '{"file_path": "/proj/foo.py"}',
        }
        result = handle_pre_file_guard(payload)
        assert result.get("exit_code") is None
        assert result.get("output", "") == ""

    def test_allows_unclaimed_file(self, coord_mgr, monkeypatch):
        """Should allow if file has no claim."""
        from omega.server.hook_server import handle_pre_file_guard
        import omega.coordination as coord_mod

        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        payload = {
            "tool_name": "Edit",
            "session_id": "sess-A",
            "tool_input": '{"file_path": "/proj/new.py"}',
        }
        result = handle_pre_file_guard(payload)
        assert result.get("exit_code") is None
        assert result.get("output", "") == ""

    def test_skips_non_edit_tools(self, coord_mgr, monkeypatch):
        """Should skip tools that aren't Edit/Write/NotebookEdit."""
        from omega.server.hook_server import handle_pre_file_guard

        payload = {
            "tool_name": "Bash",
            "session_id": "sess-A",
            "tool_input": '{"command": "ls"}',
        }
        result = handle_pre_file_guard(payload)
        assert result.get("exit_code") is None

    def test_skips_when_no_session_id(self, coord_mgr, monkeypatch):
        """No session = single-agent mode — no enforcement."""
        from omega.server.hook_server import handle_pre_file_guard

        payload = {
            "tool_name": "Edit",
            "session_id": "",
            "tool_input": '{"file_path": "/proj/foo.py"}',
        }
        result = handle_pre_file_guard(payload)
        assert result.get("exit_code") is None

    def test_fail_open_on_import_error(self, monkeypatch):
        """Should fail-open if omega.coordination can't be imported."""
        from omega.server.hook_server import handle_pre_file_guard
        import omega.server.hook_server.guards as guards_mod

        def mock_get_manager():
            raise ImportError("no module")

        import omega.coordination as coord_mod
        monkeypatch.setattr(coord_mod, "get_manager", mock_get_manager)

        # Suppress _log_hook_error on guards module (where it's actually called)
        monkeypatch.setattr(guards_mod, "_log_hook_error", lambda *a, **kw: None)

        # Monkey-patch the module-level coordination import
        import builtins
        real_import = builtins.__import__
        def mock_import(name, *args, **kwargs):
            if name == "omega.coordination":
                raise ImportError("mocked")
            return real_import(name, *args, **kwargs)

        payload = {
            "tool_name": "Edit",
            "session_id": "sess-A",
            "tool_input": '{"file_path": "/proj/foo.py"}',
        }

        monkeypatch.setattr(builtins, "__import__", mock_import)
        result = handle_pre_file_guard(payload)
        assert result.get("exit_code") is None  # Fail-open

    def test_fail_open_on_database_error(self, coord_mgr, monkeypatch):
        """Should fail-open if database query fails."""
        from omega.server.hook_server import handle_pre_file_guard
        import omega.server.hook_server.guards as guards_mod
        import omega.coordination as coord_mod

        # Suppress _log_hook_error on guards module (where it's actually called)
        monkeypatch.setattr(guards_mod, "_log_hook_error", lambda *a, **kw: None)

        # Close the DB to force an error on next query
        coord_mgr._conn.close()
        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        payload = {
            "tool_name": "Edit",
            "session_id": "sess-A",
            "tool_input": '{"file_path": "/proj/foo.py"}',
        }
        result = handle_pre_file_guard(payload)
        assert result.get("exit_code") is None  # Fail-open

    def test_handles_notebook_path(self, coord_mgr, monkeypatch):
        """Should extract notebook_path for NotebookEdit."""
        from omega.server.hook_server import handle_pre_file_guard
        import omega.coordination as coord_mod

        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.claim_file("sess-A", "/proj/notebook.ipynb", task="editing")

        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        payload = {
            "tool_name": "NotebookEdit",
            "session_id": "sess-B",
            "tool_input": '{"notebook_path": "/proj/notebook.ipynb"}',
        }
        result = handle_pre_file_guard(payload)
        assert result.get("exit_code") == 2
        assert "[FILE-GUARD] BLOCKED" in result.get("output", "")

    def test_expired_claim_allows_edit(self, coord_mgr, monkeypatch):
        """An expired claim should not block the edit."""
        from omega.server.hook_server import handle_pre_file_guard
        from omega.coordination import CLAIM_TTL_SECONDS
        import omega.coordination as coord_mod

        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.claim_file("sess-A", "/proj/foo.py")

        # Backdate to expired
        expired_time = (datetime.now(timezone.utc) - timedelta(seconds=CLAIM_TTL_SECONDS + 60)).isoformat()
        coord_mgr._conn.execute(
            "UPDATE coord_file_claims SET last_activity = ? WHERE file_path = ?",
            (expired_time, "/proj/foo.py")
        )
        coord_mgr._conn.commit()

        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        payload = {
            "tool_name": "Edit",
            "session_id": "sess-B",
            "tool_input": '{"file_path": "/proj/foo.py"}',
        }
        result = handle_pre_file_guard(payload)
        assert result.get("exit_code") is None  # Allowed — claim expired


class TestMCPForceClaim:
    """Test force-claim via MCP handler."""

    @pytest.mark.asyncio
    async def test_handle_file_claim_force(self, coord_mgr, monkeypatch):
        from omega.server.coord_handlers import handle_file_claim
        import omega.coordination as coord_mod

        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.register_session("sess-B", pid=2, project="/proj")
        coord_mgr.claim_file("sess-A", "/proj/foo.py", task="editing")

        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        result = await handle_file_claim({
            "session_id": "sess-B",
            "file_path": "/proj/foo.py",
            "task": "urgent fix",
            "force": True,
        })

        text = result["content"][0]["text"]
        assert "force-override" in text
        assert "sess-A" in text

    @pytest.mark.asyncio
    async def test_handle_file_claim_no_force_conflict(self, coord_mgr, monkeypatch):
        from omega.server.coord_handlers import handle_file_claim
        import omega.coordination as coord_mod

        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.register_session("sess-B", pid=2, project="/proj")
        coord_mgr.claim_file("sess-A", "/proj/foo.py")

        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        result = await handle_file_claim({
            "session_id": "sess-B",
            "file_path": "/proj/foo.py",
        })

        text = result["content"][0]["text"]
        assert "CONFLICT" in text
        assert "force=true" in text
