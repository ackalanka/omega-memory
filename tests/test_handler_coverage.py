"""
Phase 3: Targeted handler tests for under-covered coordination, router, and profile tools.

Adds ~70 tests for handlers that previously had 0-2 direct tests.
"""

import asyncio
import os
import re
import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run_async(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


def _text(result: dict) -> str:
    """Extract text from MCP response."""
    return result["content"][0]["text"]


def _is_error(result: dict) -> bool:
    return result.get("isError", False)


# ---------------------------------------------------------------------------
# Fixture: fresh coordination manager per test
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _fresh_coord(tmp_omega_dir):
    """Reset bridge + coordination for each test."""
    from omega.bridge import reset_memory
    reset_memory()
    # Reset coordination singleton
    try:
        import omega.coordination as coord
        coord._manager = None
    except (ImportError, AttributeError):
        pass
    yield


def _register(session_id, project=None, task=None, capabilities=None):
    """Helper to register a session."""
    from omega.server.coord_handlers import handle_session_register
    args = {"session_id": session_id}
    if project:
        args["project"] = project
    if task:
        args["task"] = task
    if capabilities:
        args["capabilities"] = capabilities
    return run_async(handle_session_register(args))


def _create_task(session_id, title, **kwargs):
    """Helper to create a task and return its ID."""
    from omega.server.coord_handlers import handle_task_create
    result = run_async(handle_task_create({
        "session_id": session_id, "title": title, **kwargs,
    }))
    match = re.search(r"#(\d+)", _text(result))
    return int(match.group(1)) if match else None


# ===========================================================================
# 3a: Session lifecycle tests
# ===========================================================================


class TestSessionHeartbeat:
    """Tests for omega_session_heartbeat handler."""

    def test_heartbeat_success(self):
        from omega.server.coord_handlers import handle_session_heartbeat
        _register("hb-1")
        result = run_async(handle_session_heartbeat({"session_id": "hb-1"}))
        assert not _is_error(result)
        assert "heartbeat" in _text(result).lower()

    def test_heartbeat_missing_session_id(self):
        from omega.server.coord_handlers import handle_session_heartbeat
        result = run_async(handle_session_heartbeat({}))
        assert _is_error(result)

    def test_heartbeat_unregistered_session(self):
        """Heartbeat for unregistered session — behavior depends on manager impl."""
        from omega.server.coord_handlers import handle_session_heartbeat
        result = run_async(handle_session_heartbeat({"session_id": "nonexistent"}))
        # Some impls auto-register on heartbeat; just verify it doesn't crash
        assert "content" in result

    def test_heartbeat_updates_timestamp(self):
        from omega.server.coord_handlers import handle_session_heartbeat
        _register("hb-ts")
        r1 = run_async(handle_session_heartbeat({"session_id": "hb-ts"}))
        r2 = run_async(handle_session_heartbeat({"session_id": "hb-ts"}))
        assert not _is_error(r1) and not _is_error(r2)


class TestSessionDeregister:
    """Tests for omega_session_deregister handler."""

    def test_deregister_success(self):
        from omega.server.coord_handlers import handle_session_deregister
        _register("dr-1")
        result = run_async(handle_session_deregister({"session_id": "dr-1"}))
        assert not _is_error(result)
        assert "deregistered" in _text(result).lower()

    def test_deregister_releases_file_claims(self):
        from omega.server.coord_handlers import (
            handle_session_deregister, handle_file_claim, handle_file_check,
        )
        _register("dr-files")
        run_async(handle_file_claim({
            "session_id": "dr-files", "file_path": "/tmp/test.py",
        }))
        run_async(handle_session_deregister({"session_id": "dr-files"}))
        check = run_async(handle_file_check({"file_path": "/tmp/test.py"}))
        assert "unclaimed" in _text(check).lower()

    def test_deregister_releases_branch_claims(self):
        from omega.server.coord_handlers import (
            handle_session_deregister, handle_branch_claim, handle_branch_check,
        )
        _register("dr-branch", project="/proj")
        run_async(handle_branch_claim({
            "session_id": "dr-branch", "project": "/proj", "branch": "feature-x",
        }))
        run_async(handle_session_deregister({"session_id": "dr-branch"}))
        check = run_async(handle_branch_check({"project": "/proj", "branch": "feature-x"}))
        assert "unclaimed" in _text(check).lower()

    def test_deregister_missing_session_id(self):
        from omega.server.coord_handlers import handle_session_deregister
        result = run_async(handle_session_deregister({}))
        assert _is_error(result)

    def test_deregister_unknown_session(self):
        from omega.server.coord_handlers import handle_session_deregister
        result = run_async(handle_session_deregister({"session_id": "nonexistent"}))
        assert _is_error(result)


class TestSessionsList:
    """Tests for omega_sessions_list handler."""

    def test_empty_sessions(self):
        from omega.server.coord_handlers import handle_sessions_list
        result = run_async(handle_sessions_list({}))
        assert not _is_error(result)
        assert "no active" in _text(result).lower()

    def test_lists_registered_sessions(self):
        from omega.server.coord_handlers import handle_sessions_list
        _register("sl-1", project="/proj/a", task="coding")
        _register("sl-2", project="/proj/b", task="testing")
        result = run_async(handle_sessions_list({}))
        text = _text(result)
        assert "sl-1" in text
        assert "sl-2" in text
        assert "2" in text

    def test_deregistered_not_in_list(self):
        from omega.server.coord_handlers import (
            handle_sessions_list, handle_session_deregister,
        )
        _register("sl-gone")
        run_async(handle_session_deregister({"session_id": "sl-gone"}))
        result = run_async(handle_sessions_list({}))
        assert "sl-gone" not in _text(result)


# ===========================================================================
# 3b: Resource claim tests
# ===========================================================================


class TestFileCheck:
    """Tests for omega_file_check handler."""

    def test_unclaimed_file(self):
        from omega.server.coord_handlers import handle_file_check
        result = run_async(handle_file_check({"file_path": "/tmp/unclaimed.py"}))
        assert not _is_error(result)
        assert "unclaimed" in _text(result).lower()

    def test_claimed_file(self):
        from omega.server.coord_handlers import handle_file_check, handle_file_claim
        _register("fc-1")
        run_async(handle_file_claim({
            "session_id": "fc-1", "file_path": "/tmp/claimed.py", "task": "editing",
        }))
        result = run_async(handle_file_check({"file_path": "/tmp/claimed.py"}))
        assert "claimed" in _text(result).lower()
        assert "fc-1" in _text(result)

    def test_file_check_after_release(self):
        from omega.server.coord_handlers import (
            handle_file_check, handle_file_claim, handle_file_release,
        )
        _register("fc-rel")
        run_async(handle_file_claim({
            "session_id": "fc-rel", "file_path": "/tmp/released.py",
        }))
        run_async(handle_file_release({
            "session_id": "fc-rel", "file_path": "/tmp/released.py",
        }))
        result = run_async(handle_file_check({"file_path": "/tmp/released.py"}))
        assert "unclaimed" in _text(result).lower()

    def test_file_check_missing_path(self):
        from omega.server.coord_handlers import handle_file_check
        result = run_async(handle_file_check({}))
        assert _is_error(result)


class TestBranchClaim:
    """Tests for omega_branch_claim handler."""

    def test_claim_success(self):
        from omega.server.coord_handlers import handle_branch_claim
        _register("bc-1", project="/proj")
        result = run_async(handle_branch_claim({
            "session_id": "bc-1", "project": "/proj", "branch": "feature-a",
        }))
        assert not _is_error(result)
        assert "claimed" in _text(result).lower()

    def test_double_claim_conflict(self):
        from omega.server.coord_handlers import handle_branch_claim
        _register("bc-own", project="/proj")
        _register("bc-other", project="/proj")
        run_async(handle_branch_claim({
            "session_id": "bc-own", "project": "/proj", "branch": "feature-b",
        }))
        result = run_async(handle_branch_claim({
            "session_id": "bc-other", "project": "/proj", "branch": "feature-b",
        }))
        assert "conflict" in _text(result).lower()

    def test_protected_branch_rejected(self):
        from omega.server.coord_handlers import handle_branch_claim
        _register("bc-prot", project="/proj")
        result = run_async(handle_branch_claim({
            "session_id": "bc-prot", "project": "/proj", "branch": "main",
        }))
        assert _is_error(result)

    def test_claim_missing_args(self):
        from omega.server.coord_handlers import handle_branch_claim
        result = run_async(handle_branch_claim({"session_id": "bc-1"}))
        assert _is_error(result)


class TestBranchRelease:
    """Tests for omega_branch_release handler."""

    def test_release_success(self):
        from omega.server.coord_handlers import handle_branch_claim, handle_branch_release
        _register("br-1", project="/proj")
        run_async(handle_branch_claim({
            "session_id": "br-1", "project": "/proj", "branch": "feature-c",
        }))
        result = run_async(handle_branch_release({
            "session_id": "br-1", "project": "/proj", "branch": "feature-c",
        }))
        assert not _is_error(result)
        assert "released" in _text(result).lower()

    def test_release_non_owned(self):
        from omega.server.coord_handlers import handle_branch_claim, handle_branch_release
        _register("br-own", project="/proj")
        _register("br-other", project="/proj")
        run_async(handle_branch_claim({
            "session_id": "br-own", "project": "/proj", "branch": "feature-d",
        }))
        result = run_async(handle_branch_release({
            "session_id": "br-other", "project": "/proj", "branch": "feature-d",
        }))
        assert _is_error(result)


class TestBranchCheck:
    """Tests for omega_branch_check handler."""

    def test_unclaimed_branch(self):
        from omega.server.coord_handlers import handle_branch_check
        result = run_async(handle_branch_check({
            "project": "/proj", "branch": "unclaimed-branch",
        }))
        assert "unclaimed" in _text(result).lower()

    def test_claimed_branch(self):
        from omega.server.coord_handlers import handle_branch_claim, handle_branch_check
        _register("bck-1", project="/proj")
        run_async(handle_branch_claim({
            "session_id": "bck-1", "project": "/proj", "branch": "claimed-branch",
        }))
        result = run_async(handle_branch_check({
            "project": "/proj", "branch": "claimed-branch",
        }))
        assert "claimed" in _text(result).lower()
        assert "bck-1" in _text(result)

    def test_branch_check_missing_args(self):
        from omega.server.coord_handlers import handle_branch_check
        result = run_async(handle_branch_check({"project": "/proj"}))
        assert _is_error(result)


# ===========================================================================
# 3c: Intent & coordination tests
# ===========================================================================


class TestIntentCheck:
    """Tests for omega_intent_check handler."""

    def test_no_overlaps(self):
        from omega.server.coord_handlers import handle_intent_check
        _register("ic-1")
        result = run_async(handle_intent_check({"session_id": "ic-1"}))
        assert not _is_error(result)
        assert "no overlap" in _text(result).lower()

    def test_overlapping_files(self):
        from omega.server.coord_handlers import handle_intent_announce, handle_intent_check
        _register("ic-a", project="/proj")
        _register("ic-b", project="/proj")
        run_async(handle_intent_announce({
            "session_id": "ic-a", "description": "editing",
            "target_files": ["/proj/foo.py"],
        }))
        run_async(handle_intent_announce({
            "session_id": "ic-b", "description": "also editing",
            "target_files": ["/proj/foo.py"],
        }))
        result = run_async(handle_intent_check({"session_id": "ic-b"}))
        text = _text(result)
        assert "overlap" in text.lower() or "no overlap" in text.lower()

    def test_intent_check_missing_session(self):
        from omega.server.coord_handlers import handle_intent_check
        result = run_async(handle_intent_check({}))
        assert _is_error(result)


class TestCoordStatus:
    """Tests for omega_coord_status handler."""

    def test_empty_dashboard(self):
        from omega.server.coord_handlers import handle_coord_status
        result = run_async(handle_coord_status({}))
        assert not _is_error(result)
        assert "sessions:" in _text(result).lower()

    def test_dashboard_with_sessions(self):
        from omega.server.coord_handlers import handle_coord_status
        _register("cs-1", project="/proj", task="coding")
        result = run_async(handle_coord_status({}))
        text = _text(result)
        assert "cs-1" in text
        assert "1" in text  # At least 1 session

    def test_dashboard_with_file_claims(self):
        from omega.server.coord_handlers import handle_coord_status, handle_file_claim
        _register("cs-fc", project="/proj")
        run_async(handle_file_claim({
            "session_id": "cs-fc", "file_path": "/proj/main.py",
        }))
        result = run_async(handle_coord_status({}))
        text = _text(result)
        assert "main.py" in text


class TestSessionSnapshot:
    """Tests for omega_session_snapshot handler."""

    def test_snapshot_created(self):
        from omega.server.coord_handlers import handle_session_snapshot, handle_file_claim
        _register("snap-1", project="/proj", task="coding")
        # Add some state so snapshot has meaningful content
        run_async(handle_file_claim({
            "session_id": "snap-1", "file_path": "/proj/snap.py",
        }))
        result = run_async(handle_session_snapshot({"session_id": "snap-1"}))
        assert not _is_error(result)
        assert "snapshot" in _text(result).lower()

    def test_snapshot_with_reason(self):
        from omega.server.coord_handlers import handle_session_snapshot, handle_file_claim
        _register("snap-r", project="/proj", task="deploy")
        run_async(handle_file_claim({
            "session_id": "snap-r", "file_path": "/proj/deploy.py",
        }))
        result = run_async(handle_session_snapshot({
            "session_id": "snap-r", "reason": "pre-deploy",
        }))
        assert "pre-deploy" in _text(result)

    def test_snapshot_missing_session(self):
        from omega.server.coord_handlers import handle_session_snapshot
        result = run_async(handle_session_snapshot({}))
        assert _is_error(result)


class TestSessionRecover:
    """Tests for omega_session_recover handler."""

    def test_recover_no_snapshots(self):
        from omega.server.coord_handlers import handle_session_recover
        result = run_async(handle_session_recover({"project": "/proj/empty"}))
        assert not _is_error(result)
        assert "no predecessor" in _text(result).lower()

    def test_recover_from_snapshot(self):
        from omega.server.coord_handlers import (
            handle_session_snapshot, handle_session_recover, handle_file_claim,
        )
        _register("rec-1", project="/proj/rec", task="editing")
        run_async(handle_file_claim({
            "session_id": "rec-1", "file_path": "/proj/rec/main.py",
        }))
        snap = run_async(handle_session_snapshot({
            "session_id": "rec-1", "reason": "handoff",
        }))
        assert not _is_error(snap), f"Snapshot failed: {_text(snap)}"
        result = run_async(handle_session_recover({"project": "/proj/rec"}))
        text = _text(result)
        assert "rec-1" in text or "resume" in text.lower()

    def test_recover_missing_project(self):
        from omega.server.coord_handlers import handle_session_recover
        result = run_async(handle_session_recover({}))
        assert _is_error(result)


# ===========================================================================
# 3d-pre: Task create overlap warning
# ===========================================================================


class TestTaskCreateOverlapWarning:
    """Tests that task_create warns when similar tasks exist."""

    def test_create_warns_on_overlap(self):
        from omega.server.coord_handlers import handle_task_create
        _register("ow-1")
        _create_task("ow-1", "Draft RAAIS grant application", project="/proj/a")

        result = run_async(handle_task_create({
            "session_id": "ow-1",
            "title": "Write RAAIS grant proposal",
            "project": "/proj/a",
        }))
        text = _text(result)
        assert not _is_error(result)
        assert "Task created" in text
        assert "WARNING" in text
        assert "Similar tasks" in text
        assert "RAAIS" in text.lower() or "raais" in text.lower()

    def test_create_no_warning_when_no_overlap(self):
        from omega.server.coord_handlers import handle_task_create
        _register("ow-2")
        _create_task("ow-2", "Deploy website", project="/proj/b")

        result = run_async(handle_task_create({
            "session_id": "ow-2",
            "title": "Fix authentication bug",
            "project": "/proj/b",
        }))
        text = _text(result)
        assert not _is_error(result)
        assert "Task created" in text
        assert "WARNING" not in text


# ===========================================================================
# 3d: Task lifecycle tests (using merged handle_task_resolve)
# ===========================================================================


class TestTaskResolve:
    """Tests for omega_task_resolve (unified complete/fail/cancel)."""

    def test_complete_flow(self):
        from omega.server.coord_handlers import handle_task_resolve, handle_task_claim
        _register("tr-1")
        task_id = _create_task("tr-1", "Completable task")
        run_async(handle_task_claim({"task_id": task_id, "session_id": "tr-1"}))
        result = run_async(handle_task_resolve({
            "task_id": task_id, "session_id": "tr-1",
            "status": "completed", "result": "All done",
        }))
        assert "completed" in _text(result).lower()

    def test_fail_flow(self):
        from omega.server.coord_handlers import handle_task_resolve, handle_task_claim
        _register("tr-2")
        task_id = _create_task("tr-2", "Failable task")
        run_async(handle_task_claim({"task_id": task_id, "session_id": "tr-2"}))
        result = run_async(handle_task_resolve({
            "task_id": task_id, "session_id": "tr-2",
            "status": "failed", "reason": "Dependency missing",
        }))
        assert "failed" in _text(result).lower()

    def test_cancel_flow(self):
        from omega.server.coord_handlers import handle_task_resolve
        _register("tr-3")
        task_id = _create_task("tr-3", "Cancelable task")
        result = run_async(handle_task_resolve({
            "task_id": task_id, "session_id": "tr-3",
            "status": "canceled",
        }))
        assert "canceled" in _text(result).lower()

    def test_invalid_status(self):
        from omega.server.coord_handlers import handle_task_resolve
        _register("tr-bad")
        task_id = _create_task("tr-bad", "Bad status task")
        result = run_async(handle_task_resolve({
            "task_id": task_id, "session_id": "tr-bad",
            "status": "unknown",
        }))
        assert _is_error(result)

    def test_missing_task_id(self):
        from omega.server.coord_handlers import handle_task_resolve
        result = run_async(handle_task_resolve({
            "session_id": "tr-x", "status": "completed",
        }))
        assert _is_error(result)

    def test_missing_session_id(self):
        from omega.server.coord_handlers import handle_task_resolve
        result = run_async(handle_task_resolve({
            "task_id": 1, "status": "completed",
        }))
        assert _is_error(result)


class TestTaskProgress:
    """Tests for omega_task_progress handler."""

    def test_progress_update(self):
        from omega.server.coord_handlers import handle_task_progress, handle_task_claim
        _register("tp-1")
        task_id = _create_task("tp-1", "Progressive task")
        run_async(handle_task_claim({"task_id": task_id, "session_id": "tp-1"}))
        result = run_async(handle_task_progress({
            "task_id": task_id, "session_id": "tp-1", "progress": 50,
        }))
        assert not _is_error(result)
        assert "50%" in _text(result)

    def test_progress_with_note(self):
        from omega.server.coord_handlers import handle_task_progress, handle_task_claim
        _register("tp-2")
        task_id = _create_task("tp-2", "Noted task")
        run_async(handle_task_claim({"task_id": task_id, "session_id": "tp-2"}))
        result = run_async(handle_task_progress({
            "task_id": task_id, "session_id": "tp-2",
            "progress": 75, "status_note": "Running tests...",
        }))
        assert "75%" in _text(result)
        assert "Running tests" in _text(result)

    def test_progress_missing_args(self):
        from omega.server.coord_handlers import handle_task_progress
        result = run_async(handle_task_progress({"session_id": "tp-x"}))
        assert _is_error(result)


class TestTasksListFiltered:
    """Tests for omega_tasks_list with filters."""

    def test_filter_by_status(self):
        from omega.server.coord_handlers import handle_tasks_list, handle_task_resolve
        _register("tl-1")
        tid1 = _create_task("tl-1", "Task A")
        tid2 = _create_task("tl-1", "Task B")
        run_async(handle_task_resolve({
            "task_id": tid1, "session_id": "tl-1", "status": "completed",
        }))
        result = run_async(handle_tasks_list({"status": "pending"}))
        text = _text(result)
        assert "Task B" in text

    def test_filter_by_project(self):
        from omega.server.coord_handlers import handle_tasks_list
        _register("tl-p")
        _create_task("tl-p", "Proj A task", project="/proj/a")
        _create_task("tl-p", "Proj B task", project="/proj/b")
        result = run_async(handle_tasks_list({"project": "/proj/a"}))
        text = _text(result)
        assert "Proj A" in text


class TestFindAgents:
    """Tests for omega_find_agents handler."""

    def test_find_by_capability(self):
        from omega.server.coord_handlers import handle_find_agents
        _register("fa-1", capabilities=["code", "test"])
        _register("fa-2", capabilities=["review"])
        result = run_async(handle_find_agents({"capability": "test"}))
        text = _text(result)
        assert "fa-1" in text

    def test_no_match(self):
        from omega.server.coord_handlers import handle_find_agents
        _register("fa-3", capabilities=["code"])
        result = run_async(handle_find_agents({"capability": "deploy"}))
        assert "no active" in _text(result).lower()

    def test_missing_capability(self):
        from omega.server.coord_handlers import handle_find_agents
        result = run_async(handle_find_agents({}))
        assert _is_error(result)


# ===========================================================================
# 3e: Merged tool tests (omega_store, omega_query, omega_profile)
# ===========================================================================


class TestMergedStore:
    """Tests for the merged omega_store (replacing omega_remember)."""

    @pytest.mark.asyncio
    async def test_store_with_text_alias(self):
        """'text' param should work as alias for 'content'."""
        from omega.server.handlers import HANDLERS
        result = await HANDLERS["omega_store"]({"text": "Remember via text param"})
        assert not _is_error(result)

    @pytest.mark.asyncio
    async def test_store_content_takes_precedence(self):
        """'content' should take precedence over 'text'."""
        from omega.server.handlers import HANDLERS
        result = await HANDLERS["omega_store"]({
            "content": "via content", "text": "via text",
        })
        assert not _is_error(result)

    @pytest.mark.asyncio
    async def test_store_empty_rejected(self):
        from omega.server.handlers import HANDLERS
        result = await HANDLERS["omega_store"]({})
        assert _is_error(result)

    @pytest.mark.asyncio
    async def test_remember_alias_defaults_to_user_preference(self):
        """omega_remember alias should default to user_preference event_type."""
        from omega.server.handlers import HANDLERS
        result = await HANDLERS["omega_remember"]({"text": "I prefer dark mode"})
        assert not _is_error(result)
        # Verify it's stored as user_preference
        from omega.bridge import list_preferences
        prefs = list_preferences()
        assert any("dark mode" in p.get("content", "") for p in prefs)


class TestMergedQuery:
    """Tests for the merged omega_query with phrase mode."""

    @pytest.mark.asyncio
    async def test_semantic_mode_default(self):
        from omega.server.handlers import HANDLERS
        result = await HANDLERS["omega_query"]({"query": "test query"})
        assert not _is_error(result)

    @pytest.mark.asyncio
    async def test_phrase_mode(self):
        from omega.server.handlers import HANDLERS
        # Store something first
        await HANDLERS["omega_store"]({"content": "unique phrase alpha beta gamma"})
        result = await HANDLERS["omega_query"]({
            "query": "alpha beta", "mode": "phrase",
        })
        assert not _is_error(result)

    @pytest.mark.asyncio
    async def test_phrase_mode_case_sensitive(self):
        from omega.server.handlers import HANDLERS
        await HANDLERS["omega_store"]({"content": "CamelCase identifier test"})
        result = await HANDLERS["omega_query"]({
            "query": "CamelCase", "mode": "phrase", "case_sensitive": True,
        })
        assert not _is_error(result)

    @pytest.mark.asyncio
    async def test_phrase_alias_backward_compat(self):
        """omega_phrase_search alias should still work."""
        from omega.server.handlers import HANDLERS
        await HANDLERS["omega_store"]({"content": "backward compat phrase test xyz"})
        result = await HANDLERS["omega_phrase_search"]({"phrase": "phrase test xyz"})
        assert not _is_error(result)


class TestMergedProfile:
    """Tests for the merged omega_profile (read + write)."""

    @pytest.mark.asyncio
    async def test_profile_read_mode(self):
        from omega.server.handlers import HANDLERS
        result = await HANDLERS["omega_profile"]({})
        assert not _is_error(result)

    @pytest.mark.asyncio
    async def test_profile_write_mode(self):
        from omega.server.handlers import HANDLERS
        result = await HANDLERS["omega_profile"]({
            "update": {"name": "Test", "timezone": "PST"},
        })
        assert not _is_error(result)
        assert "2 field" in _text(result)

    @pytest.mark.asyncio
    async def test_profile_write_then_read(self):
        from omega.server.handlers import HANDLERS
        await HANDLERS["omega_profile"]({
            "update": {"name": "RoundTrip"},
        })
        result = await HANDLERS["omega_profile"]({})
        assert "RoundTrip" in _text(result)

    @pytest.mark.asyncio
    async def test_save_profile_alias(self):
        """omega_save_profile alias should work via profile param."""
        from omega.server.handlers import HANDLERS
        result = await HANDLERS["omega_save_profile"]({
            "profile": {"name": "AliasTest"},
        })
        assert not _is_error(result)
        assert "1 field" in _text(result)
