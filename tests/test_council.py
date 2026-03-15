"""Tests for the self-audit council system."""
import pytest
from pathlib import Path
from unittest.mock import patch


def test_council_loads_prompt_template():
    from omega.council import Council

    c = Council(domain="platform_health")
    assert "Platform Health" in c.prompt_template
    assert "health_score" in c.prompt_template


def test_council_gathers_signals(tmp_path):
    from omega.council import Council

    c = Council(domain="platform_health", db_dir=str(tmp_path))
    # Mock bridge and coordination to avoid real store initialization
    with patch("omega.council.Council._query_recent_errors", return_value=[]), \
         patch("omega.council.Council._get_health_metrics", return_value={"capacity_pct": 45}), \
         patch("omega.council.Council._get_tool_failures", return_value=[]):
        signals = c.gather_signals(project="omega")
    assert isinstance(signals, dict)
    assert "recent_errors" in signals
    assert "health_metrics" in signals


def test_council_gathers_security_signals():
    from omega.council import Council

    c = Council(domain="security")
    with patch("omega.council.Council._scan_credential_patterns", return_value=[]), \
         patch("omega.council.Council._get_external_actions", return_value=[]), \
         patch("omega.council.Council._get_content_samples", return_value=[]):
        signals = c.gather_signals(project="omega")
    assert isinstance(signals, dict)
    assert "credential_patterns" in signals
    assert "external_actions" in signals


def test_council_gathers_innovation_signals():
    from omega.council import Council

    c = Council(domain="innovation")
    with patch("omega.council.Council._get_tool_usage", return_value=[]), \
         patch("omega.council.Council._get_recent_decisions", return_value=[]), \
         patch("omega.council.Council._get_recent_lessons", return_value=[]):
        signals = c.gather_signals(project="omega")
    assert isinstance(signals, dict)
    assert "tool_usage" in signals
    assert "recent_decisions" in signals


def test_council_formats_prompt():
    from omega.council import Council

    c = Council(domain="platform_health")
    signals = {"recent_errors": [], "health_metrics": {"capacity_pct": 45}}
    prompt = c.format_prompt(signals)
    assert "capacity_pct" in prompt
    assert "Platform Health" in prompt


def test_council_unknown_domain_raises():
    from omega.council import Council

    with pytest.raises(FileNotFoundError):
        Council(domain="nonexistent_domain")


def test_all_domains_have_templates():
    from omega.council import COUNCIL_DOMAINS

    for domain in COUNCIL_DOMAINS:
        path = Path(__file__).parent.parent / "config" / "councils" / f"{domain}.md"
        assert path.exists(), f"Missing template: {path}"
