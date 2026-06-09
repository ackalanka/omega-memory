# Iteration 1 Retrieval Research And Implementation Plan

Captured: 2026-06-09T08:15:46Z.

Status: research complete; development implementation complete on branch
`dev/retrieval-tools`; live promotion pending. Last verified code head recorded
for this implementation: `2abb057` (`feat: add budgeted direct memory get`). The
branch can move after that; always run `git log --oneline --decorate -12`
before relying on a specific head. Future-session completed-vs-remaining
details are maintained in
`docs/development/iteration-1-future-session-handoff.md`.

Implementation progress:

- `omega_memory(action="get")` completed and pushed in commit `2cbd6b2`
  (`feat: add direct memory retrieval action`).
- Structured/full-content semantic `omega_query` output completed in commit
  `669a056`. It preserves default markdown behavior unless a
  caller explicitly requests JSON, full content, custom preview size,
  metadata controls, constraint/preference injection controls, or budget
  controls.
- `omega_recall` completed in commit `3d78ab8` with transparent
  profiles, profile event-type expansion, phrase fallback for selected
  profiles, dedupe, budgeted full-content packing, JSON/markdown output, and
  optional related expansion.
- Full and paginated browse completed in commit `ffb9723`:
  `omega_query(mode="browse")` preserves default markdown previews while
  adding SQL-backed `offset`, JSON output, `content_mode`, `preview_chars`,
  `include_metadata`, and full-content budget reporting.
- Project context packs completed in commit `7b63c82`:
  `omega_context` assembles deterministic project-scoped handoff/planning/debug
  sections from recent typed memories, includes stable IDs, supports
  markdown/JSON output, content controls, lifecycle status filters, and an
  optional focused query section.
- Agent-facing retrieval guidance is maintained as part of Iteration 1:
  MCP startup instructions, `omega_protocol`, managed client setup fragments,
  condensed-mode meta-tool descriptions and `omega_tools(tool=..., detail="full")`
  discovery output, and `skills/omega-memory/SKILL.md` teach the long-context
  workflow from `omega_context` and `omega_recall` through structured/full
  `omega_query` and `omega_memory(action="get")`.
- Related-memory MCP output hardening completed in commit `54d311b`: direct
  get edge expansion now preserves `node_id` and adds an `id` alias so agents
  consume related records consistently across direct-get and recall payloads.

Worktree: `/home/akalanka/projects/omega-memory-dev`.

Live safety reference: see `docs/development/live-safe-development.md`.

Future-session handoff: see
`docs/development/iteration-1-future-session-handoff.md`.

## Objective

Iteration 1 should make open/community OMEGA materially better at the thing
agents need most: finding, inspecting, and hydrating the right memories without
needing Pro-only coordination, router, oracle, or cloud features.

The long-term direction remains open. Community OMEGA can eventually implement
equivalents of every useful Pro MCP capability and go beyond them. The first
iteration is intentionally narrow because higher-level features depend on
reliable retrieval.

## Research Inputs

Local open-core code evidence:

- `src/omega/server/tool_schemas.py:64` defines `omega_query`.
- `src/omega/server/tool_schemas.py:180` defines `omega_memory`.
- `src/omega/server/tool_schemas.py:185` shows `omega_memory.action` lacks a
  `get` action.
- `src/omega/server/handlers.py:587` handles `omega_query`.
- `src/omega/server/handlers.py:828` handles browse mode.
- `src/omega/server/handlers.py:860` truncates browse content to 200
  characters.
- `src/omega/server/handlers.py:2287` routes `omega_memory`.
- `src/omega/server/handlers.py:2291` through
  `src/omega/server/handlers.py:2308` route edit/delete/feedback/similar/
  traverse/link/flagged/check_contradictions/supersede, but no get action.
- `src/omega/bridge.py:1777` defines markdown `query()`.
- `src/omega/bridge.py:1893` truncates semantic query content to 200
  characters.
- `src/omega/bridge.py:1982` defines `query_structured()`.
- `src/omega/bridge.py:2057` includes full memory `content` in structured
  query results.
- `src/omega/sqlite_store/_store.py:277` exposes `get_node(node_id,
  track_access=True)` returning full `MemoryResult`.
- `src/omega/sqlite_store/_maintenance.py:997` exposes graph traversal through
  `get_related_chain()`, with returned related memory content.

Installed OMEGA MCP evidence:

- `omega_tools(category="all")` in the installed server reported 15 Free tools.
- The same call listed 75 Pro-only tool names.
- Pro-only retrieval-adjacent tools include `omega_search_documents`,
  `omega_list_documents`, `omega_entity_get`, `omega_entity_list`,
  `omega_profile_get`, `omega_profile_list`, `omega_profile_search`,
  `omega_decision_query`, `omega_handoff`, and `omega_session_snapshot`.
- The installed Free `omega_tools(tool=...)` schema lookup does not expose
  Pro-only schemas; it returns "Unknown tool" for Pro-only tool names.

Official OMEGA docs and README:

- OMEGA docs home and JSON-LD describe Core as local SQLite, semantic search,
  auto-capture, and open source, and Pro as adding coordination, routing,
  entity management, knowledge base, audit chain, federation, typed memory,
  cloud sync, and a larger tunable tool surface:
  <https://omegamax.co/docs>.
- The Memory guide states OMEGA stores memories as semantically embedded graph
  nodes and that retrieval blends semantic similarity with BM25, word overlap,
  tags, and feedback signals:
  <https://omegamax.co/docs/guides/memory>.
- The Knowledge guide describes Pro knowledge tools for document ingestion,
  semantic chunk search, listing, removal, scanning, and sync:
  <https://omegamax.co/docs/guides/knowledge>.
- The Entity guide describes entities as scoping boundaries for memories,
  profiles, and documents, with create/get/list/update/delete and relationship
  tools:
  <https://omegamax.co/docs/guides/entity>.
- The upstream README describes the search pipeline as vector similarity,
  FTS5, type-weighted scoring, contextual reranking, and deduplication:
  <https://raw.githubusercontent.com/ackalanka/omega-memory/main/README.md>.

External memory system evidence:

- LangMem exposes separate manage-memory and search-memory tools over a
  namespace-scoped store. Context7 source:
  `/langchain-ai/langmem`, `create_manage_memory_tool`,
  `create_search_memory_tool`.
- LangGraph's store pattern separates `put`, `get`, and `search`, and supports
  vector indexing for persistent long-term memory. Context7 source:
  `/langchain-ai/langgraph`, `PostgresStore`.
- LlamaIndex retrievers return node text plus IDs/similarities and support
  top-k retrieval plus metadata filters. Context7 source:
  `/websites/developers_llamaindex_ai_python`.
- Mem0 exposes add/search/list/get/update/delete memory operations. Its MCP
  server specifically has `search_memories`, `get_memories`, and `get_memory`.
  Context7 sources: `/mem0ai/mem0`, `/mem0ai/mem0-mcp`.
- Zep/Graphiti retrieval combines semantic search, BM25, graph traversal,
  scopes, filters, and rerankers. Zep's auto search produces a prompt-ready
  context block packed to a character budget:
  <https://help.getzep.com/searching-the-graph>. Context7 source:
  `/getzep/graphiti`.
- Letta distinguishes core memory from archival memory; archival memory is
  long-term semantically searchable storage with tags and pagination exposed
  through `archival_memory_insert` and `archival_memory_search`. Context7
  source: `/websites/letta`.
- The official MCP memory server exposes separate graph search and direct-open
  tools: `search_nodes` and `open_nodes`, plus full graph read:
  <https://raw.githubusercontent.com/modelcontextprotocol/servers/main/src/memory/README.md>.

## Key Findings

### 1. The snippet-only problem is real in the MCP surface

The current open MCP `omega_query` and browse outputs are preview-oriented:
semantic query truncates each memory to 200 characters, and browse truncates
each memory to 200 characters.

This explains the agent failure mode where search finds the correct memory ID
but cannot recover full checklist or handoff content. The limitation is in the
MCP-facing output, not in the core storage model.

### 2. OMEGA already has the core data needed for full retrieval

Open-core OMEGA already has:

- full node fetch by ID through `SQLiteStore.get_node()`;
- full structured query results through `bridge.query_structured()`;
- full related-chain traversal content through `get_related_chain()`;
- metadata fields that already carry event type, tags, project, session,
  entity, status, source URI, derived-from, validity windows, and strength.

Iteration 1 should expose these existing paths through stable MCP tools and
schema options. It should not replace the storage layer or search pipeline.

### 3. Pro's relevant retrieval ideas are knowledge, entity scoping, profiles,
decision query, and handoff/session context

For this iteration, the useful Pro-adjacent ideas are not coordination locks or
oracle intelligence. The useful retrieval ideas are:

- document chunk search (`omega_search_documents`);
- entity-scoped memory and document filtering (`entity_id`);
- profile lookup/search for structured personal or org attributes;
- decision-focused retrieval (`omega_decision_query`);
- handoff/session snapshot context assembly.

The open implementation does not need to copy those modules. It can implement
community equivalents by making memory retrieval precise, scoped, structured,
and prompt-ready first.

### 4. Reputed memory systems converge on the same primitives

Across LangMem, LangGraph, LlamaIndex, Mem0, Zep/Graphiti, Letta, and the MCP
memory server, the durable pattern is:

- `search`: ranked retrieval over text/embeddings with filters;
- `list` or `browse`: non-semantic listing with pagination and filters;
- `get` or `open`: direct full-record hydration by stable ID;
- `metadata filters`: entity/user/project/session/tags/date/type/status;
- `related context`: graph expansion or adjacent records;
- `budgeted context assembly`: prompt-ready result packing with explicit
  output limits;
- `structured output`: machine-readable results for agents, not only markdown.

OMEGA already has most internal mechanics. The missing part is a clean MCP
contract that exposes those mechanics reliably.

### 5. The best first version is not one monolithic search tool

Agents need both surgical tools and one-call recall:

- surgical direct fetch by ID for exact recovery;
- structured/full query for inspection and programmatic workflows;
- recall that searches, hydrates, and packs results into a bounded context
  block.

This mirrors the split between Mem0's `search_memories`/`get_memory`, the MCP
memory server's `search_nodes`/`open_nodes`, and Zep's lower-level scoped search
plus higher-level auto context block.

## Iteration 1 Build Shape

### P0. `omega_memory(action="get")`

Implementation status: completed in commit `2cbd6b2`.

Purpose: direct full memory hydration by stable memory ID.

Why first:

- fixes the exact snippet-only failure mode;
- uses existing `SQLiteStore.get_node()`;
- low blast radius;
- aligns with Mem0 `get_memory` and MCP memory `open_nodes`.

Schema additions to `omega_memory`:

- `action`: add `"get"`;
- `memory_id`: single ID;
- `memory_ids`: optional batch list;
- `include_metadata`: default `true`;
- `include_edges`: default `false`;
- `track_access`: default `true`;
- `content_mode`: `full`, `preview`, or `none`, default `full`;
- `preview_chars`: default `800`, clamped;
- `budget_chars`: optional global content budget when
  `content_mode="full"`; omit for unbounded direct fetch;
- `format`: `markdown` or `json`, default `markdown`;
- `max_related`: optional, only used when `include_edges=true`;
- `edge_types`: reuse existing edge type filter.

Return contract:

- single fetch returns one full record or explicit not-found;
- batch fetch preserves requested order and returns `not_found` IDs;
- JSON format returns stable fields:
  `id`, `content`, `event_type`, `created_at`, `updated_at` if available,
  `session_id`, `project`, `entity_id`, `agent_type`, `tags`, `status`,
  `source_uri`, `derived_from`, `metadata`, `strength`, `relevance`,
  `access_count`, `last_accessed`, `valid_from`, `valid_until`;
- JSON format includes content-control metadata with content mode, optional
  budget, budget used, truncated IDs, and omitted IDs;
- markdown format prints ID, type, status, timestamps, metadata summary, then
  full content, plus a compact budget/truncation footer when relevant;
- related edge records follow the same content mode and optional budget as
  primary records.

Safety:

- never mutate content or lifecycle;
- `track_access=false` for audits and tests;
- clamp batch size, probably 50;
- clamp per-record content if caller asks for preview;
- clamp optional full-content budget to safe bounds and report truncation
  explicitly instead of silently dropping content.

### P0. Full and structured `omega_query`

Implementation status: completed in commit `669a056`.

Purpose: preserve today's default query behavior while allowing agents to ask
for machine-readable and/or full-content results.

Schema additions to `omega_query`:

- `format`: `markdown` or `json`, default `markdown`;
- `content_mode`: `preview`, `full`, or `none`, default `preview`;
- `preview_chars`: default `200` to match current semantic query previews,
  clamped;
- `include_metadata`: default `false` for markdown, `true` for JSON;
- `budget_chars`: optional global content budget when `content_mode="full"`,
  default `30000`, clamped;
- `include_constraints`: default `true`, explicit toggle for structured output;
- `include_preferences`: default `true`, explicit toggle for structured output.

Implementation direction:

- keep existing `query()` behavior as the default;
- for JSON or full output, call `query_structured()` or refactor shared query
  collection into one helper so markdown and JSON do not drift;
- add `status` to `query_structured()` for parity with markdown query;
- pass `scope` and `perspective` through `query_structured()` for parity with
  markdown query;
- include query metadata: mode, filters, result_count, truncated, omitted IDs,
  confidence when available.

Safety:

- default output remains backward compatible;
- `content_mode="full"` must honor `budget_chars`;
- report truncation explicitly.

Verified behavior in this slice:

- default semantic `omega_query` without new output options still uses the
  existing markdown preview path;
- `format="json"` returns `results` and `metadata` with stable IDs, full
  content when requested, query filters, confidence, and content budget
  reporting;
- `content_mode="preview"` honors `preview_chars`;
- `content_mode="full"` honors `budget_chars` and reports truncated or
  omitted content IDs;
- `content_mode="none"` keeps IDs and metadata while omitting body text;
- `include_constraints=false` and `include_preferences=false` suppress
  structured injection records.

### P0. `omega_recall`

Implementation status: completed in commit `3d78ab8`.

Purpose: one-call query-then-hydrate workflow for agent recovery.

This is the community equivalent of the useful part of Pro context retrieval
and Zep-style auto search, without requiring Pro knowledge/router/oracle.

Proposed schema:

```text
omega_recall(
    query: string,
    profile: "general" | "debug" | "planning" | "handoff" | "review" | "implementation",
    limit: int = 5,
    budget_chars: int = 12000,
    project: string?,
    session_id: string?,
    entity_id: string?,
    event_type: string?,
    filter_tags: string[]?,
    temporal_range: [start_iso, end_iso]?,
    status: "active" | "superseded" | "speculative" | "archived"?,
    expand_related: bool = false,
    max_related: int = 3,
    format: "markdown" | "json" = "markdown"
)
```

Retrieval profile behavior:

- `general`: normal semantic query, hydrate top results.
- `debug`: prioritize `error_pattern`, `lesson_learned`, exact phrase fallback,
  and high-strength memories.
- `planning`: prioritize `decision`, `constraint`, `task_completion`,
  `checkpoint`, and project-scoped memories.
- `handoff`: prioritize `checkpoint`, `task_completion`, recent project
  memories, and session continuity.
- `review`: prioritize `lesson_learned`, `decision`, contradicted/outdated
  markers, and constraints.
- `implementation`: prioritize `decision`, `lesson_learned`, `error_pattern`,
  and code/file metadata when available.

Return contract:

- ranked selected records with full content packed until `budget_chars`;
- `context` string in markdown mode suitable for direct prompt insertion;
- JSON mode includes `context`, `results`, `omitted`, `truncated`, `profile`,
  `filters`, and `searches_run`;
- every result includes stable ID and enough metadata for follow-up
  `omega_memory(action="get")`;
- when related expansion is enabled, related results are grouped under the
  parent result and share the same budget.
- `searches_run` reports base semantic search, profile event-type searches,
  and phrase fallback where used.

Safety:

- enforce total budget;
- keep profile rules transparent in output;
- dedupe by memory ID across semantic, phrase, and profile subqueries;
- never hide exact not-found/truncation conditions.

Verified behavior in this slice:

- `omega_recall` is a first-class MCP schema and handler in the `query`
  category;
- markdown mode returns a prompt-ready context block with profile and search
  plan information;
- JSON mode returns `context`, `results`, `profile`, `filters`,
  `searches_run`, `budget`, `omitted`, and `truncated`;
- tight budgets truncate content and report truncated IDs;
- profiles are defined in `src/omega/server/retrieval_profiles.py` and are
  included in output;
- `event_type` acts as a hard override and suppresses profile event-type
  expansion;
- `expand_related=true` uses existing graph edges and shares the same output
  budget.

### P1. Full and paginated browse

Implementation status: completed in commit `ffb9723`.

Purpose: make browse useful when the agent does not know exact query terms.

Schema additions:

- `offset`;
- `content_mode`;
- `preview_chars`;
- `format`;
- `include_metadata`;
- `budget_chars`;
- `browse_by`, `event_type`, and `session_id` filters remain as before.

Return contract:

- default remains current preview behavior;
- JSON mode returns `items`, `limit`, `offset`, `next_offset`, `has_more`;
- full mode honors budget.

Verified behavior in this slice:

- default `omega_query(mode="browse")` still returns markdown previews without
  structured-control fields;
- `format="json"` returns stable browse payloads with `items`, pagination,
  filters, metadata defaults, and content budget metadata;
- `offset` is implemented in the SQLite browse helpers for recent/type/session
  browse rather than by slicing only in the MCP handler;
- `content_mode="preview"` honors `preview_chars`;
- `content_mode="full"` honors `budget_chars` and reports truncation;
- `content_mode="none"` preserves IDs and metadata while omitting body text.

### P1. Related-memory expansion

Purpose: expose graph context around a memory without requiring a manual second
or third call.

Where:

- `omega_memory(action="get", include_edges=true, max_related=...)`;
- `omega_recall(expand_related=true, max_related=...)`.

Implementation direction:

- use existing `get_related_chain()`;
- include hop, edge type, edge weight, and content;
- respect edge filters and output budget.

Implementation status: completed for the Iteration 1 target surfaces,
`omega_memory(action="get")` and `omega_recall`. Commit `54d311b` also
normalizes direct-get related records with an `id` alias while preserving
the store-level `node_id` field for compatibility.

### P1. Retrieval profile definitions as code, not hard-coded prose

Purpose: profiles should become transparent reusable retrieval plans.

Implementation direction:

- create a small internal mapping such as
  `omega.server.retrieval_profiles`;
- each profile declares:
  `event_types`, `modes`, `boost_terms`, `phrase_fallback`, `default_limit`,
  and `description`;
- output the profile plan used.

This keeps the feature inspectable and easy to improve later.

Implementation status: completed in `src/omega/server/retrieval_profiles.py`.

### P2. Project context pack

Implementation status: completed in commit `7b63c82`.

Purpose: provide a deterministic project briefing when agents do not yet know
which exact memory to search for.

Schema:

- `project`;
- `mode`: `handoff`, `planning`, or `debug`;
- `query`: optional focused query section;
- `limit_per_type`;
- `budget_chars`;
- `content_mode`;
- `preview_chars`;
- `format`;
- `include_metadata`;
- `status`.

Return contract:

- markdown mode returns a compact context pack with cited memory IDs;
- JSON mode returns `sections`, `items`, `event_types`, `filters`, and content
  budget/truncation metadata;
- project scoping uses exact project metadata/DB column matches for the typed
  sections;
- optional focused query sections use existing structured query retrieval and
  dedupe against already included IDs.

Verified behavior in this slice:

- `omega_context` is a first-class MCP schema and handler in the `query`
  category;
- handoff mode includes project-scoped checkpoints, completions, status,
  constraints, lessons, and decisions;
- planning mode includes decisions, constraints, preferences, completions,
  checkpoints, and lessons;
- debug mode includes errors, lessons, constraints, decisions, checkpoints,
  completions, and optional focused query results;
- JSON output includes stable IDs, sections, metadata when requested, status
  filtering, and content budget/truncation metadata.

## Deferred But Kept Open

These should stay out of iteration one unless they become blockers:

- document ingestion/search equivalent to `omega_search_documents`;
- entity registry storage and relationship management;
- encrypted profile search/get/list;
- full decision registry;
- handoff/session snapshot tools;
- coordination locks/tasks/messages;
- router/model tools;
- oracle/council/review tools;
- cloud sync and federation.

The reason is sequencing, not rejection. Reliable memory retrieval should land
first. After that, knowledge, entity, and handoff/session context are the next
most natural expansions.

## Recommended Implementation Order

1. Add formatting helpers for `MemoryResult` to JSON and markdown.
2. Add `omega_memory(action="get")` for single and batch fetch.
3. Add focused tests for full fetch, metadata, not-found, batch order, and
   `track_access=false`.
4. Add `format`, `content_mode`, `preview_chars`, and `budget_chars` to
   semantic `omega_query`. Completed in commit `669a056`.
5. Add focused tests proving default query output is unchanged and full/JSON
   output includes full content within budget. Completed in
   `tests/test_query_structured_output.py`.
6. Add `omega_recall` schema and handler.
   Completed in commit `3d78ab8`.
7. Add retrieval profiles and dedupe/budget packing. Completed in current
   commit `3d78ab8`.
8. Add tests for each recall profile, truncation, omitted IDs, and JSON shape.
   Covered by `tests/test_recall_handler.py`.
9. Extend browse with JSON, pagination, and content modes.
   Completed in commit `ffb9723` and covered by
   `tests/test_browse_structured_output.py`.
10. Add related expansion to get/recall. Completed for `get` and `recall`;
    browse remains separate.
11. Add project context pack. Completed in commit `7b63c82` and
    covered by `tests/test_context_handler.py`.

## Test Plan

Focused unit/integration tests:

- MCP schema includes new arguments and `omega_memory.action="get"`.
- `omega_memory(get)` returns full content longer than 200 characters.
- batch get returns full content and explicit not-found entries.
- batch get honors optional `budget_chars` and reports truncated/omitted IDs.
- `track_access=false` does not increment access count.
- default `omega_query` output remains preview markdown.
- `omega_query(content_mode="full")` returns full content subject to
  `budget_chars`.
- `omega_query(format="json")` returns machine-readable result objects.
- `omega_recall` returns a prompt-ready context string and stable IDs.
- `omega_recall` reports truncation and omitted IDs when budget is tight.
- retrieval profiles are transparent and dedupe overlapping results.
- browse pagination returns stable `next_offset`/`has_more`.
- related expansion includes hop/edge metadata and respects `max_related`.
- `omega_context` returns project-scoped handoff/planning/debug packs with
  stable memory IDs.
- MCP startup instructions, `omega_protocol`, managed client setup fragments,
  condensed-mode schema text, `omega_tools(tool=..., detail="full")`
  discovery output, and the `omega-memory` skill explain how agents discover
  and use the retrieval tools.

Existing checks to run after implementation:

```bash
.venv/bin/pytest tests/test_agent_instruction_surfaces.py -q
.venv/bin/ruff check src/omega tests
.venv/bin/pytest <focused retrieval tests> -q
.venv/bin/pytest tests/test_init_and_json_compat.py tests/test_types.py -q
```

Promotion-readiness smoke:

```bash
rm -rf /tmp/omega-memory-dev-promotion-home
OMEGA_HOME=/tmp/omega-memory-dev-promotion-home \
  .venv/bin/python scripts/retrieval_promotion_smoke.py
```

Latest verification on `2abb057`:

- `.venv/bin/pytest tests/test_handler_actions.py tests/test_query_structured_output.py tests/test_browse_structured_output.py tests/test_recall_handler.py tests/test_context_handler.py tests/test_agent_instruction_surfaces.py -q`
  passed with 72 tests.
- `.venv/bin/ruff check src/omega/server/handlers.py src/omega/server/tool_schemas.py tests/test_handler_actions.py tests/test_query_structured_output.py tests/test_browse_structured_output.py tests/test_recall_handler.py tests/test_context_handler.py tests/test_agent_instruction_surfaces.py scripts/retrieval_promotion_smoke.py`
  passed.
- `git diff --check` passed.
- `OMEGA_HOME=/tmp/omega-memory-dev-promotion-home .venv/bin/python scripts/retrieval_promotion_smoke.py`
  passed with `status: ok`, `tool_count: 17`, `query_results: 2`,
  `browse_count: 1`, `recall_results: 3`, and `context_items: 5`.

The optional fresh-venv install probe is documented in
`docs/development/live-safe-development.md`; it may fail for network/resolver
reasons unrelated to the retrieval handlers.

Use isolated smoke tests with:

```bash
OMEGA_HOME=/tmp/omega-memory-dev-home .venv/bin/python -m pytest <focused tests> -q
```

Do not run `omega setup` from the dev checkout during this iteration.

## First Iteration Acceptance Criteria

Development checkout status: met. Live promotion has not been performed.

Iteration 1 is acceptable when a zero-context agent can:

1. search for a memory and see enough metadata to identify the right record;
2. fetch the full memory by ID without Pro;
3. request JSON output for programmatic handling;
4. run one recall call that returns a budgeted, prompt-ready block;
5. browse memory classes with pagination;
6. optionally expand related memories;
7. learn the workflow from MCP instructions, `omega_protocol`, managed client
   fragments, tool schemas, `omega_tools(tool=..., detail="full")` output, and
   the `omega-memory` skill without chat history;
8. do all of the above against the isolated dev OMEGA home in tests.

## Summary Recommendation

Build `get`, full/structured query, and `recall` first.

That gives open OMEGA the minimum reliable retrieval substrate found in every
serious memory system: search, list, get, structured results, scoped filters,
and budgeted context hydration. It also creates the base for future community
equivalents of knowledge search, entity context, handoff snapshots, decision
registry, and eventually higher-level Pro-style tools.
