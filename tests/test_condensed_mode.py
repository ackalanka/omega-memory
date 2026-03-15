"""Tests for Condensed Mode (CodeMode-inspired tool condensation)."""
import json
import pytest
from omega.server.tool_schemas import (
    TOOL_SCHEMAS,
    STANDALONE_TOOLS,
    CONDENSED_TOOL_SCHEMAS,
    TOOL_CATEGORIES,
    get_condensed_schemas,
)
from omega.server.handlers import (
    HANDLERS,
    handle_omega_tools,
    handle_omega_call,
    _ALL_SCHEMAS,
    _ALL_HANDLERS,
)


# ============================================================================
# Setup: ensure handlers module has schema/handler references
# ============================================================================

@pytest.fixture(autouse=True)
def _wire_schemas():
    """Ensure _ALL_SCHEMAS and _ALL_HANDLERS are populated for tests."""
    import omega.server.handlers as h
    if not h._ALL_SCHEMAS:
        h._ALL_SCHEMAS = list(TOOL_SCHEMAS)
    if not h._ALL_HANDLERS:
        h._ALL_HANDLERS.update(HANDLERS)


# ============================================================================
# Schema Tests
# ============================================================================

def test_standalone_tools_exist():
    """All standalone tools should exist in TOOL_SCHEMAS."""
    schema_names = {s["name"] for s in TOOL_SCHEMAS}
    for name in STANDALONE_TOOLS:
        assert name in schema_names, f"Standalone tool {name} not in TOOL_SCHEMAS"


def test_condensed_meta_tools_have_schemas():
    """omega_tools and omega_call should have valid schemas."""
    assert len(CONDENSED_TOOL_SCHEMAS) == 2
    names = {s["name"] for s in CONDENSED_TOOL_SCHEMAS}
    assert "omega_tools" in names
    assert "omega_call" in names
    for schema in CONDENSED_TOOL_SCHEMAS:
        assert "description" in schema
        assert "inputSchema" in schema


def test_condensed_schemas_count():
    """Condensed mode should return standalone + meta-tools only."""
    condensed = get_condensed_schemas(TOOL_SCHEMAS)
    expected = len(STANDALONE_TOOLS) + len(CONDENSED_TOOL_SCHEMAS)
    assert len(condensed) == expected
    names = {s["name"] for s in condensed}
    for standalone in STANDALONE_TOOLS:
        assert standalone in names
    assert "omega_tools" in names
    assert "omega_call" in names


def test_all_core_tools_have_categories():
    """Every core tool should have a category mapping."""
    for schema in TOOL_SCHEMAS:
        assert schema["name"] in TOOL_CATEGORIES, (
            f"Tool {schema['name']} missing from TOOL_CATEGORIES"
        )


def test_meta_tools_have_handlers():
    """omega_tools and omega_call should be in HANDLERS."""
    assert "omega_tools" in HANDLERS
    assert "omega_call" in HANDLERS


# ============================================================================
# Token Savings Tests
# ============================================================================

def test_token_savings():
    """Condensed mode should be at least 70% smaller than full mode."""
    full_json = json.dumps(
        [{"name": s["name"], "description": s["description"], "inputSchema": s["inputSchema"]}
         for s in TOOL_SCHEMAS]
    )
    condensed = get_condensed_schemas(TOOL_SCHEMAS)
    condensed_json = json.dumps(
        [{"name": s["name"], "description": s["description"], "inputSchema": s["inputSchema"]}
         for s in condensed]
    )
    full_size = len(full_json)
    condensed_size = len(condensed_json)
    savings = 1 - (condensed_size / full_size)
    assert savings >= 0.70, (
        f"Expected >=70% savings, got {savings:.1%} "
        f"(full={full_size}B, condensed={condensed_size}B)"
    )


# ============================================================================
# Handler Tests
# ============================================================================

@pytest.mark.asyncio
async def test_omega_tools_list():
    """omega_tools with no args should list all tools."""
    result = await handle_omega_tools({})
    text = result["content"][0]["text"]
    assert "omega_query" in text
    assert "omega_maintain" in text


@pytest.mark.asyncio
async def test_omega_tools_detail():
    """omega_tools with tool name should return full schema."""
    result = await handle_omega_tools({"tool": "omega_query"})
    text = result["content"][0]["text"]
    schema = json.loads(text)
    assert "properties" in schema
    assert "query" in schema["properties"]


@pytest.mark.asyncio
async def test_omega_tools_unknown():
    """omega_tools with unknown tool should return error."""
    result = await handle_omega_tools({"tool": "nonexistent"})
    text = result["content"][0]["text"]
    assert "Unknown tool" in text


@pytest.mark.asyncio
async def test_omega_tools_category_filter():
    """omega_tools with category should filter results."""
    result = await handle_omega_tools({"category": "maintenance"})
    text = result["content"][0]["text"]
    assert "omega_maintain" in text
    # Session tools should not appear in maintenance category
    assert "omega_welcome" not in text


@pytest.mark.asyncio
async def test_omega_call_unknown_tool():
    """omega_call with unknown tool should return error."""
    result = await handle_omega_call({"tool": "nonexistent", "args": {}})
    text = result["content"][0]["text"]
    assert "Unknown tool" in text


@pytest.mark.asyncio
async def test_omega_call_missing_tool():
    """omega_call without tool param should return error."""
    result = await handle_omega_call({})
    text = result["content"][0]["text"]
    assert "missing" in text.lower()
