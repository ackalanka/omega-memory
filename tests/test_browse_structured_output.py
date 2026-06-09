"""Tests for paginated/full-content omega_query browse output."""

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


def _store_browse_memory(content: str, *, event_type: str = "memory", session_id: str | None = None) -> None:
    from omega.bridge import store

    metadata = {"tags": ["browse-structured"]}
    if session_id:
        metadata["session_id"] = session_id
    store(content=content, event_type=event_type, metadata=metadata, session_id=session_id)


class TestOmegaBrowseStructuredSchema:
    def test_schema_exposes_browse_pagination_options(self):
        props = _query_schema_props()

        assert "offset" in props
        assert props["format"]["enum"] == ["markdown", "json"]
        assert props["content_mode"]["enum"] == ["preview", "full", "none"]
        assert "preview_chars" in props
        assert "budget_chars" in props
        assert "include_metadata" in props


class TestOmegaBrowseStructuredOutput:
    @pytest.mark.asyncio
    async def test_default_browse_remains_markdown_preview(self):
        long_content = "Default browse compatibility preview content. " * 12
        _store_browse_memory(long_content, event_type="decision")

        result = await handle_omega_query({"mode": "browse", "limit": 1})

        assert not _is_error(result)
        text = _text(result)
        assert text.startswith("# Most recent memories")
        assert "Offset:" not in text
        assert "content_mode" not in text
        assert long_content[:200] in text
        assert long_content[240:] not in text

    @pytest.mark.asyncio
    async def test_json_browse_returns_page_and_metadata(self):
        _store_browse_memory("Browse JSON oldest", event_type="decision")
        _store_browse_memory("Browse JSON middle", event_type="lesson_learned")
        _store_browse_memory("Browse JSON newest", event_type="checkpoint")

        result = await handle_omega_query({
            "mode": "browse",
            "browse_by": "recent",
            "limit": 2,
            "offset": 0,
            "format": "json",
        })

        assert not _is_error(result)
        payload = json.loads(_text(result))
        assert payload["mode"] == "browse"
        assert payload["browse_by"] == "recent"
        assert payload["count"] == 2
        assert payload["limit"] == 2
        assert payload["offset"] == 0
        assert payload["has_more"] is True
        assert payload["next_offset"] == 2
        assert [item["content"] for item in payload["items"]] == [
            "Browse JSON newest",
            "Browse JSON middle",
        ]
        assert payload["items"][0]["metadata"]["tags"] == ["browse-structured"]

    @pytest.mark.asyncio
    async def test_json_browse_offset_returns_next_page(self):
        _store_browse_memory("Browse offset oldest alpha canoe river", event_type="memory")
        _store_browse_memory("Browse offset middle tungsten invoice nebula", event_type="memory")
        _store_browse_memory("Browse offset newest quartz latitude engine", event_type="memory")

        result = await handle_omega_query({
            "mode": "browse",
            "limit": 2,
            "offset": 2,
            "format": "json",
        })

        assert not _is_error(result)
        payload = json.loads(_text(result))
        assert payload["count"] == 1
        assert payload["offset"] == 2
        assert payload["has_more"] is False
        assert payload["next_offset"] is None
        assert payload["items"][0]["content"] == "Browse offset oldest alpha canoe river"

    @pytest.mark.asyncio
    async def test_preview_chars_truncates_browse_content(self):
        content = "Browse preview truncation should be explicit."
        _store_browse_memory(content)

        result = await handle_omega_query({
            "mode": "browse",
            "format": "json",
            "content_mode": "preview",
            "preview_chars": 14,
            "limit": 1,
        })

        assert not _is_error(result)
        payload = json.loads(_text(result))
        item = payload["items"][0]
        assert item["content"] == content[:14]
        assert item["content_truncated"] is True
        assert payload["content"]["content_truncated_ids"] == [item["id"]]

    @pytest.mark.asyncio
    async def test_full_browse_budget_truncates_and_omits_content(self):
        _store_browse_memory("A" * 30)
        _store_browse_memory("B" * 30)

        result = await handle_omega_query({
            "mode": "browse",
            "format": "json",
            "content_mode": "full",
            "budget_chars": 40,
            "limit": 2,
        })

        assert not _is_error(result)
        payload = json.loads(_text(result))
        assert payload["content"]["content_budget_used"] == 40
        assert payload["content"]["content_truncated"] is True
        assert len(payload["items"][0]["content"]) == 30
        assert len(payload["items"][1]["content"]) == 10
        assert payload["items"][1]["content_truncated"] is True

    @pytest.mark.asyncio
    async def test_browse_content_mode_none_keeps_ids_without_body(self):
        _store_browse_memory("Browse none body")

        result = await handle_omega_query({
            "mode": "browse",
            "format": "json",
            "content_mode": "none",
            "limit": 1,
        })

        assert not _is_error(result)
        payload = json.loads(_text(result))
        assert payload["items"][0]["id"].startswith("mem-")
        assert payload["items"][0]["content"] is None
        assert payload["items"][0]["content_length"] == len("Browse none body")

    @pytest.mark.asyncio
    async def test_type_and_session_browse_support_pagination(self):
        _store_browse_memory("Decision oldest", event_type="decision", session_id="sess-page")
        _store_browse_memory("Decision middle", event_type="decision", session_id="sess-page")
        _store_browse_memory("Decision newest", event_type="decision", session_id="sess-page")
        _store_browse_memory("Unrelated lesson", event_type="lesson_learned", session_id="sess-other")

        by_type = await handle_omega_query({
            "mode": "browse",
            "browse_by": "type",
            "event_type": "decision",
            "limit": 2,
            "offset": 2,
            "format": "json",
        })
        by_session = await handle_omega_query({
            "mode": "browse",
            "browse_by": "session",
            "session_id": "sess-page",
            "limit": 2,
            "offset": 2,
            "format": "json",
        })

        assert not _is_error(by_type)
        assert not _is_error(by_session)
        type_payload = json.loads(_text(by_type))
        session_payload = json.loads(_text(by_session))
        assert type_payload["items"][0]["content"] == "Decision oldest"
        assert session_payload["items"][0]["content"] == "Decision oldest"
        assert type_payload["filters"]["event_type"] == "decision"
        assert session_payload["filters"]["session_id"] == "sess-page"


class TestSQLiteBrowseOffsets:
    def test_store_browse_helpers_accept_offset(self, tmp_omega_dir):
        from omega.sqlite_store import SQLiteStore

        db = SQLiteStore(db_path=str(tmp_omega_dir / "browse-offset.db"))
        db.store(
            "Offset oldest alpha canoe river",
            metadata={"event_type": "decision"},
            session_id="sess-offset",
        )
        db.store(
            "Offset middle tungsten invoice nebula",
            metadata={"event_type": "decision"},
            session_id="sess-offset",
        )
        db.store(
            "Offset newest quartz latitude engine",
            metadata={"event_type": "decision"},
            session_id="sess-offset",
        )

        assert db.get_recent(limit=1, offset=1)[0].content == "Offset middle tungsten invoice nebula"
        assert db.get_by_type("decision", limit=1, offset=1)[0].content == "Offset middle tungsten invoice nebula"
        assert db.get_by_session("sess-offset", limit=1, offset=1)[0].content == "Offset middle tungsten invoice nebula"
