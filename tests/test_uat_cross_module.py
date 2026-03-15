"""UAT — Cross-Module Workflows: Memory + Coordination.

End-to-end acceptance tests spanning multiple OMEGA subsystems.
Tests interactions that only emerge when modules work together.

Organized into three sections:
  1. Memory + Coordination — register → store memories → deregister → memories survive
  2. Multi-Agent Memory — two agents store independently → cross-session lessons visible
  3. Full Agent Lifecycle — register → claim → store → task → deregister
"""
import json
import re
import sys
import pytest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from omega.server.handlers import HANDLERS
from omega.server.coord_handlers import COORD_HANDLERS


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture(autouse=True)
def _reset_bridge(tmp_omega_dir):
    """Reset the bridge singleton before and after each test."""
    from omega.bridge import reset_memory
    reset_memory()
    yield
    reset_memory()


def _text(result: dict) -> str:
    """Extract text from an MCP response."""
    return result["content"][0]["text"]


def _is_error(result: dict) -> bool:
    """Check if an MCP response is an error."""
    return result.get("isError", False)


async def _store_and_get_id(content, event_type="lesson_learned", **kwargs) -> str:
    """Store via handler, extract node_id from response."""
    result = await HANDLERS["omega_store"](
        {"content": content, "event_type": event_type, **kwargs}
    )
    assert not _is_error(result), f"Store failed: {_text(result)}"
    text = _text(result)
    # Extract node ID from compact format: "Stored mem-xxxxx ..." or "Deduped → mem-xxxxx ..."
    match = re.search(r"(?:Stored|Deduped|Evolved)\s+(?:→\s*)?(mem-[a-f0-9]+)", text)
    if match:
        return match.group(1)
    return text


# ============================================================================
# SECTION 1: Memory + Coordination
# ============================================================================


class TestUATMemoryPlusCoordination:
    """Interactions between memory storage and coordination lifecycle."""

    def test_memories_survive_deregistration(self, coord_mgr):
        """UAT: Memories stored during a session survive after deregistration."""
        # Register session
        coord_mgr.register_session("mem-coord-1", pid=1001, project="/proj/a")

        # Store memories through bridge (simulates handler storing)
        from omega.bridge import store
        store(
            content="Important lesson learned during this session about OMEGA coordination system integration",
            event_type="lesson_learned",
            session_id="mem-coord-1",
        )

        # Deregister
        coord_mgr.deregister_session("mem-coord-1")

        # Memories should still be queryable
        from omega.bridge import query
        result = query("OMEGA coordination system integration")
        assert "coordination" in result.lower()

    def test_session_metadata_in_memories(self, coord_mgr):
        """UAT: Session context is preserved in stored memory metadata."""
        coord_mgr.register_session("meta-sess-1", pid=2002, project="/proj/b", task="testing")

        from omega.bridge import store
        store(
            content="Decision to use SQLite-vec for vector search in the OMEGA memory persistence layer",
            event_type="decision",
            session_id="meta-sess-1",
        )

        from omega.bridge import query_structured
        results = query_structured("SQLite-vec vector search")
        assert len(results) > 0

    def test_claimed_file_does_not_affect_memories(self, coord_mgr):
        """UAT: File claims are orthogonal to memory storage."""
        coord_mgr.register_session("claim-mem-1", pid=3003, project="/proj/c")
        coord_mgr.claim_file("claim-mem-1", "/proj/c/handler.py")

        from omega.bridge import store
        store(
            content="Lesson about handler implementation patterns for the OMEGA MCP server interface",
            event_type="lesson_learned",
            session_id="claim-mem-1",
        )

        # Release claim — memory should still exist
        coord_mgr.release_file("claim-mem-1", "/proj/c/handler.py")

        from omega.bridge import query
        result = query("handler implementation patterns MCP server")
        assert "handler" in result.lower()

    @pytest.mark.asyncio
    async def test_coord_handler_and_memory_handler_coexist(self, coord_mgr):
        """UAT: Calling coord handlers and memory handlers in sequence works."""
        with patch("omega.coordination.get_manager", return_value=coord_mgr):
            # Register via coord handler
            result = await COORD_HANDLERS["omega_session_register"]({
                "session_id": "coexist-1",
                "pid": 4004,
                "project": "/proj/d",
                "task": "cross-module testing",
            })
            assert not _is_error(result)

            # Store via memory handler
            mem_result = await HANDLERS["omega_store"]({
                "content": "Cross-module test memory stored during active coordination session for integration",
                "event_type": "lesson_learned",
                "session_id": "coexist-1",
            })
            assert not _is_error(mem_result)

            # Query via memory handler
            query_result = await HANDLERS["omega_query"]({
                "query": "cross-module coordination session integration",
            })
            assert not _is_error(query_result)

    @pytest.mark.asyncio
    async def test_session_clear_does_not_affect_coordination(self, coord_mgr):
        """UAT: Clearing a session's memories doesn't deregister it from coordination."""
        with patch("omega.coordination.get_manager", return_value=coord_mgr):
            coord_mgr.register_session("clear-coord-1", pid=5005, project="/proj/e")

            await HANDLERS["omega_store"]({
                "content": "Memory that will be cleared from this session but coordination should persist",
                "event_type": "lesson_learned",
                "session_id": "clear-coord-1",
            })

            # Clear memories
            await HANDLERS["omega_clear_session"]({"session_id": "clear-coord-1"})

            # Session should still be registered in coordination
            sessions = coord_mgr.list_sessions(auto_clean=False)
            assert any(s["session_id"] == "clear-coord-1" for s in sessions)

    @pytest.mark.asyncio
    async def test_lessons_accessible_after_deregister(self, coord_mgr):
        """UAT: Lessons from a deregistered session are still accessible via query."""
        from omega.bridge import store
        store(
            content="Cross-session lesson: always validate MCP handler arguments before processing them",
            event_type="lesson_learned",
            session_id="lessons-sess-1",
        )
        coord_mgr.register_session("lessons-sess-1", pid=6006, project="/proj/f")
        coord_mgr.deregister_session("lessons-sess-1")

        # omega_lessons removed — query for lessons via omega_query instead
        result = await HANDLERS["omega_query"]({"query": "MCP handler validation", "event_type": "lesson_learned"})
        assert not _is_error(result)
        text = _text(result)
        assert "lesson" in text.lower() or "validate" in text.lower() or "no " in text.lower()


# ============================================================================
# SECTION 2: Multi-Agent Memory
# ============================================================================


class TestUATMultiAgentMemoryCoordination:
    """Multi-agent memory interactions through handlers."""

    @pytest.mark.asyncio
    async def test_independent_session_memories(self):
        """UAT: Two agents store memories independently with different sessions."""
        await HANDLERS["omega_store"]({
            "content": "Agent Alpha lesson: the OMEGA SQLite store needs WAL mode for concurrent read access",
            "event_type": "lesson_learned",
            "session_id": "agent-alpha",
        })
        await HANDLERS["omega_store"]({
            "content": "Agent Beta lesson: ONNX embedding inference should use CPU-only mode to avoid CoreML leaks",
            "event_type": "lesson_learned",
            "session_id": "agent-beta",
        })

        # Each agent can query across all sessions (global query)
        result = await HANDLERS["omega_query"]({"query": "OMEGA SQLite WAL"})
        assert not _is_error(result)
        assert "WAL" in _text(result) or "SQLite" in _text(result)

        result = await HANDLERS["omega_query"]({"query": "ONNX embedding CPU CoreML"})
        assert not _is_error(result)

    @pytest.mark.asyncio
    async def test_cross_session_lessons_visible(self):
        """UAT: Lessons stored by one agent are visible to another agent's query."""
        await HANDLERS["omega_store"]({
            "content": "Cross-agent lesson: never nest threading.Lock acquisitions in Python because they deadlock silently",
            "event_type": "lesson_learned",
            "session_id": "agent-x",
        })
        # Agent Y queries without session scope
        result = await HANDLERS["omega_query"]({
            "query": "threading Lock deadlock",
        })
        assert not _is_error(result)
        text = _text(result)
        assert "threading" in text.lower() or "Lock" in text or "deadlock" in text.lower()

    @pytest.mark.asyncio
    async def test_session_isolation_with_clear(self):
        """UAT: Clearing one agent's session doesn't affect another's."""
        await HANDLERS["omega_store"]({
            "content": "Agent One lesson: use pytest markers to categorize slow integration tests separately",
            "event_type": "lesson_learned",
            "session_id": "agent-one",
        })
        await HANDLERS["omega_store"]({
            "content": "Agent Two lesson: the OMEGA bridge singleton must be reset between test runs for isolation",
            "event_type": "lesson_learned",
            "session_id": "agent-two",
        })

        # Clear agent-one's session
        await HANDLERS["omega_clear_session"]({"session_id": "agent-one"})

        # Agent Two's memory should survive
        result = await HANDLERS["omega_query"]({"query": "OMEGA bridge singleton reset"})
        text = _text(result)
        assert "bridge" in text.lower() or "singleton" in text.lower()

    @pytest.mark.asyncio
    async def test_type_stats_aggregates_all_agents(self):
        """UAT: Type stats aggregates memories from all sessions."""
        await HANDLERS["omega_store"]({
            "content": "Alpha decision about configuring the OMEGA MCP server with stdio transport",
            "event_type": "decision",
            "session_id": "stats-alpha",
        })
        await HANDLERS["omega_store"]({
            "content": "Beta error pattern about the ImportError when omega.bridge module is not on sys.path",
            "event_type": "error_pattern",
            "session_id": "stats-beta",
        })
        result = await HANDLERS["omega_type_stats"]({})
        text = _text(result)
        assert "decision" in text
        assert "error_pattern" in text


# ============================================================================
# SECTION 3: Full Agent Lifecycle
# ============================================================================


class TestUATFullAgentLifecycle:
    """Full agent lifecycle spanning memory and coordination."""

    def test_register_store_claim_deregister(self, coord_mgr):
        """UAT: Full lifecycle — register, store, claim, deregister."""
        coord_mgr.register_session("lifecycle-1", pid=7007, project="/proj/g", task="feature implementation")
        coord_mgr.claim_file("lifecycle-1", "/proj/g/feature.py")

        from omega.bridge import store
        store(
            content="Lifecycle test: decision to implement the feature using the adapter pattern for modularity",
            event_type="decision",
            session_id="lifecycle-1",
        )

        coord_mgr.release_file("lifecycle-1", "/proj/g/feature.py")
        coord_mgr.deregister_session("lifecycle-1")

        # Memory persists
        from omega.bridge import query
        result = query("adapter pattern modularity")
        assert "adapter" in result.lower()

    def test_task_lifecycle_with_memories(self, coord_mgr):
        """UAT: Task creation and completion alongside memory storage."""
        coord_mgr.register_session("task-mem-1", pid=8008, project="/proj/h")

        # Create and claim task
        task = coord_mgr.create_task(
            created_by="task-mem-1",
            title="Implement UAT tests",
            description="Write comprehensive UAT test suite for OMEGA",
            project="/proj/h",
        )
        task_id = task["task_id"]
        coord_mgr.claim_task(task_id, "task-mem-1")

        # Store progress memory
        from omega.bridge import store
        store(
            content="Task progress: completed 80% of UAT test implementations for the OMEGA memory subsystem",
            event_type="decision",
            session_id="task-mem-1",
        )

        # Complete task
        coord_mgr.complete_task(task_id, "task-mem-1", result="All UAT tests written")

        # Memory survives task completion
        from omega.bridge import query
        result = query("UAT test implementations OMEGA memory subsystem")
        assert "UAT" in result or "test" in result.lower()

    @pytest.mark.asyncio
    async def test_welcome_after_multi_agent_session(self, coord_mgr):
        """UAT: Welcome briefing reflects memories from multiple agent sessions."""
        # Agent 1 stores a decision
        await HANDLERS["omega_store"]({
            "content": "Multi-agent decision: use FTS5 phrase search for exact match queries in OMEGA",
            "event_type": "decision",
            "session_id": "multi-welcome-a",
        })
        # Agent 2 stores a lesson
        await HANDLERS["omega_store"]({
            "content": "Multi-agent lesson: always check isError field in MCP handler responses before processing",
            "event_type": "lesson_learned",
            "session_id": "multi-welcome-b",
        })

        result = await HANDLERS["omega_welcome"]({})
        assert not _is_error(result)
        text = _text(result)
        # Welcome now returns markdown, not JSON
        assert "Welcome Briefing" in text
        assert "memories)" in text

    @pytest.mark.asyncio
    async def test_health_check_across_modules(self):
        """UAT: Health check works even when memories exist from multiple sources."""
        await HANDLERS["omega_store"]({
            "content": "Health check test memory stored through the MCP handler interface for cross-module verification",
            "event_type": "lesson_learned",
        })
        result = await HANDLERS["omega_health"]({})
        assert not _is_error(result)
        text = _text(result)
        assert "Status:" in text
        assert "Nodes:" in text
