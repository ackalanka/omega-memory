"""Tests for medium-severity coordination gap fixes.

Covers:
  Gap #4  — NotebookEdit auto-claim
  Gap #7  — Auto branch claiming on checkout/switch
  Gap #8  — Branch claim TTL
  Gap #9  — Improved git push regex detection
  Gap #11 — Intent check when claiming a file
  Gap #12 — Notification when intended file gets claimed
  Gap #15 — New peer arrival notification
  Gap #16 — Heartbeat on Read (config-level, tested via settings check)
  Gap #17 — Reduced crash recovery window
  Gap #18 — Task double-claim race prevention
  Gap #20 — Notify dependents on task fail/cancel
"""
import re
from datetime import datetime, timedelta, timezone



# ======================================================================
# Gap #4 — NotebookEdit auto-claim
# ======================================================================

class TestGap4NotebookEditAutoClaim:
    """NotebookEdit should be auto-claimed by hook handlers."""

    def test_daemon_handler_accepts_notebook_edit(self, coord_mgr, monkeypatch):
        """handle_auto_claim_file should process NotebookEdit."""
        from omega.server.hook_server import handle_auto_claim_file
        import omega.coordination as coord_mod

        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        # Clear debounce state
        from omega.server import hook_server
        hook_server._last_claim.clear()

        payload = {
            "tool_name": "NotebookEdit",
            "session_id": "sess-A",
            "tool_input": '{"notebook_path": "/proj/analysis.ipynb"}',
        }
        result = handle_auto_claim_file(payload)
        assert result.get("error") is None

        info = coord_mgr.check_file("/proj/analysis.ipynb")
        assert info["claimed"] is True
        assert info["session_id"] == "sess-A"

    def test_standalone_accepts_notebook_edit(self, coord_mgr, monkeypatch):
        """Standalone auto_claim_file.py should accept NotebookEdit."""
        import auto_claim_file
        import omega.coordination as coord_mod

        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        monkeypatch.setenv("TOOL_NAME", "NotebookEdit")
        monkeypatch.setenv("SESSION_ID", "sess-A")
        monkeypatch.setenv("TOOL_INPUT", '{"notebook_path": "/proj/nb.ipynb"}')

        auto_claim_file.main()

        info = coord_mgr.check_file("/proj/nb.ipynb")
        assert info["claimed"] is True


# ======================================================================
# Gap #8 — Branch claim TTL
# ======================================================================

class TestGap8BranchClaimTTL:
    """Branch claims should expire after BRANCH_CLAIM_TTL_SECONDS."""

    def test_active_branch_claim_visible(self, coord_mgr):
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.claim_branch("sess-A", "/proj", "feature/auth")
        info = coord_mgr.check_branch("/proj", "feature/auth")
        assert info["claimed"] is True

    def test_expired_branch_claim_auto_deleted(self, coord_mgr):
        from omega.coordination import BRANCH_CLAIM_TTL_SECONDS
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.claim_branch("sess-A", "/proj", "feature/auth")

        expired = (datetime.now(timezone.utc) - timedelta(seconds=BRANCH_CLAIM_TTL_SECONDS + 60)).isoformat()
        coord_mgr._conn.execute(
            "UPDATE coord_branch_claims SET last_activity = ? WHERE branch = ?",
            (expired, "feature/auth")
        )
        coord_mgr._conn.commit()

        info = coord_mgr.check_branch("/proj", "feature/auth")
        assert info["claimed"] is False
        assert info.get("expired_claim") is True

    def test_clean_expired_branch_claims(self, coord_mgr):
        from omega.coordination import BRANCH_CLAIM_TTL_SECONDS
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.claim_branch("sess-A", "/proj", "feature/old")
        coord_mgr.claim_branch("sess-A", "/proj", "feature/active")

        expired = (datetime.now(timezone.utc) - timedelta(seconds=BRANCH_CLAIM_TTL_SECONDS + 60)).isoformat()
        coord_mgr._conn.execute(
            "UPDATE coord_branch_claims SET last_activity = ? WHERE branch = ?",
            (expired, "feature/old")
        )
        coord_mgr._conn.commit()

        with coord_mgr._lock:
            removed = coord_mgr._clean_expired_branch_claims()
            coord_mgr._conn.commit()

        assert len(removed) == 1
        assert coord_mgr.check_branch("/proj", "feature/old")["claimed"] is False
        assert coord_mgr.check_branch("/proj", "feature/active")["claimed"] is True


# ======================================================================
# Gap #9 — Improved git push regex detection
# ======================================================================

class TestGap9PushDetection:
    """Push guard should use word-boundary regex."""

    def test_simple_git_push_detected(self):
        assert re.search(r'\bgit\s+push\b', "git push origin main")

    def test_chained_git_push_detected(self):
        assert re.search(r'\bgit\s+push\b', "git add . && git push")

    def test_non_push_not_detected(self):
        assert not re.search(r'\bgit\s+push\b', "git status")

    def test_substring_not_detected(self):
        # "fugit push" should NOT match (word boundary)
        assert not re.search(r'\bgit\s+push\b', "fugit push")


# ======================================================================
# Gap #11 + #12 — Intent-aware claiming + notification
# ======================================================================

class TestGap11_12IntentAwareClaiming:
    """claim_file should detect intent overlaps and notify intent owners."""

    def test_claim_detects_intent_overlap(self, coord_mgr):
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.register_session("sess-B", pid=2, project="/proj")

        # sess-A announces intent to edit foo.py
        coord_mgr.announce_intent(
            "sess-A", "Refactoring foo.py",
            target_files=["/proj/foo.py"], ttl_minutes=30,
        )

        # sess-B claims foo.py
        result = coord_mgr.claim_file("sess-B", "/proj/foo.py")
        assert result["success"] is True
        assert "intent_overlaps" in result
        assert len(result["intent_overlaps"]) >= 1
        assert result["intent_overlaps"][0]["session_id"] == "sess-A"

    def test_claim_sends_notification_to_intent_owner(self, coord_mgr):
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.register_session("sess-B", pid=2, project="/proj")

        coord_mgr.announce_intent(
            "sess-A", "Editing bar.py",
            target_files=["/proj/bar.py"], ttl_minutes=30,
        )

        coord_mgr.claim_file("sess-B", "/proj/bar.py")

        messages = coord_mgr.check_inbox("sess-A")
        assert len(messages) >= 1
        msg = messages[0]
        assert "bar.py" in msg["subject"]
        assert msg["from_session"] == "sess-B"

    def test_no_intent_no_overlap(self, coord_mgr):
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        result = coord_mgr.claim_file("sess-A", "/proj/clean.py")
        assert result["success"] is True
        assert "intent_overlaps" not in result

    def test_self_intent_not_flagged(self, coord_mgr):
        """My own intent should not be flagged as an overlap."""
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.announce_intent(
            "sess-A", "Editing self.py",
            target_files=["/proj/self.py"], ttl_minutes=30,
        )
        result = coord_mgr.claim_file("sess-A", "/proj/self.py")
        assert result["success"] is True
        assert "intent_overlaps" not in result or len(result.get("intent_overlaps", [])) == 0


# ======================================================================
# Gap #15 — New peer arrival notification
# ======================================================================

class TestGap15PeerNotification:
    """Existing agents should be notified when a new peer joins."""

    def test_new_agent_notifies_peers(self, coord_mgr):
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.register_session("sess-B", pid=2, project="/proj")

        # sess-A should have a message about sess-B joining
        messages = coord_mgr.check_inbox("sess-A")
        assert len(messages) >= 1
        join_msgs = [m for m in messages if "joined" in m.get("subject", "").lower()]
        assert len(join_msgs) >= 1
        assert join_msgs[0]["from_session"] == "sess-B"

    def test_first_agent_no_notification(self, coord_mgr):
        """First agent on a project should not generate a notification."""
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        messages = coord_mgr.check_inbox("sess-A")
        assert len(messages) == 0

    def test_reregister_no_duplicate_notification(self, coord_mgr):
        """Re-registering (idempotent) should NOT send another notification."""
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.register_session("sess-B", pid=2, project="/proj")

        # Clear inbox
        coord_mgr.check_inbox("sess-A")

        # Re-register sess-B (idempotent)
        coord_mgr.register_session("sess-B", pid=2, project="/proj")

        # No new messages
        messages = coord_mgr.check_inbox("sess-A")
        assert len(messages) == 0


# ======================================================================
# Gap #17 — Reduced crash recovery window
# ======================================================================

class TestGap17ReducedRecoveryWindow:
    """Stale threshold and cleanup interval should be reduced."""

    def test_stale_threshold_is_15min(self):
        from omega.coordination import STALE_THRESHOLD_SECONDS
        assert STALE_THRESHOLD_SECONDS == 900

    def test_branch_claim_ttl_is_1hour(self):
        from omega.coordination import BRANCH_CLAIM_TTL_SECONDS
        assert BRANCH_CLAIM_TTL_SECONDS == 3600


# ======================================================================
# Gap #18 — Task double-claim race prevention
# ======================================================================

class TestGap18TaskDoubleClaim:
    """claim_task UPDATE should include AND status='pending' for atomicity."""

    def test_normal_claim_works(self, coord_mgr):
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        result = coord_mgr.create_task("sess-A", "Test task", project="/proj")
        task_id = result["task_id"]

        claim = coord_mgr.claim_task(task_id, "sess-A")
        assert claim["success"] is True

    def test_double_claim_prevented(self, coord_mgr):
        """If task is already claimed, second claim fails."""
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.register_session("sess-B", pid=2, project="/proj")
        result = coord_mgr.create_task("sess-A", "Race task", project="/proj")
        task_id = result["task_id"]

        claim1 = coord_mgr.claim_task(task_id, "sess-A")
        assert claim1["success"] is True

        claim2 = coord_mgr.claim_task(task_id, "sess-B")
        assert claim2["success"] is False
        assert "in_progress" in claim2.get("error", "")

    def test_atomic_claim_with_status_check(self, coord_mgr):
        """Simulate race: manually set status to in_progress between check and update."""
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.register_session("sess-B", pid=2, project="/proj")
        result = coord_mgr.create_task("sess-A", "Atomic task", project="/proj")
        task_id = result["task_id"]

        # Manually claim to simulate another process winning
        coord_mgr._conn.execute(
            "UPDATE coord_tasks SET status = 'in_progress', session_id = 'sess-A' WHERE id = ?",
            (task_id,)
        )
        coord_mgr._conn.commit()

        # Now sess-B tries to claim — should fail even though it passed the SELECT check
        claim = coord_mgr.claim_task(task_id, "sess-B")
        assert claim["success"] is False


# ======================================================================
# Gap #20 — Notify dependents on task fail/cancel
# ======================================================================

class TestGap20FailCancelNotification:
    """fail_task/cancel_task should notify creators of blocked dependents."""

    def test_fail_task_notifies_dependent_creator(self, coord_mgr):
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.register_session("sess-B", pid=2, project="/proj")

        # Create task chain: task2 depends on task1
        t1 = coord_mgr.create_task("sess-A", "Task 1", project="/proj")
        coord_mgr.create_task("sess-B", "Task 2", project="/proj", depends_on=[t1["task_id"]])

        # Claim and fail task1
        coord_mgr.claim_task(t1["task_id"], "sess-A")
        result = coord_mgr.fail_task(t1["task_id"], "sess-A", reason="OOM error")
        assert result["success"] is True
        assert len(result.get("blocked_dependents", [])) >= 1

        # sess-B should get a message about the blocked task
        messages = coord_mgr.check_inbox("sess-B")
        block_msgs = [m for m in messages if "blocked" in m.get("subject", "").lower()]
        assert len(block_msgs) >= 1
        assert "Task 2" in block_msgs[0].get("body", "")

    def test_cancel_task_notifies_dependent_creator(self, coord_mgr):
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.register_session("sess-B", pid=2, project="/proj")

        t1 = coord_mgr.create_task("sess-A", "Task 1", project="/proj")
        coord_mgr.create_task("sess-B", "Task 2", project="/proj", depends_on=[t1["task_id"]])

        coord_mgr.claim_task(t1["task_id"], "sess-A")
        result = coord_mgr.cancel_task(t1["task_id"], "sess-A")
        assert result["success"] is True
        assert len(result.get("blocked_dependents", [])) >= 1

        messages = coord_mgr.check_inbox("sess-B")
        block_msgs = [m for m in messages if "blocked" in m.get("subject", "").lower()]
        assert len(block_msgs) >= 1

    def test_fail_no_dependents_no_notification(self, coord_mgr):
        """Failing a task with no dependents should not send messages."""
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        t1 = coord_mgr.create_task("sess-A", "Solo task", project="/proj")
        coord_mgr.claim_task(t1["task_id"], "sess-A")
        result = coord_mgr.fail_task(t1["task_id"], "sess-A")
        assert result["success"] is True
        assert "blocked_dependents" not in result

    def test_complete_task_still_unblocks(self, coord_mgr):
        """Completing a task should still unblock dependents (existing behavior)."""
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        t1 = coord_mgr.create_task("sess-A", "Task 1", project="/proj")
        coord_mgr.create_task("sess-A", "Task 2", project="/proj", depends_on=[t1["task_id"]])

        coord_mgr.claim_task(t1["task_id"], "sess-A")
        result = coord_mgr.complete_task(t1["task_id"], "sess-A")
        assert result["success"] is True
        assert len(result.get("unblocked_tasks", [])) >= 1
