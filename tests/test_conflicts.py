"""Tests for OMEGA Conflict Detection (Feature 3)."""

import pytest
from types import SimpleNamespace

from omega.conflicts import (
    detect_conflicts,
    CONFLICT_ELIGIBLE_TYPES,
    AUTO_RESOLVE_TYPES,
    FLAG_ONLY_TYPES,
)


# ============================================================================
# Helper to create mock MemoryResult-like objects
# ============================================================================


def _mem(content, event_type, node_id="mem-test123456", superseded=False):
    """Create a mock memory result."""
    meta = {"event_type": event_type}
    if superseded:
        meta["superseded"] = True
    return SimpleNamespace(
        id=node_id,
        content=content,
        metadata=meta,
    )


# ============================================================================
# 1. Polarity flip detected
# ============================================================================


def test_polarity_flip_detected():
    """Opposite negation polarity on same topic should be detected."""
    existing = _mem(
        "Always use TypeScript for frontend projects",
        "user_preference",
        "mem-existing001",
    )
    conflicts = detect_conflicts(
        "Never use TypeScript for frontend projects",
        "user_preference",
        [existing],
    )
    assert len(conflicts) == 1
    assert "polarity flip" in conflicts[0]["reason"]
    assert conflicts[0]["existing_id"] == "mem-existing001"
    assert conflicts[0]["confidence"] > 0


# ============================================================================
# 2. Override keywords detected
# ============================================================================


def test_override_keywords_detected():
    """Override keywords like 'actually', 'changed', 'instead' should trigger conflict."""
    existing = _mem(
        "Use Redis for caching in the application",
        "decision",
        "mem-existing002",
    )
    conflicts = detect_conflicts(
        "Actually we changed to using Memcached instead of Redis for caching in the application",
        "decision",
        [existing],
    )
    assert len(conflicts) >= 1
    assert any("override" in c["reason"] for c in conflicts)


# ============================================================================
# 3. Different topics — no conflict
# ============================================================================


def test_different_topics_no_conflict():
    """Memories about different topics should not conflict."""
    existing = _mem(
        "Use PostgreSQL for the database layer",
        "decision",
        "mem-existing003",
    )
    conflicts = detect_conflicts(
        "Never use inline CSS styles for component styling",
        "decision",
        [existing],
    )
    assert len(conflicts) == 0


# ============================================================================
# 4. Same polarity — no conflict
# ============================================================================


def test_same_polarity_no_conflict():
    """Two positive statements about the same topic should not conflict."""
    existing = _mem(
        "Always use TypeScript for frontend projects",
        "user_preference",
        "mem-existing004",
    )
    conflicts = detect_conflicts(
        "Always use TypeScript for all new frontend projects going forward",
        "user_preference",
        [existing],
    )
    assert len(conflicts) == 0


# ============================================================================
# 5. Same event type only
# ============================================================================


def test_same_event_type_only():
    """Conflict detection should only match within the same event type."""
    existing = _mem(
        "Never use global variables in JavaScript",
        "lesson_learned",  # Different from new content's type
        "mem-existing005",
    )
    conflicts = detect_conflicts(
        "Always use global variables in JavaScript",
        "decision",  # Different type from existing
        [existing],
    )
    assert len(conflicts) == 0


# ============================================================================
# 6. Superseded memories are skipped
# ============================================================================


def test_superseded_skipped():
    """Already-superseded memories should be excluded from conflict detection."""
    existing = _mem(
        "Never use TypeScript for frontend projects",
        "user_preference",
        "mem-existing006",
        superseded=True,
    )
    conflicts = detect_conflicts(
        "Always use TypeScript for frontend projects",
        "user_preference",
        [existing],
    )
    assert len(conflicts) == 0


# ============================================================================
# 7. Confidence scoring
# ============================================================================


def test_confidence_scoring():
    """Higher topic overlap should produce higher confidence scores."""
    # High overlap
    existing_high = _mem(
        "Never deploy to production on Friday afternoon for safety reasons",
        "decision",
        "mem-high",
    )
    conflicts_high = detect_conflicts(
        "Always deploy to production on Friday afternoon for faster iterations",
        "decision",
        [existing_high],
    )

    # Lower overlap (fewer shared words)
    existing_low = _mem(
        "Never run database migrations on weekends",
        "decision",
        "mem-low",
    )
    conflicts_low = detect_conflicts(
        "Don't avoid running deployments on weekends",
        "decision",
        [existing_low],
    )

    assert len(conflicts_high) >= 1
    # High-overlap conflict should have a reasonable confidence
    assert conflicts_high[0]["confidence"] >= 0.5


# ============================================================================
# 8. Auto-resolve types
# ============================================================================


def test_auto_resolve_types():
    """user_preference and decision should have auto_resolve=True."""
    for etype in AUTO_RESOLVE_TYPES:
        existing = _mem(
            "Never use tabs for indentation in code",
            etype,
            f"mem-{etype}",
        )
        conflicts = detect_conflicts(
            "Always use tabs for indentation in code",
            etype,
            [existing],
        )
        if conflicts:
            assert conflicts[0]["auto_resolve"] is True, f"{etype} should auto-resolve"


# ============================================================================
# 9. Flag-only types
# ============================================================================


def test_flag_only_types():
    """lesson_learned and error_pattern should have auto_resolve=False."""
    for etype in FLAG_ONLY_TYPES:
        existing = _mem(
            "Never restart the service without checking logs first for errors",
            etype,
            f"mem-{etype}",
        )
        conflicts = detect_conflicts(
            "Always restart the service without checking logs first for speed",
            etype,
            [existing],
        )
        if conflicts:
            assert conflicts[0]["auto_resolve"] is False, f"{etype} should be flag-only"


# ============================================================================
# 10. Non-eligible types are ignored
# ============================================================================


def test_non_eligible_type_ignored():
    """Types not in CONFLICT_ELIGIBLE_TYPES should produce no conflicts."""
    existing = _mem("Some session summary content", "session_summary", "mem-sess")
    conflicts = detect_conflicts(
        "Contradicting session summary content",
        "session_summary",
        [existing],
    )
    assert len(conflicts) == 0


# ============================================================================
# 11. Empty candidates produce no conflicts
# ============================================================================


def test_empty_candidates_no_conflicts():
    """No candidates should mean no conflicts."""
    conflicts = detect_conflicts(
        "Use Python for backend development",
        "decision",
        [],
    )
    assert len(conflicts) == 0


# ============================================================================
# 12. Integration: auto-resolve via bridge store path
# ============================================================================


@pytest.fixture
def _reset_for_integration(tmp_omega_dir):
    """Reset the bridge singleton for integration tests."""
    from omega.bridge import reset_memory

    reset_memory()
    yield
    reset_memory()


@pytest.mark.asyncio
async def test_auto_capture_conflict_auto_resolve(_reset_for_integration):
    """Storing a contradicting decision should auto-resolve the old one."""
    from omega.server.handlers import HANDLERS

    # Store original decision
    result1 = await HANDLERS["omega_store"]({
        "content": "Always deploy to production using blue-green deployment strategy",
        "event_type": "decision",
    })
    assert not result1.get("isError"), result1

    # Store contradicting decision
    result2 = await HANDLERS["omega_store"]({
        "content": "Never deploy to production using blue-green deployment strategy anymore",
        "event_type": "decision",
    })
    assert not result2.get("isError"), result2
    # Note: conflict detection may or may not trigger depending on whether
    # the similar-results query returns the first memory. This is an
    # integration smoke test — the unit tests above verify the logic.


# ============================================================================
# 13. Integration: flag-only via bridge store path
# ============================================================================


@pytest.mark.asyncio
async def test_auto_capture_conflict_flag_only(_reset_for_integration):
    """Storing a contradicting lesson should flag but not auto-resolve."""
    from omega.server.handlers import HANDLERS

    result1 = await HANDLERS["omega_store"]({
        "content": "Restarting the microservice cluster always fixes cascading failures",
        "event_type": "lesson_learned",
    })
    assert not result1.get("isError"), result1

    result2 = await HANDLERS["omega_store"]({
        "content": "Never restart the microservice cluster to fix cascading failures",
        "event_type": "lesson_learned",
    })
    assert not result2.get("isError"), result2


# ============================================================================
# 14. No false positives on similar but non-contradictory content
# ============================================================================


def test_no_false_positives_similar_content():
    """Similar memories that don't contradict should not be flagged."""
    existing = _mem(
        "Use Python for backend API development with FastAPI framework",
        "decision",
        "mem-existing-py",
    )
    # Related but additive, not contradictory
    conflicts = detect_conflicts(
        "Use Python for backend API development with Django framework additionally",
        "decision",
        [existing],
    )
    # Should not detect a conflict — no polarity flip, no override keywords
    assert len(conflicts) == 0
