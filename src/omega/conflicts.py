"""
OMEGA Conflict Detection — pre-storage conflict gate (Pipeline Phase 2.5).

Runs inside bridge.store() BEFORE the new memory is written to disk.
Called after dedup (Phase 1) and evolution (Phase 2), before store.store() (Phase 3).

This is a lightweight, type-scoped gate — separate from contradictions.py (the
heuristic engine used by store internals and reflect.py). It uses cheaper signals
(negation polarity + override keywords) tuned for the fast pre-storage path.

Eligible types: user_preference, decision, lesson_learned, error_pattern.

Detection signals:
1. Negation polarity flip (one has "don't/never/avoid", other doesn't)
2. Override keywords ("actually", "correction", "no longer", "changed", "instead")

Auto-resolve policy (side effects on existing memories):
- user_preference, decision → auto-resolve (mark old as outdated via feedback)
- lesson_learned, error_pattern → flag only (both may be valid in different contexts)

See also:
- contradictions.py — pure heuristic engine (no side effects, called by store + reflect)
- reflect.py — query-time pairwise audit of already-stored memories
"""

import os
import re
import logging
from typing import Any, Dict, List

logger = logging.getLogger("omega.conflicts")

# Types eligible for conflict detection
CONFLICT_ELIGIBLE_TYPES = frozenset({
    "user_preference", "decision", "lesson_learned", "error_pattern",
})

# Types where the newer memory automatically supersedes the older
AUTO_RESOLVE_TYPES = frozenset({"user_preference", "decision"})

# Types where conflicts are flagged but not auto-resolved
FLAG_ONLY_TYPES = frozenset({"lesson_learned", "error_pattern"})

# Negation words — same set as preferences.py for consistency
_NEGATION_WORDS = frozenset({
    "don't", "dont", "don", "never", "no", "not", "without", "avoid", "stop",
    "shouldn't", "shouldnt", "can't", "cant", "won't", "wont", "disable", "remove",
})

# Override keywords that signal the new content replaces/corrects the old
_OVERRIDE_KEYWORDS = frozenset({
    "actually", "correction", "no longer", "changed", "instead",
    "updated", "revised", "now using", "switched to", "replaced",
})

# Minimum topic overlap to even consider a conflict
_MIN_TOPIC_OVERLAP = float(os.environ.get("OMEGA_CONFLICT_MIN_OVERLAP", "0.25"))


def detect_conflicts(
    new_content: str,
    event_type: str,
    candidates: List[Any],
) -> List[Dict[str, Any]]:
    """Detect conflicts between new content and existing similar memories.

    Args:
        new_content: The content being stored.
        event_type: The event type of the new content.
        candidates: Top similar existing memories (MemoryResult objects).

    Returns:
        List of conflict dicts: {existing_id, reason, confidence, auto_resolve}
    """
    if event_type not in CONFLICT_ELIGIBLE_TYPES:
        return []

    conflicts = []
    new_words = set(re.findall(r"\b\w{3,}\b", new_content.lower()))
    new_has_negation = bool(new_words & _NEGATION_WORDS)
    new_topic_words = new_words - _NEGATION_WORDS

    # Check for override keywords in the new content
    new_lower = new_content.lower()
    new_has_override = any(kw in new_lower for kw in _OVERRIDE_KEYWORDS)

    for existing in candidates:
        existing_content = existing.content if hasattr(existing, "content") else str(existing)
        existing_id = existing.id if hasattr(existing, "id") else ""
        existing_meta = existing.metadata if hasattr(existing, "metadata") else {}

        # Only compare within the same event type
        existing_event_type = existing_meta.get("event_type", "") if isinstance(existing_meta, dict) else ""
        if existing_event_type != event_type:
            continue

        # Skip already-superseded memories
        if isinstance(existing_meta, dict) and existing_meta.get("superseded"):
            continue

        existing_words = set(re.findall(r"\b\w{3,}\b", existing_content.lower()))
        existing_has_negation = bool(existing_words & _NEGATION_WORDS)
        existing_topic_words = existing_words - _NEGATION_WORDS

        if not new_topic_words or not existing_topic_words:
            continue

        # Topic overlap check
        intersection = new_topic_words & existing_topic_words
        union = new_topic_words | existing_topic_words
        topic_overlap = len(intersection) / len(union) if union else 0

        if topic_overlap < _MIN_TOPIC_OVERLAP:
            continue

        # Signal 1: Negation polarity flip
        polarity_flip = new_has_negation != existing_has_negation

        # Signal 2: Override keywords in new content
        has_override = new_has_override

        if not polarity_flip and not has_override:
            continue

        # Compute confidence — signals are partially overlapping so use
        # diminishing returns when both fire (not purely additive).
        confidence = 0.0
        reasons = []

        if polarity_flip:
            confidence = 0.5 + topic_overlap * 0.3  # 0.5-0.8 range
            reasons.append(f"polarity flip (overlap: {topic_overlap:.0%})")

        if has_override:
            # Smaller boost when polarity flip already present (redundant signal)
            boost = 0.15 if polarity_flip else 0.3
            confidence += boost
            reasons.append("override keywords detected")

        auto_resolve = event_type in AUTO_RESOLVE_TYPES

        conflicts.append({
            "existing_id": existing_id,
            "existing_preview": existing_content[:120],
            "reason": "; ".join(reasons),
            "confidence": round(confidence, 2),
            "auto_resolve": auto_resolve,
            "topic_overlap": round(topic_overlap, 2),
        })

    return conflicts
