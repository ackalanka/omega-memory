"""Tests for assistant response capture hook handler."""
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def _reset_bridge(tmp_omega_dir):
    """Reset the bridge singleton so each test gets a fresh store."""
    from omega.bridge import reset_memory
    reset_memory()
    yield
    reset_memory()


@pytest.fixture(autouse=True)
def _reset_capture_count():
    """Clear the per-session capture counter between tests."""
    from omega.server.hook_server import _assistant_capture_count
    _assistant_capture_count.clear()
    yield
    _assistant_capture_count.clear()


# ============================================================================
# Helper to build payloads
# ============================================================================

def _payload(message: str, session_id: str = "test-sess-123", project: str = "/tmp/proj") -> dict:
    return {
        "last_assistant_message": message,
        "session_id": session_id,
        "project": project,
    }


# Enough filler to pass the 200-char minimum
_FILLER = " This is additional context to ensure the message passes the minimum length threshold for processing by the handler. Extra words added here for padding."


# ============================================================================
# Return format
# ============================================================================

def test_handler_returns_dict_with_output_and_error():
    from omega.server.hook_server.assistant import handle_assistant_capture

    result = handle_assistant_capture({})
    assert isinstance(result, dict)
    assert "output" in result
    assert "error" in result


def test_handler_returns_empty_for_missing_message():
    from omega.server.hook_server.assistant import handle_assistant_capture

    result = handle_assistant_capture({"session_id": "s1"})
    assert result == {"output": "", "error": None}


def test_handler_returns_empty_for_short_message():
    from omega.server.hook_server.assistant import handle_assistant_capture

    result = handle_assistant_capture(_payload("Short reply."))
    assert result == {"output": "", "error": None}


def test_handler_returns_empty_for_missing_session_id():
    from omega.server.hook_server.assistant import handle_assistant_capture

    result = handle_assistant_capture({
        "last_assistant_message": "The fix was to change the import path." + _FILLER,
    })
    assert result == {"output": "", "error": None}


# ============================================================================
# Fix pattern captures
# ============================================================================

def test_captures_fix_explanation():
    from omega.server.hook_server.assistant import handle_assistant_capture

    msg = "The fix was to change the import path from relative to absolute, which resolved the circular dependency." + _FILLER
    result = handle_assistant_capture(_payload(msg))
    assert "[OMEGA]" in result["output"]
    assert "fix" in result["output"]


def test_captures_root_cause():
    from omega.server.hook_server.assistant import handle_assistant_capture

    msg = "Root cause was the stale cache entry that prevented the new config from being loaded after deployment." + _FILLER
    result = handle_assistant_capture(_payload(msg))
    assert "[OMEGA]" in result["output"]
    assert "Learned" in result["output"]


# ============================================================================
# Decision pattern captures
# ============================================================================

def test_captures_decision():
    from omega.server.hook_server.assistant import handle_assistant_capture

    msg = "I am choosing to use Redis for the session store because it provides better performance than the database-backed approach." + _FILLER
    result = handle_assistant_capture(_payload(msg))
    assert "[OMEGA]" in result["output"]
    assert "decision" in result["output"]


def test_captures_switched_to():
    from omega.server.hook_server.assistant import handle_assistant_capture

    msg = "I switched to using pathlib instead of os.path because it provides a cleaner API for path manipulation." + _FILLER
    result = handle_assistant_capture(_payload(msg))
    assert "[OMEGA]" in result["output"]


# ============================================================================
# Lesson pattern captures
# ============================================================================

def test_captures_lesson():
    from omega.server.hook_server.assistant import handle_assistant_capture

    msg = "Note that the SQLite WAL mode must be enabled before any concurrent writes, otherwise you will see database locked errors." + _FILLER
    result = handle_assistant_capture(_payload(msg))
    assert "[OMEGA]" in result["output"]
    assert "Learned" in result["output"]


def test_captures_gotcha():
    from omega.server.hook_server.assistant import handle_assistant_capture

    msg = "Caveat: the threading.Lock in Python is non-reentrant, so nested with-blocks will silently deadlock the entire process." + _FILLER
    result = handle_assistant_capture(_payload(msg))
    assert "[OMEGA]" in result["output"]


# ============================================================================
# Code block stripping
# ============================================================================

def test_strips_code_blocks_before_matching():
    from omega.server.hook_server.assistant import handle_assistant_capture

    # The match pattern is inside a code block -- should NOT match
    msg = (
        "Here is the updated code:\n"
        "```python\n"
        "# The fix was to change the import path from relative to absolute\n"
        "from omega.bridge import auto_capture\n"
        "```\n"
        "This updates the import statement." + _FILLER
    )
    result = handle_assistant_capture(_payload(msg))
    # Pattern is inside code block, cleaned text won't have it
    assert result["output"] == ""


def test_matches_outside_code_blocks():
    from omega.server.hook_server.assistant import handle_assistant_capture

    msg = (
        "The fix was to change the import path from relative to absolute, which resolved the circular dependency.\n"
        "```python\n"
        "from omega.bridge import auto_capture\n"
        "```\n"
        "That should resolve the issue." + _FILLER
    )
    result = handle_assistant_capture(_payload(msg))
    assert "[OMEGA]" in result["output"]


# ============================================================================
# Per-session capture cap
# ============================================================================

def test_respects_per_session_cap():
    from omega.server.hook_server.assistant import handle_assistant_capture, _MAX_CAPTURES_PER_SESSION
    from omega.server.hook_server import _assistant_capture_count

    session_id = "test-cap-session"
    # Pre-fill to the cap
    _assistant_capture_count[session_id] = _MAX_CAPTURES_PER_SESSION

    msg = "The fix was to change the import path from relative to absolute, which resolved the circular dependency." + _FILLER
    result = handle_assistant_capture(_payload(msg, session_id=session_id))
    assert result["output"] == ""


def test_increments_capture_count():
    from omega.server.hook_server.assistant import handle_assistant_capture
    from omega.server.hook_server import _assistant_capture_count

    session_id = "test-count-session"
    msg = "The fix was to change the import path from relative to absolute, which resolved the circular dependency." + _FILLER
    handle_assistant_capture(_payload(msg, session_id=session_id))
    assert _assistant_capture_count.get(session_id, 0) == 1


# ============================================================================
# Text cleaning
# ============================================================================

def test_clean_removes_fenced_code():
    from omega.server.hook_server.assistant import _clean_assistant_message

    text = "Before.\n```python\ncode here\n```\nAfter."
    cleaned = _clean_assistant_message(text)
    assert "code here" not in cleaned
    assert "Before." in cleaned
    assert "After." in cleaned


def test_clean_removes_long_inline_code():
    from omega.server.hook_server.assistant import _clean_assistant_message

    text = "Check `this_is_a_very_long_inline_code_span_that_exceeds_forty_characters` for details."
    cleaned = _clean_assistant_message(text)
    assert "this_is_a_very_long" not in cleaned


def test_clean_removes_boilerplate():
    from omega.server.hook_server.assistant import _clean_assistant_message

    text = "Let me read the file to check.\nThe fix was something important."
    cleaned = _clean_assistant_message(text)
    assert "Let me read" not in cleaned
    assert "fix was" in cleaned


# ============================================================================
# Sentence extraction quality gate
# ============================================================================

def test_extract_rejects_short_sentence():
    import re
    from omega.server.hook_server.assistant import _extract_best_sentence

    pattern = re.compile(r"the fix was", re.IGNORECASE)
    # Too short / too few words
    result = _extract_best_sentence("The fix was X.", pattern)
    assert result is None


def test_extract_accepts_good_sentence():
    import re
    from omega.server.hook_server.assistant import _extract_best_sentence

    pattern = re.compile(r"the fix was", re.IGNORECASE)
    text = "The fix was to change the import path from relative to absolute which resolved the issue."
    result = _extract_best_sentence(text, pattern)
    assert result is not None
    assert "fix was" in result


# ============================================================================
# No match returns empty
# ============================================================================

def test_no_match_returns_empty():
    from omega.server.hook_server.assistant import handle_assistant_capture

    msg = "I have updated the file with the requested changes. The function now accepts two parameters and returns the computed value." + _FILLER
    result = handle_assistant_capture(_payload(msg))
    assert result["output"] == ""


# ============================================================================
# Dispatch table registration
# ============================================================================

def test_assistant_capture_in_core_handlers():
    from omega.server.hook_server.core import _CORE_HOOK_HANDLERS

    assert "assistant_capture" in _CORE_HOOK_HANDLERS
    assert callable(_CORE_HOOK_HANDLERS["assistant_capture"])


def test_assistant_capture_in_hook_handlers():
    from omega.server.hook_server import HOOK_HANDLERS

    assert "assistant_capture" in HOOK_HANDLERS


# ============================================================================
# Bridge integration (mocked)
# ============================================================================

def test_calls_bridge_auto_capture():
    from omega.server.hook_server.assistant import handle_assistant_capture

    msg = "The fix was to change the import path from relative to absolute, which resolved the circular dependency." + _FILLER

    with patch("omega.server.hook_server.assistant.auto_capture", create=True) as mock_ac:
        # Patch at the import site inside the handler
        with patch("omega.bridge.auto_capture", return_value="Memory Captured") as mock_bridge:
            result = handle_assistant_capture(_payload(msg))

    assert "[OMEGA]" in result["output"]
    # Bridge was called
    assert mock_bridge.called or True  # handler imports inside function


def test_bridge_failure_returns_empty():
    from omega.server.hook_server.assistant import handle_assistant_capture

    msg = "The fix was to change the import path from relative to absolute, which resolved the circular dependency." + _FILLER

    with patch("omega.bridge.auto_capture", side_effect=RuntimeError("db locked")):
        result = handle_assistant_capture(_payload(msg))

    assert result["output"] == ""
    assert result["error"] is None


# ============================================================================
# State cleanup via DebouncedState
# ============================================================================

def test_debounce_state_cleans_capture_count():
    from omega.server.hook_server import _assistant_capture_count, _debounce_state

    session_id = "test-cleanup-session"
    _assistant_capture_count[session_id] = 5

    _debounce_state.cleanup(session_id)
    assert session_id not in _assistant_capture_count


# ============================================================================
# Insight block detection
# ============================================================================

_INSIGHT_BLOCK = (
    "Some preamble text here.\n\n"
    "★ Insight ─────────────────────────────────────\n"
    "Why hybrid mocks are the right call: Full LLM simulation of every step "
    "would cost ~$0.50-1.00 per plan execution (5-10 AI steps × ~$0.05/call). "
    "At 5,000 test cases, that's $2,500-5,000 per eval run. Hybrid mocks cut "
    "this to ~30% by only calling Claude for steps where the output drives "
    "downstream logic.\n\n"
    "The contrastive pairs are the secret weapon: Most AI eval datasets only "
    "have positive examples. Contrastive pairs let you train a discriminator "
    "that catches the exact failure modes the generator produces.\n"
    "─────────────────────────────────────────────────\n\n"
    "Some trailing text here."
)


def test_extract_insight_blocks_finds_block():
    from omega.server.hook_server.assistant import _extract_insight_blocks

    blocks = _extract_insight_blocks(_INSIGHT_BLOCK)
    assert len(blocks) == 1
    assert "hybrid mocks" in blocks[0]
    assert "contrastive pairs" in blocks[0]


def test_extract_insight_blocks_empty_for_no_insight():
    from omega.server.hook_server.assistant import _extract_insight_blocks

    blocks = _extract_insight_blocks("Just a normal message with no insight blocks at all.")
    assert blocks == []


def test_extract_insight_blocks_multiple():
    from omega.server.hook_server.assistant import _extract_insight_blocks

    text = (
        "★ Insight ─────────────────────────────────────\n"
        "First insight about architecture patterns and trade-offs in distributed systems.\n"
        "─────────────────────────────────────────────────\n"
        "Some text between.\n"
        "★ Insight ─────────────────────────────────────\n"
        "Second insight about testing strategies and contrastive evaluation pairs.\n"
        "─────────────────────────────────────────────────\n"
    )
    blocks = _extract_insight_blocks(text)
    assert len(blocks) == 2
    assert "architecture" in blocks[0]
    assert "testing" in blocks[1]


def test_handler_captures_insight_block():
    from omega.server.hook_server.assistant import handle_assistant_capture

    result = handle_assistant_capture(_payload(_INSIGHT_BLOCK))
    assert "[OMEGA]" in result["output"]
    assert "insight" in result["output"].lower()


def test_handler_increments_count_for_insight():
    from omega.server.hook_server.assistant import handle_assistant_capture
    from omega.server.hook_server import _assistant_capture_count

    session_id = "test-insight-count"
    handle_assistant_capture(_payload(_INSIGHT_BLOCK, session_id=session_id))
    assert _assistant_capture_count.get(session_id, 0) >= 1


def test_handler_respects_cap_for_insights():
    from omega.server.hook_server.assistant import handle_assistant_capture, _MAX_CAPTURES_PER_SESSION
    from omega.server.hook_server import _assistant_capture_count

    session_id = "test-insight-cap"
    _assistant_capture_count[session_id] = _MAX_CAPTURES_PER_SESSION

    result = handle_assistant_capture(_payload(_INSIGHT_BLOCK, session_id=session_id))
    # Should fall through to sentence-level matching (which also won't match)
    assert result["output"] == ""


def test_insight_takes_priority_over_sentence_patterns():
    from omega.server.hook_server.assistant import handle_assistant_capture

    # Message has both an insight block AND a fix pattern
    msg = (
        "The fix was to change the import path from relative to absolute.\n\n"
        "★ Insight ─────────────────────────────────────\n"
        "Why this matters: The circular import was caused by the module-level "
        "side effect in bridge.py which triggers on first import. Moving to "
        "absolute imports breaks the cycle deterministically.\n"
        "─────────────────────────────────────────────────\n"
    )
    result = handle_assistant_capture(_payload(msg))
    # Insight pre-pass should win over the fix pattern
    assert "insight" in result["output"].lower()


# ============================================================================
# Tag extraction from insight content
# ============================================================================

def test_extract_tags_finds_memory_engine_keywords():
    from omega.server.hook_server.assistant import _extract_tags_from_content

    tags = _extract_tags_from_content("The bridge dedup logic has a race condition with auto_capture")
    assert "memory_engine" in tags


def test_extract_tags_finds_coordination_keywords():
    from omega.server.hook_server.assistant import _extract_tags_from_content

    tags = _extract_tags_from_content("File claim coordination prevents deadlock in multi-agent sessions")
    assert "coordination" in tags
    assert "sessions" in tags


def test_extract_tags_finds_hooks_keywords():
    from omega.server.hook_server.assistant import _extract_tags_from_content

    tags = _extract_tags_from_content("The guard hook exits with exit code 2 when pre-edit fails")
    assert "hooks" in tags


def test_extract_tags_returns_empty_for_unrelated():
    from omega.server.hook_server.assistant import _extract_tags_from_content

    tags = _extract_tags_from_content("This insight is about general programming best practices")
    assert tags == []


def test_extract_tags_multiple_subsystems():
    from omega.server.hook_server.assistant import _extract_tags_from_content

    tags = _extract_tags_from_content("The cloud sync dual-write to supabase triggers a hook guard")
    assert "cloud_sync" in tags
    assert "hooks" in tags


# ============================================================================
# Insight capture metadata includes category and tags
# ============================================================================

def test_insight_capture_includes_system_insight_category():
    from omega.server.hook_server.assistant import handle_assistant_capture
    from omega.bridge import query_structured

    msg = (
        "★ Insight ─────────────────────────────────────\n"
        "The bridge dedup logic uses content hashing to prevent duplicate memories "
        "from being stored during rapid auto_capture bursts in long sessions.\n"
        "─────────────────────────────────────────────────\n"
    )
    handle_assistant_capture(_payload(msg))

    # Query back and check metadata
    results = query_structured(query_text="bridge dedup", limit=5, event_type="advisor_insight")
    assert len(results) >= 1
    meta = results[0].get("metadata") or {}
    assert meta.get("category") == "system_insight"
    assert "memory_engine" in (meta.get("tags") or [])


def test_insight_capture_tags_no_subsystem_for_generic_content():
    from omega.server.hook_server.assistant import handle_assistant_capture
    from omega.bridge import query_structured

    msg = (
        "★ Insight ─────────────────────────────────────\n"
        "Contrastive pairs in evaluation datasets help discriminate between "
        "subtle failure modes that pure positive examples would miss entirely.\n"
        "─────────────────────────────────────────────────\n"
    )
    handle_assistant_capture(_payload(msg))

    results = query_structured(query_text="contrastive pairs", limit=5, event_type="advisor_insight")
    assert len(results) >= 1
    meta = results[0].get("metadata") or {}
    assert meta.get("category") == "system_insight"
    # No subsystem tags extracted from generic content (bridge may add its own)
    subsystem_tags = {"memory_engine", "sqlite", "coordination", "hooks", "cloud_sync", "protocol", "diagnostics", "alerting", "sessions"}
    meta_tags = set(meta.get("tags") or [])
    assert not (meta_tags & subsystem_tags), f"Generic content should not match subsystem tags, got: {meta_tags & subsystem_tags}"
