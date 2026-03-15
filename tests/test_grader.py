"""Tests for benchmarks/memorystress/grader.py."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# benchmarks/ is not a regular package — add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from benchmarks.memorystress.grader import GRADE_PROMPTS, grade_answer


def _mock_llm_result(text, input_tokens=100, output_tokens=5):
    result = MagicMock()
    result.text = text
    result.input_tokens = input_tokens
    result.output_tokens = output_tokens
    return result


# ---------------------------------------------------------------------------
# Correctness detection
# ---------------------------------------------------------------------------


@patch("benchmarks.memorystress.grader.call_llm")
def test_grade_answer_yes_returns_true(mock_call_llm):
    """grade_answer returns True when the LLM responds 'yes'."""
    mock_call_llm.return_value = _mock_llm_result("yes")
    question = {"question": "What color?", "answer": "blue", "question_type": "fact_recall"}
    is_correct, inp, out = grade_answer(question, "blue")
    assert is_correct is True
    assert inp == 100
    assert out == 5


@patch("benchmarks.memorystress.grader.call_llm")
def test_grade_answer_no_returns_false(mock_call_llm):
    """grade_answer returns False when the LLM responds 'no'."""
    mock_call_llm.return_value = _mock_llm_result("no")
    question = {"question": "What color?", "answer": "blue", "question_type": "fact_recall"}
    is_correct, inp, out = grade_answer(question, "red")
    assert is_correct is False
    assert inp == 100
    assert out == 5


@patch("benchmarks.memorystress.grader.call_llm")
def test_grade_answer_case_insensitive_yes(mock_call_llm):
    """grade_answer treats 'Yes' (capital) as correct (case-insensitive check)."""
    mock_call_llm.return_value = _mock_llm_result("Yes")
    question = {"question": "What color?", "answer": "blue", "question_type": "fact_recall"}
    is_correct, _, _ = grade_answer(question, "blue")
    assert is_correct is True


# ---------------------------------------------------------------------------
# Prompt template selection
# ---------------------------------------------------------------------------


@patch("benchmarks.memorystress.grader.call_llm")
def test_selects_default_prompt_for_unknown_type(mock_call_llm):
    """Unknown question_type falls back to the default prompt template."""
    mock_call_llm.return_value = _mock_llm_result("yes")
    question = {
        "question": "Something?",
        "answer": "42",
        "question_type": "totally_unknown_type",
    }
    grade_answer(question, "42")

    prompt_used = mock_call_llm.call_args[1]["messages"][0]["content"]
    # The default template starts with "I will give you a question"
    # and does NOT contain contradiction/temporal/cross-agent-specific language.
    assert "subset of the information" in prompt_used  # unique to default template


@patch("benchmarks.memorystress.grader.call_llm")
def test_selects_contradiction_resolution_prompt(mock_call_llm):
    """contradiction_resolution type uses the contradiction-specific template."""
    mock_call_llm.return_value = _mock_llm_result("yes")
    question = {
        "question": "What is the current value?",
        "answer": "new_value",
        "question_type": "contradiction_resolution",
    }
    grade_answer(question, "new_value")

    prompt_used = mock_call_llm.call_args[1]["messages"][0]["content"]
    assert "most recent value is the ground truth" in prompt_used


@patch("benchmarks.memorystress.grader.call_llm")
def test_selects_temporal_ordering_prompt(mock_call_llm):
    """temporal_ordering type uses the temporal-specific template."""
    mock_call_llm.return_value = _mock_llm_result("yes")
    question = {
        "question": "How many days?",
        "answer": "18 days",
        "question_type": "temporal_ordering",
    }
    grade_answer(question, "18 days")

    prompt_used = mock_call_llm.call_args[1]["messages"][0]["content"]
    assert "off-by-one errors" in prompt_used


# ---------------------------------------------------------------------------
# answer_detail handling
# ---------------------------------------------------------------------------


@patch("benchmarks.memorystress.grader.call_llm")
def test_answer_detail_included_in_ground_truth(mock_call_llm):
    """When answer_detail is present, it is appended to the ground truth."""
    mock_call_llm.return_value = _mock_llm_result("yes")
    question = {
        "question": "Who wrote it?",
        "answer": "Alice",
        "answer_detail": "Alice Smith, the lead author",
        "question_type": "fact_recall",
    }
    grade_answer(question, "Alice Smith")

    prompt_used = mock_call_llm.call_args[1]["messages"][0]["content"]
    assert "Alice" in prompt_used
    assert "(Context: Alice Smith, the lead author)" in prompt_used


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@patch("benchmarks.memorystress.grader.call_llm")
def test_empty_hypothesis(mock_call_llm):
    """grade_answer handles an empty hypothesis string without errors."""
    mock_call_llm.return_value = _mock_llm_result("no")
    question = {"question": "What color?", "answer": "blue", "question_type": "fact_recall"}
    is_correct, inp, out = grade_answer(question, "")
    assert is_correct is False
    assert inp == 100
    assert out == 5


# ---------------------------------------------------------------------------
# GRADE_PROMPTS structure
# ---------------------------------------------------------------------------


def test_grade_prompts_has_all_expected_keys():
    """GRADE_PROMPTS contains all expected question-type keys."""
    expected_keys = {
        "default",
        "contradiction_resolution",
        "temporal_ordering",
        "cross_agent_recall",
        "cold_start_recall",
    }
    assert set(GRADE_PROMPTS.keys()) == expected_keys
