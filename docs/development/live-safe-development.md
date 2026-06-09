# Live-Safe Development Setup

This checkout is a development worktree for changes that must not disturb the
currently running OMEGA MCP installation.

## Paths

- Live checkout used by Codex/Claude MCP:
  `/home/akalanka/projects/omega-memory`
- Development checkout:
  `/home/akalanka/projects/omega-memory-dev`
- Development branch:
  `dev/retrieval-tools`
- Development virtualenv:
  `/home/akalanka/projects/omega-memory-dev/.venv`
- Isolated development OMEGA home:
  `/tmp/omega-memory-dev-home`
- Live OMEGA home:
  `/home/akalanka/.omega`

## Why This Exists

Codex and Claude are configured to run the live MCP server and hooks from:

```text
/home/akalanka/projects/omega-memory/.venv/bin/python3.12 -m omega.server.mcp_server
```

and hook scripts under:

```text
/home/akalanka/projects/omega-memory/src/omega/hooks/
```

Editing the live checkout directly can affect new MCP server or hook processes
as soon as an agent session restarts. This development worktree lets us build
and test retrieval changes away from the live checkout, then promote only tested
diffs back to the live worktree.

## Isolation Rules

Run development commands from this checkout:

```bash
cd /home/akalanka/projects/omega-memory-dev
```

Use the development virtualenv:

```bash
.venv/bin/python -m pytest tests/test_init_and_json_compat.py tests/test_types.py -q
.venv/bin/ruff check src/omega
```

For memory-store smoke tests, set `OMEGA_HOME` so the core bridge and SQLite
store use `/tmp/omega-memory-dev-home/omega.db` instead of the live database:

```bash
OMEGA_HOME=/tmp/omega-memory-dev-home .venv/bin/python -c \
  'from omega.bridge import store, query; print(store("dev smoke", event_type="memory")); print(query("dev smoke", limit=1))'
```

Do not run `omega setup` from the development checkout unless the goal is to
rewrite real client MCP/hook configuration. Setup modifies files outside the
repository, including agent/client config.

## Known Caveat

Not all code paths honor `OMEGA_HOME` consistently. The core bridge and
`SQLiteStore` do honor it, which is the path used by MCP memory operations.
Some CLI and hook code still hardcodes `~/.omega`; for example, at the time this
note was written, `OMEGA_HOME=/tmp/omega-memory-dev-home .venv/bin/python -m
omega.cli status` still reported the live `/home/akalanka/.omega/omega.db`.

Use MCP handler tests, bridge tests, and direct bridge smoke tests for isolated
development. Treat CLI/hook commands as live-risk unless inspected first.

## Safe Promotion Back To Live

Before promotion:

1. Verify the development worktree:

   ```bash
   cd /home/akalanka/projects/omega-memory-dev
   .venv/bin/ruff check src/omega
   .venv/bin/pytest <focused tests>
   ```

2. Back up live memory data:

   ```bash
   /home/akalanka/projects/omega-memory/.venv/bin/python3.12 -m omega.cli backup
   ```

3. Review the diff:

   ```bash
   git diff --stat
   git diff
   ```

Then merge or cherry-pick the tested branch into the live checkout:

```bash
cd /home/akalanka/projects/omega-memory
git merge --ff-only dev/retrieval-tools
```

Restart the MCP client/session after promotion so new MCP tool schemas and
handlers are loaded.

## Current Goal

The initial retrieval work should focus on core memory access, not Pro-only
coordination or oracle features:

- full memory fetch by ID
- structured/full-content query output
- query-then-hydrate recall workflow
- full/paginated browse
- retrieval profiles for common agent intents
