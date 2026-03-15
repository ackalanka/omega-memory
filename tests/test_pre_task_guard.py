"""Tests for OMEGA Pre-Task Guard — enforcement of task declaration before edits.

Covers: blocking, opt-in enforcement, active task allows, single-agent skip,
        fail-open, file outside project, no project dir, daemon handler parity.
"""
import importlib.util
import os
from pathlib import Path

_HOOKS_DIR = Path(__file__).parent.parent / "hooks"


def _load_pre_task_guard():
    """Import pre_task_guard.py by file path (hooks/ is not on sys.path)."""
    spec = importlib.util.spec_from_file_location(
        "pre_task_guard", _HOOKS_DIR / "pre_task_guard.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestTaskGuardStandalone:
    """Tests for the standalone pre_task_guard.py hook logic."""

    def test_skips_non_edit_tools(self):
        """Should skip tools that aren't Edit/Write/NotebookEdit."""
        os.environ["TOOL_NAME"] = "Bash"
        os.environ["SESSION_ID"] = "sess-A"
        os.environ["TOOL_INPUT"] = '{"command": "ls"}'
        os.environ["PROJECT_DIR"] = "/proj"

        mod = _load_pre_task_guard()
        # Should return without calling sys.exit
        mod.main()

    def test_skips_when_no_session_id(self):
        """No session = single-agent mode — no enforcement."""
        os.environ["TOOL_NAME"] = "Edit"
        os.environ["SESSION_ID"] = ""
        os.environ["TOOL_INPUT"] = '{"file_path": "/proj/foo.py"}'
        os.environ["PROJECT_DIR"] = "/proj"

        mod = _load_pre_task_guard()
        mod.main()

    def test_skips_when_no_project_dir(self):
        """No project dir — can't determine enforcement scope."""
        os.environ["TOOL_NAME"] = "Edit"
        os.environ["SESSION_ID"] = "sess-A"
        os.environ["TOOL_INPUT"] = '{"file_path": "/proj/foo.py"}'
        os.environ.pop("PROJECT_DIR", None)

        mod = _load_pre_task_guard()
        mod.main()

    def test_skips_file_outside_project(self):
        """Files outside project should not be enforced."""
        os.environ["TOOL_NAME"] = "Edit"
        os.environ["SESSION_ID"] = "sess-A"
        os.environ["TOOL_INPUT"] = '{"file_path": "/other/place/foo.py"}'
        os.environ["PROJECT_DIR"] = "/proj"

        mod = _load_pre_task_guard()
        mod.main()


class TestTaskGuardDaemon:
    """Tests for the hook_server daemon handler handle_pre_task_guard."""

    def test_skips_non_edit_tools(self):
        from omega.server.hook_server import handle_pre_task_guard

        payload = {
            "tool_name": "Bash",
            "session_id": "sess-A",
            "tool_input": '{"command": "ls"}',
            "project": "/proj",
        }
        result = handle_pre_task_guard(payload)
        assert result.get("exit_code") is None

    def test_skips_when_no_session_id(self):
        from omega.server.hook_server import handle_pre_task_guard

        payload = {
            "tool_name": "Edit",
            "session_id": "",
            "tool_input": '{"file_path": "/proj/foo.py"}',
            "project": "/proj",
        }
        result = handle_pre_task_guard(payload)
        assert result.get("exit_code") is None

    def test_skips_when_no_project(self):
        from omega.server.hook_server import handle_pre_task_guard

        payload = {
            "tool_name": "Edit",
            "session_id": "sess-A",
            "tool_input": '{"file_path": "/proj/foo.py"}',
            "project": "",
        }
        result = handle_pre_task_guard(payload)
        assert result.get("exit_code") is None

    def test_skips_file_outside_project(self):
        from omega.server.hook_server import handle_pre_task_guard

        payload = {
            "tool_name": "Edit",
            "session_id": "sess-A",
            "tool_input": '{"file_path": "/other/place/foo.py"}',
            "project": "/proj",
        }
        result = handle_pre_task_guard(payload)
        assert result.get("exit_code") is None

    def test_allows_when_project_has_no_tasks(self, coord_mgr, monkeypatch):
        """Opt-in: projects without tasks have no enforcement."""
        from omega.server.hook_server import handle_pre_task_guard
        import omega.coordination as coord_mod

        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        payload = {
            "tool_name": "Edit",
            "session_id": "sess-A",
            "tool_input": '{"file_path": "/proj/foo.py"}',
            "project": "/proj",
        }
        result = handle_pre_task_guard(payload)
        assert result.get("exit_code") is None

    def test_blocks_when_project_has_tasks_but_session_doesnt(self, coord_mgr, monkeypatch):
        """Should block if project has active tasks but session has none."""
        from omega.server.hook_server import handle_pre_task_guard
        import omega.coordination as coord_mod

        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.register_session("sess-B", pid=2, project="/proj")
        # Create a task on the project (activates enforcement)
        coord_mgr.create_task("sess-B", "Some task", project="/proj")
        coord_mgr.claim_task(1, "sess-B")

        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        payload = {
            "tool_name": "Edit",
            "session_id": "sess-A",
            "tool_input": '{"file_path": "/proj/foo.py"}',
            "project": "/proj",
        }
        result = handle_pre_task_guard(payload)
        assert result.get("exit_code") == 2
        assert "[TASK-GUARD] BLOCKED" in result.get("output", "")
        assert "omega_task_create" in result.get("output", "")

    def test_allows_when_session_has_active_task(self, coord_mgr, monkeypatch):
        """Should allow if session has an in_progress task."""
        from omega.server.hook_server import handle_pre_task_guard
        import omega.coordination as coord_mod

        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.create_task("sess-A", "My task", project="/proj")
        coord_mgr.claim_task(1, "sess-A")

        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        payload = {
            "tool_name": "Edit",
            "session_id": "sess-A",
            "tool_input": '{"file_path": "/proj/foo.py"}',
            "project": "/proj",
        }
        result = handle_pre_task_guard(payload)
        assert result.get("exit_code") is None

    def test_allows_after_all_tasks_completed(self, coord_mgr, monkeypatch):
        """Enforcement stops when all tasks are terminal (completed/failed/canceled)."""
        from omega.server.hook_server import handle_pre_task_guard
        import omega.coordination as coord_mod

        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.create_task("sess-A", "My task", project="/proj")
        coord_mgr.claim_task(1, "sess-A")
        coord_mgr.complete_task(1, "sess-A")

        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        payload = {
            "tool_name": "Edit",
            "session_id": "sess-A",
            "tool_input": '{"file_path": "/proj/foo.py"}',
            "project": "/proj",
        }
        result = handle_pre_task_guard(payload)
        assert result.get("exit_code") is None

    def test_blocks_with_pending_task_not_claimed(self, coord_mgr, monkeypatch):
        """A pending task activates enforcement even if nobody claimed it."""
        from omega.server.hook_server import handle_pre_task_guard
        import omega.coordination as coord_mod

        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.create_task("sess-A", "Unclaimed task", project="/proj")
        # Task is pending but not claimed — enforcement is active, session has no in_progress task

        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        payload = {
            "tool_name": "Edit",
            "session_id": "sess-A",
            "tool_input": '{"file_path": "/proj/foo.py"}',
            "project": "/proj",
        }
        result = handle_pre_task_guard(payload)
        assert result.get("exit_code") == 2

    def test_handles_write_tool(self, coord_mgr, monkeypatch):
        """Should enforce on Write tool too."""
        from omega.server.hook_server import handle_pre_task_guard
        import omega.coordination as coord_mod

        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.create_task("sess-A", "Some task", project="/proj")
        # Not claimed — enforcement active, no in_progress task

        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        payload = {
            "tool_name": "Write",
            "session_id": "sess-A",
            "tool_input": '{"file_path": "/proj/new.py"}',
            "project": "/proj",
        }
        result = handle_pre_task_guard(payload)
        assert result.get("exit_code") == 2

    def test_handles_notebook_edit(self, coord_mgr, monkeypatch):
        """Should enforce on NotebookEdit with notebook_path."""
        from omega.server.hook_server import handle_pre_task_guard
        import omega.coordination as coord_mod

        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.create_task("sess-A", "Some task", project="/proj")

        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        payload = {
            "tool_name": "NotebookEdit",
            "session_id": "sess-A",
            "tool_input": '{"notebook_path": "/proj/nb.ipynb"}',
            "project": "/proj",
        }
        result = handle_pre_task_guard(payload)
        assert result.get("exit_code") == 2

    def test_fail_open_on_import_error(self, monkeypatch):
        """Should fail-open if omega.coordination can't be imported."""
        from omega.server.hook_server import handle_pre_task_guard
        import omega.server.hook_server.guards as guards_mod
        import omega.coordination as coord_mod

        def mock_get_manager():
            raise ImportError("no module")

        monkeypatch.setattr(coord_mod, "get_manager", mock_get_manager)
        monkeypatch.setattr(guards_mod, "_log_hook_error", lambda *a, **kw: None)

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
            "project": "/proj",
        }

        monkeypatch.setattr(builtins, "__import__", mock_import)
        result = handle_pre_task_guard(payload)
        assert result.get("exit_code") is None  # Fail-open

    def test_fail_open_on_database_error(self, coord_mgr, monkeypatch):
        """Should fail-open if database query fails."""
        from omega.server.hook_server import handle_pre_task_guard
        import omega.server.hook_server.guards as guards_mod
        import omega.coordination as coord_mod

        monkeypatch.setattr(guards_mod, "_log_hook_error", lambda *a, **kw: None)
        coord_mgr._conn.close()
        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        payload = {
            "tool_name": "Edit",
            "session_id": "sess-A",
            "tool_input": '{"file_path": "/proj/foo.py"}',
            "project": "/proj",
        }
        result = handle_pre_task_guard(payload)
        assert result.get("exit_code") is None  # Fail-open

    def test_different_project_tasks_dont_trigger(self, coord_mgr, monkeypatch):
        """Tasks on a different project shouldn't activate enforcement here."""
        from omega.server.hook_server import handle_pre_task_guard
        import omega.coordination as coord_mod

        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        # Task on a DIFFERENT project
        coord_mgr.create_task("sess-A", "Other task", project="/other-proj")

        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)

        payload = {
            "tool_name": "Edit",
            "session_id": "sess-A",
            "tool_input": '{"file_path": "/proj/foo.py"}',
            "project": "/proj",
        }
        result = handle_pre_task_guard(payload)
        assert result.get("exit_code") is None  # No enforcement on /proj


class TestGoldenPath:
    """End-to-end golden path: auto-register -> create task -> claim -> edit -> complete."""

    def test_full_golden_path(self, coord_mgr, monkeypatch):
        """Agent goes through the full happy path without hitting any blocks."""
        from omega.server.hook_server import handle_pre_task_guard, handle_pre_file_guard
        import omega.coordination as coord_mod

        monkeypatch.setattr(coord_mod, "_manager", coord_mgr)
        session_id = "golden-sess"
        project = "/proj"

        # Step 1: Agent is unregistered — creates a task (auto-registers via golden path)
        result = coord_mgr.create_task(session_id, "Implement feature X", project=project)
        assert result["success"] is True
        task_id = result["task_id"]

        # Verify auto-registration happened
        sessions = coord_mgr.list_sessions(auto_clean=False)
        assert any(s["session_id"] == session_id for s in sessions)

        # Step 2: Claim the task
        result = coord_mgr.claim_task(task_id, session_id)
        assert result["success"] is True

        # Step 3: Edit should pass both guards
        payload = {
            "tool_name": "Edit",
            "session_id": session_id,
            "tool_input": f'{{"file_path": "{project}/foo.py"}}',
            "project": project,
        }
        # Task guard allows (has in_progress task)
        tg_result = handle_pre_task_guard(payload)
        assert tg_result.get("exit_code") is None

        # File guard allows (no claim conflict)
        fg_result = handle_pre_file_guard(payload)
        assert fg_result.get("exit_code") is None

        # Step 4: Complete the task
        result = coord_mgr.complete_task(task_id, session_id)
        assert result["success"] is True

        # Step 5: After all tasks done, enforcement is off — edits pass
        tg_result = handle_pre_task_guard(payload)
        assert tg_result.get("exit_code") is None

    def test_unregistered_agent_claim_file_auto_registers(self, coord_mgr):
        """An unregistered agent claiming a file should auto-register transparently."""
        result = coord_mgr.claim_file("new-agent", "/proj/foo.py", task="editing")
        assert result["success"] is True

        # Verify the agent got auto-registered
        sessions = coord_mgr.list_sessions(auto_clean=False)
        assert any(s["session_id"] == "new-agent" for s in sessions)

    def test_unregistered_agent_claim_branch_auto_registers(self, coord_mgr):
        """An unregistered agent claiming a branch should auto-register transparently."""
        result = coord_mgr.claim_branch("new-agent", "/proj", "feat-1")
        assert result["success"] is True

        sessions = coord_mgr.list_sessions(auto_clean=False)
        assert any(s["session_id"] == "new-agent" for s in sessions)

    def test_unregistered_agent_announce_intent_auto_registers(self, coord_mgr):
        """An unregistered agent announcing intent should auto-register transparently."""
        result = coord_mgr.announce_intent("new-agent", "Working on feature X")
        assert result["success"] is True

        sessions = coord_mgr.list_sessions(auto_clean=False)
        assert any(s["session_id"] == "new-agent" for s in sessions)

    def test_unregistered_agent_create_task_auto_registers(self, coord_mgr):
        """An unregistered agent creating a task should auto-register transparently."""
        result = coord_mgr.create_task("new-agent", "Some task", project="/proj")
        assert result["success"] is True

        sessions = coord_mgr.list_sessions(auto_clean=False)
        assert any(s["session_id"] == "new-agent" for s in sessions)

    def test_unregistered_agent_claim_task_auto_registers(self, coord_mgr):
        """An unregistered agent claiming a task should auto-register transparently."""
        # First create a task with a registered session
        coord_mgr.register_session("creator", pid=1, project="/proj")
        coord_mgr.create_task("creator", "Task for new agent", project="/proj")

        # Now claim it with an unregistered session
        result = coord_mgr.claim_task(1, "new-agent")
        assert result["success"] is True

        sessions = coord_mgr.list_sessions(auto_clean=False)
        assert any(s["session_id"] == "new-agent" for s in sessions)


class TestHasActiveTask:
    """Tests for has_active_task and project_has_active_tasks."""

    def test_no_tasks(self, coord_mgr):
        result = coord_mgr.has_active_task("sess-A")
        assert result["has_task"] is False

    def test_with_in_progress_task(self, coord_mgr):
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.create_task("sess-A", "My task", project="/proj")
        coord_mgr.claim_task(1, "sess-A")
        result = coord_mgr.has_active_task("sess-A")
        assert result["has_task"] is True
        assert result["task_id"] == 1
        assert result["title"] == "My task"

    def test_with_only_pending_task(self, coord_mgr):
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.create_task("sess-A", "Unclaimed task", project="/proj")
        result = coord_mgr.has_active_task("sess-A")
        assert result["has_task"] is False  # Pending != in_progress

    def test_with_completed_task(self, coord_mgr):
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.create_task("sess-A", "Done task", project="/proj")
        coord_mgr.claim_task(1, "sess-A")
        coord_mgr.complete_task(1, "sess-A")
        result = coord_mgr.has_active_task("sess-A")
        assert result["has_task"] is False

    def test_project_has_no_tasks(self, coord_mgr):
        assert coord_mgr.project_has_active_tasks("/proj") is False

    def test_project_has_pending_task(self, coord_mgr):
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.create_task("sess-A", "Pending task", project="/proj")
        assert coord_mgr.project_has_active_tasks("/proj") is True

    def test_project_has_in_progress_task(self, coord_mgr):
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.create_task("sess-A", "Active task", project="/proj")
        coord_mgr.claim_task(1, "sess-A")
        assert coord_mgr.project_has_active_tasks("/proj") is True

    def test_project_only_completed_tasks(self, coord_mgr):
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.create_task("sess-A", "Done task", project="/proj")
        coord_mgr.claim_task(1, "sess-A")
        coord_mgr.complete_task(1, "sess-A")
        assert coord_mgr.project_has_active_tasks("/proj") is False

    def test_project_mixed_tasks(self, coord_mgr):
        coord_mgr.register_session("sess-A", pid=1, project="/proj")
        coord_mgr.create_task("sess-A", "Done task", project="/proj")
        coord_mgr.claim_task(1, "sess-A")
        coord_mgr.complete_task(1, "sess-A")
        coord_mgr.create_task("sess-A", "New task", project="/proj")
        assert coord_mgr.project_has_active_tasks("/proj") is True


class TestProjectFromPath:
    """Tests for _project_from_path static method."""

    def test_returns_none_for_nonexistent(self):
        from omega.coordination import CoordinationManager
        result = CoordinationManager._project_from_path("/nonexistent/path/foo.py")
        assert result is None

    def test_returns_none_for_empty(self):
        from omega.coordination import CoordinationManager
        result = CoordinationManager._project_from_path("")
        assert result is None
