"""Tests for Intelligence Cards -- card formatters, card tracker, complexity scoring."""

import pytest


# ============================================================================
# Card formatters -- 15 tests (5 types x 3 levels)
# ============================================================================


class TestFormatMemoryCard:
    """format_memory_card at MINIMAL, NORMAL, VERBOSE."""

    def test_minimal_suppresses_low_relevance(self):
        from omega.server.hook_server.cards import format_memory_card, TransparencyLevel

        memories = [{"relevance": 0.5, "content": "some context", "event_type": "decision", "id": "abc12345"}]
        result = format_memory_card(memories, "test.py", TransparencyLevel.MINIMAL)
        assert result == []

    def test_minimal_shows_high_relevance(self):
        from omega.server.hook_server.cards import format_memory_card, TransparencyLevel

        memories = [{"relevance": 0.90, "content": "important fix", "event_type": "lesson", "id": "abc12345"}]
        result = format_memory_card(memories, "test.py", TransparencyLevel.MINIMAL)
        assert len(result) == 2  # header + 1 memory
        assert "[OMEGA MEMORY]" in result[0]
        assert "test.py" in result[0]

    def test_normal_shows_top_three(self):
        from omega.server.hook_server.cards import format_memory_card, TransparencyLevel

        memories = [
            {"relevance": 0.8, "content": f"memory {i}", "event_type": "decision", "id": f"id{i}"}
            for i in range(5)
        ]
        result = format_memory_card(memories, "app.py", TransparencyLevel.NORMAL)
        # Header + 3 memories
        assert len(result) == 4
        assert "[OMEGA MEMORY] Relevant context" in result[0]

    def test_verbose_shows_all_plus_linked(self):
        from omega.server.hook_server.cards import format_memory_card, TransparencyLevel

        memories = [
            {"relevance": 0.7, "content": f"mem {i}", "event_type": "decision", "id": f"id{i}"}
            for i in range(5)
        ]
        linked = [{"content": "linked memory", "metadata": {"event_type": "lesson"}}]
        result = format_memory_card(memories, "app.py", TransparencyLevel.VERBOSE, linked=linked)
        # Header + 5 memories + 1 linked
        assert len(result) == 7
        assert "[linked]" in result[-1]

    def test_empty_memories_returns_empty(self):
        from omega.server.hook_server.cards import format_memory_card, TransparencyLevel

        result = format_memory_card([], "test.py", TransparencyLevel.NORMAL)
        assert result == []


class TestFormatDecisionCard:
    """format_decision_card at MINIMAL, NORMAL, VERBOSE."""

    def test_minimal_suppressed(self):
        from omega.server.hook_server.cards import format_decision_card, TransparencyLevel

        decisions = [{"content": "decided to use X"}]
        result = format_decision_card(decisions, TransparencyLevel.MINIMAL)
        assert result == []

    def test_normal_shows_latest_only(self):
        from omega.server.hook_server.cards import format_decision_card, TransparencyLevel

        decisions = [{"content": "latest decision"}, {"content": "older decision"}]
        result = format_decision_card(decisions, TransparencyLevel.NORMAL)
        assert len(result) == 1
        assert "[OMEGA DECISIONS] Prior:" in result[0]
        assert "latest decision" in result[0]

    def test_verbose_shows_trail(self):
        from omega.server.hook_server.cards import format_decision_card, TransparencyLevel

        decisions = [{"content": f"decision {i}", "age": f"{i}d"} for i in range(3)]
        result = format_decision_card(decisions, TransparencyLevel.VERBOSE)
        assert "[OMEGA DECISIONS] Decision trail:" in result[0]
        assert len(result) == 4  # header + 3 decisions


class TestFormatLearningCard:
    """format_learning_card at MINIMAL, NORMAL, VERBOSE."""

    def test_minimal_suppressed(self):
        from omega.server.hook_server.cards import format_learning_card, TransparencyLevel

        result = format_learning_card("fix", "the bug was in X", 0.8, TransparencyLevel.MINIMAL)
        assert result == []

    def test_normal_shows_oneliner_with_confidence(self):
        from omega.server.hook_server.cards import format_learning_card, TransparencyLevel

        result = format_learning_card("fix", "the bug was in the parser logic", 0.85, TransparencyLevel.NORMAL)
        assert len(result) == 1
        assert "[OMEGA LEARNED]" in result[0]
        assert "85% confidence" in result[0]

    def test_verbose_same_as_normal(self):
        from omega.server.hook_server.cards import format_learning_card, TransparencyLevel

        result = format_learning_card("decision", "chose X over Y", 0.0, TransparencyLevel.VERBOSE)
        assert len(result) == 1
        assert "[OMEGA LEARNED]" in result[0]
        # No confidence shown when 0
        assert "confidence" not in result[0]


class TestFormatWarningCard:
    """format_warning_card at MINIMAL, NORMAL, VERBOSE."""

    def test_minimal_suppresses_low_count(self):
        from omega.server.hook_server.cards import format_warning_card, TransparencyLevel

        warnings = [{"message": "potential issue", "count": 1, "tag": "WARNING"}]
        result = format_warning_card(warnings, TransparencyLevel.MINIMAL)
        assert result == []

    def test_minimal_shows_high_count(self):
        from omega.server.hook_server.cards import format_warning_card, TransparencyLevel

        warnings = [{"message": "recurring error in auth", "count": 5, "tag": "WARNING"}]
        result = format_warning_card(warnings, TransparencyLevel.MINIMAL)
        assert len(result) == 1
        assert "[OMEGA WARNING]" in result[0]

    def test_normal_shows_any(self):
        from omega.server.hook_server.cards import format_warning_card, TransparencyLevel

        warnings = [{"message": "watch out for X", "count": 1, "tag": "WATCH"}]
        result = format_warning_card(warnings, TransparencyLevel.NORMAL)
        assert len(result) == 1
        assert "[OMEGA WARNING]" in result[0]

    def test_verbose_includes_ids(self):
        from omega.server.hook_server.cards import format_warning_card, TransparencyLevel

        warnings = [{"message": "error pattern", "count": 2, "tag": "WARNING", "memory_ids": ["abc12345def"]}]
        result = format_warning_card(warnings, TransparencyLevel.VERBOSE)
        assert len(result) == 1
        assert "ids:" in result[0]
        assert "abc12345" in result[0]


class TestFormatSessionCard:
    """format_session_card always verbose."""

    def test_basic_captured(self):
        from omega.server.hook_server.cards import format_session_card

        result = format_session_card(captured=5, surfaced_count=10)
        assert "[OMEGA SESSION]" in result[0]
        assert "5 captured" in result[0]

    def test_zero_captured(self):
        from omega.server.hook_server.cards import format_session_card

        result = format_session_card(captured=0, surfaced_count=3)
        assert "3 memories surfaced" in result[0]

    def test_with_diff_correlation(self):
        from omega.server.hook_server.cards import format_session_card

        result = format_session_card(
            captured=3, surfaced_count=5,
            diff_correlated=2, diff_total=4,
        )
        output = "\n".join(result)
        assert "2/4" in output
        assert "50%" in output

    def test_with_type_breakdown(self):
        from omega.server.hook_server.cards import format_session_card

        result = format_session_card(
            captured=5, surfaced_count=3,
            type_breakdown={"decision": 2, "lesson_learned": 1, "error_pattern": 1, "task_completion": 1},
        )
        output = "\n".join(result)
        assert "2 decisions" in output
        assert "1 lesson" in output
        assert "1 error" in output
        assert "1 other" in output


# ============================================================================
# Complexity scoring -- 6 scenarios
# ============================================================================


class TestComplexityScoring:
    """compute_transparency with various input combinations."""

    def test_zero_complexity_is_minimal(self):
        from omega.server.hook_server.cards import compute_transparency, TransparencyLevel

        level = compute_transparency()
        assert level == TransparencyLevel.MINIMAL

    def test_single_edit_coding_is_normal(self):
        """1 file edit (2.0) + coding intent (2.0) = 4.0 -> NORMAL."""
        from omega.server.hook_server.cards import compute_transparency, TransparencyLevel

        level = compute_transparency(files_edited=1, intent="coding")
        assert level == TransparencyLevel.NORMAL

    def test_exploration_alone_is_minimal(self):
        """Exploration intent (1.0) alone = 1.0 -> MINIMAL."""
        from omega.server.hook_server.cards import compute_transparency, TransparencyLevel

        level = compute_transparency(intent="exploration")
        assert level == TransparencyLevel.MINIMAL

    def test_multi_file_with_errors_is_verbose(self):
        """3 files (6.0) + 2 errors (3.0) = 9.0 -> VERBOSE."""
        from omega.server.hook_server.cards import compute_transparency, TransparencyLevel

        level = compute_transparency(files_edited=3, error_count=2)
        assert level == TransparencyLevel.VERBOSE

    def test_boundary_below_normal(self):
        """Score exactly 2.5 -> MINIMAL (< 3.0)."""
        from omega.server.hook_server.cards import compute_transparency, TransparencyLevel

        # 1 file (2.0) + creative (0.5) = 2.5
        level = compute_transparency(files_edited=1, intent="creative")
        assert level == TransparencyLevel.MINIMAL

    def test_boundary_at_verbose(self):
        """Score exactly 8.0 -> VERBOSE (>= 8.0)."""
        from omega.server.hook_server.cards import compute_transparency, TransparencyLevel

        # 3 files (6.0) + coding (2.0) = 8.0
        level = compute_transparency(files_edited=3, intent="coding")
        assert level == TransparencyLevel.VERBOSE


# ============================================================================
# SessionCardTracker -- diff correlation scenarios
# ============================================================================


class TestSessionCardTracker:
    """SessionCardTracker: surfacing tracking and diff correlation."""

    def test_transparency_escalates(self):
        from omega.server.hook_server.card_tracker import SessionCardTracker
        from omega.server.hook_server.cards import TransparencyLevel

        tracker = SessionCardTracker("test-session")
        assert tracker.transparency == TransparencyLevel.MINIMAL

        tracker.record_edit("/path/to/file1.py")
        tracker.intent = "coding"
        assert tracker.transparency == TransparencyLevel.NORMAL

        tracker.record_edit("/path/to/file2.py")
        tracker.record_edit("/path/to/file3.py")
        assert tracker.transparency == TransparencyLevel.VERBOSE

    def test_positive_correlation(self):
        from omega.server.hook_server.card_tracker import SessionCardTracker

        tracker = SessionCardTracker("test-session")
        tracker.record_surfacing("mem-1", "/app/models.py")
        tracker.record_surfacing("mem-2", "/app/views.py")

        result = tracker.correlate_with_diff(["/app/models.py"])
        assert result["positive"] == 1
        assert result["weak_negative"] == 1  # mem-2 wasn't committed but session had commits
        assert result["outcomes"]["mem-1"] == "positive"
        assert result["outcomes"]["mem-2"] == "weak_negative"

    def test_no_signal_when_no_commits(self):
        from omega.server.hook_server.card_tracker import SessionCardTracker

        tracker = SessionCardTracker("test-session")
        tracker.record_surfacing("mem-1", "/app/models.py")

        result = tracker.correlate_with_diff([])
        assert result["no_signal"] == 1
        assert result["positive"] == 0

    def test_multiple_files_per_memory(self):
        from omega.server.hook_server.card_tracker import SessionCardTracker

        tracker = SessionCardTracker("test-session")
        tracker.record_surfacing("mem-1", "/app/models.py")
        tracker.record_surfacing("mem-1", "/app/views.py")

        # Committing either file counts as positive
        result = tracker.correlate_with_diff(["/app/views.py"])
        assert result["positive"] == 1
        assert result["outcomes"]["mem-1"] == "positive"

    def test_outcome_stats(self):
        from omega.server.hook_server.card_tracker import SessionCardTracker

        tracker = SessionCardTracker("test-session")
        tracker.record_edit("/app/foo.py")
        tracker.record_error()
        tracker.record_surfacing("mem-1", "/app/foo.py", card_type="memory")

        stats = tracker.get_outcome_stats()
        assert stats["files_edited"] == 1
        assert stats["error_count"] == 1
        assert stats["card_surfacings"]["memory"] == 1


# ============================================================================
# get_card_tracker lifecycle
# ============================================================================


class TestGetCardTracker:
    """get_card_tracker creates and retrieves trackers."""

    def setup_method(self):
        from omega.server.hook_server import _card_trackers
        _card_trackers.clear()

    def test_creates_new_tracker(self):
        from omega.server.hook_server import get_card_tracker

        tracker = get_card_tracker("session-abc")
        assert tracker.session_id == "session-abc"

    def test_returns_same_tracker(self):
        from omega.server.hook_server import get_card_tracker

        t1 = get_card_tracker("session-abc")
        t2 = get_card_tracker("session-abc")
        assert t1 is t2

    def test_cleanup_removes_tracker(self):
        from omega.server.hook_server import get_card_tracker, _card_trackers, _debounce_state

        get_card_tracker("session-cleanup")
        assert "session-cleanup" in _card_trackers
        _debounce_state.cleanup("session-cleanup")
        assert "session-cleanup" not in _card_trackers


# ============================================================================
# Graduation -- 3 scenarios
# ============================================================================


class TestCheckGraduation:
    """_check_graduation: promote or demote memories based on feedback history."""

    @pytest.fixture(autouse=True)
    def _reset(self, tmp_omega_dir):
        from omega.bridge import reset_memory
        reset_memory()
        yield
        reset_memory()

    def _create_memory(self, content, event_type="decision"):
        """Helper: create a memory and return (mem_id, initial_priority)."""
        from omega.bridge import auto_capture, _get_store

        auto_capture(content=content, event_type=event_type)
        store = _get_store()
        row = store._conn.execute(
            "SELECT node_id, priority FROM memories ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        return row[0], row[1] or 3

    def test_graduates_on_two_positive_correlations(self):
        from omega.bridge import record_feedback, _check_graduation, _get_store

        mem_id, initial_pri = self._create_memory("test memory for graduation")

        # Record 2 diff-correlated positive feedbacks
        record_feedback(mem_id, "helpful", "Auto: diff-correlated with commit")
        record_feedback(mem_id, "helpful", "Auto: diff-correlated with commit")

        result = _check_graduation(mem_id)
        assert result == "graduated"

        # Verify priority increased
        store = _get_store()
        row = store._conn.execute("SELECT priority FROM memories WHERE node_id = ?", (mem_id,)).fetchone()
        assert row[0] > initial_pri

    def test_decays_on_three_uncorrelated_surfacings(self):
        from omega.bridge import record_feedback, _check_graduation, _get_store

        mem_id, initial_pri = self._create_memory("test memory for decay", "lesson_learned")

        # Record 3 surfacings where file was not committed
        for _ in range(3):
            record_feedback(mem_id, "unhelpful", "Auto: surfaced but file not committed")

        result = _check_graduation(mem_id)
        assert result == "decayed"

        # Verify priority decreased
        store = _get_store()
        row = store._conn.execute("SELECT priority FROM memories WHERE node_id = ?", (mem_id,)).fetchone()
        assert row[0] < initial_pri

    def test_no_change_on_mixed_signals(self):
        from omega.bridge import record_feedback, _check_graduation

        mem_id, _ = self._create_memory("test memory for mixed")

        # 1 positive, 2 negatives: not enough to graduate or decay
        record_feedback(mem_id, "helpful", "Auto: diff-correlated with commit")
        record_feedback(mem_id, "unhelpful", "Auto: surfaced but file not committed")
        record_feedback(mem_id, "unhelpful", "Auto: surfaced but file not committed")

        result = _check_graduation(mem_id)
        assert result is None
