# Iteration 1 Future Session Handoff

This document is the future-agent handoff for the Iteration 1 retrieval-tools
work in `/home/akalanka/projects/omega-memory-dev`.

Read it after:

1. `docs/development/live-safe-development.md`
2. `docs/development/community-tools-roadmap.md`
3. `docs/development/iteration-1-retrieval-research.md`

The purpose of this file is to make the current state unambiguous: which parts
of Iteration 1 are implemented, which parts remain unfinished, and what a
future session should do next without disturbing the live OMEGA installation.

## Current Safety Boundary

Work must continue in the development checkout:

```text
/home/akalanka/projects/omega-memory-dev
```

The live installed checkout is:

```text
/home/akalanka/projects/omega-memory
```

The live OMEGA home is:

```text
/home/akalanka/.omega
```

Do not edit the live checkout, do not run `omega setup`, and do not write to
the live OMEGA home unless the user explicitly asks for live promotion or live
installation work.

For smoke tests, use isolated homes such as:

```bash
OMEGA_HOME=/tmp/omega-memory-dev-home
OMEGA_HOME=/tmp/omega-memory-dev-promotion-home
```

Some CLI and hook paths may still hardcode `~/.omega`; inspect the path before
running any command that is not already known to be isolated.

## Branch And Verification Snapshot

Development branch:

```text
dev/retrieval-tools
```

Do not rely on this document for the current Git head. Check the current head
at session start:

```bash
git status -sb
git log --oneline --decorate -12
```

The last verified code head recorded before this handoff was:

```text
2abb057 feat: add budgeted direct memory get
```

Previous docs status checkpoint before the budgeted direct-get slice:

```text
30756db docs: record retrieval verification status
```

The following verification had passed against the `2abb057` code state:

```bash
.venv/bin/pytest tests/test_handler_actions.py tests/test_query_structured_output.py tests/test_browse_structured_output.py tests/test_recall_handler.py tests/test_context_handler.py tests/test_agent_instruction_surfaces.py -q
.venv/bin/ruff check src/omega/server/handlers.py src/omega/server/tool_schemas.py tests/test_handler_actions.py tests/test_query_structured_output.py tests/test_browse_structured_output.py tests/test_recall_handler.py tests/test_context_handler.py tests/test_agent_instruction_surfaces.py scripts/retrieval_promotion_smoke.py
git diff --check
OMEGA_HOME=/tmp/omega-memory-dev-promotion-home .venv/bin/python scripts/retrieval_promotion_smoke.py
```

Observed results:

- focused retrieval suite: 72 tests passed;
- ruff: passed;
- whitespace check: passed;
- isolated promotion smoke: `status: ok`, `tool_count: 17`,
  `query_results: 2`, `browse_count: 1`, `recall_results: 3`,
  `context_items: 5`.

Before any future claim that Iteration 1 is still verified, rerun the relevant
focused tests from the current head.

Additional current-slice verification before committing the related-ordering
hardening on 2026-06-10:

```bash
.venv/bin/pytest tests/test_handler_actions.py tests/test_query_structured_output.py tests/test_browse_structured_output.py tests/test_recall_handler.py tests/test_context_handler.py tests/test_agent_instruction_surfaces.py tests/test_improvements.py::TestGraphTraversal -q
.venv/bin/ruff check src/omega/sqlite_store/_maintenance.py tests/test_improvements.py tests/test_handler_actions.py tests/test_recall_handler.py
git diff --check
rm -rf /tmp/omega-memory-dev-promotion-home
OMEGA_HOME=/tmp/omega-memory-dev-promotion-home \
  .venv/bin/python scripts/retrieval_promotion_smoke.py
```

Observed results:

- focused retrieval plus graph traversal suite: 88 tests passed;
- ruff on the touched implementation/test files: passed;
- whitespace check: passed.
- isolated promotion smoke: `status: ok`, `tool_count: 17`,
  `query_results: 2`, `browse_count: 1`, `recall_results: 3`,
  `context_items: 5`.

The broader `tests/test_improvements.py` file contains sqlite-vec-dependent
ranking tests outside this slice. In this environment, one older reranking test
can return no results when sqlite-vec is installed and the local embedding
state is not suitable for that assertion. The current slice therefore verifies
the graph traversal class directly plus all Iteration 1 MCP retrieval handler
surfaces. Do not treat that older ranking test as evidence about related
expansion ordering.

## Completed In Iteration 1

The development implementation for the core retrieval slice is complete in the
dev checkout. The live installation has not been promoted.

### Completed: Direct Full Memory Fetch

Implemented:

```text
omega_memory(action="get")
```

What it does:

- fetches one full memory by `memory_id`;
- fetches multiple full memories by `memory_ids`;
- preserves batch order for found records;
- reports missing IDs through `not_found`;
- supports `format="markdown"` and `format="json"`;
- supports `content_mode="full"`, `content_mode="preview"`, and
  `content_mode="none"`;
- supports optional `budget_chars` for `content_mode="full"`; omit it for
  unbounded direct fetch;
- includes stable record fields such as ID, content, event type, timestamps,
  project, session, entity, agent type, tags, lifecycle status, source URI,
  derived-from, strength, relevance, access counters, validity windows, TTL,
  and metadata;
- reports direct-get content-control metadata including budget, budget used,
  truncated IDs, and omitted IDs;
- supports `track_access=false` for audits and tests;
- supports `include_edges=true`, `max_related`, and `edge_types`.

Important compatibility detail:

- direct edge expansion preserves store-level `node_id`;
- direct edge expansion also adds an `id` alias so agents can consume related
  records consistently with `omega_recall`;
- direct edge records now follow the same `content_mode` and optional
  `budget_chars` contract as primary direct-get records.

Primary tests:

```text
tests/test_handler_actions.py
```

### Completed: Deterministic Related Expansion Ordering

Implemented in:

```text
src/omega/sqlite_store/_maintenance.py
```

What it does:

- makes `SQLiteStore.get_related_chain()` traversal deterministic even when
  the same graph can be reached through unordered frontiers or multiple
  same-hop edges;
- keeps the existing nearest-hop behavior: a node found at hop 1 ranks before
  a node found at hop 2, even if the hop-2 edge has a stronger weight;
- orders related memories within the same hop by strongest edge weight first;
- breaks equal-weight ties by explicit edge-type priority:
  `supersedes`, `contradicts`, `evolves`, `causal`, `related`,
  `derived_from`, then unknown edge types;
- breaks remaining ties by newest edge timestamp and then stable `node_id`;
- records `edge_created_at` in related-chain entries so downstream MCP
  handlers can expose or inspect the exact edge timestamp used for ordering;
- replaces a previously visited same-hop node if a later traversal path
  reaches the same node through a better edge under the same policy;
- preserves deterministic frontier traversal by visiting frontier IDs in
  sorted order;
- preserves direct-get and recall behavior because both MCP paths consume
  `get_related_chain()` ordering.

Primary tests:

```text
tests/test_improvements.py::TestGraphTraversal
tests/test_handler_actions.py::TestOmegaMemoryGet::test_get_include_edges_preserves_deterministic_related_order
tests/test_recall_handler.py::TestOmegaRecallOutput::test_related_expansion_preserves_deterministic_related_order
```

Test coverage added:

- stronger same-hop edge ordering;
- hop-first ordering over stronger distant edges;
- edge-type priority for equal weights;
- newest edge timestamp for equal type/weight ties;
- stable `node_id` ordering for complete ties;
- duplicate same-hop target replacement with the best edge metadata;
- propagation of the store order through direct `omega_memory(action="get",
  include_edges=true)` JSON output;
- propagation of the store order through `omega_recall(expand_related=true)`
  JSON output.

### Completed: Structured And Full Semantic Query Output

Implemented optional structured controls for:

```text
omega_query(...)
```

What it does:

- preserves existing default markdown preview behavior;
- adds `format="json"`;
- adds `content_mode="preview" | "full" | "none"`;
- adds configurable `preview_chars`;
- adds full-content budget control through `budget_chars`;
- reports truncated IDs and omitted IDs explicitly;
- includes query metadata, filters, result count, confidence where available,
  and stable record fields;
- lets callers control structured constraint/preference injection with
  `include_constraints` and `include_preferences`.

Primary tests:

```text
tests/test_query_structured_output.py
```

### Completed: Query-Then-Hydrate Recall

Implemented:

```text
omega_recall
```

What it does:

- runs ranked retrieval and hydrates selected memories into a prompt-ready
  context block;
- packs full memory content into `budget_chars`;
- returns markdown or JSON;
- returns stable result records and a `context` string;
- reports search plan details in `searches_run`;
- dedupes overlapping hits by stable memory ID;
- reports truncation and omitted content IDs;
- supports transparent retrieval profiles:
  `general`, `debug`, `planning`, `handoff`, `review`, `implementation`;
- supports optional related expansion through `expand_related`, `max_related`,
  and `edge_types`;
- respects shared filters such as `project`, `session_id`, `entity_id`,
  `event_type`, `filter_tags`, `temporal_range`, `memory_type`, `status`,
  `include_contradicted`, and `valid_at`.

Primary tests:

```text
tests/test_recall_handler.py
```

### Completed: Retrieval Profiles

Implemented:

```text
src/omega/server/retrieval_profiles.py
```

What it does:

- defines transparent profile behavior as code rather than hidden prose;
- maps each profile to event-type preferences, surfacing context, perspective,
  and phrase fallback behavior;
- exposes the selected profile plan in `omega_recall` output.

The initial profiles are useful but not final. They need future evaluation and
tuning against real memory corpora.

### Completed: Full And Paginated Browse

Implemented structured browse support for:

```text
omega_query(mode="browse")
```

What it does:

- preserves existing default markdown preview behavior;
- supports `browse_by="recent"`, `browse_by="type"`, and
  `browse_by="session"`;
- adds SQL-backed `offset`;
- adds `format="json"`;
- adds `content_mode`, `preview_chars`, `include_metadata`, and
  `budget_chars`;
- returns `items`, `limit`, `offset`, `has_more`, `next_offset`, filters, and
  content budget metadata in JSON mode.

Primary tests:

```text
tests/test_browse_structured_output.py
```

### Completed: Project Context Packs

Implemented:

```text
omega_context
```

What it does:

- builds deterministic project-scoped context packs;
- supports `mode="handoff"`, `mode="planning"`, and `mode="debug"`;
- pulls typed sections from recent checkpoints, completions, project status,
  constraints, lessons, decisions, preferences, and error patterns depending on
  mode;
- supports optional focused recall through `query`;
- supports markdown and JSON;
- supports `content_mode`, `preview_chars`, `budget_chars`,
  `include_metadata`, `limit_per_type`, and `status`;
- includes stable memory IDs for follow-up direct fetch.

Primary tests:

```text
tests/test_context_handler.py
```

### Completed: Agent-Facing Tool Discovery Guidance

Updated agent-facing surfaces so future agents can discover and use the new
retrieval tools:

- `src/omega/server/mcp_server.py`
- `src/omega/server/handlers.py` `omega_protocol` fallback text
- `src/omega/server/tool_schemas.py`
- `src/omega/data/claude-md-fragment.md`
- `src/omega/data/claude-md-fragment-pro.md`
- `skills/omega-memory/SKILL.md`
- `AGENTS.md`

Also added:

```text
tests/test_agent_instruction_surfaces.py
```

This is important because MCP clients do not rely on repository docs alone.
Agents see tool schemas, descriptions, startup instructions, `omega_protocol`,
and local skills. Those surfaces must stay synchronized with behavior.

### Completed: Isolated Promotion Smoke

Implemented:

```text
scripts/retrieval_promotion_smoke.py
```

What it does:

- refuses to run without `OMEGA_HOME`;
- refuses to run against `/home/akalanka/.omega`;
- exercises the Iteration 1 MCP handlers against an isolated SQLite database;
- verifies tool discovery count, direct get, structured query, structured
  browse, recall, context pack, and metadata surfaces.

Primary command:

```bash
rm -rf /tmp/omega-memory-dev-promotion-home
OMEGA_HOME=/tmp/omega-memory-dev-promotion-home \
  .venv/bin/python scripts/retrieval_promotion_smoke.py
```

## Remaining Work Before Live Promotion

The code is implemented in the dev checkout, but it is not live for active MCP
clients. Promotion is a separate operational step.

### Remaining: Re-verify Current Dev Head

At the start of the future session, run:

```bash
cd /home/akalanka/projects/omega-memory-dev
git status -sb
git log --oneline --decorate -12
.venv/bin/pytest tests/test_handler_actions.py tests/test_query_structured_output.py tests/test_browse_structured_output.py tests/test_recall_handler.py tests/test_context_handler.py tests/test_agent_instruction_surfaces.py -q
.venv/bin/ruff check src/omega/server/handlers.py src/omega/server/tool_schemas.py tests/test_handler_actions.py tests/test_query_structured_output.py tests/test_browse_structured_output.py tests/test_recall_handler.py tests/test_context_handler.py tests/test_agent_instruction_surfaces.py
git diff --check
rm -rf /tmp/omega-memory-dev-promotion-home
OMEGA_HOME=/tmp/omega-memory-dev-promotion-home \
  .venv/bin/python scripts/retrieval_promotion_smoke.py
```

If those pass, the dev checkout is ready for live-promotion planning. If they
fail, fix the current-head regression in the dev checkout and commit the fix
before touching live state.

### Remaining: Optional Fresh-Venv Install Probe

This is useful but not mandatory if network or dependency resolution blocks it:

```bash
cd /home/akalanka/projects/omega-memory-dev
tmpdir="$(mktemp -d /tmp/omega-promotion-venv.XXXXXX)"
python3 -m venv "$tmpdir/venv"
"$tmpdir/venv/bin/python" -m pip install -e ".[server]"
OMEGA_HOME=/tmp/omega-memory-dev-promotion-home \
  "$tmpdir/venv/bin/python" scripts/retrieval_promotion_smoke.py
rm -rf "$tmpdir"
```

If this fails during install for network or resolver reasons, record the exact
failure, keep the live checkout untouched, and do not treat it as a retrieval
handler failure unless the package installs and the smoke itself fails.

### Remaining: Back Up Live OMEGA Memory

Before promotion, back up live memory data from the live checkout and live
virtualenv, not from the dev checkout:

```bash
/home/akalanka/projects/omega-memory/.venv/bin/python3.12 -m omega.cli backup
```

After the command, record:

- backup command;
- backup output path;
- timestamp;
- whether the command touched the expected live database;
- any warnings.

Do not promote without a live memory backup unless the user explicitly accepts
that risk.

### Remaining: Promote Tested Code To Live Checkout

The intended promotion path is in
`docs/development/live-safe-development.md`.

Before promotion, inspect both checkouts:

```bash
cd /home/akalanka/projects/omega-memory-dev
git status -sb
git log --oneline --decorate -5

cd /home/akalanka/projects/omega-memory
git status -sb
git log --oneline --decorate -5
```

Then choose a promotion strategy based on the live checkout state:

- fast-forward merge if the live checkout has the dev branch available and no
  unrelated local changes block it;
- cherry-pick the verified commits if a direct merge is not clean;
- stop and ask the user if live checkout changes would be overwritten or if
  the live branch has diverged in a way that requires a release decision.

Do not use destructive commands such as `git reset --hard` or
`git checkout --` on the live checkout unless the user explicitly asks for that
operation.

### Remaining: Restart MCP Clients

Tool schemas and handler registrations are loaded by MCP client processes.
After promotion, the active MCP clients or sessions must be restarted so agents
see the new tools and updated tool descriptions.

At minimum, verify after restart that an MCP client can see:

- `omega_recall`;
- `omega_context`;
- `omega_memory` with `action="get"`;
- `omega_query` with structured output options;
- `omega_tools(tool="omega_recall", detail="full")`.

### Remaining: Live MCP Smoke After Restart

After promotion and MCP restart, run a safe live smoke that avoids writing
private or unnecessary test memories if possible.

Recommended sequence:

1. `omega_tools(category="query")`
2. `omega_tools(tool="omega_recall", detail="full")`
3. `omega_protocol(project="/home/akalanka/projects/omega-memory-dev", section="memory")`
4. `omega_query(query="<known harmless existing term>", limit=1, format="json", content_mode="preview")`
5. If an existing memory ID is available, `omega_memory(action="get",
   memory_id="<id>", content_mode="preview", track_access=false,
   format="json")`

Avoid creating throwaway memories in live OMEGA unless the user explicitly
accepts that. If a write is necessary for live verification, make it clearly
scoped, harmless, and easy to identify.

### Remaining: Record Promotion Result

After live promotion, update this file or a successor handoff doc with:

- live promotion date and time;
- live checkout path;
- promoted branch/head SHA;
- backup path;
- MCP restart method;
- live smoke commands and results;
- any preserved live checkout dirtiness;
- any residual risks.

## Remaining Engineering Work After Live Promotion

These are not blockers for the first live promotion, but they are the next
engineering improvements to consider if Iteration 1 continues.

### Remaining: Retrieval Evaluation Corpus

The retrieval profiles are sensible defaults, not tuned policy. Build a small
evaluation corpus with representative project memories and expected retrieval
outcomes.

Include cases for:

- exact checklist recovery;
- long handoff recovery;
- error/debug recovery;
- decision recovery;
- project planning orientation;
- review and contradiction-oriented retrieval;
- related-edge expansion;
- query terms that should not retrieve stale or unrelated memories.

The goal is to measure whether profiles improve agent behavior, not just
whether handlers return syntactically valid JSON.

### Remaining: Stronger Ranking Assertions

The current tests prove shape, hydration, budget controls, and basic behavior.
Future tests should assert ranking quality for controlled corpora where the
expected top result is unambiguous.

Add tests for:

- profile-specific event-type boosts;
- phrase fallback rescuing exact checklist text;
- project filter preventing cross-project leakage;
- lifecycle status filters excluding archived/superseded records by default
  where appropriate;
- `strength_min`, `memory_type`, `valid_at`, and contradicted-memory filters in
  recall paths.

### Remaining: Context Pack Budget Accounting Audit

`omega_context` applies a shared content budget across typed sections and then
the focused query section. Future work should audit whether the markdown
wrapper text should count toward the budget or whether content-only accounting
is the intended contract.

The current implementation accounts for memory content, not every rendered
markdown character.

### Completed: Related Expansion Scoring Policy

This is no longer remaining work for Iteration 1. The implemented policy is:

1. nearest hop first;
2. strongest edge weight;
3. edge-type priority:
   `supersedes`, `contradicts`, `evolves`, `causal`, `related`,
   `derived_from`, then unknown edge types;
4. newest edge timestamp;
5. stable `node_id`.

The policy is intentionally graph-local. It does not mix source retrieval
relevance into related expansion ordering yet. That keeps direct get and recall
related expansion predictable: related records are ordered by the relationship
evidence, while primary search results remain ordered by retrieval relevance.

Future evaluation work can revisit this if real corpora show that recall should
blend primary result relevance with edge weight. If that happens, document it
as a new ranking policy change and add tests that distinguish direct-get graph
ordering from recall-specific ranking.

### Remaining: Tool Schema Contract Tests

The instruction-surface tests cover important guidance. Future work can add a
more explicit schema contract test that snapshots required properties for:

- `omega_recall`;
- `omega_context`;
- `omega_query` structured options;
- `omega_memory(action="get")` options;
- `omega_tools(tool=..., detail="full")` compatibility.

Keep snapshots small and semantic. Avoid brittle full-schema snapshots unless
the project adopts that style elsewhere.

### Remaining: Packaging Probe Stability

The optional fresh-venv install probe should be repeated once dependency and
network conditions are stable. If it fails for package reasons, fix packaging
before promoting broadly.

Possible follow-up:

- run `pip install -e ".[server]"` in a fresh venv;
- run the promotion smoke from that venv;
- document the exact Python version and platform;
- decide whether the live promotion requires package metadata changes.

### Remaining: Live-Safe CLI Audit

The live-safety doc notes that some CLI and hook paths may still hardcode
`~/.omega`. A future safety hardening pass should audit OMEGA_HOME behavior
across CLI and hook paths.

This is adjacent to Iteration 1 but not required for the retrieval MCP handler
promotion because the focused handler tests and promotion smoke use isolated
MCP/bridge paths.

## Deferred Beyond Iteration 1

These are intentionally out of scope for the first retrieval iteration, but
the roadmap keeps the door open:

- local knowledge base tools such as document ingest/list/search/remove;
- entity registry create/get/list/update/delete and relationship tools;
- decision-query or decision-registry tools;
- handoff/session snapshot tools beyond `omega_context`;
- local coordination, task queues, claims, and agent inboxes;
- encrypted profile get/list/search;
- router/model-context tools;
- oracle/council/review tools;
- cloud sync and federation.

The sequencing rule is: make retrieval dependable first, then build higher
level systems on top of it.

## Future Session Checklist

At the next session, do this in order:

1. Read `AGENTS.md`.
2. Read `docs/development/live-safe-development.md`.
3. Read this handoff.
4. Run `git status -sb` and `git log --oneline --decorate -12`.
5. Re-run the focused retrieval tests and isolated promotion smoke.
6. If the user wants more dev hardening, pick from "Remaining Engineering Work
   After Live Promotion" and commit each successful slice.
7. If the user wants live promotion, follow "Remaining Work Before Live
   Promotion" exactly.
8. Keep docs updated in the same slice as behavior or verification changes.
9. Commit after each successful slice.
10. Never disturb live OMEGA unless the user explicitly asks for promotion or
    live installation work.
