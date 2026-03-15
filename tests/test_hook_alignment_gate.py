"""Tests for the pre-action alignment gate in hook_server/guards.py."""

import pytest

from omega.server.hook_server.guards import (
    _infer_domain_from_path,
    handle_pre_alignment_gate,
)
from omega.server.hook_server import (
    _session_approach_domains,
    _session_approach_warned,
)


class TestInferDomain:
    """Domain inference from file paths."""

    def test_src_auth_path(self):
        assert _infer_domain_from_path("/proj/src/auth/login.py") == "auth"

    def test_tests_path(self):
        assert _infer_domain_from_path("/proj/tests/test_auth.py") == "testing"

    def test_website_path(self):
        assert _infer_domain_from_path("/proj/website/app/page.tsx") == "website"

    def test_hooks_path(self):
        assert _infer_domain_from_path("/proj/hooks/fast_hook.py") == "hooks"

    def test_src_fallback(self):
        """Falls back to first directory after src/."""
        assert _infer_domain_from_path("/proj/src/foobar/baz.py") == "foobar"

    def test_no_match(self):
        """Returns None for unrecognizable paths."""
        assert _infer_domain_from_path("random.txt") is None

    def test_empty_path(self):
        assert _infer_domain_from_path("") is None

    def test_none_path(self):
        assert _infer_domain_from_path(None) is None


class TestAlignmentGate:
    """Pre-action alignment gate behavior."""

    def _make_payload(self, tool_name, session_id="s1", project="/proj", **extra):
        payload = {
            "tool_name": tool_name,
            "session_id": session_id,
            "project": project,
            "tool_input": extra.get("tool_input", {}),
        }
        if "tool_input" in extra:
            payload["tool_input"] = extra["tool_input"]
        return payload

    def test_passthrough_non_edit_tool(self):
        """Non-edit/bash tools pass through immediately."""
        payload = self._make_payload("Read")
        result = handle_pre_alignment_gate(payload)
        assert result["output"] == ""
        assert result.get("exit_code") is None

    def test_passthrough_no_session(self):
        """No session_id passes through."""
        payload = self._make_payload("Edit", session_id="")
        result = handle_pre_alignment_gate(payload)
        assert result["output"] == ""

    def test_solo_approach_first_reminder(self, coord_mgr, monkeypatch):
        """Single-agent mode surfaces [APPROACH-FIRST] on first edit in a domain."""
        coord_mgr.register_session("s1", pid=1, project="/proj")
        monkeypatch.setattr("omega.coordination.get_manager", lambda: coord_mgr)
        _session_approach_domains.clear()
        _session_approach_warned.clear()

        payload = self._make_payload(
            "Edit",
            tool_input={"file_path": "/proj/src/auth/login.py"},
        )
        result = handle_pre_alignment_gate(payload)
        assert "[APPROACH-FIRST]" in result["output"]
        assert "auth" in result["output"]
        assert result.get("exit_code") is None  # non-blocking

    def test_solo_approach_first_fires_only_once(self, coord_mgr, monkeypatch):
        """Solo approach-first reminder fires only once per domain."""
        coord_mgr.register_session("s1", pid=1, project="/proj")
        monkeypatch.setattr("omega.coordination.get_manager", lambda: coord_mgr)
        _session_approach_domains.clear()
        _session_approach_warned.clear()

        payload = self._make_payload(
            "Edit",
            tool_input={"file_path": "/proj/src/auth/login.py"},
        )
        r1 = handle_pre_alignment_gate(payload)
        assert "[APPROACH-FIRST]" in r1["output"]

        # Second call: already warned, should be empty
        r2 = handle_pre_alignment_gate(payload)
        assert r2["output"] == ""

    def test_solo_approach_suppressed_by_decision(self, coord_mgr, monkeypatch):
        """Solo approach-first reminder suppressed when domain has registered decision."""
        from omega.server.hook_server.guards import _mark_approach_registered

        coord_mgr.register_session("s1", pid=1, project="/proj")
        monkeypatch.setattr("omega.coordination.get_manager", lambda: coord_mgr)
        _session_approach_domains.clear()
        _session_approach_warned.clear()

        # Register approach before editing
        _mark_approach_registered("s1", "auth")

        payload = self._make_payload(
            "Edit",
            tool_input={"file_path": "/proj/src/auth/login.py"},
        )
        result = handle_pre_alignment_gate(payload)
        assert result["output"] == ""

    def test_alignment_warn_on_file_edit(self, coord_mgr, monkeypatch):
        """File edit in domain with active decisions surfaces [ALIGNMENT] warning."""
        coord_mgr.register_session("s1", pid=1, project="/proj")
        coord_mgr.register_session("s2", pid=2, project="/proj")
        coord_mgr.register_decision("s1", "/proj", "auth", "Use JWT for all endpoints")

        monkeypatch.setattr("omega.coordination.get_manager", lambda: coord_mgr)

        # Clear debounce state
        from omega.server.hook_server.guards import _last_alignment_check
        _last_alignment_check.clear()

        payload = {
            "tool_name": "Edit",
            "session_id": "s2",
            "project": "/proj",
            "tool_input": {"file_path": "/proj/src/auth/login.py"},
        }
        result = handle_pre_alignment_gate(payload)
        assert "[ALIGNMENT]" in result["output"]
        assert "auth" in result["output"]
        assert "JWT" in result["output"]

    def test_alignment_no_decisions_passthrough(self, coord_mgr, monkeypatch):
        """File edit in domain with no decisions passes through."""
        coord_mgr.register_session("s1", pid=1, project="/proj")
        coord_mgr.register_session("s2", pid=2, project="/proj")

        monkeypatch.setattr("omega.coordination.get_manager", lambda: coord_mgr)

        from omega.server.hook_server.guards import _last_alignment_check
        _last_alignment_check.clear()

        payload = {
            "tool_name": "Edit",
            "session_id": "s2",
            "project": "/proj",
            "tool_input": {"file_path": "/proj/src/auth/login.py"},
        }
        result = handle_pre_alignment_gate(payload)
        assert result["output"] == ""

    def test_debounce_skips_repeated_checks(self, coord_mgr, monkeypatch):
        """Same (session, domain) within debounce window is skipped."""
        coord_mgr.register_session("s1", pid=1, project="/proj")
        coord_mgr.register_session("s2", pid=2, project="/proj")
        coord_mgr.register_decision("s1", "/proj", "auth", "Use JWT")

        monkeypatch.setattr("omega.coordination.get_manager", lambda: coord_mgr)

        from omega.server.hook_server.guards import _last_alignment_check
        _last_alignment_check.clear()

        payload = {
            "tool_name": "Edit",
            "session_id": "s2",
            "project": "/proj",
            "tool_input": {"file_path": "/proj/src/auth/login.py"},
        }
        # First call should surface
        r1 = handle_pre_alignment_gate(payload)
        assert "[ALIGNMENT]" in r1["output"]

        # Second call within debounce window should be empty
        r2 = handle_pre_alignment_gate(payload)
        assert r2["output"] == ""
