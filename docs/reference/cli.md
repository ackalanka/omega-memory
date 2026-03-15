# CLI Commands

All commands are invoked as `omega <command>`. The CLI is implemented in `src/omega/cli.py`.

---

## Core Commands

### `omega setup`

Set up OMEGA: create directories, download embedding model, initialize database, register MCP server, install hooks, update CLAUDE.md.

```
omega setup [--download-model] [--client {claude-code}]
```

| Option | Description |
|--------|-------------|
| `--download-model` | Download bge-small-en-v1.5 ONNX model (upgrade from all-MiniLM-L6-v2) |
| `--client {claude-code}` | Configure a specific client (MCP registration, hooks) |

### `omega doctor`

Verify installation health: imports, embedding model, database, MCP registration, hooks.

```
omega doctor [--client {claude-code}]
```

| Option | Description |
|--------|-------------|
| `--client {claude-code}` | Include client-specific checks (MCP registration, hooks) |

### `omega status`

Show memory count, database size, model status, edge count.

```
omega status
```

### `omega serve`

Run the MCP server in stdio mode. Used by Claude Code internally -- not normally called directly.

```
omega serve
```

---

## Memory Commands

### `omega query`

Search memories by semantic similarity or exact phrase match.

```
omega query <text> [--exact] [--limit N] [--json]
```

| Option | Description |
|--------|-------------|
| `<text>` | Search text (positional, one or more words) |
| `--exact` | Use FTS5 exact phrase search instead of semantic |
| `--limit N` | Max results (default: 10) |
| `--json` | Output as JSON |

Example:

```
omega query "database migration pattern" --limit 5
omega query "threading deadlock" --exact
```

### `omega store`

Store a memory with a specified type.

```
omega store <content> [-t TYPE]
```

| Option | Description |
|--------|-------------|
| `<content>` | Memory content (positional, one or more words) |
| `-t`, `--type` | Memory type: `memory` (default), `lesson`, `decision`, `error`, `task`, `preference` |

Example:

```
omega store "Always use absolute paths in hooks" -t lesson
omega store "Switched from PyPDF2 to Docling for PDF extraction" -t decision
```

### `omega remember`

Store a permanent user preference.

```
omega remember <text>
```

Example:

```
omega remember "I prefer tabs over spaces"
```

### `omega timeline`

Show memory timeline grouped by day.

```
omega timeline [--days N] [--json]
```

| Option | Description |
|--------|-------------|
| `--days N` | Number of days to show (default: 7) |
| `--json` | Output as JSON |

---

## Maintenance Commands

### `omega consolidate`

Deduplicate, prune stale memories, cap session summaries, clean orphaned edges.

```
omega consolidate [--prune-days N]
```

| Option | Description |
|--------|-------------|
| `--prune-days N` | Prune entries older than N days with zero access (default: 30) |

### `omega compact`

Cluster and summarize related memories to reduce noise.

```
omega compact [-t TYPE] [--threshold FLOAT] [--dry-run]
```

| Option | Description |
|--------|-------------|
| `-t`, `--type` | Event type to compact: `lesson_learned` (default), `decision`, `error_pattern`, `task_completion` |
| `--threshold` | Similarity threshold for clustering (default: 0.60) |
| `--dry-run` | Preview clusters without compacting |

### `omega backup`

Back up omega.db to ~/.omega/backups/ (keeps last 5).

```
omega backup
```

### `omega validate`

Validate omega.db integrity (SQLite + FTS5 + vec index).

```
omega validate [--repair]
```

| Option | Description |
|--------|-------------|
| `--repair` | Attempt to repair FTS5 index if corrupted |

### `omega stats`

Show memory type distribution and health summary.

```
omega stats [--json]
```

| Option | Description |
|--------|-------------|
| `--json` | Output as JSON |

### `omega activity`

Show recent session activity overview.

```
omega activity [--days N] [--json]
```

| Option | Description |
|--------|-------------|
| `--days N` | Number of days to show (default: 7) |
| `--json` | Output as JSON |

### `omega logs`

Show recent hook errors from hooks.log.

```
omega logs [-n LINES]
```

| Option | Description |
|--------|-------------|
| `-n`, `--lines` | Number of lines to show (default: 50) |

---

## Knowledge Commands

### `omega knowledge scan`

Scan ~/.omega/documents/ for new or changed files and auto-ingest. Alias: `omega kb scan`.

```
omega knowledge scan [--dir PATH]
```

| Option | Description |
|--------|-------------|
| `--dir` | Custom directory to scan (default: ~/.omega/documents/) |

### `omega knowledge list`

List all ingested documents with chunk counts and metadata.

```
omega knowledge list
```

### `omega knowledge search`

Search across ingested documents using vector similarity.

```
omega knowledge search <query> [--limit N]
```

| Option | Description |
|--------|-------------|
| `<query>` | Search query (positional) |
| `--limit N` | Max results (default: 5) |

---

## Cloud Commands

### `omega cloud setup`

Configure Supabase connection for cloud sync.

```
omega cloud setup [--url URL] [--key KEY] [--service-key KEY]
```

| Option | Description |
|--------|-------------|
| `--url` | Supabase project URL |
| `--key` | Supabase anon key |
| `--service-key` | Supabase service role key (optional) |

### `omega cloud sync`

Sync local data to Supabase cloud.

```
omega cloud sync
```

### `omega cloud pull`

Pull memories and documents from Supabase cloud.

```
omega cloud pull
```

### `omega cloud status`

Show cloud sync status.

```
omega cloud status
```

### `omega cloud schema`

Print the Supabase SQL schema for manual setup.

```
omega cloud schema
```

### `omega cloud verify`

Verify the Supabase connection is working.

```
omega cloud verify
```

---

## Mobile Commands

### `omega mobile setup`

Print setup instructions for mobile access via mcp-proxy + Tailscale.

```
omega mobile setup
```

### `omega mobile serve`

Start an mcp-proxy HTTP server for mobile access.

```
omega mobile serve [--port PORT] [--host HOST]
```

| Option | Description |
|--------|-------------|
| `--port` | HTTP port (default: 8089) |
| `--host` | Bind address (default: 127.0.0.1) |

---

## Migration Commands

### `omega migrate`

Copy MAGMA data to OMEGA (non-destructive legacy migration).

```
omega migrate
```

### `omega migrate-db`

Migrate legacy JSON graphs to the SQLite backend.

```
omega migrate-db [--force]
```

| Option | Description |
|--------|-------------|
| `--force` | Overwrite existing SQLite database |

### `omega reingest`

Reload store.jsonl entries into the graph system.

```
omega reingest
```
