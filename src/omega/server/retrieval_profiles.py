"""Transparent retrieval profile definitions for omega_recall."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class RetrievalProfile:
    """Declarative recall profile used to tune query and context assembly."""

    name: str
    description: str
    event_types: Tuple[str, ...]
    context: str
    perspective: str
    phrase_fallback: bool = False


RETRIEVAL_PROFILES: Dict[str, RetrievalProfile] = {
    "general": RetrievalProfile(
        name="general",
        description="Normal semantic recall with no event-type bias.",
        event_types=(),
        context="general",
        perspective="implementation",
        phrase_fallback=False,
    ),
    "debug": RetrievalProfile(
        name="debug",
        description="Prioritize known failures, fixes, and lessons.",
        event_types=("error_pattern", "lesson_learned", "decision"),
        context="error_debug",
        perspective="implementation",
        phrase_fallback=True,
    ),
    "planning": RetrievalProfile(
        name="planning",
        description="Prioritize decisions, constraints, checkpoints, and prior completions.",
        event_types=("decision", "constraint", "task_completion", "checkpoint"),
        context="planning",
        perspective="verification",
        phrase_fallback=False,
    ),
    "handoff": RetrievalProfile(
        name="handoff",
        description="Prioritize checkpoints, completions, summaries, and project status.",
        event_types=("checkpoint", "task_completion", "session_summary", "project_status"),
        context="planning",
        perspective="implementation",
        phrase_fallback=False,
    ),
    "review": RetrievalProfile(
        name="review",
        description="Prioritize lessons, decisions, constraints, and contradiction markers.",
        event_types=("lesson_learned", "decision", "constraint", "contradiction_detected"),
        context="review",
        perspective="critique",
        phrase_fallback=True,
    ),
    "implementation": RetrievalProfile(
        name="implementation",
        description="Prioritize implementation decisions, lessons, errors, and file/code context.",
        event_types=("decision", "lesson_learned", "error_pattern", "code_pattern", "file_summary"),
        context="file_edit",
        perspective="implementation",
        phrase_fallback=False,
    ),
}


def get_retrieval_profile(name: str | None) -> RetrievalProfile:
    """Return a known retrieval profile, defaulting to general."""
    return RETRIEVAL_PROFILES.get(name or "general", RETRIEVAL_PROFILES["general"])
