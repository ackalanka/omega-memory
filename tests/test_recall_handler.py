"""Tests for omega_recall MCP handler."""

import json

import pytest

from omega.server.handlers import HANDLERS, handle_omega_recall
from omega.server.tool_schemas import TOOL_CATEGORIES, TOOL_SCHEMAS


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


def _recall_schema_props() -> dict:
    schema = next(tool for tool in TOOL_SCHEMAS if tool["name"] == "omega_recall")
    return schema["inputSchema"]["properties"]


class TestOmegaRecallSchema:
    def test_schema_and_handler_are_registered(self):
        assert "omega_recall" in HANDLERS
        assert TOOL_CATEGORIES["omega_recall"] == "query"
        props = _recall_schema_props()
        assert props["profile"]["enum"] == ["general", "debug", "planning", "handoff", "review", "implementation"]
        assert "budget_chars" in props
        assert "expand_related" in props

    @pytest.mark.asyncio
    async def test_missing_query_errors(self):
        result = await handle_omega_recall({})
        assert _is_error(result)
        assert "query" in _text(result).lower()


class TestOmegaRecallOutput:
    @pytest.mark.asyncio
    async def test_markdown_context_contains_full_memory_and_profile_plan(self):
        from omega.bridge import store

        content = "Recall markdown full body for agent recovery. " * 16
        store(
            content=content,
            event_type="checkpoint",
            project="/tmp/omega-recall-test",
            metadata={"tags": ["recall-markdown"]},
        )

        result = await handle_omega_recall({
            "query": "recall markdown full body",
            "profile": "handoff",
            "limit": 1,
            "budget_chars": 5000,
        })

        assert not _is_error(result)
        text = _text(result)
        assert text.startswith("# OMEGA Recall:")
        assert "Profile: handoff" in text
        assert content in text
        assert "Searches run:" in text

    @pytest.mark.asyncio
    async def test_json_output_has_context_results_budget_and_searches(self):
        from omega.bridge import store

        content = "Recall JSON body with enough detail for a packed context."
        store(content=content, event_type="decision", metadata={"tags": ["recall-json"]})

        result = await handle_omega_recall({
            "query": "recall json packed context",
            "profile": "planning",
            "limit": 1,
            "format": "json",
            "include_metadata": True,
        })

        assert not _is_error(result)
        payload = json.loads(_text(result))
        assert payload["mode"] == "recall"
        assert payload["profile"]["name"] == "planning"
        assert payload["context"].startswith("# OMEGA Recall:")
        assert payload["result_count"] >= 1
        assert payload["results"][0]["content"] == content
        assert "metadata" in payload["results"][0]
        assert payload["budget"]["content_budget_used"] <= payload["budget"]["budget_chars"]
        assert payload["searches_run"]

    @pytest.mark.asyncio
    async def test_budget_truncation_is_reported(self):
        from omega.bridge import store

        content = "Budgeted recall content should be truncated explicitly. " * 10
        store(content=content, event_type="memory", metadata={"tags": ["recall-budget"]})

        result = await handle_omega_recall({
            "query": "budgeted recall content",
            "limit": 1,
            "format": "json",
            "budget_chars": 40,
        })

        assert not _is_error(result)
        payload = json.loads(_text(result))
        assert payload["budget"]["content_budget_used"] <= 40
        assert payload["truncated"]["content"] is True
        assert payload["truncated"]["content_ids"]
        assert len(payload["results"][0]["content"]) == 40

    @pytest.mark.asyncio
    async def test_debug_profile_runs_profile_searches_and_phrase_fallback(self):
        from omega.bridge import store

        store(
            content="ShellCheck failure lesson: run shellcheck on every shell script.",
            event_type="lesson_learned",
            metadata={"tags": ["shellcheck"]},
        )

        result = await handle_omega_recall({
            "query": "ShellCheck failure lesson",
            "profile": "debug",
            "limit": 3,
            "format": "json",
        })

        assert not _is_error(result)
        payload = json.loads(_text(result))
        sources = {search["source"] for search in payload["searches_run"]}
        assert "semantic" in sources
        assert "profile:debug" in sources
        assert "phrase_fallback" in sources
        assert any("profile:debug" in record["retrieval_sources"] for record in payload["results"])

    @pytest.mark.asyncio
    async def test_event_type_override_limits_profile_expansion(self):
        from omega.bridge import store

        store(content="Decision about recall event override", event_type="decision")
        store(content="Lesson about recall event override", event_type="lesson_learned")

        result = await handle_omega_recall({
            "query": "recall event override",
            "profile": "debug",
            "event_type": "decision",
            "limit": 3,
            "format": "json",
        })

        assert not _is_error(result)
        payload = json.loads(_text(result))
        assert all(record["event_type"] == "decision" for record in payload["results"])
        assert {search["event_type"] for search in payload["searches_run"]} == {"decision"}

    @pytest.mark.asyncio
    async def test_related_expansion_packs_related_records(self):
        from omega.bridge import _get_store, store

        parent_text = "Parent recall memory about graph expansion."
        child_text = "Related recall memory with edge metadata."
        parent_result = store(content=parent_text, event_type="decision", metadata={"tags": ["related-recall"]})
        child_result = store(content=child_text, event_type="lesson_learned", metadata={"tags": ["related-recall"]})
        parent_id = parent_result.split()[1]
        child_id = child_result.split()[1]
        _get_store().add_edge(parent_id, child_id, edge_type="related", weight=0.9)

        result = await handle_omega_recall({
            "query": "parent recall graph expansion",
            "limit": 1,
            "format": "json",
            "expand_related": True,
            "max_related": 2,
            "budget_chars": 5000,
        })

        assert not _is_error(result)
        payload = json.loads(_text(result))
        related = payload["results"][0].get("related", [])
        assert related
        assert related[0]["id"] == child_id
        assert related[0]["edge_type"] == "related"
        assert related[0]["content"] == child_text

    @pytest.mark.asyncio
    async def test_related_expansion_preserves_deterministic_related_order(self):
        from omega.bridge import _get_store

        parent_text = "Parent recall memory about deterministic graph ordering."
        weak_text = "Weak recall related ordering target."
        strong_text = "Strong recall related ordering target."
        db = _get_store()
        parent_id = db.store(
            parent_text,
            metadata={"event_type": "decision", "tags": ["related-order"]},
            skip_inference=True,
        )
        weak_id = db.store(
            weak_text,
            metadata={"event_type": "memory", "tags": ["related-order"]},
            skip_inference=True,
        )
        strong_id = db.store(
            strong_text,
            metadata={"event_type": "lesson_learned", "tags": ["related-order"]},
            skip_inference=True,
        )
        db.add_edge(parent_id, weak_id, edge_type="related", weight=0.2)
        db.add_edge(parent_id, strong_id, edge_type="supersedes", weight=0.9)

        result = await handle_omega_recall({
            "query": "deterministic graph ordering",
            "limit": 1,
            "format": "json",
            "expand_related": True,
            "max_related": 2,
            "budget_chars": 5000,
        })

        assert not _is_error(result)
        payload = json.loads(_text(result))
        related = payload["results"][0].get("related", [])
        assert [record["id"] for record in related] == [strong_id, weak_id]
        assert [record["edge_type"] for record in related] == ["supersedes", "related"]
        assert [record["weight"] for record in related] == [0.9, 0.2]
