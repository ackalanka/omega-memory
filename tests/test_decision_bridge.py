"""Tests for the decision dual-write bridge (coord_decisions → memories)."""
from unittest.mock import patch


class TestDecisionDualWrite:
    """Verify register_decision() mirrors decisions into the memories table."""

    def test_register_decision_creates_memory(self, tmp_omega_dir, coord_mgr):
        """Registering a coord decision should also store it in memories."""
        from omega.bridge import _get_store, reset_memory
        reset_memory()
        store = _get_store()

        coord_mgr.register_session("s1", pid=1, project="/proj/a")
        result = coord_mgr.register_decision(
            session_id="s1",
            project="/proj/a",
            domain="database/engine",
            decision="Use SQLite for storage",
            rationale="Simplicity and portability",
        )
        assert result["success"] is True

        # Verify the decision exists in the memories table
        nodes = store.get_by_type("decision", limit=10)
        matching = [
            n for n in nodes
            if "Use SQLite for storage" in n.content
        ]
        assert len(matching) >= 1
        reset_memory()

    def test_dual_write_includes_domain_prefix(self, tmp_omega_dir, coord_mgr):
        """Dual-written content should start with [domain]."""
        from omega.bridge import _get_store, reset_memory
        reset_memory()
        store = _get_store()

        coord_mgr.register_session("s1", pid=1, project="/proj/a")
        coord_mgr.register_decision(
            session_id="s1",
            project="/proj/a",
            domain="api/auth",
            decision="JWT tokens for auth",
        )

        nodes = store.get_by_type("decision", limit=10)
        matching = [n for n in nodes if "JWT tokens" in n.content]
        assert len(matching) >= 1
        assert matching[0].content.startswith("[api/auth]")
        reset_memory()

    def test_dual_write_metadata_has_coord_id(self, tmp_omega_dir, coord_mgr):
        """Metadata should include coord_decision_id and source."""
        from omega.bridge import _get_store, reset_memory
        reset_memory()
        store = _get_store()

        coord_mgr.register_session("s1", pid=1, project="/proj/a")
        result = coord_mgr.register_decision(
            session_id="s1",
            project="/proj/a",
            domain="infra",
            decision="Deploy on Railway",
        )
        decision_id = result["decision_id"]

        nodes = store.get_by_type("decision", limit=10)
        matching = [n for n in nodes if "Deploy on Railway" in n.content]
        assert len(matching) >= 1
        meta = matching[0].metadata or {}
        assert meta.get("source") == "coord_dual_write"
        assert meta.get("coord_decision_id") == decision_id
        assert meta.get("domain") == "infra"
        reset_memory()

    def test_dual_write_failure_doesnt_break_coord(self, tmp_omega_dir, coord_mgr):
        """If auto_capture raises, register_decision should still succeed."""
        coord_mgr.register_session("s1", pid=1, project="/proj/a")

        with patch("omega.bridge.auto_capture", side_effect=RuntimeError("boom")):
            result = coord_mgr.register_decision(
                session_id="s1",
                project="/proj/a",
                domain="test",
                decision="This should still work",
            )
        assert result["success"] is True
        assert result["decision_id"] is not None

    def test_welcome_surfaces_coord_decisions(self, tmp_omega_dir, coord_mgr):
        """welcome(project=...) should include coordination decisions."""
        from omega.bridge import welcome, reset_memory
        reset_memory()

        coord_mgr.register_session("s1", pid=1, project="/proj/a")
        coord_mgr.register_decision(
            session_id="s1",
            project="/proj/a",
            domain="architecture",
            decision="Microservices pattern",
        )

        # Patch get_manager where it's imported in welcome()
        with patch("omega.coordination.get_manager", return_value=coord_mgr):
            result = welcome(project="/proj/a")

        ctx = result.get("project_context", "")
        assert "Coordination Decisions" in ctx
        assert "Microservices pattern" in ctx
        reset_memory()
