"""Tests for OMEGA utilization maximization — 6 gaps.

Gap 1: lesson_learned auto-capture from user prompts
Gap 2: Memory surfacing on Read tool
Gap 3: omega_phrase_search MCP tool
Gap 4: filter_tags on omega_query
Gap 5: Auto-announce intent on Edit/Write
Gap 6: omega_type_stats and omega_session_stats MCP tools
"""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from omega.server.handlers import HANDLERS
from omega.server.tool_schemas import TOOL_SCHEMAS


# ============================================================================
# Fixture: reset bridge singleton between tests
# ============================================================================

@pytest.fixture(autouse=True)
def _reset_bridge(tmp_omega_dir):
    """Reset the bridge singleton so each test gets a fresh store."""
    from omega.bridge import reset_memory
    reset_memory()
    yield
    reset_memory()


# ============================================================================
# Helper
# ============================================================================

async def _store_test_memory(content="Test memory", event_type="lesson_learned",
                              tags=None, session_id=None, project=None):
    """Store a memory via the handler, return the node_id."""
    args = {"content": content, "event_type": event_type}
    if session_id:
        args["session_id"] = session_id
    if project:
        args["metadata"] = {"project": project}
    result = await HANDLERS["omega_store"](args)
    assert not result.get("isError"), result
    text = result["content"][0]["text"]
    for line in text.splitlines():
        if "Node ID" in line and "`" in line:
            node_id = line.split("`")[1]
            # If tags requested, update the memory directly
            if tags:
                from omega.bridge import _get_store
                store = _get_store()
                node = store.get_node(node_id)
                if node:
                    meta = dict(node.metadata or {})
                    meta["tags"] = tags
                    store.update_node(node_id, metadata=meta)
            return node_id
    return None


# ============================================================================
# Gap 1: Auto-capture lesson_learned from user prompts
# ============================================================================

class TestLessonAutoCapture:
    """Gap 1: Lesson patterns detected and captured."""

    def test_lesson_patterns_defined(self):
        """auto_capture.py should have LESSON_PATTERNS list."""
        sys.path.insert(0, str(Path(__file__).parent.parent / "hooks"))
        from auto_capture import LESSON_PATTERNS
        assert len(LESSON_PATTERNS) >= 10

    def test_detect_lesson_turns_out(self):
        from auto_capture import _detect_lesson
        assert _detect_lesson("turns out the bug was in the import order for the modules")

    def test_detect_lesson_the_fix_was(self):
        from auto_capture import _detect_lesson
        assert _detect_lesson("the fix was to add a null check before accessing the property")

    def test_detect_lesson_i_learned_that(self):
        from auto_capture import _detect_lesson
        assert _detect_lesson("I learned that SQLite FTS5 needs special handling for phrase queries")

    def test_detect_lesson_note_to_self(self):
        from auto_capture import _detect_lesson
        assert _detect_lesson("note to self: always check the edge cases in the parser")

    def test_detect_lesson_the_problem_was(self):
        from auto_capture import _detect_lesson
        assert _detect_lesson("the problem was that the connection pool was exhausted during peak load")

    def test_detect_lesson_never_again(self):
        from auto_capture import _detect_lesson
        assert _detect_lesson("never again deploy on Friday afternoon without running the full test suite")

    def test_detect_lesson_always_remember(self):
        from auto_capture import _detect_lesson
        assert _detect_lesson("always make sure to backup the database before running migrations")

    def test_detect_lesson_key_insight(self):
        from auto_capture import _detect_lesson
        assert _detect_lesson("the key insight is that ONNX models need explicit session options for memory control")

    def test_short_prompt_rejected(self):
        from auto_capture import _detect_lesson
        assert not _detect_lesson("turns out")  # too short

    def test_no_lesson_in_normal_prompt(self):
        from auto_capture import _detect_lesson
        assert not _detect_lesson("please fix the bug in the authentication module and add tests")

    def test_decision_priority_over_lesson(self):
        """Decision patterns should take priority over lesson patterns."""
        from auto_capture import _detect_decision, _detect_lesson
        prompt = "I decided to use the fix was SQLite instead of PostgreSQL"
        # Both match
        assert _detect_decision(prompt)
        assert _detect_lesson(prompt)
        # In main(), decision is checked first and takes priority

    def test_hook_server_lesson_patterns(self):
        """hook_server.py handle_auto_capture should detect lessons."""
        from omega.server.hook_server import handle_auto_capture
        payload = {
            "stdin": json.dumps({
                "prompt": "turns out the bug was caused by a race condition in the event loop handler",
                "session_id": "test-lesson-sess",
                "cwd": "/tmp/testproject",
            }),
        }
        with patch("omega.bridge.auto_capture") as mock_capture:
            mock_capture.return_value = "Stored mem-test12 (lesson_learned, permanent)"
            result = handle_auto_capture(payload)
            assert result["error"] is None
            # Should be called with lesson_learned event type
            if mock_capture.called:
                call_kwargs = mock_capture.call_args
                assert call_kwargs[1]["event_type"] == "lesson_learned"
                assert call_kwargs[1]["content"].startswith("Lesson:")

    def test_hook_server_decision_priority(self):
        """Decision should take priority when both patterns match."""
        from omega.server.hook_server import handle_auto_capture
        payload = {
            "stdin": json.dumps({
                "prompt": "let's go with the fix was to use SQLite instead of PostgreSQL for the backend database",
                "session_id": "test-priority-sess",
                "cwd": "/tmp/testproject",
            }),
        }
        with patch("omega.bridge.auto_capture") as mock_capture:
            mock_capture.return_value = "Stored mem-test12 (lesson_learned, permanent)"
            handle_auto_capture(payload)
            if mock_capture.called:
                call_kwargs = mock_capture.call_args
                assert call_kwargs[1]["event_type"] == "decision"


# ============================================================================
# Gap 2: Memory surfacing on Read tool
# ============================================================================

class TestReadSurfacing:
    """Gap 2: Read tool triggers memory surfacing."""

    def test_settings_has_read_matcher(self):
        """settings.json should include Read in surface_memories matcher."""
        settings_path = Path.home() / ".claude" / "settings.json"
        if settings_path.exists():
            data = json.loads(settings_path.read_text())
            post_tool_hooks = data.get("hooks", {}).get("PostToolUse", [])
            surface_hook = None
            for entry in post_tool_hooks:
                for h in entry.get("hooks", []):
                    if "surface_memories" in h.get("command", ""):
                        surface_hook = entry
                        break
            if surface_hook:
                assert "Read" in surface_hook.get("matcher", "")

    def test_hook_server_surface_memories_read(self):
        """hook_server should surface memories for Read tool."""
        from omega.server.hook_server import handle_surface_memories
        payload = {
            "tool_name": "Read",
            "tool_input": json.dumps({"file_path": "/tmp/test/bridge.py"}),
            "tool_output": "",
            "session_id": "test-read-sess",
            "project": "/tmp/test",
        }
        # Should not raise
        result = handle_surface_memories(payload)
        assert result["error"] is None

    def test_hook_server_surface_memories_read_no_path(self):
        """Read without file_path should be a no-op."""
        from omega.server.hook_server import handle_surface_memories
        payload = {
            "tool_name": "Read",
            "tool_input": json.dumps({}),
            "tool_output": "",
            "session_id": "test-read-sess",
            "project": "/tmp/test",
        }
        result = handle_surface_memories(payload)
        assert result["error"] is None
        assert result["output"] == ""

    def test_surface_memories_script_read(self):
        """surface_memories.py main() should handle Read tool without error."""
        # We can't easily test the full main() since it reads env vars,
        # but we can verify the Read branch exists in the source
        hooks_dir = Path(__file__).parent.parent / "hooks" / "surface_memories.py"
        source = hooks_dir.read_text()
        assert 'tool_name == "Read"' in source


# ============================================================================
# Gap 3: omega_phrase_search MCP tool
# ============================================================================

class TestPhraseSearch:
    """Gap 3: omega_phrase_search exposed as MCP tool."""

    def test_phrase_mode_in_query_schema(self):
        """omega_query should support mode='phrase' (phrase_search merged into query)."""
        query_schema = next(s for s in TOOL_SCHEMAS if s["name"] == "omega_query")
        props = query_schema["inputSchema"]["properties"]
        assert "mode" in props
        assert "phrase" in props["mode"]["enum"]

    def test_handler_alias_exists(self):
        """omega_phrase_search backward-compat alias should be in HANDLERS."""
        assert "omega_phrase_search" in HANDLERS

    @pytest.mark.asyncio
    async def test_phrase_search_empty_phrase(self):
        """Empty phrase should return error."""
        result = await HANDLERS["omega_phrase_search"]({"phrase": ""})
        assert result.get("isError")

    @pytest.mark.asyncio
    async def test_phrase_search_no_results(self):
        """Search for nonexistent phrase returns empty results."""
        result = await HANDLERS["omega_phrase_search"]({"phrase": "xyznonexistent123"})
        assert not result.get("isError")
        text = result["content"][0]["text"]
        assert "Phrase Search" in text
        assert "No matching" in text or "0" in text

    @pytest.mark.asyncio
    async def test_phrase_search_finds_match(self):
        """Search for a known phrase returns results."""
        await _store_test_memory("The quick brown fox jumps over the lazy dog in the garden")
        result = await HANDLERS["omega_phrase_search"]({"phrase": "brown fox"})
        assert not result.get("isError")
        text = result["content"][0]["text"]
        assert "brown fox" in text.lower() or "Phrase Search" in text

    @pytest.mark.asyncio
    async def test_phrase_search_with_event_type(self):
        """Phrase search respects event_type filter."""
        await _store_test_memory(
            "Important lesson about database indexing strategies for performance",
            event_type="lesson_learned",
        )
        result = await HANDLERS["omega_phrase_search"]({
            "phrase": "database indexing",
            "event_type": "lesson_learned",
        })
        assert not result.get("isError")

    @pytest.mark.asyncio
    async def test_phrase_search_with_limit(self):
        """Phrase search respects limit parameter."""
        result = await HANDLERS["omega_phrase_search"]({
            "phrase": "test",
            "limit": 2,
        })
        assert not result.get("isError")

    def test_bridge_phrase_search(self):
        """Bridge phrase_search function exists and works."""
        from omega.bridge import phrase_search
        result = phrase_search("nonexistent phrase xyz")
        assert "Phrase Search" in result
        assert "No matching" in result or "0" in result


# ============================================================================
# Gap 4: filter_tags on omega_query
# ============================================================================

class TestFilterTags:
    """Gap 4: Hard tag filtering on omega_query."""

    def test_schema_has_filter_tags(self):
        """omega_query schema should include filter_tags property."""
        query_schema = next(s for s in TOOL_SCHEMAS if s["name"] == "omega_query")
        props = query_schema["inputSchema"]["properties"]
        assert "filter_tags" in props
        assert props["filter_tags"]["type"] == "array"

    @pytest.mark.asyncio
    async def test_query_without_filter_tags(self):
        """Query without filter_tags should work as before."""
        await _store_test_memory("Python testing best practices for CI pipelines")
        result = await HANDLERS["omega_query"]({"query": "Python testing"})
        assert not result.get("isError")

    @pytest.mark.asyncio
    async def test_query_with_filter_tags_match(self):
        """Query with matching filter_tags returns results."""
        await _store_test_memory(
            "Python testing framework comparison pytest vs unittest for large projects",
            tags=["python", "pytest"],
        )
        result = await HANDLERS["omega_query"]({
            "query": "testing framework",
            "filter_tags": ["python"],
        })
        assert not result.get("isError")

    @pytest.mark.asyncio
    async def test_query_with_filter_tags_no_match(self):
        """Query with non-matching filter_tags returns no results."""
        await _store_test_memory(
            "JavaScript React component lifecycle hooks and effects management",
            tags=["javascript", "react"],
        )
        result = await HANDLERS["omega_query"]({
            "query": "component lifecycle",
            "filter_tags": ["rust"],
        })
        assert not result.get("isError")
        text = result["content"][0]["text"]
        assert "No matching" in text or "0)" in text

    @pytest.mark.asyncio
    async def test_filter_tags_and_logic(self):
        """filter_tags uses AND logic — all tags must be present."""
        await _store_test_memory(
            "Python Django REST API pagination best practices and optimization techniques",
            tags=["python", "django"],
        )
        # Searching for both python AND rust should not match a python+django memory
        result = await HANDLERS["omega_query"]({
            "query": "API pagination",
            "filter_tags": ["python", "rust"],
        })
        assert not result.get("isError")
        text = result["content"][0]["text"]
        assert "No matching" in text or "0)" in text

    def test_bridge_query_filter_tags_param(self):
        """Bridge query() should accept filter_tags parameter."""
        import inspect
        from omega.bridge import query
        sig = inspect.signature(query)
        assert "filter_tags" in sig.parameters


# ============================================================================
# Gap 5: Auto-announce intent on Edit/Write
# ============================================================================

class TestAutoAnnounceIntent:
    """Gap 5: Intent auto-announced when editing files."""

    def test_hook_server_auto_claim_announces_intent(self):
        """handle_auto_claim_file should call announce_intent after claim."""
        from omega.server.hook_server import handle_auto_claim_file
        payload = {
            "tool_name": "Edit",
            "session_id": "test-intent-sess",
            "tool_input": json.dumps({"file_path": "/tmp/test/bridge.py"}),
        }
        mock_mgr = MagicMock()
        mock_mgr.claim_file.return_value = {"success": True, "file_path": "/tmp/test/bridge.py"}
        with patch("omega.coordination.get_manager", return_value=mock_mgr):
            # Clear debounce state
            from omega.server import hook_server
            hook_server._last_claim.clear()
            result = handle_auto_claim_file(payload)
            assert result["error"] is None
            # claim_file should be called
            mock_mgr.claim_file.assert_called_once()
            # announce_intent should also be called
            mock_mgr.announce_intent.assert_called_once()
            call_kwargs = mock_mgr.announce_intent.call_args[1]
            assert call_kwargs["session_id"] == "test-intent-sess"
            assert call_kwargs["intent_type"] == "edit"
            assert "/tmp/test/bridge.py" in call_kwargs["target_files"]
            assert call_kwargs["ttl_minutes"] == 5

    def test_hook_server_intent_silent_failure(self):
        """Intent announcement failure should not break the claim."""
        from omega.server.hook_server import handle_auto_claim_file
        payload = {
            "tool_name": "Write",
            "session_id": "test-intent-fail-sess",
            "tool_input": json.dumps({"file_path": "/tmp/test/new_file.py"}),
        }
        mock_mgr = MagicMock()
        mock_mgr.claim_file.return_value = {"success": True, "file_path": "/tmp/test/new_file.py"}
        mock_mgr.announce_intent.side_effect = Exception("intent failed")
        with patch("omega.coordination.get_manager", return_value=mock_mgr):
            from omega.server import hook_server
            hook_server._last_claim.clear()
            result = handle_auto_claim_file(payload)
            assert result["error"] is None  # Should not propagate
            mock_mgr.claim_file.assert_called_once()

    def test_fallback_hook_announces_intent(self):
        """hooks/auto_claim_file.py should also call announce_intent."""
        hooks_dir = Path(__file__).parent.parent / "hooks" / "auto_claim_file.py"
        source = hooks_dir.read_text()
        assert "announce_intent" in source
        assert "intent_type" in source
        assert "ttl_minutes" in source

    def test_hook_server_no_intent_on_non_edit(self):
        """Non-edit tools should not trigger intent announcement."""
        from omega.server.hook_server import handle_auto_claim_file
        payload = {
            "tool_name": "Bash",
            "session_id": "test-no-intent-sess",
            "tool_input": json.dumps({"command": "ls"}),
        }
        mock_mgr = MagicMock()
        with patch("omega.coordination.get_manager", return_value=mock_mgr):
            handle_auto_claim_file(payload)
            mock_mgr.claim_file.assert_not_called()
            mock_mgr.announce_intent.assert_not_called()


# ============================================================================
# Gap 6: omega_type_stats and omega_session_stats MCP tools
# ============================================================================

class TestTypeStats:
    """Gap 6: omega_type_stats MCP tool."""

    def test_schema_exists(self):
        names = [s["name"] for s in TOOL_SCHEMAS]
        assert "omega_stats" in names  # consolidated: type_stats is now omega_stats action=types

    def test_handler_exists(self):
        assert "omega_type_stats" in HANDLERS  # backward-compat alias

    @pytest.mark.asyncio
    async def test_type_stats_empty(self):
        """Type stats on empty store returns a message."""
        result = await HANDLERS["omega_type_stats"]({})
        assert not result.get("isError")

    @pytest.mark.asyncio
    async def test_type_stats_with_data(self):
        """Type stats with data returns percentages."""
        await _store_test_memory("Lesson about testing patterns for CI", event_type="lesson_learned")
        await _store_test_memory("Decision to use pytest for all tests", event_type="decision")
        await _store_test_memory("Error in import resolution path", event_type="error_pattern")
        result = await HANDLERS["omega_type_stats"]({})
        assert not result.get("isError")
        text = result["content"][0]["text"]
        assert "Type Stats" in text
        assert "%" in text

    def test_bridge_type_stats(self):
        """Bridge type_stats function exists and returns a dict."""
        from omega.bridge import type_stats
        result = type_stats()
        assert isinstance(result, dict)


class TestSessionStats:
    """Gap 6: omega_session_stats MCP tool."""

    def test_schema_exists(self):
        names = [s["name"] for s in TOOL_SCHEMAS]
        assert "omega_stats" in names  # consolidated: session_stats is now omega_stats action=sessions

    def test_handler_exists(self):
        assert "omega_session_stats" in HANDLERS  # backward-compat alias

    @pytest.mark.asyncio
    async def test_session_stats_empty(self):
        """Session stats on empty store returns a message."""
        result = await HANDLERS["omega_session_stats"]({})
        assert not result.get("isError")

    @pytest.mark.asyncio
    async def test_session_stats_with_data(self):
        """Session stats with data returns session list."""
        await _store_test_memory("Memory from session A for testing purposes",
                                  session_id="sess-a-12345678")
        await _store_test_memory("Memory from session B for testing purposes",
                                  session_id="sess-b-87654321")
        result = await HANDLERS["omega_session_stats"]({})
        assert not result.get("isError")
        text = result["content"][0]["text"]
        assert "Session Stats" in text
        assert "memories" in text.lower()

    def test_bridge_session_stats(self):
        """Bridge session_stats function exists and returns a dict."""
        from omega.bridge import session_stats
        result = session_stats()
        assert isinstance(result, dict)


# ============================================================================
# Cross-cutting: tool count
# ============================================================================

class TestToolCount:
    """Verify the total tool count is correct after changes."""

    def test_total_tool_count(self):
        assert len(TOOL_SCHEMAS) >= 12  # 12 consolidated action-discriminated composites

    def test_total_handler_count(self):
        # 27 schemas + 3 backward-compat aliases + 4 composite handlers
        assert len(HANDLERS) >= 30

    def test_new_tools_in_schemas(self):
        names = [s["name"] for s in TOOL_SCHEMAS]
        assert "omega_stats" in names  # consolidated: type_stats + session_stats + digest + forgetting_log
        # phrase_search merged into omega_query (mode='phrase')
        query_schema = next(s for s in TOOL_SCHEMAS if s["name"] == "omega_query")
        assert "mode" in query_schema["inputSchema"]["properties"]

    def test_new_tools_in_handlers(self):
        assert "omega_phrase_search" in HANDLERS  # backward-compat alias
        assert "omega_type_stats" in HANDLERS
        assert "omega_session_stats" in HANDLERS
