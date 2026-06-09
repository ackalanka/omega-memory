"""Regression tests for agent-facing MCP retrieval guidance."""

import importlib.resources

import pytest

from omega import json_compat as json
from omega.server import handlers
from omega.server.handlers import handle_omega_protocol
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

    assert "detail='full'" in meta["omega_tools"]["description"]
    assert "Use omega_tools() first" in meta["omega_call"]["description"]
    assert "omega_recall" in meta["omega_call"]["description"]


@pytest.mark.asyncio
async def test_omega_tools_specific_tool_returns_full_discovery_record():
    """Condensed agents need description, category, schema, and call examples."""
    handlers._ALL_SCHEMAS = TOOL_SCHEMAS
    handlers._ALL_HANDLERS = handlers.HANDLERS

    schema_result = await handlers.handle_omega_tools({"tool": "omega_recall"})
    assert not schema_result.get("isError")
    schema_payload = json.loads(schema_result["content"][0]["text"])
    assert "properties" in schema_payload
    assert "profile" in schema_payload["properties"]
    assert "description" not in schema_payload

    result = await handlers.handle_omega_tools({"tool": "omega_recall", "detail": "full"})

    assert not result.get("isError")
    payload = json.loads(result["content"][0]["text"])
    assert payload["name"] == "omega_recall"
    assert payload["category"] == "query"
    assert "prompt-ready context" in payload["description"]
    assert payload["inputSchema"]["properties"]["profile"]["enum"] == [
        "general",
        "debug",
        "planning",
        "handoff",
        "review",
        "implementation",
    ]
    assert payload["omega_call_example"]["tool"] == "omega_recall"
    assert payload["omega_call_example"]["args"]["profile"] == "planning"
    assert payload["omega_call_example"]["args"]["budget_chars"] == 12000


@pytest.mark.asyncio
async def test_free_protocol_fallback_teaches_retrieval_workflow():
    """omega_protocol Free fallback is a startup instruction surface too."""
    result = await handle_omega_protocol({"project": "/tmp/omega-instruction-test"})

    assert not result.get("isError")
    text = result["content"][0]["text"]
    assert "omega_context" in text
    assert "omega_recall" in text
    assert "omega_memory(action=\"get\"" in text
    assert "omega_query(format=\"json\"" in text
    assert "omega_tools" in text
    assert "omega_call" in text
    assert "Call `omega_query()` before non-trivial tasks" not in text


def test_claude_setup_fragments_teach_retrieval_workflow():
    """Managed client fragments should not regress to preview-only query advice."""
    for filename in ("claude-md-fragment.md", "claude-md-fragment-pro.md"):
        text = importlib.resources.files("omega.data").joinpath(filename).read_text()
        assert "omega_context" in text
        assert "omega_recall" in text
        assert "omega_memory(action=\"get\"" in text
        assert "omega_query(format=\"json\"" in text
        assert "omega_tools" in text
        assert "omega_call" in text
        assert "Before non-trivial tasks: `omega_query()`" not in text
