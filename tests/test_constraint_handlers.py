"""Tests for constraint management via omega_maintain handler."""

import pytest
from unittest.mock import patch


@pytest.mark.asyncio
async def test_maintain_list_constraints():
    """omega_maintain(action='list_constraints') returns rules."""
    from omega.server.handlers import handle_omega_maintain

    mock_result = {"count": 1, "rules": [{"pattern": "*.env", "constraint": "no edit", "severity": "block"}], "constraints_dir": "/tmp"}
    with patch("omega.bridge.list_constraints", return_value=mock_result):
        result = await handle_omega_maintain({"action": "list_constraints"})
    assert result["content"][0]["text"]  # mcp_response wraps in content


@pytest.mark.asyncio
async def test_maintain_list_constraints_with_project():
    """list_constraints passes project through."""
    from omega.server.handlers import handle_omega_maintain

    with patch("omega.bridge.list_constraints", return_value={"count": 0, "rules": [], "constraints_dir": "/tmp"}) as mock_lc:
        await handle_omega_maintain({"action": "list_constraints", "project": "/my/project"})
    mock_lc.assert_called_once_with("/my/project")


@pytest.mark.asyncio
async def test_maintain_check_constraint():
    """omega_maintain(action='check_constraint') checks file path."""
    from omega.server.handlers import handle_omega_maintain

    mock_violations = [{"pattern": ".env*", "constraint": "secrets file", "severity": "block", "source": "global"}]
    with patch("omega.bridge.check_constraints", return_value=mock_violations):
        result = await handle_omega_maintain({"action": "check_constraint", "file_path": ".env"})
    text = result["content"][0]["text"]
    assert "violations" in text or ".env" in text


@pytest.mark.asyncio
async def test_maintain_check_constraint_missing_path():
    """check_constraint requires file_path."""
    from omega.server.handlers import handle_omega_maintain

    result = await handle_omega_maintain({"action": "check_constraint"})
    assert result.get("isError") is True


@pytest.mark.asyncio
async def test_maintain_save_constraints():
    """omega_maintain(action='save_constraints') round-trips rules."""
    from omega.server.handlers import handle_omega_maintain

    rules = [{"pattern": "*.secret", "constraint": "no touch", "severity": "warn"}]
    mock_result = {"saved": 1, "file": "/tmp/global.json"}
    with patch("omega.bridge.save_constraints", return_value=mock_result):
        result = await handle_omega_maintain({"action": "save_constraints", "rules": rules})
    assert not result.get("isError")


@pytest.mark.asyncio
async def test_maintain_save_constraints_missing_rules():
    """save_constraints requires rules list."""
    from omega.server.handlers import handle_omega_maintain

    result = await handle_omega_maintain({"action": "save_constraints"})
    assert result.get("isError") is True


@pytest.mark.asyncio
async def test_maintain_synthesize_insights():
    """synthesize_insights action doesn't error."""
    from omega.server.handlers import handle_omega_maintain

    with patch("omega.bridge.synthesize_system_insights", return_value={"insights": [], "count": 0}):
        result = await handle_omega_maintain({"action": "synthesize_insights"})
    assert not result.get("isError")


@pytest.mark.asyncio
async def test_maintain_backfill_embeddings():
    """backfill_embeddings action doesn't error."""
    from omega.server.handlers import handle_omega_maintain

    with patch("omega.bridge.backfill_embeddings", return_value={"processed": 0, "skipped": 0}):
        result = await handle_omega_maintain({"action": "backfill_embeddings"})
    assert not result.get("isError")
