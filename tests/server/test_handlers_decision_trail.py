"""Tests for decision trail card wiring in omega_store handler."""
from unittest.mock import patch, MagicMock


class TestDecisionTrailOnStore:
    """Test that storing a decision surfaces prior decision trail."""

    @patch("omega.coordination.get_manager")
    @patch("omega.bridge.store")
    @patch("omega.bridge.query_structured")
    def test_decision_store_appends_trail(self, mock_query, mock_store, mock_mgr):
        """When storing a decision with prior decisions, response includes trail."""
        import asyncio
        from omega.server.handlers import handle_omega_store

        mock_store.return_value = "Stored mem-new123"
        mock_query.return_value = [
            {
                "id": "mem-old1",
                "content": "Use SQLite for local storage",
                "relevance": 0.85,
                "event_type": "decision",
                "created_at": "2026-02-20T10:00:00Z",
            },
        ]

        result = asyncio.get_event_loop().run_until_complete(
            handle_omega_store({
                "content": "Switching to WAL mode for SQLite",
                "event_type": "decision",
                "session_id": "test-trail",
                "project": "/test",
            })
        )

        text = result["content"][0]["text"]
        assert "[OMEGA] Prior decisions" in text

    @patch("omega.coordination.get_manager")
    @patch("omega.bridge.store")
    @patch("omega.bridge.query_structured")
    def test_non_decision_store_has_no_trail(self, mock_query, mock_store, mock_mgr):
        """Non-decision types should not trigger trail lookup."""
        import asyncio
        from omega.server.handlers import handle_omega_store

        mock_store.return_value = "Stored mem-123"

        result = asyncio.get_event_loop().run_until_complete(
            handle_omega_store({
                "content": "Some lesson learned",
                "event_type": "lesson_learned",
                "session_id": "test-trail",
                "project": "/test",
            })
        )

        text = result["content"][0]["text"]
        assert "[OMEGA] Prior decisions" not in text
        mock_query.assert_not_called()

    @patch("omega.coordination.get_manager")
    @patch("omega.bridge.store")
    @patch("omega.bridge.query_structured")
    def test_decision_store_no_priors_no_trail(self, mock_query, mock_store, mock_mgr):
        """When no prior decisions exist, no trail is appended."""
        import asyncio
        from omega.server.handlers import handle_omega_store

        mock_store.return_value = "Stored mem-new456"
        mock_query.return_value = []

        result = asyncio.get_event_loop().run_until_complete(
            handle_omega_store({
                "content": "Brand new decision topic",
                "event_type": "decision",
                "session_id": "test-trail",
                "project": "/test",
            })
        )

        text = result["content"][0]["text"]
        assert "[OMEGA] Prior decisions" not in text
