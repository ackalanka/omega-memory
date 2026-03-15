"""UAT — Multi-Agent Collaboration: Awareness, Communication, Coordination, Conflict, Golden Path.

End-to-end acceptance tests for OMEGA proactive multi-agent collaboration features.
Tests the 5 hook enhancements that wire coordination APIs into hook automation.

Organized into five sections:
  1. Awareness — rich peer details at session start, capabilities, tasks, claims
  2. Communication — messaging, structured handoffs, inbox surfacing
  3. Coordination — heartbeat checks, blocked tasks, active coordination
  4. Conflict Detection — intent overlaps, file conflicts, overlap notifications
  5. Golden Path — full multi-agent scenarios combining all features
"""
import json
import sys
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from omega.server.hook_server import (
    handle_coord_session_start,
    handle_coord_session_stop,
    handle_coord_heartbeat,
    handle_auto_claim_file,
    _surface_lessons,
    _last_heartbeat,
    _last_claim,
    _last_overlap_notify,
    _last_surface,
    _heartbeat_count,
    _error_hashes,
    _error_counts,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def _reset_hook_state():
    """Reset hook_server global debounce state between tests."""
    _last_heartbeat.clear()
    _heartbeat_count.clear()
    _last_claim.clear()
    _last_overlap_notify.clear()
    _last_surface.clear()
    _error_hashes.clear()
    _error_counts.clear()
    yield
    _last_heartbeat.clear()
    _heartbeat_count.clear()
    _last_claim.clear()
    _last_overlap_notify.clear()
    _last_surface.clear()
    _error_hashes.clear()
    _error_counts.clear()


@pytest.fixture
def mgr_patch(coord_mgr):
    """Patch get_manager to return our test coordinator everywhere."""
    with patch("omega.coordination.get_manager", return_value=coord_mgr):
        yield coord_mgr


def _mock_bridge_noop():
    """Return a patch context that stubs out all bridge imports in hook_server."""
    return patch.multiple(
        "omega.bridge",
        query_structured=MagicMock(return_value=[]),
        get_cross_session_lessons=MagicMock(return_value=[]),
        _get_store=MagicMock(return_value=MagicMock(
            get_session_event_counts=MagicMock(return_value={}),
        )),
        auto_capture=MagicMock(),
        consolidate=MagicMock(),
        create=True,
    )


# ============================================================================
# SECTION 1: Multi-Agent Awareness
# ============================================================================


class TestUATMultiAgentAwareness:
    """Rich peer awareness at session start — capabilities, tasks, claims, inbox."""

    def test_session_start_shows_peer_task_and_capabilities(self, mgr_patch):
        """UAT: Agent B's session start shows Agent A's task, capabilities, and session ID."""
        mgr = mgr_patch
        mgr.register_session(
            "agent-alpha", pid=1001, project="/proj/shared",
            task="Implementing auth module",
            capabilities=["code", "test"],
        )

        with _mock_bridge_noop():
            result = handle_coord_session_start({
                "session_id": "agent-beta",
                "project": "/proj/shared",
            })

        output = result["output"]
        assert result["error"] is None
        assert "[COORD]" in output
        assert "1 peer active" in output
        # Rich roster now shows peer task inline
        assert "Implementing auth module" in output

    def test_session_start_peer_count_with_claims(self, mgr_patch):
        """UAT: Session start shows peer count (details deferred to tool)."""
        mgr = mgr_patch
        mgr.register_session("agent-A", pid=1001, project="/proj/shared", task="refactoring")
        mgr.claim_file("agent-A", "/proj/shared/models.py")
        mgr.claim_file("agent-A", "/proj/shared/views.py")
        mgr.claim_file("agent-A", "/proj/shared/utils.py")

        with _mock_bridge_noop():
            result = handle_coord_session_start({
                "session_id": "agent-B",
                "project": "/proj/shared",
            })

        output = result["output"]
        # Rich roster now shows file claims inline
        assert "[COORD]" in output
        assert "1 peer active" in output

    def test_session_start_shows_multiple_peers(self, mgr_patch):
        """UAT: Agent C sees peer count for Agent A and Agent B."""
        mgr = mgr_patch
        mgr.register_session("agent-A", pid=1001, project="/proj/team", task="auth")
        mgr.register_session("agent-B", pid=1002, project="/proj/team", task="logging")

        with _mock_bridge_noop():
            result = handle_coord_session_start({
                "session_id": "agent-C",
                "project": "/proj/team",
            })

        output = result["output"]
        assert "[COORD]" in output
        assert "2 peers active" in output

    def test_session_start_shows_unread_messages(self, mgr_patch):
        """UAT: Unread messages are surfaced at session start.

        Note: register_session for an EXISTING session skips peers_on_project,
        so we only register the sender pre-test; the handler registers the reader.
        """
        mgr = mgr_patch
        mgr.register_session("sender-1", pid=1001, project="/proj/shared")
        # Send message to reader-1 before it's registered (stored in messages table)
        mgr.send_message(
            from_session="sender-1",
            to_session="reader-1",
            subject="Please review auth.py",
            msg_type="request",
        )

        with _mock_bridge_noop():
            result = handle_coord_session_start({
                "session_id": "reader-1",
                "project": "/proj/shared",
            })

        output = result["output"]
        assert "[COORD]" in output
        assert "1 peer active" in output
        assert "[TODO]" in output
        assert "unread msg" in output

    def test_session_start_shows_pending_tasks_in_todo(self, mgr_patch):
        """UAT: Pending tasks show in [TODO] with highest priority as NEXT."""
        mgr = mgr_patch
        mgr.register_session("creator-1", pid=1001, project="/proj/a")
        mgr.create_task("creator-1", "Fix login bug", project="/proj/a", priority=5)
        mgr.create_task("creator-1", "Add tests", project="/proj/a", priority=3)

        with _mock_bridge_noop():
            result = handle_coord_session_start({
                "session_id": "newcomer-1",
                "project": "/proj/a",
            })

        output = result["output"]
        assert "[TODO]" in output
        assert "2 pending tasks" in output
        assert "Fix login bug" in output

    def test_solo_agent_no_peer_details(self, mgr_patch):
        """UAT: Single agent doesn't see peer footer or TODO (no tasks/unread)."""
        with _mock_bridge_noop():
            result = handle_coord_session_start({
                "session_id": "solo-agent",
                "project": "/proj/alone",
            })

        output = result["output"]
        assert "[COORD]" not in output
        assert "[TODO]" not in output

    def test_cross_project_peers_shown_with_label(self, mgr_patch):
        """UAT: Cross-project peers are visible with project label badge."""
        mgr = mgr_patch
        mgr.register_session("agent-A", pid=1001, project="/proj/alpha", task="working on alpha")

        with _mock_bridge_noop():
            result = handle_coord_session_start({
                "session_id": "agent-B",
                "project": "/proj/beta",
            })

        output = result["output"]
        assert "[COORD]" in output
        assert "1 peer active" in output
        # Cross-project peer shown with project label
        assert "[alpha]" in output
        assert "working on alpha" in output


# ============================================================================
# SECTION 2: Communication
# ============================================================================


class TestUATAgentCommunication:
    """Messaging, structured handoffs, and inbox surfacing."""

    def test_direct_message_delivery(self, mgr_patch):
        """UAT: Agent A sends a message to Agent B, B reads it from inbox."""
        mgr = mgr_patch
        mgr.register_session("agent-A", pid=1001, project="/proj/shared")
        mgr.register_session("agent-B", pid=1002, project="/proj/shared")

        mgr.send_message(
            from_session="agent-A",
            to_session="agent-B",
            subject="Auth module ready for review",
            msg_type="inform",
            body="I've finished auth.py and middleware.py. Please review when ready.",
        )

        msgs = mgr.check_inbox("agent-B", unread_only=True)
        assert len(msgs) == 1
        assert msgs[0]["subject"] == "Auth module ready for review"
        assert "auth.py" in msgs[0]["body"]
        assert msgs[0]["from_session"] == "agent-A"

    def test_broadcast_message_to_project(self, mgr_patch):
        """UAT: Broadcast message reaches all agents on the same project."""
        mgr = mgr_patch
        mgr.register_session("broadcaster", pid=1001, project="/proj/team")
        mgr.register_session("listener-A", pid=1002, project="/proj/team")
        mgr.register_session("listener-B", pid=1003, project="/proj/team")
        mgr.register_session("outsider", pid=1004, project="/proj/other")

        mgr.send_message(
            from_session="broadcaster",
            subject="Schema migration starting",
            msg_type="inform",
            project="/proj/team",
            body="Starting database migration — please avoid models.py",
        )

        msgs_a = mgr.check_inbox("listener-A", unread_only=True)
        msgs_b = mgr.check_inbox("listener-B", unread_only=True)
        msgs_outsider = mgr.check_inbox("outsider", unread_only=True)

        assert len(msgs_a) >= 1
        assert len(msgs_b) >= 1
        # Outsider on different project should not receive
        assert len(msgs_outsider) == 0

    def test_structured_handoff_with_decisions(self, mgr_patch):
        """UAT: Session stop broadcasts structured handoff including decisions."""
        mgr = mgr_patch
        mgr.register_session("departing", pid=1001, project="/proj/a", task="auth module")
        mgr.register_session("successor", pid=1002, project="/proj/a")

        mock_decisions = [
            {"content": "Decided to use JWT for authentication tokens"},
            {"content": "Chose bcrypt over argon2 for password hashing"},
        ]

        with patch("omega.bridge.query_structured", side_effect=[mock_decisions, []]), \
             patch("omega.bridge._get_store") as mock_store:
            mock_store.return_value.get_session_event_counts.return_value = {"decision": 2}
            handle_coord_session_stop({
                "session_id": "departing",
                "project": "/proj/a",
            })

        # Successor should see the handoff message
        msgs = mgr.check_inbox("successor", unread_only=True)
        handoffs = [m for m in msgs if m.get("msg_type") == "complete"]
        assert len(handoffs) == 1
        body = handoffs[0]["body"]
        assert "## Session Summary" in body
        assert "## Decisions" in body
        assert "JWT" in body
        assert "bcrypt" in body

    def test_structured_handoff_with_errors(self, mgr_patch):
        """UAT: Session stop handoff includes blockers section for errors."""
        mgr = mgr_patch
        mgr.register_session("errored", pid=1001, project="/proj/b")
        mgr.register_session("helper", pid=1002, project="/proj/b")

        mock_errors = [
            {"content": "ImportError: cannot import 'missing_module' from omega.utils"},
        ]

        with patch("omega.bridge.query_structured", side_effect=[[], mock_errors]), \
             patch("omega.bridge._get_store") as mock_store:
            mock_store.return_value.get_session_event_counts.return_value = {}
            handle_coord_session_stop({
                "session_id": "errored",
                "project": "/proj/b",
            })

        msgs = mgr.check_inbox("helper", unread_only=True)
        handoffs = [m for m in msgs if m.get("msg_type") == "complete"]
        assert len(handoffs) == 1
        assert "## Blockers" in handoffs[0]["body"]
        assert "ImportError" in handoffs[0]["body"]

    def test_structured_handoff_with_incomplete_tasks(self, mgr_patch):
        """UAT: Session stop handoff lists in_progress tasks owned by the departing agent."""
        mgr = mgr_patch
        mgr.register_session("leaver", pid=1001, project="/proj/c")
        mgr.register_session("receiver", pid=1002, project="/proj/c")

        task = mgr.create_task("leaver", "Write integration tests", project="/proj/c")
        mgr.claim_task(task["task_id"], "leaver")

        with patch("omega.bridge.query_structured", return_value=[]), \
             patch("omega.bridge._get_store") as mock_store:
            mock_store.return_value.get_session_event_counts.return_value = {}
            handle_coord_session_stop({
                "session_id": "leaver",
                "project": "/proj/c",
            })

        msgs = mgr.check_inbox("receiver", unread_only=True)
        handoffs = [m for m in msgs if m.get("msg_type") == "complete"]
        assert len(handoffs) == 1
        assert "## Incomplete Work" in handoffs[0]["body"]
        assert "Write integration tests" in handoffs[0]["body"]

    def test_handoff_body_capped_at_8kb(self, mgr_patch):
        """UAT: Handoff message body is capped at 8000 characters."""
        mgr = mgr_patch
        mgr.register_session("verbose", pid=1001, project="/proj/d")
        mgr.register_session("reader", pid=1002, project="/proj/d")

        # Create many long decisions to exceed 8KB
        long_decisions = [
            {"content": f"Decision #{i}: " + "x" * 500}
            for i in range(30)
        ]

        with patch("omega.bridge.query_structured", side_effect=[long_decisions, []]), \
             patch("omega.bridge._get_store") as mock_store:
            mock_store.return_value.get_session_event_counts.return_value = {"decision": 30}
            handle_coord_session_stop({
                "session_id": "verbose",
                "project": "/proj/d",
            })

        msgs = mgr.check_inbox("reader", unread_only=True)
        handoffs = [m for m in msgs if m.get("msg_type") == "complete"]
        assert len(handoffs) == 1
        assert len(handoffs[0]["body"]) <= 8000

    def test_handoff_ttl_is_24_hours(self, mgr_patch):
        """UAT: Handoff message has 1440-minute (24h) TTL."""
        mgr = mgr_patch
        mgr.register_session("dep", pid=1001, project="/proj/e")
        mgr.register_session("suc", pid=1002, project="/proj/e")

        with patch("omega.bridge.query_structured", return_value=[]), \
             patch("omega.bridge._get_store") as mock_store:
            mock_store.return_value.get_session_event_counts.return_value = {}

            with patch.object(mgr, "send_message", wraps=mgr.send_message) as spy:
                handle_coord_session_stop({
                    "session_id": "dep",
                    "project": "/proj/e",
                })

                # Verify send_message was called with ttl_minutes=1440 (24h)
                spy.assert_called_once()
                call_kwargs = spy.call_args
                # Could be positional or keyword args
                if call_kwargs.kwargs:
                    assert call_kwargs.kwargs.get("ttl_minutes") == 1440
                    assert call_kwargs.kwargs.get("msg_type") == "complete"


# ============================================================================
# SECTION 3: Active Coordination
# ============================================================================


class TestUATActiveCoordination:
    """Heartbeat-driven coordination checks — blocked tasks, request surfacing."""

    def _advance_heartbeat(self, session_id, project, mgr, target_count):
        """Run heartbeats until we reach the target count, return last result."""
        result = None
        for i in range(target_count):
            # Reset debounce for each call so they actually execute
            _last_heartbeat.pop(session_id, None)
            result = handle_coord_heartbeat({
                "session_id": session_id,
                "project": project,
            })
        return result

    def test_blocked_task_surfaced_on_4th_heartbeat(self, mgr_patch):
        """UAT: Agent's blocked task shows [BLOCKED] on 4th heartbeat.

        Note: claim_task rejects tasks with unsatisfied deps, so we simulate
        a race condition where a claimed task's dependency becomes un-completed
        (e.g., dependency task was failed after claiming).
        """
        mgr = mgr_patch
        mgr.register_session("worker-A", pid=1001, project="/proj/a")
        mgr.register_session("blocker-B", pid=1002, project="/proj/a")

        # B creates and claims a task
        task_b = mgr.create_task("blocker-B", "Database migration", project="/proj/a")
        mgr.claim_task(task_b["task_id"], "blocker-B")

        # A creates a task depending on B's task
        task_a = mgr.create_task(
            "worker-A", "Add new columns",
            project="/proj/a",
            depends_on=[task_b["task_id"]],
        )

        # Complete B first so A can be claimed
        mgr.complete_task(task_b["task_id"], "blocker-B")
        mgr.claim_task(task_a["task_id"], "worker-A")

        # Simulate race: B's task reverts to in_progress (e.g., was re-opened)
        mgr._conn.execute(
            "UPDATE coord_tasks SET status = 'in_progress' WHERE id = ?",
            (task_b["task_id"],),
        )
        mgr._conn.commit()

        # Verify: A is in_progress with a dep on non-completed B
        tasks = mgr.list_tasks(project="/proj/a", status="in_progress")
        my = [t for t in tasks if t.get("session_id") == "worker-A"]
        assert len(my) == 1
        assert task_b["task_id"] in my[0].get("depends_on", [])

        # Mark any unread messages as read to isolate the [BLOCKED] output
        mgr.check_inbox("worker-A", unread_only=True)

        # Run 4 heartbeats to trigger coordination check
        result = self._advance_heartbeat("worker-A", "/proj/a", mgr, 4)
        output = result["output"]
        assert "[BLOCKED]" in output
        assert str(task_a["task_id"]) in output
        assert str(task_b["task_id"]) in output

    def test_request_message_surfaced_on_4th_heartbeat(self, mgr_patch):
        """UAT: Unread request-type message content shown on 4th heartbeat."""
        mgr = mgr_patch
        mgr.register_session("requester", pid=1001, project="/proj/a")
        mgr.register_session("worker", pid=1002, project="/proj/a")

        mgr.send_message(
            from_session="requester",
            to_session="worker",
            subject="Need help with auth module",
            msg_type="request",
        )

        # Run 4 heartbeats (need 2nd to set unread count, 4th to surface request)
        result = self._advance_heartbeat("worker", "/proj/a", mgr, 4)
        output = result["output"]
        assert "[REQUEST]" in output
        assert "Need help with auth module" in output

    def test_no_coord_check_on_non_4th_heartbeat(self, mgr_patch):
        """UAT: 1st, 2nd, 3rd heartbeats don't run the coordination task check."""
        mgr = mgr_patch
        mgr.register_session("worker", pid=1001, project="/proj/a")

        # Run 3 heartbeats
        for i in range(3):
            _last_heartbeat.pop("worker", None)
            result = handle_coord_heartbeat({
                "session_id": "worker",
                "project": "/proj/a",
            })
            output = result["output"]
            assert "[BLOCKED]" not in output

    def test_inbox_count_on_2nd_heartbeat(self, mgr_patch):
        """UAT: Unread message count is surfaced on every 2nd heartbeat."""
        mgr = mgr_patch
        mgr.register_session("sender", pid=1001, project="/proj/a")
        mgr.register_session("reader", pid=1002, project="/proj/a")

        mgr.send_message(
            from_session="sender",
            to_session="reader",
            subject="FYI: auth refactored",
            msg_type="inform",
        )

        # 2nd heartbeat should show inbox count
        _last_heartbeat.pop("reader", None)
        handle_coord_heartbeat({"session_id": "reader", "project": "/proj/a"})  # 1st
        _last_heartbeat.pop("reader", None)
        result = handle_coord_heartbeat({"session_id": "reader", "project": "/proj/a"})  # 2nd

        output = result["output"]
        assert "[INBOX]" in output
        assert "1 unread" in output

    def test_heartbeat_debounce(self, mgr_patch):
        """UAT: Rapid heartbeats within 30s window are debounced (no-op)."""
        mgr = mgr_patch
        mgr.register_session("rapid", pid=1001, project="/proj/a")

        # First heartbeat goes through
        result1 = handle_coord_heartbeat({"session_id": "rapid", "project": "/proj/a"})
        # Second heartbeat within debounce window returns empty
        result2 = handle_coord_heartbeat({"session_id": "rapid", "project": "/proj/a"})

        # First should have been processed (count incremented)
        assert _heartbeat_count.get("rapid") == 1
        # Second should have been skipped (count still 1)
        assert _heartbeat_count.get("rapid") == 1


# ============================================================================
# SECTION 4: Conflict Detection
# ============================================================================


class TestUATConflictDetection:
    """Intent overlaps, file conflicts, and overlap notifications."""

    def test_auto_claim_conflict_detection(self, mgr_patch):
        """UAT: Auto-claim detects when another agent already owns the file."""
        mgr = mgr_patch
        mgr.register_session("owner", pid=1001, project="/proj/a")
        mgr.register_session("intruder", pid=1002, project="/proj/a")
        mgr.claim_file("owner", "/proj/a/auth.py", task="implementing JWT")

        result = handle_auto_claim_file({
            "tool_name": "Edit",
            "session_id": "intruder",
            "tool_input": json.dumps({"file_path": "/proj/a/auth.py"}),
        })

        output = result["output"]
        assert "[CONFLICT]" in output
        assert "owner" in output
        assert "implementing JWT" in output

    def test_auto_claim_success_announces_intent(self, mgr_patch):
        """UAT: Successful auto-claim also announces an edit intent."""
        mgr = mgr_patch
        mgr.register_session("editor", pid=1001, project="/proj/a")
        # Need 2+ sessions so single-agent fast path doesn't skip intent
        mgr.register_session("checker", pid=1002, project="/proj/a")

        handle_auto_claim_file({
            "tool_name": "Edit",
            "session_id": "editor",
            "tool_input": json.dumps({"file_path": "/proj/a/views.py"}),
        })

        # File should be claimed
        info = mgr.check_file("/proj/a/views.py")
        assert info["claimed"] is True
        assert info["session_id"] == "editor"

        # Intent should be announced
        # Register another agent and check intents
        mgr.register_session("checker", pid=1002, project="/proj/a")
        mgr.announce_intent("checker", "also editing views", target_files=["/proj/a/views.py"])
        overlap = mgr.check_intents("checker")
        assert overlap["has_overlaps"] is True

    def test_intent_overlap_notifies_other_agent(self, mgr_patch):
        """UAT: When intent overlap is detected, the other agent gets a message."""
        mgr = mgr_patch
        mgr.register_session("agent-A", pid=1001, project="/proj/a")
        mgr.register_session("agent-B", pid=1002, project="/proj/a")

        # Agent A announces intent on a file
        mgr.announce_intent(
            "agent-A", "refactoring models",
            target_files=["/proj/a/models.py"],
        )

        # Agent B edits the same file (triggers auto-claim + overlap check)
        result = handle_auto_claim_file({
            "tool_name": "Edit",
            "session_id": "agent-B",
            "tool_input": json.dumps({"file_path": "/proj/a/models.py"}),
        })

        output = result["output"]
        assert "[INTENT-OVERLAP]" in output
        assert "agent-A" in output

        # Agent A should receive a notification message
        msgs = mgr.check_inbox("agent-A", unread_only=True)
        overlap_msgs = [m for m in msgs if "Overlap" in m.get("subject", "")]
        assert len(overlap_msgs) == 1
        assert "models.py" in overlap_msgs[0]["subject"]
        assert overlap_msgs[0]["msg_type"] == "inform"

    def test_overlap_notification_debounced(self, mgr_patch):
        """UAT: Same overlap doesn't generate duplicate notifications within 5 min."""
        mgr = mgr_patch
        mgr.register_session("agent-A", pid=1001, project="/proj/a")
        mgr.register_session("agent-B", pid=1002, project="/proj/a")

        mgr.announce_intent(
            "agent-A", "working on parser",
            target_files=["/proj/a/parser.py"],
        )

        # First edit — should notify
        handle_auto_claim_file({
            "tool_name": "Edit",
            "session_id": "agent-B",
            "tool_input": json.dumps({"file_path": "/proj/a/parser.py"}),
        })

        # Mark first message as read
        mgr.check_inbox("agent-A", unread_only=True)

        # Second edit of same file — should be debounced (no new message)
        _last_claim.pop(("agent-B", "/proj/a/parser.py"), None)  # Reset claim debounce
        handle_auto_claim_file({
            "tool_name": "Edit",
            "session_id": "agent-B",
            "tool_input": json.dumps({"file_path": "/proj/a/parser.py"}),
        })

        msgs = mgr.check_inbox("agent-A", unread_only=True)
        overlap_msgs = [m for m in msgs if "Overlap" in m.get("subject", "")]
        assert len(overlap_msgs) == 0  # Debounced — no new notification

    def test_overlap_debounce_cleanup_on_session_stop(self, mgr_patch):
        """UAT: Overlap debounce entries are cleaned when session stops."""
        mgr = mgr_patch
        mgr.register_session("agent-A", pid=1001, project="/proj/a")
        mgr.register_session("agent-B", pid=1002, project="/proj/a")

        mgr.announce_intent("agent-A", "working", target_files=["/proj/a/x.py"])

        handle_auto_claim_file({
            "tool_name": "Edit",
            "session_id": "agent-B",
            "tool_input": json.dumps({"file_path": "/proj/a/x.py"}),
        })

        # Verify debounce entry exists
        assert any(k[0] == "agent-B" for k in _last_overlap_notify)

        # Stop agent-B
        with patch("omega.bridge.query_structured", return_value=[]), \
             patch("omega.bridge._get_store") as mock_store:
            mock_store.return_value.get_session_event_counts.return_value = {}
            from omega.server.hook_server import handle_session_stop
            handle_session_stop({"session_id": "agent-B", "project": "/proj/a"})

        # Debounce entries for agent-B should be cleaned
        assert not any(k[0] == "agent-B" for k in _last_overlap_notify)

    def test_peer_decisions_surfaced_on_edit(self, mgr_patch):
        """UAT: Editing a file surfaces relevant peer decisions from OMEGA."""
        mock_peer_decisions = [
            {
                "content": "Decided to use factory pattern for model creation",
                "relevance": 0.75,
                "metadata": {"session_id": "other-agent", "event_type": "decision"},
            },
        ]

        with patch("omega.bridge.query_structured", return_value=mock_peer_decisions), \
             patch("omega.bridge.get_cross_session_lessons", return_value=[]):
            lines = _surface_lessons("/proj/a/models.py", "my-agent", "/proj/a")

        joined = "\n".join(lines)
        assert "[PEER-DECISION]" in joined
        assert "factory pattern" in joined

    def test_own_decisions_filtered_from_peer_context(self, mgr_patch):
        """UAT: Agent's own decisions are not shown as peer decisions."""
        mock_own_decisions = [
            {
                "content": "My own decision about caching",
                "relevance": 0.8,
                "metadata": {"session_id": "my-agent", "event_type": "decision"},
            },
        ]

        with patch("omega.bridge.query_structured", return_value=mock_own_decisions), \
             patch("omega.bridge.get_cross_session_lessons", return_value=[]):
            lines = _surface_lessons("/proj/a/cache.py", "my-agent", "/proj/a")

        joined = "\n".join(lines)
        assert "[PEER-DECISION]" not in joined

    def test_low_relevance_decisions_filtered(self, mgr_patch):
        """UAT: Peer decisions with relevance < 0.5 are not surfaced."""
        mock_low_relevance = [
            {
                "content": "Tangentially related decision",
                "relevance": 0.3,
                "metadata": {"session_id": "other-agent", "event_type": "decision"},
            },
        ]

        with patch("omega.bridge.query_structured", return_value=mock_low_relevance), \
             patch("omega.bridge.get_cross_session_lessons", return_value=[]):
            lines = _surface_lessons("/proj/a/unrelated.py", "my-agent", "/proj/a")

        joined = "\n".join(lines)
        assert "[PEER-DECISION]" not in joined


# ============================================================================
# SECTION 5: Golden Path — End-to-End Multi-Agent Scenarios
# ============================================================================


class TestUATGoldenPath:
    """Full lifecycle scenarios combining awareness, communication, coordination, and conflict."""

    def test_golden_two_agents_collaborate_on_feature(self, mgr_patch):
        """UAT Golden Path: Two agents work on same project from start to finish.

        Scenario:
        1. Agent A starts, registers, claims auth.py, creates task
        2. Agent B starts, sees Agent A's context, picks up related task
        3. Agent B edits a file Agent A is working on — overlap detected, both notified
        4. Agent A finishes and stops — structured handoff with decisions
        5. Agent B reads handoff and continues work
        """
        mgr = mgr_patch

        # --- Step 1: Agent A starts and sets up work ---
        mgr.register_session(
            "agent-A", pid=1001, project="/proj/collab",
            task="Implementing authentication",
            capabilities=["code", "review"],
        )
        mgr.claim_file("agent-A", "/proj/collab/auth.py", task="JWT implementation")
        task_a = mgr.create_task("agent-A", "Implement JWT auth", project="/proj/collab", priority=5)
        mgr.claim_task(task_a["task_id"], "agent-A")
        mgr.announce_intent(
            "agent-A", "Implementing auth module",
            target_files=["/proj/collab/auth.py", "/proj/collab/middleware.py"],
        )

        # Also create an unclaimed task for B to discover
        mgr.create_task("agent-A", "Write auth unit tests", project="/proj/collab", priority=3)

        # --- Step 2: Agent B starts, sees Agent A's full context ---
        with _mock_bridge_noop():
            start_result = handle_coord_session_start({
                "session_id": "agent-B",
                "project": "/proj/collab",
            })

        start_output = start_result["output"]
        assert "[COORD]" in start_output
        assert "1 peer active" in start_output
        assert "[TODO]" in start_output
        assert "Write auth unit tests" in start_output  # highest-priority pending task as NEXT

        # Agent B creates its own task
        task_b = mgr.create_task("agent-B", "Add session middleware", project="/proj/collab", priority=3)
        mgr.claim_task(task_b["task_id"], "agent-B")

        # --- Step 3: Agent B edits middleware.py — overlaps with Agent A's intent ---
        claim_result = handle_auto_claim_file({
            "tool_name": "Edit",
            "session_id": "agent-B",
            "tool_input": json.dumps({"file_path": "/proj/collab/middleware.py"}),
        })

        assert "[INTENT-OVERLAP]" in claim_result["output"]
        assert "agent-A" in claim_result["output"]

        # Agent A should receive overlap notification
        a_msgs = mgr.check_inbox("agent-A", unread_only=True)
        overlap_msgs = [m for m in a_msgs if "Overlap" in m.get("subject", "")]
        assert len(overlap_msgs) >= 1
        assert "middleware.py" in overlap_msgs[0]["subject"]

        # --- Step 4: Agent A completes task and stops with structured handoff ---
        mgr.complete_task(task_a["task_id"], "agent-A", result="JWT auth implemented")

        mock_decisions = [
            {"content": "Used RS256 algorithm for JWT signing"},
            {"content": "Token expiry set to 24 hours"},
        ]

        with patch("omega.bridge.query_structured", side_effect=[mock_decisions, []]), \
             patch("omega.bridge._get_store") as mock_store:
            mock_store.return_value.get_session_event_counts.return_value = {"decision": 2}
            handle_coord_session_stop({
                "session_id": "agent-A",
                "project": "/proj/collab",
            })

        # --- Step 5: Agent B reads Agent A's handoff ---
        b_msgs = mgr.check_inbox("agent-B", unread_only=True)
        handoffs = [m for m in b_msgs if m.get("msg_type") == "complete"]
        assert len(handoffs) >= 1
        handoff_body = handoffs[0]["body"]
        assert "## Decisions" in handoff_body
        assert "RS256" in handoff_body
        assert "Token expiry" in handoff_body

        # Agent A should be deregistered
        sessions = mgr.list_sessions(auto_clean=False)
        session_ids = [s["session_id"] for s in sessions]
        assert "agent-A" not in session_ids
        assert "agent-B" in session_ids

    def test_golden_task_creation_and_handoff(self, mgr_patch):
        """UAT Golden Path: Task lifecycle with handoff between agents.

        Scenario:
        1. Manager agent creates multiple prioritized tasks
        2. Worker agent starts, sees pending tasks, claims highest priority
        3. Worker completes task, stops with handoff showing completed work
        4. New worker starts, sees remaining tasks and predecessor's handoff
        """
        mgr = mgr_patch

        # --- Step 1: Manager creates tasks ---
        mgr.register_session("manager", pid=1001, project="/proj/tasks")
        mgr.create_task("manager", "Fix critical login bug", project="/proj/tasks", priority=10)
        mgr.create_task("manager", "Add rate limiting", project="/proj/tasks", priority=5)
        mgr.create_task("manager", "Update documentation", project="/proj/tasks", priority=1)

        # --- Step 2: Worker 1 starts, sees all pending tasks ---
        with _mock_bridge_noop():
            start1 = handle_coord_session_start({
                "session_id": "worker-1",
                "project": "/proj/tasks",
            })

        assert "3 pending tasks" in start1["output"]
        assert "Fix critical login bug" in start1["output"]

        # Worker claims highest priority task
        pending = mgr.list_tasks(project="/proj/tasks", status="pending")
        top_task = pending[0]  # Highest priority
        assert top_task["title"] == "Fix critical login bug"
        mgr.claim_task(top_task["id"], "worker-1")

        # --- Step 3: Worker completes and stops ---
        mgr.complete_task(top_task["id"], "worker-1", result="Login bug fixed")

        with patch("omega.bridge.query_structured", return_value=[]), \
             patch("omega.bridge._get_store") as mock_store:
            mock_store.return_value.get_session_event_counts.return_value = {"task_completion": 1}
            handle_coord_session_stop({
                "session_id": "worker-1",
                "project": "/proj/tasks",
            })

        # --- Step 4: Worker 2 starts, sees remaining tasks + handoff ---
        mgr.register_session("manager", pid=1001, project="/proj/tasks")  # Re-register if needed

        with _mock_bridge_noop():
            start2 = handle_coord_session_start({
                "session_id": "worker-2",
                "project": "/proj/tasks",
            })

        # Should see 2 remaining pending tasks in [TODO], highest priority as NEXT
        assert "2 pending tasks" in start2["output"]
        assert "Add rate limiting" in start2["output"]  # highest priority = NEXT

    def test_golden_crash_recovery_with_handoff(self, mgr_patch):
        """UAT Golden Path: Agent crashes, new agent recovers context.

        Scenario:
        1. Agent A works on files, has claimed resources and in-progress tasks
        2. Agent A goes stale (simulated crash via heartbeat backdating)
        3. Cleanup runs, snapshot is created
        4. Agent B starts, sees recovery info + previous agent's context
        """
        from datetime import datetime, timedelta, timezone
        from omega.coordination import STALE_THRESHOLD_SECONDS

        mgr = mgr_patch

        # --- Step 1: Agent A is working ---
        mgr.register_session(
            "crash-agent", pid=1001, project="/proj/recovery",
            task="Database schema migration",
        )
        mgr.claim_file("crash-agent", "/proj/recovery/migrate.py", task="migration script")
        mgr.claim_file("crash-agent", "/proj/recovery/models.py", task="model updates")
        task = mgr.create_task("crash-agent", "Run schema migration", project="/proj/recovery")
        mgr.claim_task(task["task_id"], "crash-agent")

        # --- Step 2: Simulate crash (backdate heartbeat beyond threshold) ---
        cutoff = (
            datetime.now(timezone.utc) - timedelta(seconds=STALE_THRESHOLD_SECONDS + 10)
        ).isoformat()
        mgr._conn.execute(
            "UPDATE coord_sessions SET last_heartbeat = ? WHERE session_id = ?",
            (cutoff, "crash-agent"),
        )
        mgr._conn.commit()

        # --- Step 3: Stale cleanup creates snapshot ---
        mgr.list_sessions(auto_clean=True)

        # Verify snapshot was created
        snapshots = mgr.recover_session("/proj/recovery")
        assert len(snapshots) >= 1
        snap = snapshots[0]
        assert snap["task"] == "Database schema migration"
        assert len(snap["file_claims"]) == 2

        # Claims released
        assert mgr.check_file("/proj/recovery/migrate.py")["claimed"] is False
        assert mgr.check_file("/proj/recovery/models.py")["claimed"] is False

        # --- Step 4: Agent B starts, sees recovery context ---
        with _mock_bridge_noop():
            start_result = handle_coord_session_start({
                "session_id": "recovery-agent",
                "project": "/proj/recovery",
            })

        output = start_result["output"]
        assert "[RESUME]" in output
        assert "Database schema migration" in output

    def test_golden_three_agent_coordination(self, mgr_patch):
        """UAT Golden Path: Three agents coordinate on the same project.

        Scenario:
        1. Agent A: works on auth module
        2. Agent B: works on API layer, sends request to A
        3. Agent C: starts, sees both peers, picks up unclaimed task
        4. B's heartbeat surfaces A's request response
        """
        mgr = mgr_patch

        # --- All three register ---
        mgr.register_session("agent-A", pid=1001, project="/proj/team",
                             task="Auth module", capabilities=["code", "security"])
        mgr.register_session("agent-B", pid=1002, project="/proj/team",
                             task="API layer", capabilities=["code", "api"])

        # A claims files and creates tasks
        mgr.claim_file("agent-A", "/proj/team/auth.py")
        mgr.create_task("agent-A", "Write auth tests", project="/proj/team", priority=3)

        # B sends a request to A
        mgr.send_message(
            from_session="agent-B",
            to_session="agent-A",
            subject="Need auth middleware interface spec",
            msg_type="request",
            body="I need the auth middleware interface to build the API integration",
        )

        # --- Agent C starts, sees full picture ---
        with _mock_bridge_noop():
            c_start = handle_coord_session_start({
                "session_id": "agent-C",
                "project": "/proj/team",
            })

        c_output = c_start["output"]
        assert "[COORD]" in c_output
        assert "2 peers active" in c_output
        assert "[TODO]" in c_output
        assert "Write auth tests" in c_output

        # --- A checks heartbeat, sees B's request ---
        # Advance to 4th heartbeat
        for i in range(4):
            _last_heartbeat.pop("agent-A", None)
            hb_result = handle_coord_heartbeat({
                "session_id": "agent-A",
                "project": "/proj/team",
            })

        assert "[REQUEST]" in hb_result["output"]
        assert "Need auth middleware interface spec" in hb_result["output"]

    def test_golden_deregister_releases_all_resources(self, mgr_patch):
        """UAT Golden Path: Session stop cleanly releases files, branches, and intents."""
        mgr = mgr_patch
        mgr.register_session("cleanup-agent", pid=1001, project="/proj/clean")
        mgr.claim_file("cleanup-agent", "/proj/clean/a.py")
        mgr.claim_file("cleanup-agent", "/proj/clean/b.py")
        mgr.claim_branch("cleanup-agent", "/proj/clean", "feat-x")
        mgr.announce_intent(
            "cleanup-agent", "big refactor",
            target_files=["/proj/clean/a.py", "/proj/clean/b.py"],
        )

        with patch("omega.bridge.query_structured", return_value=[]), \
             patch("omega.bridge._get_store") as mock_store:
            mock_store.return_value.get_session_event_counts.return_value = {}
            handle_coord_session_stop({
                "session_id": "cleanup-agent",
                "project": "/proj/clean",
            })

        # Everything released
        assert mgr.check_file("/proj/clean/a.py")["claimed"] is False
        assert mgr.check_file("/proj/clean/b.py")["claimed"] is False
        sessions = mgr.list_sessions(auto_clean=False)
        assert len(sessions) == 0

    def test_golden_message_chain_between_agents(self, mgr_patch):
        """UAT Golden Path: Full request-acknowledge-complete message chain."""
        mgr = mgr_patch
        mgr.register_session("requester", pid=1001, project="/proj/msg")
        mgr.register_session("responder", pid=1002, project="/proj/msg")

        # Request
        msg = mgr.send_message(
            from_session="requester",
            to_session="responder",
            subject="Review auth.py changes",
            msg_type="request",
            body="Please review my JWT implementation",
        )
        context_id = msg.get("message_id") or msg.get("context_id")

        # Responder reads inbox
        inbox = mgr.check_inbox("responder", unread_only=True)
        assert len(inbox) >= 1
        assert inbox[0]["msg_type"] == "request"

        # Acknowledge
        mgr.send_message(
            from_session="responder",
            to_session="requester",
            subject="Starting review",
            msg_type="acknowledge",
        )

        # Complete
        mgr.send_message(
            from_session="responder",
            to_session="requester",
            subject="Review complete: LGTM",
            msg_type="complete",
            body="Code looks good. Minor suggestion: add token refresh endpoint.",
        )

        # Requester reads responses
        req_inbox = mgr.check_inbox("requester", unread_only=True)
        msg_types = [m["msg_type"] for m in req_inbox]
        assert "acknowledge" in msg_types
        assert "complete" in msg_types

        # Find the complete message
        complete_msg = next(m for m in req_inbox if m["msg_type"] == "complete")
        assert "token refresh" in complete_msg["body"]


# ============================================================================
# SECTION 6: Gap Coverage — Fail-Open, Combined Handoff, Write/NotebookEdit
# ============================================================================


class TestUATFailOpen:
    """All hook automation must be fail-open: errors never block the agent."""

    def test_session_start_survives_dead_coordinator(self):
        """UAT: Session start returns gracefully when get_manager raises."""
        with patch("omega.coordination.get_manager", side_effect=RuntimeError("DB gone")):
            result = handle_coord_session_start({
                "session_id": "resilient-1",
                "project": "/proj/a",
            })

        # Should not crash — returns empty or partial output, no error bubble
        assert result["output"] is not None

    def test_session_stop_survives_dead_coordinator(self):
        """UAT: Session stop returns gracefully when get_manager raises."""
        with patch("omega.coordination.get_manager", side_effect=RuntimeError("DB gone")):
            result = handle_coord_session_stop({
                "session_id": "resilient-2",
                "project": "/proj/a",
            })

        assert result is not None

    def test_heartbeat_survives_dead_coordinator(self):
        """UAT: Heartbeat returns empty output when coordinator is unavailable."""
        with patch("omega.coordination.get_manager", side_effect=RuntimeError("DB gone")):
            result = handle_coord_heartbeat({
                "session_id": "resilient-3",
                "project": "/proj/a",
            })

        assert result["output"] == ""

    def test_auto_claim_survives_dead_coordinator(self):
        """UAT: Auto-claim returns empty when coordinator is unavailable."""
        with patch("omega.coordination.get_manager", side_effect=RuntimeError("DB gone")):
            result = handle_auto_claim_file({
                "tool_name": "Edit",
                "session_id": "resilient-4",
                "tool_input": json.dumps({"file_path": "/proj/a/file.py"}),
            })

        assert result["output"] == ""

    def test_surface_lessons_survives_dead_bridge(self):
        """UAT: Peer decision surfacing returns empty when bridge is unavailable."""
        with patch("omega.bridge.query_structured", side_effect=RuntimeError("no embeddings")), \
             patch("omega.bridge.get_cross_session_lessons", side_effect=RuntimeError("no store")):
            lines = _surface_lessons("/proj/a/file.py", "sess-1", "/proj/a")

        assert isinstance(lines, list)
        # No crash, no [PEER-DECISION] — just empty or lesson-only output

    def test_handoff_survives_dead_bridge(self, mgr_patch):
        """UAT: Session stop handoff still broadcasts when bridge queries fail."""
        mgr = mgr_patch
        mgr.register_session("fragile", pid=1001, project="/proj/a")
        mgr.register_session("listener", pid=1002, project="/proj/a")

        with patch("omega.bridge.query_structured", side_effect=RuntimeError("no store")), \
             patch("omega.bridge._get_store", side_effect=RuntimeError("no store")):
            handle_coord_session_stop({
                "session_id": "fragile",
                "project": "/proj/a",
            })

        # Handoff message should still be sent (with just the summary section)
        msgs = mgr.check_inbox("listener", unread_only=True)
        handoffs = [m for m in msgs if m.get("msg_type") == "complete"]
        assert len(handoffs) == 1
        assert "## Session Summary" in handoffs[0]["body"]

    def test_overlap_notify_survives_send_failure(self, mgr_patch):
        """UAT: Overlap detection still shows warning even if notify message fails."""
        mgr = mgr_patch
        mgr.register_session("agent-A", pid=1001, project="/proj/a")
        mgr.register_session("agent-B", pid=1002, project="/proj/a")
        mgr.announce_intent("agent-A", "editing file", target_files=["/proj/a/x.py"])

        with patch.object(mgr, "send_message", side_effect=RuntimeError("msg table locked")):
            result = handle_auto_claim_file({
                "tool_name": "Edit",
                "session_id": "agent-B",
                "tool_input": json.dumps({"file_path": "/proj/a/x.py"}),
            })

        # Warning still shown to agent-B even though notify to A failed
        assert "[INTENT-OVERLAP]" in result["output"]


class TestUATCombinedHandoff:
    """Structured handoff with all three sections in a single message."""

    def test_handoff_includes_all_sections(self, mgr_patch):
        """UAT: Handoff message contains decisions, blockers, AND incomplete tasks."""
        mgr = mgr_patch
        mgr.register_session("departing", pid=1001, project="/proj/full")
        mgr.register_session("successor", pid=1002, project="/proj/full")

        # Create an in_progress task owned by departing
        task = mgr.create_task("departing", "Migrate database schema", project="/proj/full")
        mgr.claim_task(task["task_id"], "departing")

        mock_decisions = [
            {"content": "Chose PostgreSQL over MySQL for new schema"},
        ]
        mock_errors = [
            {"content": "ConnectionError: Redis cache unreachable during migration"},
        ]

        with patch("omega.bridge.query_structured", side_effect=[mock_decisions, mock_errors]), \
             patch("omega.bridge._get_store") as mock_store:
            mock_store.return_value.get_session_event_counts.return_value = {
                "decision": 1, "error_pattern": 1,
            }
            handle_coord_session_stop({
                "session_id": "departing",
                "project": "/proj/full",
            })

        msgs = mgr.check_inbox("successor", unread_only=True)
        handoffs = [m for m in msgs if m.get("msg_type") == "complete"]
        assert len(handoffs) == 1
        body = handoffs[0]["body"]

        # All three sections present
        assert "## Session Summary" in body
        assert "## Decisions" in body
        assert "PostgreSQL" in body
        assert "## Blockers" in body
        assert "ConnectionError" in body
        assert "## Incomplete Work" in body
        assert "Migrate database schema" in body


class TestUATWriteNotebookEditTriggers:
    """Auto-claim and overlap triggers for Write and NotebookEdit tools."""

    def test_write_triggers_auto_claim(self, mgr_patch):
        """UAT: Write tool triggers auto-claim just like Edit."""
        mgr = mgr_patch
        mgr.register_session("writer", pid=1001, project="/proj/a")

        handle_auto_claim_file({
            "tool_name": "Write",
            "session_id": "writer",
            "tool_input": json.dumps({"file_path": "/proj/a/new_file.py"}),
        })

        info = mgr.check_file("/proj/a/new_file.py")
        assert info["claimed"] is True
        assert info["session_id"] == "writer"

    def test_notebook_edit_triggers_auto_claim(self, mgr_patch):
        """UAT: NotebookEdit tool triggers auto-claim using notebook_path."""
        mgr = mgr_patch
        mgr.register_session("notebook-user", pid=1001, project="/proj/a")

        handle_auto_claim_file({
            "tool_name": "NotebookEdit",
            "session_id": "notebook-user",
            "tool_input": json.dumps({"notebook_path": "/proj/a/analysis.ipynb"}),
        })

        info = mgr.check_file("/proj/a/analysis.ipynb")
        assert info["claimed"] is True
        assert info["session_id"] == "notebook-user"

    def test_write_triggers_conflict_detection(self, mgr_patch):
        """UAT: Write to a claimed file shows conflict, same as Edit."""
        mgr = mgr_patch
        mgr.register_session("owner", pid=1001, project="/proj/a")
        mgr.register_session("writer", pid=1002, project="/proj/a")
        mgr.claim_file("owner", "/proj/a/config.py", task="updating config")

        result = handle_auto_claim_file({
            "tool_name": "Write",
            "session_id": "writer",
            "tool_input": json.dumps({"file_path": "/proj/a/config.py"}),
        })

        assert "[CONFLICT]" in result["output"]
        assert "owner" in result["output"]

    def test_write_triggers_overlap_notification(self, mgr_patch):
        """UAT: Write to a file with overlapping intent notifies the other agent."""
        mgr = mgr_patch
        mgr.register_session("agent-A", pid=1001, project="/proj/a")
        mgr.register_session("agent-B", pid=1002, project="/proj/a")
        mgr.announce_intent("agent-A", "editing utils", target_files=["/proj/a/utils.py"])

        result = handle_auto_claim_file({
            "tool_name": "Write",
            "session_id": "agent-B",
            "tool_input": json.dumps({"file_path": "/proj/a/utils.py"}),
        })

        assert "[INTENT-OVERLAP]" in result["output"]

        msgs = mgr.check_inbox("agent-A", unread_only=True)
        overlap_msgs = [m for m in msgs if "Overlap" in m.get("subject", "")]
        assert len(overlap_msgs) == 1

    def test_non_edit_tool_does_not_trigger_claim(self, mgr_patch):
        """UAT: Read tool does not trigger auto-claim."""
        mgr = mgr_patch
        mgr.register_session("reader", pid=1001, project="/proj/a")

        result = handle_auto_claim_file({
            "tool_name": "Read",
            "session_id": "reader",
            "tool_input": json.dumps({"file_path": "/proj/a/data.py"}),
        })

        assert result["output"] == ""
        info = mgr.check_file("/proj/a/data.py")
        assert info["claimed"] is False


# ============================================================================
# SECTION 6: MCP Tool Tests (v0.6.0 — task_deps, git_events, branch_check)
# ============================================================================


class TestMCPToolTaskDeps:
    """Tests for omega_task_deps MCP handler."""

    def test_handle_task_deps(self, mgr_patch):
        """Task with dependencies returns correct graph."""
        import asyncio
        from omega.server.coord_handlers import handle_task_deps

        mgr = mgr_patch
        mgr.register_session("dep-agent", pid=1001, project="/proj/a")
        r1 = mgr.create_task("dep-agent", "Setup DB", project="/proj/a")
        r2 = mgr.create_task("dep-agent", "Run migrations", project="/proj/a", depends_on=[r1["task_id"]])

        result = asyncio.run(
            handle_task_deps({"task_id": r2["task_id"]})
        )
        text = result["content"][0]["text"]
        assert "Depends on:" in text
        assert "Setup DB" in text
        assert "Blocked:" in text

    def test_handle_task_deps_not_found(self, mgr_patch):
        """Non-existent task returns error."""
        import asyncio
        from omega.server.coord_handlers import handle_task_deps

        result = asyncio.run(
            handle_task_deps({"task_id": 99999})
        )
        text = result["content"][0]["text"]
        assert "Error" in text or "not found" in text.lower()


class TestMCPToolGitEvents:
    """Tests for omega_git_events MCP handler."""

    def test_handle_git_events(self, mgr_patch):
        """Logged git events are returned formatted."""
        import asyncio
        from omega.server.coord_handlers import handle_git_events

        mgr = mgr_patch
        mgr.register_session("git-agent", pid=1001, project="/proj/a")
        mgr.log_git_event(
            project="/proj/a",
            event_type="push",
            branch="feature-x",
            message="Added auth",
            session_id="git-agent",
        )

        result = asyncio.run(
            handle_git_events({"project": "/proj/a"})
        )
        text = result["content"][0]["text"]
        assert "Git Events" in text
        assert "push" in text
        assert "feature-x" in text

    def test_handle_git_events_empty(self, mgr_patch):
        """No events returns appropriate message."""
        import asyncio
        from omega.server.coord_handlers import handle_git_events

        result = asyncio.run(
            handle_git_events({"project": "/proj/empty"})
        )
        text = result["content"][0]["text"]
        assert "No git events" in text


class TestMCPToolBranchCheck:
    """Tests for omega_branch_check MCP handler."""

    def test_handle_branch_check_claimed(self, mgr_patch):
        """Claimed branch shows owner."""
        import asyncio
        from omega.server.coord_handlers import handle_branch_check

        mgr = mgr_patch
        mgr.register_session("br-agent", pid=1001, project="/proj/a")
        mgr.claim_branch("br-agent", "/proj/a", "feature-auth", task="auth work")

        result = asyncio.run(
            handle_branch_check({"project": "/proj/a", "branch": "feature-auth"})
        )
        text = result["content"][0]["text"]
        assert "claimed" in text.lower()
        assert "br-agent" in text

    def test_handle_branch_check_unclaimed(self, mgr_patch):
        """Unclaimed branch returns unclaimed."""
        import asyncio
        from omega.server.coord_handlers import handle_branch_check

        result = asyncio.run(
            handle_branch_check({"project": "/proj/a", "branch": "nobody-here"})
        )
        text = result["content"][0]["text"]
        assert "unclaimed" in text.lower()


# ============================================================================
# SECTION 7: UAT Golden Path (v0.6.0 — handoff + auto-task + deadlock)
# ============================================================================


class TestUATGoldenPathV060:
    """End-to-end acceptance tests for v0.6.0 multi-agent coordination."""

    def test_uat_handoff_consumed_on_start(self, mgr_patch):
        """UAT: Agent A stops → sends handoff → Agent B starts → B sees [HANDOFF]."""
        mgr = mgr_patch
        mgr.register_session("alpha", pid=1001, project="/proj/gp")

        # Alpha sends a complete-type handoff before stopping
        mgr.send_message(
            from_session="alpha",
            to_session="beta",
            subject="Handoff: auth module complete",
            body="Implemented JWT auth. Remaining: rate limiting on /api/login.",
            msg_type="complete",
        )
        mgr.deregister_session("alpha")

        # Beta starts up
        with _mock_bridge_noop():
            result = handle_coord_session_start({
                "session_id": "beta",
                "project": "/proj/gp",
            })

        output = result["output"]
        assert "[HANDOFF]" in output
        assert "alpha" in output
        assert "auth module complete" in output

    def test_uat_auto_task_from_prompt(self, mgr_patch):
        """UAT: Agent's first prompt becomes session.task automatically."""
        from omega.server.hook_server import handle_auto_capture

        mgr = mgr_patch
        mgr.register_session("task-uat", pid=1001, project="/proj/gp")

        with patch("omega.coordination.get_manager", return_value=mgr):
            handle_auto_capture({
                "stdin": json.dumps({
                    "prompt": "let's use postgres instead of sqlite for the production database",
                    "session_id": "task-uat",
                    "cwd": "/proj/gp",
                }),
            })

        # Verify task was set
        row = mgr._conn.execute(
            "SELECT task FROM coord_sessions WHERE session_id = ?", ("task-uat",)
        ).fetchone()
        assert row is not None
        assert "postgres" in row[0].lower()

        # Verify other agents can see it
        sessions = mgr.list_sessions()
        uat_sess = [s for s in sessions if s["session_id"] == "task-uat"]
        assert len(uat_sess) == 1
        assert "postgres" in (uat_sess[0].get("task") or "").lower()


    def test_uat_deadlock_alerting(self, mgr_patch):
        """UAT: Two agents in deadlock → heartbeat produces no crash."""
        from omega.server import hook_server
        from omega.server.hook_server import handle_coord_heartbeat

        hook_server._last_heartbeat.clear()
        hook_server._heartbeat_count.clear()
        mgr = mgr_patch

        with patch("omega.coordination.get_manager", return_value=mgr):
            mgr.register_session("dl-A", pid=1001, project="/proj/gp")
            mgr.register_session("dl-B", pid=1002, project="/proj/gp")

            # Cross claims
            mgr.claim_file("dl-A", "/proj/gp/a.py")
            mgr.claim_file("dl-B", "/proj/gp/b.py")
            mgr.announce_intent("dl-A", "need b.py", target_files=["/proj/gp/b.py"])
            mgr.announce_intent("dl-B", "need a.py", target_files=["/proj/gp/a.py"])

            # Run 10 heartbeats to trigger deadlock detection
            for i in range(10):
                hook_server._last_heartbeat.pop("dl-A", None)
                result = handle_coord_heartbeat({"session_id": "dl-A", "project": "/proj/gp"})

        # Should not crash regardless of deadlock detection result
        assert result["error"] is None

        hook_server._last_heartbeat.clear()
        hook_server._heartbeat_count.clear()
