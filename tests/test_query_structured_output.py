"""Tests for structured/full-content omega_query MCP output."""

import json

import pytest

from omega.server.handlers import handle_omega_query
from omega.server.tool_schemas import TOOL_SCHEMAS


def _text(result: dict) -> str:
    return result["content"][0]["text"]


def _is_error(result: dict) -> bool:
    return result.get("isError", False)


@pytest.fixture(autouse=True)
def _fresh_bridge(tmp_omega_dir):
    from omega.bridge import reset_memory

    reset_memory()
    yield
    reset_memory()


def _query_schema_props() -> dict:
    schema = next(tool for tool in TOOL_SCHEMAS if tool["name"] == "omega_query")
    return schema["inputSchema"]["properties"]


class TestOmegaQueryStructuredSchema:
    def test_schema_exposes_structured_output_options(self):
        props = _query_schema_props()

        assert props["format"]["enum"] == ["markdown", "json"]
        assert props["content_mode"]["enum"] == ["preview", "full", "none"]
        assert "preview_chars" in props
        assert "budget_chars" in props
        assert "include_metadata" in props
        assert "include_constraints" in props
        assert "include_preferences" in props


class TestOmegaQueryStructuredOutput:
    @pytest.mark.asyncio
    async def test_default_markdown_still_uses_existing_preview_shape(self):
        from omega.bridge import store

        store(
            content="Default markdown compatibility query result " * 12,
            event_type="decision",
            metadata={"tags": ["compat"]},
        )

        result = await handle_omega_query({"query": "compatibility query result", "limit": 1})

        assert not _is_error(result)
        text = _text(result)
        assert text.startswith("Results:")
        assert "content_mode" not in text
        assert "metadata" not in text

    @pytest.mark.asyncio
    async def test_json_full_content_returns_stable_records(self):
        from omega.bridge import store

        content = "Structured query full content survives MCP output. " * 20
        store(
            content=content,
            event_type="checkpoint",
            project="/tmp/omega-query-test",
            metadata={
                "tags": ["structured-query"],
                "source_uri": "test://query-source",
            },
        )

        result = await handle_omega_query({
            "query": "structured query full content",
            "limit": 1,
            "format": "json",
            "content_mode": "full",
            "include_metadata": True,
        })

        assert not _is_error(result)
        payload = json.loads(_text(result))
        assert payload["mode"] == "semantic"
        assert payload["result_count"] >= 1
        record = payload["results"][0]
        assert record["content"] == content
        assert record["content_mode"] == "full"
        assert record["content_length"] == len(content)
        assert record["content_truncated"] is False
        assert record["event_type"] == "checkpoint"
        assert record["project"] == "/tmp/omega-query-test"
        assert record["source_uri"] == "test://query-source"
        assert record["metadata"]["tags"]

    @pytest.mark.asyncio
    async def test_preview_chars_truncates_json_content_explicitly(self):
        from omega.bridge import store

        content = "Preview truncation should be explicit for agents."
        store(content=content, event_type="memory", metadata={"tags": ["preview"]})

        result = await handle_omega_query({
            "query": "preview truncation explicit",
            "limit": 1,
            "format": "json",
            "content_mode": "preview",
            "preview_chars": 12,
        })

        assert not _is_error(result)
        payload = json.loads(_text(result))
        record = payload["results"][0]
        assert record["content"] == content[:12]
        assert record["content_truncated"] is True
        assert record["content_length"] == len(content)
        assert payload["metadata"]["content_truncated_ids"] == [record["id"]]

    @pytest.mark.asyncio
    async def test_full_content_budget_truncates_and_reports(self):
        from omega.bridge import store

        first = "Budget first memory content. " * 10
        second = "Budget second memory content. " * 10
        store(content=first, event_type="memory", metadata={"tags": ["budget"]})
        store(content=second, event_type="memory", metadata={"tags": ["budget"]})

        result = await handle_omega_query({
            "query": "budget memory content",
            "limit": 2,
            "format": "json",
            "content_mode": "full",
            "budget_chars": 60,
        })

        assert not _is_error(result)
        payload = json.loads(_text(result))
        assert payload["metadata"]["budget_chars"] == 60
        assert payload["metadata"]["content_budget_used"] <= 60
        assert payload["metadata"]["content_truncated"] is True
        assert payload["metadata"]["content_truncated_ids"] or payload["metadata"]["content_omitted_ids"]

    @pytest.mark.asyncio
    async def test_markdown_structured_path_can_hide_content_and_metadata(self):
        from omega.bridge import store

        store(
            content="No content mode should keep IDs and omit body text.",
            event_type="decision",
            metadata={"tags": ["none-mode"], "private_note": "not shown"},
        )

        result = await handle_omega_query({
            "query": "none mode body text",
            "limit": 1,
            "content_mode": "none",
            "include_metadata": False,
        })

        assert not _is_error(result)
        text = _text(result)
        assert "Results:" in text
        assert "mem-" in text
        assert "No content mode should keep" not in text
        assert "private_note" not in text

    @pytest.mark.asyncio
    async def test_can_disable_constraint_and_preference_injection(self):
        from omega.bridge import store

        store(
            content="Constraint: pytest work must use isolated stores",
            event_type="constraint",
            metadata={"tags": ["pytest"]},
        )
        store(
            content="Preference: pytest reports should be concise",
            event_type="user_preference",
            metadata={"tags": ["pytest"]},
        )
        store(
            content="Regular memory about pytest output",
            event_type="memory",
            metadata={"tags": ["pytest"]},
        )

        result = await handle_omega_query({
            "query": "pytest preference rule output",
            "limit": 1,
            "format": "json",
            "include_constraints": False,
            "include_preferences": False,
        })

        assert not _is_error(result)
        payload = json.loads(_text(result))
        assert all(not record["is_constraint"] for record in payload["results"])
        assert all(not record["is_preference"] for record in payload["results"])
