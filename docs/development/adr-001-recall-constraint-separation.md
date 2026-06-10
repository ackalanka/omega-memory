# ADR-001: Separate Constraints From Ranked Results in omega_recall Output

## Status
Accepted — implemented in dev/retrieval-tools pre-promotion hardening, 2026-06-11.

## Context
Previously, `omega_recall` combined auto-injected constraints and preferences together with semantic search results in a single `results` array, relying on a sort key tiebreaker to push constraints to the top. For example: if `limit=3` and the query matched 2 constraints and 5 semantic results, the agent would receive 2 constraints and only 1 semantic result. This displaced valuable associative history and forced agents to pick apart rules versus facts from a single list.

## Decision Drivers
- Roadmap principle: "composable core tools that return exact data without
  hiding uncertainty."
- Handoff doc design policy: primary results ordered by retrieval relevance;
  standing rules are a separate concern.

## Options Considered

### Option A — Demote constraints to sort key tiebreaker
This approach would keep all records in the `results` array but rank semantic hits first. This papers over a conceptual boundary, still mixes two fundamentally different record types in one payload, and will fail again when constraint counts grow, eventually displacing semantic hits entirely from the bottom of the list.

### Option B — Dedicated `constraints` output field (chosen)
This approach removes constraints from the `results` array and places them in a dedicated `constraints` field. This ensures agents always receive their top-K semantically relevant results up to the limit, while constraints are always delivered but in a predictable, queryable field. The output is honest about record type and intent.

## Decision
Option B.

## Consequences

### Positive
- Agents receive top-K semantic results regardless of constraint count.
- Constraints are still delivered — never dropped.
- Output shape is honest: results = search hits, constraints = standing rules.

### Negative
- Schema change at a pre-promotion version boundary. Documented in schema.
- Callers iterating `results` to find constraints must update to `constraints`.

## Implementation
- `handlers.py`: `_dedupe_recall_records` partitions candidates;
  `handle_omega_recall` emits separate `results` and `constraints` fields.
- `handlers.py`: `_query_record_base` infers constraint/preference identity
  from `metadata["event_type"]` to prevent identity loss across dedup passes.
- `tool_schemas.py`: `omega_recall` schema updated with `constraints` field
  description and version boundary note.
- `skills/omega-memory/SKILL.md`: agent workflow updated.

## Verification
Test: `tests/test_recall_handler.py::test_constraint_records_do_not_displace_semantic_results`
This test stores 2 constraints and 3 semantic memories, calls omega_recall
with limit=3, and asserts all 3 semantic results are present and constraints
are in the separate constraints field.
