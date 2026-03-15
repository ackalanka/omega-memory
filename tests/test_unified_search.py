"""Tests for unified search mode in omega_query handler."""

import pytest
from unittest.mock import patch


@pytest.mark.asyncio
async def test_unified_search_returns_memory_results():
    """omega_query(mode='unified') returns memory search results."""
    from omega.server.handlers import handle_omega_query

    mock_mem = {"memories": [{"id": "m1", "content": "test memory"}], "count": 1}
    with patch("omega.bridge.query", return_value=mock_mem), \
         patch("omega.knowledge.engine.search_documents", side_effect=ImportError("no knowledge")):
        result = await handle_omega_query({"mode": "unified", "query": "test"})
    assert not result.get("isError")
    text = result["content"][0]["text"]
    assert "memory" in text


@pytest.mark.asyncio
async def test_unified_search_graceful_no_knowledge():
    """unified mode degrades gracefully when knowledge module unavailable."""
    from omega.server.handlers import handle_omega_query

    mock_mem = "No results found."
    with patch("omega.bridge.query", return_value=mock_mem), \
         patch("omega.knowledge.engine.search_documents", side_effect=ImportError("no knowledge")):
        result = await handle_omega_query({"mode": "unified", "query": "test"})
    assert not result.get("isError")
    text = result["content"][0]["text"]
    assert "not available" in text.lower() or "document" in text.lower()


@pytest.mark.asyncio
async def test_unified_search_requires_query():
    """unified mode requires a query string."""
    from omega.server.handlers import handle_omega_query

    result = await handle_omega_query({"mode": "unified", "query": ""})
    assert result.get("isError") is True


@pytest.mark.asyncio
async def test_unified_search_with_both_sources():
    """unified mode combines memory and document results."""
    from omega.server.handlers import handle_omega_query

    mock_mem = {"memories": [{"id": "m1"}], "count": 1}
    mock_docs = "Found 2 documents matching 'test'"
    with patch("omega.bridge.query", return_value=mock_mem), \
         patch("omega.knowledge.engine.search_documents", return_value=mock_docs):
        result = await handle_omega_query({"mode": "unified", "query": "test"})
    assert not result.get("isError")
    text = result["content"][0]["text"]
    assert "unified" in text.lower() or "document" in text.lower()
