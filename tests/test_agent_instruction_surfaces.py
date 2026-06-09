"""Regression tests for agent-facing MCP retrieval guidance."""

from omega.server import mcp_server
from omega.server.tool_schemas import CONDENSED_TOOL_SCHEMAS, TOOL_SCHEMAS


def _schema(name: str) -> dict:
    return next(schema for schema in TOOL_SCHEMAS if schema["name"] == name)


def test_mcp_startup_instructions_teach_long_context_retrieval():
    """Agents should see the Iteration 1 retrieval workflow at startup."""
    full = mcp_server._MCP_INSTRUCTIONS
    condensed = mcp_server._MCP_INSTRUCTIONS_CONDENSED

    for text in (full, condensed):
        assert "omega_context" in text
        assert "omega_recall" in text
        assert "omega_query" in text
        assert "omega_memory" in text
        assert "mode='browse'" in text or "'mode': 'browse'" in text

    assert "omega_call(tool='omega_recall'" in condensed
    assert "omega_call(tool='omega_memory'" in condensed


def test_retrieval_tool_schemas_explain_agent_use_cases():
    """Tool discovery should expose enough guidance for correct retrieval use."""
    recall = _schema("omega_recall")
    context = _schema("omega_context")
    memory = _schema("omega_memory")
    query = _schema("omega_query")

    assert "prompt-ready context" in recall["description"]
    assert "project-scoped context pack" in context["description"]
    assert "get full records" in memory["description"]
    assert "content_mode" in query["inputSchema"]["properties"]
    assert "budget_chars" in query["inputSchema"]["properties"]


def test_condensed_meta_tools_point_to_discovery_then_call():
    """Condensed mode should teach schema discovery before meta-calls."""
    meta = {schema["name"]: schema for schema in CONDENSED_TOOL_SCHEMAS}

    assert "full schema" in meta["omega_tools"]["description"]
    assert "Use omega_tools() first" in meta["omega_call"]["description"]
    assert "omega_recall" in meta["omega_call"]["description"]
