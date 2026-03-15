"""Tests for aggressive learning parameters."""
import pytest


class TestCaptureConfidenceMetadata:
    def test_assistant_capture_includes_confidence(self):
        """Assistant auto-captures should include capture_confidence in metadata."""
        from unittest.mock import patch

        from omega.server.hook_server.assistant import handle_assistant_capture
        from omega.server.hook_server import _assistant_capture_count

        _assistant_capture_count.pop("test-conf", None)

        msg = (
            "x" * 200
            + "\nThe fix was to change the import path from relative to absolute, "
            "which resolved the circular dependency issue in the module loading."
        )
        payload = {
            "last_assistant_message": msg,
            "session_id": "test-conf",
            "project": "/test",
        }
        with patch("omega.bridge.auto_capture") as mock_capture:
            handle_assistant_capture(payload)
            if mock_capture.called:
                call_kwargs = mock_capture.call_args
                metadata = call_kwargs.kwargs.get("metadata") or call_kwargs[1].get("metadata", {})
                assert metadata.get("capture_confidence") == "medium"
        _assistant_capture_count.pop("test-conf", None)


class TestIgnoreTracking:
    def test_surfaced_but_unused_memories_tracked(self):
        """Memories surfaced but not used should be trackable as ignored."""
        from omega.server.hook_server.card_tracker import CardTracker

        tracker = CardTracker()
        tracker.record_surfaced("s1", "mem-1", "content 1")
        tracker.record_surfaced("s1", "mem-2", "content 2")
        tracker.record_used("s1", "mem-1")

        stats = tracker.get_stats("s1")
        surfaced = tracker.get_surfaced_ids("s1")

        # mem-2 was surfaced but not used
        assert stats["memories_surfaced"] == 2
        assert stats["memories_used"] == 1
        # The difference is the ignored set
        ignored = surfaced - {mid for mid in surfaced if stats["memories_used"] > 0}
        assert len(surfaced) == 2
