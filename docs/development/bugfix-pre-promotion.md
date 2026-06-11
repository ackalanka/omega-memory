# Pre-Promotion Bug Fixes: F1–F6

This document summarizes the six findings identified during pre-promotion review and the fixes applied to ensure safe live promotion.

## F1: Recall Constraint Separation
- **Issue**: Constraint and preference records injected during recall deduplication could displace semantic results.
- **Fix**: Extracted constraint/preference logic into `_dedupe_recall_records`. Now, these injected records are returned in a separate `constraints` JSON array and separate Markdown block, preventing them from consuming the primary `limit` budget.
- **Verification**: `test_constraint_records_do_not_displace_semantic_results`

## F2: N+1 Profile Queries in Recall
- **Issue**: Recall executed an N+1 query pattern when hydrating retrieval profiles.
- **Decision**: DEFERRED.
- **Rationale**: Optimization is not strictly necessary for correctness and does not risk memory corruption. It will be addressed post-promotion as technical debt.

## F3: Context Query Post-Filter
- **Issue**: `handlers.py` post-filter strict equality check dropped unscoped memories (`project=None` or `project=""`) that correctly bypassed the SQLite scope filter.
- **Fix**: Aligned the post-filter to only exclude memories with a project set if it doesn't match the current project.
- **Verification**: `test_context_pack_retains_unscoped_memories_for_focused_queries`

## F4: Recall Content Model Divergence
- **Issue**: `_pack_recall_records` lacked `content_mode="preview"` support.
- **Fix**: Documented the divergence. Recall's primary purpose is surfacing exact, prompt-ready text to agents for hydration, meaning it intentionally forces `content_mode="full"` and diverges from search/browse discovery workflows.
- **Verification**: Inline comment applied to `_pack_recall_records`.

## F5: Recall Sort Key Bug
- **Issue**: Edge cases during deduplication sorting could cause exceptions.
- **Fix**: Added a targeted regression test.
- **Verification**: `test_constraint_records_do_not_displace_semantic_results` implicitly verifies sorting stability for both standard and injected records.

## F6: Zero-Result Output Shape Test
- **Issue**: Potential gap in zero-result output shapes returning missing arrays instead of `[]`.
- **Finding**: False positive. The zero-result shape was verified to accurately maintain its structure (e.g., returning `results: []`, `constraints: []`, etc.).
- **Verification**: `test_zero_result_output_shape` confirms structural integrity for empty returns.

## Known Technical Debt

### TD-001 — N+1 Profile Queries in omega_recall (F2)
- **Finding:** For profiles with multiple event types, handle_omega_recall
  issues one query_structured() call per event type. Each call bypasses the
  embedding LRU cache because event_type is prepended to the query string,
  changing the cache key. Worst case: implementation profile (5 event types)
  issues 6 total DB queries and 5 embedding requests per single recall call.
- **Why deferred:** Each event type uses a distinct query_hint driving
  type-specific scoring (text-dominant for error_pattern, vector-dominant for
  lesson_learned). Client-side filtering after a single broad search cannot
  replicate this without scoring degradation.
- **Risk if deferred:** Latency scales linearly with profile event type count
  under cold embedding cache. Acceptable for Iteration 1 usage patterns;
  revisit if multi-profile recall becomes a hot path.
- **Follow-up:** Post-promotion, benchmark recall latency under real load.
  If latency is a problem, explore embedding cache keying on raw query text
  only, with event_type applied as a post-filter weight rather than a
  query-string modifier.
- **Owner:** Iteration 2 session.

### TD-002 — Four Divergent Content-Control Functions (F4)
- **Finding:** Four independent content-control functions exist in handlers.py:
  _apply_query_content_controls, _apply_get_record_content_controls,
  _pack_recall_records, _apply_context_record_content_controls. The first
  three support both preview and full modes; _pack_recall_records supports
  full-only (architecturally intentional for query-then-hydrate recall).
  They share no common base class or interface.
- **Risk if deferred:** Future callers adding budget logic must understand
  all four independently. A refactor touching one without the others risks
  behavioral drift.
- **Follow-up:** Post-promotion, extract a ContentBudget class with a shared
  interface: preview tracking, full tracking, truncation signals, clamping,
  optional budget_tokens dimension. All four functions should delegate to it.
- **Owner:** Iteration 2 session.
