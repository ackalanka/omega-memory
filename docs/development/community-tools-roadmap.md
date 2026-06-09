# Community MCP Tools Roadmap

This document is the working plan for extending the open OMEGA MCP server with
community implementations of high-value agent tools.

The long-term direction is intentionally broad: over time, community tools may
cover equivalents of every Pro MCP category and may go beyond them. The first
iteration is deliberately narrow and focused on memory retrieval because that
is the capability agents depend on before they can use any higher-level
coordination, knowledge, or planning feature well.

## Principles

1. Build independently.

   Do not copy proprietary `omega_platform` internals. Implement community
   tools from public behavior, current open-core APIs, local database evidence,
   and user needs.

2. Preserve live OMEGA safety.

   Develop in `/home/akalanka/projects/omega-memory-dev` with
   `OMEGA_HOME=/tmp/omega-memory-dev-home`. Promote to the live checkout only
   after focused tests and a live memory backup.

3. Prefer composable core tools.

   A small reliable tool that returns exact data is better than a sophisticated
   tool that hides uncertainty. Agents need full records, stable IDs, metadata,
   pagination, and predictable output shapes.

4. Keep retrieval first.

   Retrieval is the base layer. Coordination and workflow tools should not be
   expanded until agents can reliably find, inspect, and hydrate the memories
   they need.

5. Maintain compatibility.

   Existing tools and argument shapes should keep working. Add optional
   parameters and new actions where possible before introducing new top-level
   tools.

## Current Gap

The open MCP server can search memories, browse recent/type/session memories,
edit/delete by ID, traverse relationships, and export/import. The most painful
gap is that search and browse output only short previews, while the internal
Python API already has full-content structured results and the SQLite store
already has full lookup by node ID.

This makes an agent do extra work, or fail entirely, when it needs to recover
complete instructions, checklists, code notes, or long handoff entries.

## Iteration 1: Core Retrieval Tools

Status: in progress.

Goal: make OMEGA Free/Open useful for agent memory recovery without requiring
Pro-only coordination or knowledge modules.

### R1. Full Memory Fetch By ID

Priority: P0.

Status: completed in commit `2cbd6b2` (`feat: add direct memory retrieval
action`).

Add a `get` action to `omega_memory`.

Example:

```text
omega_memory(action="get", memory_id="mem-...")
```

Recommended arguments:

- `memory_id`: single memory ID.
- `memory_ids`: optional list for batch fetch.
- `include_metadata`: default `true`.
- `include_edges`: default `false`.
- `track_access`: default `true`.
- `format`: `markdown` or `json`.

Expected behavior:

- Return full memory content, not a preview.
- Include ID, event type, lifecycle status, created time, tags, project,
  session, source URI, derived-from, strength/relevance if known, and metadata.
- Return not-found IDs explicitly in batch mode.
- Avoid modifying memory content or lifecycle state.

Why first:

- It directly fixes the snippet-only failure mode.
- It uses existing `SQLiteStore.get_node()`.
- It is easy to test and low risk.

### R2. Full Or Structured Query Output

Priority: P0.

Status: implemented in the current development slice; verify before promotion
with `tests/test_query_structured_output.py` and the compatibility tests listed
in `iteration-1-retrieval-research.md`.

Extend `omega_query` so agents can request full content or structured JSON.

Example:

```text
omega_query(query="pre PR checklist", content_mode="full", format="json")
omega_query(query="ShellCheck failure", content_mode="preview", preview_chars=800)
```

Recommended arguments:

- `content_mode`: `preview`, `full`, or `none`.
- `preview_chars`: default current behavior, configurable.
- `format`: `markdown` or `json`.
- `include_metadata`: default `false` for markdown, `true` for JSON.
- `budget_chars`: global content budget for `content_mode="full"`.
- `include_constraints`: include automatically injected matching constraints.
- `include_preferences`: include automatically injected matching user
  preferences.

Expected behavior:

- Preserve current markdown preview behavior by default.
- Reuse the existing structured query path where possible.
- Return full content only when explicitly requested.
- Clamp output sizes to avoid accidental huge context dumps.
- Report truncated and omitted content IDs explicitly.

Why second:

- The bridge already has `query_structured()` with full content.
- It reduces the need for follow-up fetches when the result set is small.

### R3. Query-Then-Hydrate Recall

Priority: P0.

Status: implemented in the current development slice; verify before promotion
with `tests/test_recall_handler.py` plus schema/handler compatibility tests.

Add a prompt-ready retrieval workflow that searches, then hydrates the top
results within a budget.

Candidate tool name:

```text
omega_recall
```

Example:

```text
omega_recall(query="sentinel-core pre-PR checklist", limit=5, budget_chars=12000)
```

Recommended arguments:

- `query`: required.
- `limit`: number of ranked hits.
- `budget_chars`: total content budget.
- `event_type`, `project`, `session_id`, `filter_tags`, `entity_id`,
  `memory_type`, `status`: same filters as `omega_query`.
- `expand_related`: default `false`.
- `max_related`: default `3`.
- `edge_types`: optional edge filter for related expansion.
- `format`: `markdown` or `json`.
- `profile`: `general`, `debug`, `planning`, `handoff`, `review`, or
  `implementation`.

Expected behavior:

- Run normal ranked retrieval.
- Run transparent profile-specific event-type searches when no hard
  `event_type` override is provided.
- Run phrase fallback for profiles that benefit from exact recovery.
- Hydrate full content for top results until `budget_chars` is reached.
- Report omitted IDs and truncation clearly.
- Preserve ranking, confidence, strength, IDs, metadata summaries, and source
  references.
- Dedupe records by stable memory ID and report the searches used.

Why third:

- It is the common agent workflow in one call: find relevant memory, then read
  enough full content to act.

### R4. Full And Paginated Browse

Priority: P1.

Status: implemented in the current development slice; verify before promotion
with `tests/test_browse_structured_output.py` plus the existing browse and
query compatibility tests.

Improve `omega_query(mode="browse")`.

Example:

```text
omega_query(mode="browse", browse_by="type", event_type="lesson_learned", limit=20, offset=40)
omega_query(mode="browse", browse_by="recent", content_mode="full")
```

Recommended arguments:

- `offset`: zero-based SQL-backed offset.
- `content_mode`: `preview`, `full`, or `none`.
- `preview_chars`.
- `format`: `markdown` or `json`.
- `include_metadata`: defaults true for JSON and false for markdown.
- `budget_chars`: global content budget for `content_mode="full"`.

Expected behavior:

- Keep existing browse behavior by default.
- Support paging through large result sets.
- Let agents inspect full long memories when browsing by type/session/recent.
- Return JSON payloads with `items`, `limit`, `offset`, `next_offset`,
  `has_more`, filters, and content budget/truncation metadata.

Why fourth:

- Browse is useful when query terms are uncertain.
- Pagination prevents huge, unbounded output.

### R5. Retrieval Profiles

Priority: P1.

Status: implemented for `omega_recall` in
`src/omega/server/retrieval_profiles.py`; future work can tune the profile
plans with retrieval evaluation data.

Add retrieval presets for common agent intents.

Example:

```text
omega_recall(query="pytest sqlite lock failure", profile="debug")
omega_recall(query="what must I know before editing this repo", profile="planning")
```

Initial profiles:

- `debug`: error patterns, lessons learned, exact phrase fallback.
- `planning`: decisions, constraints, task completions, project memories.
- `handoff`: checkpoints, task completions, recent high-priority memories.
- `review`: lessons, decisions, contradictions, stale/outdated markers.
- `implementation`: decisions, code patterns, errors, relevant project context.

Expected behavior:

- Profiles should be transparent: output which event types and search modes
  were used.
- Profiles should merge and deduplicate results by memory ID.
- Profiles should not hide normal filters.

Why fifth:

- Agents often do not know the right event type or query style.
- Profiles encode reliable retrieval habits without becoming a closed planner.

### R6. Related Memory Expansion

Priority: P1.

Status: implemented for the Iteration 1 target surfaces.
`omega_memory(action="get")` supports `include_edges`, `max_related`, and
`edge_types`; `omega_recall` supports `expand_related`, `max_related`, and
`edge_types` with the same output budget.

Add optional graph expansion to `omega_memory(action="get")` and `omega_recall`.

Example:

```text
omega_memory(action="get", memory_id="mem-...", expand_related=true, max_related=5)
omega_recall(query="release failure", expand_related=true)
```

Expected behavior:

- Include top related memories by edge weight and type.
- Support filtering edge types such as `related`, `derived_from`,
  `contradicts`, `supersedes`, and `evolves`.
- Respect the caller's output budget.

Why sixth:

- OMEGA already has graph edges and traversal.
- Agents need adjacent context without manually chaining several calls.

### R7. Project Context Pack

Priority: P2.

Status: implemented in the current development slice; verify before promotion
with `tests/test_context_handler.py` plus schema/handler compatibility tests.

Add a focused project briefing tool.

Candidate tool name:

```text
omega_context
```

Example:

```text
omega_context(project="/home/akalanka/sentinel-core", mode="handoff")
```

Initial modes:

- `handoff`: latest checkpoints, task completions, active constraints, current
  high-priority lessons.
- `planning`: decisions, constraints, project preferences, recent completions.
- `debug`: recent error patterns and lessons for the project.

Expected behavior:

- Return a compact, cited context pack.
- Prefer current active memories over stale historical entries.
- Include IDs for every memory so agents can fetch full records.
- Support markdown or JSON output, preview/full/none content modes, per-type
  limits, lifecycle status filtering, and optional focused query sections.

Why later in iteration 1:

- It depends on full fetch, structured query, and retrieval profiles being
  reliable first.

## Iteration 1 Acceptance Criteria

Iteration 1 is complete when:

- An agent can search for a topic and retrieve complete memory content without
  direct SQLite access.
- An agent can fetch one or more full memories by ID.
- Search and browse defaults remain backward compatible.
- Full-content outputs are opt-in and budgeted.
- Focused tests cover handler schemas, markdown output, JSON output, missing
  IDs, batch IDs, and truncation/budget behavior.
- The live deployment procedure in
  `docs/development/live-safe-development.md` has been followed before merging
  to the live checkout.

## Later Community Tool Tracks

These tracks remain open for future iterations. They should be implemented only
after the retrieval base is dependable.

### Local Coordination

Potential tools:

- `omega_session_register`
- `omega_session_heartbeat`
- `omega_sessions_list`
- `omega_file_claim`
- `omega_file_check`
- `omega_file_release`
- `omega_branch_claim`
- `omega_branch_check`
- `omega_branch_release`
- `omega_send_message`
- `omega_inbox`

Scope:

- Local SQLite-backed coordination.
- No cloud requirement.
- Fail-closed for destructive actions.
- Clear stale-session cleanup.

### Local Task Queue

Potential tools:

- `omega_task_create`
- `omega_task_claim`
- `omega_task_progress`
- `omega_task_complete`
- `omega_task_fail`
- `omega_tasks_list`
- `omega_task_deps`

Scope:

- Small local task table.
- Dependencies and handoff notes.
- Strong project scoping.

### Entity Registry

Potential tools:

- `omega_entity_create`
- `omega_entity_get`
- `omega_entity_list`
- `omega_entity_update`
- `omega_entity_delete`
- `omega_entity_add_relationship`
- `omega_entity_relationships`
- `omega_entity_tree`

Scope:

- Basic entity records and relationships.
- Entity-scoped memories already have `entity_id`; improve retrieval around it.

### Local Knowledge Base

Potential tools:

- `omega_ingest_document`
- `omega_search_documents`
- `omega_list_documents`
- `omega_remove_document`
- `omega_scan_documents`

Scope:

- Local-only document ingestion.
- Markdown/text first; PDFs later.
- Reuse existing embedding and SQLite patterns.

### Secure Profile

Potential tools:

- `omega_profile_set`
- `omega_profile_get`
- `omega_profile_search`
- `omega_profile_list`

Scope:

- Local encrypted profile fields.
- No secrets in plain metadata.
- Explicit user-controlled categories.

### Router And Model Context

Potential tools:

- `omega_classify_intent`
- `omega_router_status`
- `omega_router_context`
- `omega_get_current_model`

Scope:

- Start with classification and context summaries.
- Defer real provider switching until there is a strong local need.

### Audit And Diagnostics

Potential tools:

- `omega_audit`
- `omega_git_events`
- `omega_drift_check`
- `omega_health_report`

Scope:

- Make agent behavior inspectable.
- Record MCP calls and outcomes where feasible.
- Keep logs local and bounded.

### Beyond Pro

Potential future capabilities:

- Memory provenance and citation chains.
- Memory diff and contradiction resolution workflow.
- First-class memory migrations.
- Retrieval evaluation dashboards.
- Project-specific memory policies.
- Import/export compatibility with other agent memory systems.
- Context-pack generation for different agent roles.

## Not In Iteration 1

- Oracle or prediction tools.
- Cloud sync.
- Paid-license compatibility layers.
- Provider-level model switching.
- Hook rewrites that could affect live agents.
- Any change that requires running `omega setup` against the live environment.

## Implementation Notes

- Prefer extending `omega_memory` and `omega_query` before adding new top-level
  tools.
- Keep schema additions explicit and documented.
- Use JSON output for machine-readable workflows.
- Add tests near existing handler tests and bridge integration tests.
- Preserve the current default markdown output for existing users.
- Keep all large-output features behind explicit budget arguments.
