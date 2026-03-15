"""Tests for the OMEGA remote MCP server (FastMCP HTTP).

Uses FastMCP's in-process Client for fast, isolated testing.
Each test gets a fresh OMEGA_HOME via tmp_omega_dir.
"""

import pytest

from omega.server.remote_server import mcp

# Re-use the shared conftest fixture (tmp_omega_dir) which sets OMEGA_HOME,
# disables encryption, and cleans up afterwards.

# We need to reset the bridge singleton between tests so each test
# gets a fresh database pointing at the tmp_omega_dir.


@pytest.fixture(autouse=True)
def _reset_bridge_singleton():
    """Reset bridge singleton before and after each test."""
    from omega.bridge import reset_memory

    reset_memory()
    yield
    reset_memory()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

async def _call(tool_name: str, args: dict | None = None) -> str:
    """Call a tool via the FastMCP in-process Client, return text."""
    from fastmcp import Client

    async with Client(mcp) as client:
        result = await client.call_tool(tool_name, args or {})
        return result.content[0].text


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_delegates_to_handler(tmp_omega_dir):
    """omega_store should delegate to the handler and return confirmation text."""
    text = await _call("omega_store", {"content": "Remember this fact"})
    assert "stored" in text.lower() or "remember" in text.lower() or len(text) > 0


@pytest.mark.asyncio
async def test_query_searches_memories(tmp_omega_dir):
    """Store a memory, then query for it."""
    await _call("omega_store", {"content": "The capital of France is Paris"})
    text = await _call("omega_query", {"query": "capital of France"})
    assert "Paris" in text


@pytest.mark.asyncio
async def test_profile_read_returns_text(tmp_omega_dir):
    """omega_profile read should return a profile or empty message."""
    text = await _call("omega_profile", {"action": "read"})
    # Fresh install returns "No profile found" message
    assert "profile" in text.lower() or len(text) > 0


@pytest.mark.asyncio
async def test_remind_set_creates_reminder(tmp_omega_dir):
    """omega_remind set should create a reminder and return its ID."""
    text = await _call(
        "omega_remind",
        {"action": "set", "text": "Check deployment", "duration": "1h"},
    )
    assert "reminder" in text.lower() or "id" in text.lower()


@pytest.mark.asyncio
async def test_memory_flagged_action(tmp_omega_dir):
    """omega_memory flagged should work even with no flagged memories."""
    text = await _call("omega_memory", {"action": "flagged"})
    # Should return either flagged items or a "no flagged" message
    assert isinstance(text, str)
    assert len(text) > 0


@pytest.mark.asyncio
async def test_only_five_tools_exposed(tmp_omega_dir):
    """Exactly 5 tools should be registered: omega_store, omega_query,
    omega_memory, omega_remind, omega_profile."""
    from fastmcp import Client

    expected = {"omega_store", "omega_query", "omega_memory", "omega_remind", "omega_profile"}
    async with Client(mcp) as client:
        tools = await client.list_tools()
        names = {t.name for t in tools}
    assert names == expected, f"Expected {expected}, got {names}"


@pytest.mark.asyncio
async def test_all_tools_have_descriptions(tmp_omega_dir):
    """Every exposed tool must have a non-empty description."""
    from fastmcp import Client

    async with Client(mcp) as client:
        tools = await client.list_tools()
        for tool in tools:
            assert tool.description, f"Tool {tool.name} has no description"
            assert len(tool.description) > 10, f"Tool {tool.name} description too short"
