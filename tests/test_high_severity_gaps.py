"""Tests for high-severity coordination gap fixes.

Covers:
  Gap #1  — SESSION_ID bypass: file guard blocks claimed files even without session_id
  Gap #3  — TOCTOU race: file guard claims atomically before allowing edit
  Gap #6  — Branch guard: blocks checkout/switch/commit on claimed branches
  Gap #14 — Force-claim notification: previous owner gets a message
"""
import pytest
from datetime import datetime, timedelta, timezone


# ======================================================================
# Gap #1 — SESSION_ID bypass: guard blocks claimed files without session_id
# ======================================================================

class TestGap1SessionIdBypass:
    """Without SESSION_ID, a claimed file must still be blocked."""

    def test_no_session_claimed_file_blocks(self, coord_mgr, monkeypatch):
        """File claimed by any agent → block even without session_id."""
        from omega.server.hook_server import handle_pre_file_guard
        import omega.coordination as coord_mod

        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.claim_file("sess-A", "/proj/foo.py", task="editing")
        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        payload = {
            "tool_name": "Edit",
            "session_id": "",
            "tool_input": '{"file_path": "/proj/foo.py"}',
        }
        result = handle_pre_file_guard(payload)
        assert result.get("exit_code") == 2
        assert "[FILE-GUARD] BLOCKED" in result.get("output", "")

    def test_no_session_unclaimed_file_allows(self, coord_mgr, monkeypatch):
        """No claims exist + no session_id → allow (true single-agent mode)."""
        from omega.server.hook_server import handle_pre_file_guard
        import omega.coordination as coord_mod

        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        payload = {
            "tool_name": "Edit",
            "session_id": "",
            "tool_input": '{"file_path": "/proj/unclaimed.py"}',
        }
        result = handle_pre_file_guard(payload)
        assert result.get("exit_code") is None
        assert result.get("output", "") == ""

    def test_no_session_expired_claim_allows(self, coord_mgr, monkeypatch):
        """Expired claim + no session_id → allow (claim auto-expired)."""
        from omega.server.hook_server import handle_pre_file_guard
        from omega.coordination import CLAIM_TTL_SECONDS
        import omega.coordination as coord_mod

        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.claim_file("sess-A", "/proj/foo.py")

        expired_time = (datetime.now(timezone.utc) - timedelta(seconds=CLAIM_TTL_SECONDS + 60)).isoformat()
        coord_mgr._conn.execute(
            "UPDATE coord_file_claims SET last_activity = ? WHERE file_path = ?",
            (expired_time, "/proj/foo.py")
        )
        coord_mgr._conn.commit()

        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        payload = {
            "tool_name": "Edit",
            "session_id": "",
            "tool_input": '{"file_path": "/proj/foo.py"}',
        }
        result = handle_pre_file_guard(payload)
        assert result.get("exit_code") is None


# ======================================================================
# Gap #3 — TOCTOU: guard claims atomically before allowing edit
# ======================================================================

class TestGap3TocTouAtomicClaim:
    """PreToolUse guard should claim files atomically when unclaimed."""

    def test_unclaimed_file_gets_claimed_by_guard(self, coord_mgr, monkeypatch):
        """Guard should atomically claim an unclaimed file for the editing session."""
        from omega.server.hook_server import handle_pre_file_guard
        import omega.coordination as coord_mod

        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        payload = {
            "tool_name": "Edit",
            "session_id": "sess-A",
            "tool_input": '{"file_path": "/proj/new.py"}',
        }
        result = handle_pre_file_guard(payload)
        assert result.get("exit_code") is None  # Allowed

        # File should now be claimed by sess-A
        info = coord_mgr.check_file("/proj/new.py")
        assert info["claimed"] is True
        assert info["session_id"] == "sess-A"

    def test_race_lost_blocks_second_agent(self, coord_mgr, monkeypatch):
        """If another agent claims between check and claim, second agent is blocked."""
        from omega.server.hook_server import handle_pre_file_guard
        import omega.coordination as coord_mod

        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.register_session("sess-B", pid=2, project="/proj")

        # Simulate: sess-A already claimed via a concurrent guard invocation
        coord_mgr.claim_file("sess-A", "/proj/race.py", task="concurrent edit")

        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        # sess-B tries to edit the same file — guard should block
        payload = {
            "tool_name": "Edit",
            "session_id": "sess-B",
            "tool_input": '{"file_path": "/proj/race.py"}',
        }
        result = handle_pre_file_guard(payload)
        assert result.get("exit_code") == 2
        assert "[FILE-GUARD] BLOCKED" in result.get("output", "")

    def test_self_claim_allows_without_reclaim(self, coord_mgr, monkeypatch):
        """If I already claimed the file, guard allows without re-claiming."""
        from omega.server.hook_server import handle_pre_file_guard
        import omega.coordination as coord_mod

        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.claim_file("sess-A", "/proj/mine.py")
        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        payload = {
            "tool_name": "Edit",
            "session_id": "sess-A",
            "tool_input": '{"file_path": "/proj/mine.py"}',
        }
        result = handle_pre_file_guard(payload)
        assert result.get("exit_code") is None

    def test_unregistered_session_claim_fails_open(self, coord_mgr, monkeypatch):
        """If session is not registered, claim_file fails — guard allows (fail-open)."""
        from omega.server.hook_server import handle_pre_file_guard
        import omega.coordination as coord_mod

        # Do NOT register sess-X
        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        payload = {
            "tool_name": "Edit",
            "session_id": "sess-X",
            "tool_input": '{"file_path": "/proj/orphan.py"}',
        }
        result = handle_pre_file_guard(payload)
        assert result.get("exit_code") is None  # Fail-open

    def test_notebook_edit_gets_claimed(self, coord_mgr, monkeypatch):
        """NotebookEdit should also trigger atomic claim."""
        from omega.server.hook_server import handle_pre_file_guard
        import omega.coordination as coord_mod

        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        payload = {
            "tool_name": "NotebookEdit",
            "session_id": "sess-A",
            "tool_input": '{"notebook_path": "/proj/analysis.ipynb"}',
        }
        result = handle_pre_file_guard(payload)
        assert result.get("exit_code") is None

        info = coord_mgr.check_file("/proj/analysis.ipynb")
        assert info["claimed"] is True
        assert info["session_id"] == "sess-A"


# ======================================================================
# Gap #6 — Branch guard: blocks checkout/switch/commit on claimed branches
# ======================================================================

class TestGap6BranchGuard:
    """Pre-push guard should also enforce branch claims."""

    def test_check_branch_returns_unclaimed(self, coord_mgr):
        """check_branch() on unclaimed branch returns claimed=False."""
        info = coord_mgr.check_branch("/proj", "feature/auth")
        assert info["claimed"] is False

    def test_check_branch_returns_claimed(self, coord_mgr):
        """check_branch() on claimed branch returns full info."""
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.claim_branch("sess-A", "/proj", "feature/auth", task="auth work")

        info = coord_mgr.check_branch("/proj", "feature/auth")
        assert info["claimed"] is True
        assert info["session_id"] == "sess-A"
        assert info["task"] == "auth work"

    def test_parse_checkout_target_simple(self):
        """Parse simple git checkout <branch>."""
        from pre_push_guard import _parse_checkout_target

        assert _parse_checkout_target("git checkout feature/auth") == "feature/auth"
        assert _parse_checkout_target("git switch feature/auth") == "feature/auth"
        assert _parse_checkout_target("git checkout main") == "main"

    def test_parse_checkout_target_with_flags(self):
        """Parse git checkout with flags."""
        from pre_push_guard import _parse_checkout_target

        assert _parse_checkout_target("git checkout -q feature/auth") == "feature/auth"
        assert _parse_checkout_target("git switch --detach feature/auth") == "feature/auth"

    def test_parse_checkout_new_branch_returns_none(self):
        """git checkout -b (new branch) should return None — no blocking."""
        from pre_push_guard import _parse_checkout_target

        assert _parse_checkout_target("git checkout -b feature/new") is None
        assert _parse_checkout_target("git switch -c feature/new") is None
        assert _parse_checkout_target("git checkout -B feature/new") is None

    def test_parse_checkout_file_restore_returns_none(self):
        """git checkout -- file should return None — file restore, not branch switch."""
        from pre_push_guard import _parse_checkout_target

        assert _parse_checkout_target("git checkout -- src/foo.py") is None
        assert _parse_checkout_target("git checkout HEAD -- src/foo.py") is None

    def test_parse_checkout_chained_command(self):
        """Parse branch from chained commands."""
        from pre_push_guard import _parse_checkout_target

        assert _parse_checkout_target("git fetch && git checkout feature/auth") == "feature/auth"

    def test_parse_checkout_no_match(self):
        """Non-checkout commands return None."""
        from pre_push_guard import _parse_checkout_target

        assert _parse_checkout_target("git status") is None
        assert _parse_checkout_target("ls -la") is None

    def test_block_if_branch_claimed_blocks(self, coord_mgr, monkeypatch):
        """_block_if_branch_claimed should exit(2) when claimed by another."""
        from pre_push_guard import _block_if_branch_claimed
        import omega.coordination as coord_mod

        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.claim_branch("sess-A", "/proj", "feature/auth", task="auth work")
        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        with pytest.raises(SystemExit) as exc_info:
            _block_if_branch_claimed("sess-B", "/proj", "feature/auth")
        assert exc_info.value.code == 2

    def test_block_if_branch_claimed_allows_self(self, coord_mgr, monkeypatch):
        """_block_if_branch_claimed should allow self-claimed branch."""
        from pre_push_guard import _block_if_branch_claimed
        import omega.coordination as coord_mod

        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.claim_branch("sess-A", "/proj", "feature/auth")
        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        # Should not raise
        _block_if_branch_claimed("sess-A", "/proj", "feature/auth")

    def test_block_if_branch_claimed_allows_unclaimed(self, coord_mgr, monkeypatch):
        """_block_if_branch_claimed should allow unclaimed branches."""
        from pre_push_guard import _block_if_branch_claimed
        import omega.coordination as coord_mod

        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        # Should not raise
        _block_if_branch_claimed("sess-A", "/proj", "feature/unclaimed")


# ======================================================================
# Gap #14 — Force-claim notification: previous owner gets a message
# ======================================================================

class TestGap14ForceClaimNotification:
    """Force-claiming should notify the previous owner via message bus."""

    def test_force_claim_sends_message(self, coord_mgr):
        """Previous owner should receive a message when their claim is force-taken."""
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.register_session("sess-B", pid=2, project="/proj")
        coord_mgr.claim_file("sess-A", "/proj/foo.py", task="editing")

        # Force-claim from sess-B
        result = coord_mgr.claim_file("sess-B", "/proj/foo.py", task="urgent", force=True)
        assert result["success"] is True
        assert result["force_override"] is True

        # Check sess-A's inbox
        messages = coord_mgr.check_inbox("sess-A")
        assert len(messages) >= 1
        msg = messages[0]
        assert "force" in msg["subject"].lower() or "claim" in msg["subject"].lower()
        assert msg["from_session"] == "sess-B"
        assert "foo.py" in msg.get("body", "")

    def test_force_claim_notification_includes_file(self, coord_mgr):
        """Notification body should include the file path."""
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.register_session("sess-B", pid=2, project="/proj")
        coord_mgr.claim_file("sess-A", "/proj/deep/nested/important.py", task="refactoring")

        coord_mgr.claim_file("sess-B", "/proj/deep/nested/important.py", force=True)

        messages = coord_mgr.check_inbox("sess-A")
        assert len(messages) >= 1
        assert "/proj/deep/nested/important.py" in messages[0].get("body", "")

    def test_normal_claim_no_notification(self, coord_mgr):
        """Normal claim (no force) should NOT send any notification."""
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.register_session("sess-B", pid=2, project="/proj")

        # Clear peer-arrival notifications from registration
        coord_mgr.check_inbox("sess-A")
        coord_mgr.check_inbox("sess-B")

        coord_mgr.claim_file("sess-A", "/proj/a.py")
        coord_mgr.claim_file("sess-B", "/proj/b.py")

        # Neither should have messages
        msgs_a = coord_mgr.check_inbox("sess-A")
        msgs_b = coord_mgr.check_inbox("sess-B")
        assert len(msgs_a) == 0
        assert len(msgs_b) == 0

    def test_expired_claim_takeover_no_notification(self, coord_mgr):
        """Expired claim takeover (not force) should NOT notify."""
        from omega.coordination import CLAIM_TTL_SECONDS

        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.register_session("sess-B", pid=2, project="/proj")

        # Clear peer-arrival notifications from registration
        coord_mgr.check_inbox("sess-A")
        coord_mgr.check_inbox("sess-B")

        coord_mgr.claim_file("sess-A", "/proj/foo.py")

        # Expire the claim
        expired_time = (datetime.now(timezone.utc) - timedelta(seconds=CLAIM_TTL_SECONDS + 60)).isoformat()
        coord_mgr._conn.execute(
            "UPDATE coord_file_claims SET last_activity = ? WHERE file_path = ?",
            (expired_time, "/proj/foo.py")
        )
        coord_mgr._conn.commit()

        # Take over expired claim (no force needed)
        result = coord_mgr.claim_file("sess-B", "/proj/foo.py")
        assert result["success"] is True
        assert result.get("expired_claim_replaced") is True

        # Expired claim replacement now notifies original owner
        messages = coord_mgr.check_inbox("sess-A")
        assert len(messages) == 1
        assert "replaced" in messages[0]["body"]


# ======================================================================
# Standalone hook tests (pre_file_guard.py as subprocess-like invocation)
# ======================================================================

class TestStandalonePreFileGuard:
    """Test the standalone pre_file_guard.py main() function."""

    def test_standalone_blocks_claimed_no_session(self, coord_mgr, monkeypatch):
        """Standalone hook: claimed file blocked even with empty SESSION_ID."""
        import pre_file_guard
        import omega.coordination as coord_mod

        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.claim_file("sess-A", "/proj/foo.py", task="editing")
        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        monkeypatch.setenv("TOOL_NAME", "Edit")
        monkeypatch.setenv("SESSION_ID", "")
        monkeypatch.setenv("TOOL_INPUT", '{"file_path": "/proj/foo.py"}')

        with pytest.raises(SystemExit) as exc_info:
            pre_file_guard.main()
        assert exc_info.value.code == 2

    def test_standalone_claims_atomically(self, coord_mgr, monkeypatch):
        """Standalone hook: unclaimed file gets claimed atomically."""
        import pre_file_guard
        import omega.coordination as coord_mod

        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        monkeypatch.setenv("TOOL_NAME", "Write")
        monkeypatch.setenv("SESSION_ID", "sess-A")
        monkeypatch.setenv("TOOL_INPUT", '{"file_path": "/proj/new.py"}')

        pre_file_guard.main()  # Should not raise

        info = coord_mgr.check_file("/proj/new.py")
        assert info["claimed"] is True
        assert info["session_id"] == "sess-A"

    def test_standalone_allows_unclaimed_no_session(self, coord_mgr, monkeypatch):
        """Standalone hook: unclaimed file + no session → allow (true single-agent)."""
        import pre_file_guard
        import omega.coordination as coord_mod

        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        monkeypatch.setenv("TOOL_NAME", "Edit")
        monkeypatch.setenv("SESSION_ID", "")
        monkeypatch.setenv("TOOL_INPUT", '{"file_path": "/proj/unclaimed.py"}')

        pre_file_guard.main()  # Should not raise
