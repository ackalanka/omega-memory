# AGENTS.md

Read this file before doing work in this checkout.

This worktree is for developing community/open-core OMEGA MCP retrieval
improvements. Do not confuse this work with the general upstream product docs
already present in `docs/`.

## What This Checkout Is

- Development checkout: `/home/akalanka/projects/omega-memory-dev`
- Live installed checkout used by current MCP clients:
  `/home/akalanka/projects/omega-memory`
- Development branch: `dev/retrieval-tools`
- Development virtualenv: `.venv`
- Isolated development OMEGA home: `/tmp/omega-memory-dev-home`
- Live OMEGA home: `/home/akalanka/.omega`

The live installed MCP server and hooks may be used by active agents. Treat the
live checkout and live memory database as production state unless the user
explicitly asks for promotion or live installation work.

## Source Of Truth For This Effort

For this community retrieval-tools effort, read these files first and in this
order:

1. `docs/development/live-safe-development.md`
2. `docs/development/community-tools-roadmap.md`
3. `docs/development/iteration-1-retrieval-research.md`
4. Relevant source files under `src/omega/`
5. Relevant tests under `tests/`

The rest of `docs/` contains upstream product documentation, generated site
content, public-facing guides, and Pro feature references. Those files are
useful for evidence and comparison, but they are not the active implementation
plan for this fork/worktree. Do not treat `docs/guides/*`,
`docs/reference/*`, or `docs/index.md` as instructions for what to build next
unless a development doc above explicitly points there.

## Current Goal

Iteration 1 focuses on core memory retrieval for agents:

- full memory fetch by ID via `omega_memory(action="get")`;
- structured and full-content `omega_query` output;
- a query-then-hydrate `omega_recall` tool;
- full and paginated browse;
- optional related-memory expansion;
- retrieval profiles for common agent intents.

Do not start router, oracle, coordination, cloud sync, federation, encrypted
profile, or full knowledge-base work unless the user explicitly changes the
iteration scope.

## Live-Safety Rules

- Work in `/home/akalanka/projects/omega-memory-dev`.
- Do not edit `/home/akalanka/projects/omega-memory` while iterating.
- Do not run `omega setup` from this checkout unless the user explicitly wants
  to rewrite real MCP/client/hook configuration.
- Use `OMEGA_HOME=/tmp/omega-memory-dev-home` for memory-store smoke tests.
- Remember that some CLI and hook paths may still hardcode `~/.omega`; inspect
  before running commands that could touch live state.
- Before any live promotion, back up live memory and follow
  `docs/development/live-safe-development.md`.

## Development Commands

Use the local virtualenv:

```bash
.venv/bin/ruff check src/omega tests
.venv/bin/pytest tests/test_init_and_json_compat.py tests/test_types.py -q
```

For isolated memory smoke tests:

```bash
OMEGA_HOME=/tmp/omega-memory-dev-home .venv/bin/python -c \
  'from omega.bridge import store, query; print(store("dev smoke", event_type="memory")); print(query("dev smoke", limit=1))'
```

Add focused tests for any retrieval behavior you change. Do not claim a
retrieval change is complete if the focused test path was skipped.

## Implementation Principles

- Prefer exposing existing open-core capabilities before building new storage
  machinery.
- Keep existing MCP tool behavior backward compatible by default.
- Add optional arguments before changing existing output shapes.
- Return stable IDs, full content when requested, metadata, truncation status,
  and omitted IDs explicitly.
- Enforce output budgets when returning full content or prompt-ready context.
- Keep Pro-feature research independent; do not copy proprietary internals.

## Git Hygiene

- Check `git status -sb` before editing.
- Preserve unrelated user changes.
- Stage only intended files if asked to commit.
- Keep this work scoped to the dev checkout until promotion is explicitly
  requested.
