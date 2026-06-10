"""Tests for omega_context project context packs."""

import json

import pytest

from omega.server.handlers import HANDLERS, handle_omega_context
from omega.server.tool_schemas import TOOL_CATEGORIES, TOOL_SCHEMAS


PROJECT = "/tmp/omega-context-project"
OTHER_PROJECT = "/tmp/omega-context-other"


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


def _context_schema_props() -> dict:
    schema = next(tool for tool in TOOL_SCHEMAS if tool["name"] == "omega_context")
    return schema["inputSchema"]["properties"]


def _store_context_memory(content: str, event_type: str, *, project: str = PROJECT, status: str = "active") -> None:
    from omega.bridge import store

    store(
        content=content,
        event_type=event_type,
        project=project,
        metadata={
            "tags": ["context-pack", event_type],
            "status": status,
        },
    )


class TestOmegaContextSchema:
    def test_schema_and_handler_are_registered(self):
        assert "omega_context" in HANDLERS
        assert TOOL_CATEGORIES["omega_context"] == "query"
        props = _context_schema_props()
        assert props["mode"]["enum"] == ["handoff", "planning", "debug"]
        assert props["format"]["enum"] == ["markdown", "json"]
        assert props["content_mode"]["enum"] == ["preview", "full", "none"]
        assert "budget_chars" in props

    @pytest.mark.asyncio
    async def test_invalid_mode_errors(self):
        result = await handle_omega_context({"mode": "oracle"})
        assert _is_error(result)
        assert "mode" in _text(result).lower()


class TestOmegaContextOutput:
    @pytest.mark.asyncio
    async def test_markdown_handoff_pack_contains_project_scoped_sections_and_ids(self):
        _store_context_memory("Checkpoint for handoff pack", "checkpoint")
        _store_context_memory("Completion for handoff pack", "task_completion")
        _store_context_memory("Decision for handoff pack", "decision")
        _store_context_memory("Other project checkpoint should not leak", "checkpoint", project=OTHER_PROJECT)

        result = await handle_omega_context({
            "project": PROJECT,
            "mode": "handoff",
            "limit_per_type": 2,
        })

        assert not _is_error(result)
        text = _text(result)
        assert text.startswith(f"# OMEGA Context: {PROJECT}")
        assert "## Checkpoints" in text
        assert "Checkpoint for handoff pack" in text
        assert "Completion for handoff pack" in text
        assert "Decision for handoff pack" in text
        assert "Other project checkpoint should not leak" not in text
        assert "`mem-" in text

    @pytest.mark.asyncio
    async def test_json_planning_pack_includes_sections_metadata_and_content_controls(self):
        _store_context_memory("Planning decision body " * 8, "decision")
        _store_context_memory("Planning constraint body", "constraint")
        _store_context_memory("Planning preference body", "user_preference")

        result = await handle_omega_context({
            "project": PROJECT,
            "mode": "planning",
            "format": "json",
            "content_mode": "preview",
            "preview_chars": 20,
            "include_metadata": True,
        })

        assert not _is_error(result)
        payload = json.loads(_text(result))
        assert payload["mode"] == "planning"
        assert payload["project"] == PROJECT
        assert payload["item_count"] >= 3
        assert payload["content"]["content_mode"] == "preview"
        decision_item = next(
            item
            for section in payload["sections"]
            for item in section["items"]
            if item["event_type"] == "decision"
        )
        assert decision_item["content"] == ("Planning decision body " * 8)[:20]
        assert decision_item["content_truncated"] is True
        assert decision_item["metadata"]["tags"]

    @pytest.mark.asyncio
    async def test_debug_pack_can_add_focused_query_section(self):
        _store_context_memory("SQLite lock debug lesson: close stale connections.", "lesson_learned")
        _store_context_memory("Regular checkpoint not focused on locks.", "checkpoint")

        result = await handle_omega_context({
            "project": PROJECT,
            "mode": "debug",
            "query": "SQLite lock stale connections",
            "format": "json",
            "limit_per_type": 2,
        })

        assert not _is_error(result)
        payload = json.loads(_text(result))
        assert payload["query"] == "SQLite lock stale connections"
        assert payload["sections"][0]["kind"] == "focused_query"
        assert any("SQLite lock debug lesson" in item["content"] for item in payload["sections"][0]["items"])

    @pytest.mark.asyncio
    async def test_context_pack_retains_unscoped_memories_for_focused_queries(self):
        _store_context_memory("Unscoped global memory", "decision", project="")
        _store_context_memory("Scoped project memory", "decision", project=PROJECT)

        result = await handle_omega_context({
            "project": PROJECT,
            "mode": "debug",
            "query": "Unscoped global memory",
            "format": "json",
        })

        assert not _is_error(result)
        payload = json.loads(_text(result))
        
        # The unscoped memory should survive the post-filter
        assert any("Unscoped global memory" in item["content"] for item in payload["sections"][0]["items"])

    @pytest.mark.asyncio
    async def test_context_pack_respects_status_filter(self):
        _store_context_memory("Active decision survives", "decision")
        _store_context_memory("Archived decision filtered by default", "decision", status="archived")

        active_result = await handle_omega_context({
            "project": PROJECT,
            "mode": "planning",
            "format": "json",
        })
        archived_result = await handle_omega_context({
            "project": PROJECT,
            "mode": "planning",
            "format": "json",
            "status": "archived",
        })

        assert not _is_error(active_result)
        assert not _is_error(archived_result)
        active_text = _text(active_result)
        archived_text = _text(archived_result)
        assert "Active decision survives" in active_text
        assert "Archived decision filtered by default" not in active_text
        assert "Archived decision filtered by default" in archived_text

    @pytest.mark.asyncio
    async def test_context_full_budget_reports_truncation(self):
        _store_context_memory("A" * 30, "decision")
        _store_context_memory("B" * 30, "constraint")

        result = await handle_omega_context({
            "project": PROJECT,
            "mode": "planning",
            "format": "json",
            "content_mode": "full",
            "budget_chars": 40,
        })

        assert not _is_error(result)
        payload = json.loads(_text(result))
        assert payload["content"]["content_budget_used"] == 40
        assert payload["content"]["content_truncated"] is True
        assert payload["content"]["content_truncated_ids"] or payload["content"]["content_omitted_ids"]

    @pytest.mark.asyncio
    async def test_context_preview_mode_also_respects_global_budget(self):
        _store_context_memory("Preview budget decision " + ("A" * 80), "decision")
        _store_context_memory("Preview budget constraint " + ("B" * 80), "constraint")

        result = await handle_omega_context({
            "project": PROJECT,
            "mode": "planning",
            "format": "json",
            "content_mode": "preview",
            "preview_chars": 60,
            "budget_chars": 70,
        })

        assert not _is_error(result)
        payload = json.loads(_text(result))
        assert payload["content"]["content_budget_used"] == 70
        assert payload["content"]["content_truncated"] is True
        assert payload["content"]["content_truncated_ids"] or payload["content"]["content_omitted_ids"]


class TestSQLiteProjectBrowse:
    def test_get_by_project_filters_project_type_status_and_offset(self, tmp_omega_dir):
        from omega.sqlite_store import SQLiteStore

        db = SQLiteStore(db_path=str(tmp_omega_dir / "context-project.db"))
        db.store(
            "Project oldest alpha canoe river",
            metadata={"event_type": "decision", "project": PROJECT},
            status="active",
        )
        db.store(
            "Project middle tungsten invoice nebula",
            metadata={"event_type": "decision", "project": PROJECT},
            status="active",
        )
        db.store(
            "Project newest quartz latitude engine",
            metadata={"event_type": "decision", "project": PROJECT},
            status="active",
        )
        db.store(
            "Archived project item",
            metadata={"event_type": "decision", "project": PROJECT},
            status="archived",
        )
        db.store(
            "Other project item",
            metadata={"event_type": "decision", "project": OTHER_PROJECT},
            status="active",
        )

        page = db.get_by_project(PROJECT, event_type="decision", status="active", limit=1, offset=1)

        assert len(page) == 1
        assert page[0].content == "Project middle tungsten invoice nebula"
