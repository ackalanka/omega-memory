# OMEGA Schema — Consolidated Investigation Report

> **Synthesized from:** Four independent schema investigations (Gemini-3.1-pro, Gemini-3.5-Flash-High, Codex GPT-5.5 xhigh, unknown author)
> **Commit range covered:** `405f31e559ff606494edbcb7c9a07852aede6995` → `d7c7590bf78439b9dda8625b845c6008061f31b7`
> **Date of synthesis:** 2026-06-12
> **Purpose:** Decision-taking reference. Contains all verified schema facts, application usage data, gap analysis, and actionable recommendations.
> **Methodology:** Where investigations disagreed, the finding with the widest file-read coverage and source line evidence is preferred. Findings unique to a single investigation are included when they carry source evidence; they are labelled ⚠ single-source.

---

## Vocabulary

| Term | Meaning |
|---|---|
| **Schema-defined** | Appears in a `CREATE TABLE`, `CREATE INDEX`, `CREATE VIRTUAL TABLE`, `CREATE TRIGGER`, or `CREATE VIEW` statement. |
| **Application-used** | Read or written by Python code in `src/omega/`. |
| **Write-only** | Written by the application but never read back. |
| **Schema-only** | Schema-defined but never read, written, or called by any standard execution path. |
| **Dead** | Schema-defined and never written or read by any code path at all (distinct from schema-only tables which at least get created). |
| **Derivable** | Computable from existing schema data without a schema change. |
| **Implied** | Follows from SQLite internals (e.g., implicit `rowid`, `docid` in FTS5). |

---

## Phase 0 — File Inventory

### Databases

There are **two separate SQLite database files**. This distinction matters for connection management, PRAGMA settings, and backup strategy.

| Database file | Location | Contains |
|---|---|---|
| `omega.db` | `$OMEGA_HOME/omega.db` | All memory, graph, entity, maintenance, and coordination schema |
| `llm_usage.db` | `$OMEGA_HOME/llm_usage.db` | `llm_usage` table only; managed by `UsageTracker` independently |

### Schema-Defining Files

| File | Role |
|---|---|
| `src/omega/schema.py` | Central DDL source of truth. `init_schema()` creates all tables, indices, virtual tables, and triggers for `omega.db`. Contains versioned migration runner v1–v14. |
| `src/omega/usage_tracker.py` | Defines the `llm_usage` table DDL inline for `llm_usage.db`. Manages its own WAL-mode connection. |
| `src/omega/migrate_to_sqlite.py` | Legacy one-time JSON-graph→SQLite migration. Inserts into `memories`, `edges`, `entity_index`. |

### Application Files (SQL consumers)

| File | Tables touched |
|---|---|
| `src/omega/sqlite_store/_base.py` | PRAGMA configuration, connection init, WAL checkpoint ops, calls `init_schema()` |
| `src/omega/sqlite_store/_store.py` | `memories` (full CRUD), `edges` (INSERT/DELETE), `memories_vec` (INSERT/DELETE), `forgetting_log` (INSERT) |
| `src/omega/sqlite_store/_search.py` | `memories` (SELECT), `memories_fts` (MATCH), `memories_vec` (MATCH), `memories` (session DELETE) |
| `src/omega/sqlite_store/_query.py` | `memories` (SELECT), `memories_vec` (KNN via `_vec_query`), `memories_fts` (via `_text_search`) |
| `src/omega/sqlite_store/_maintenance.py` | `memories` (SELECT/UPDATE/DELETE), `edges` (SELECT/INSERT/DELETE), `memories_vec` (DELETE/INSERT/reembed/backfill), `forgetting_log` (INSERT/SELECT/DELETE), `cloud_delete_queue` (INSERT only), `entity_index` (helper methods defined but never called) |
| `src/omega/bridge.py` | Orchestration layer calling `_store`, `_search`, `_query`, `_maintenance`; direct `memories` SELECT |
| `src/omega/server/handlers.py` | Calls bridge/store methods; reads from `forgetting_log` indirectly; reads metadata JSON fields |
| `src/omega/server/mcp_server.py` | `llm_usage` via `UsageTracker`; Pro coordination tables (see note below) |
| `src/omega/cli.py` | `memories` (SELECT), `memories_fts` (MATCH integrity check), `entity_index` (listed in doctor row counts), PRAGMA `integrity_check`/`query_only`/`busy_timeout` |
| `src/omega/integrations/crewai.py` | `memories` DELETE (scope reset) |

> **⚠ Pro coordination tables (single-source — Investigation 4):** `src/omega/server/mcp_server.py` references `coord_sessions`, `coord_file_claims`, `coord_branch_claims`, and `coord_tasks` tables for crash recovery. These are part of the Pro/coordination module, not open-core, and their DDL is not defined in `schema.py`. They may live in `omega.db` or a separate coordination database file.

---

## Phase 1 — Schema Topology

### 1.1 — Regular Tables

#### Table 1: `schema_version`

**Source:** `src/omega/schema.py` line 39

```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
)
```

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `version` | INTEGER | NOT NULL | Single-row table tracking migration level. No PRIMARY KEY; uses implicit `rowid`. |

**Implied:** `rowid` (implicit; table has no `WITHOUT ROWID`).

**Application usage:**
- Read at startup to determine migration path (`schema.py:44`).
- INSERT on fresh database (`schema.py:46`).
- UPDATE after each migration step from v1 through v14 (`schema.py:64` through `schema.py:288`).
- **Current value:** `14` (`SCHEMA_VERSION = 14` at `schema.py:12`).

---

#### Table 2: `memories`

**Source:** `src/omega/schema.py` lines 297–325 (current full-table DDL)

```sql
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT UNIQUE NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT,
    created_at TEXT NOT NULL,
    last_accessed TEXT,
    access_count INTEGER DEFAULT 0,
    ttl_seconds INTEGER,
    session_id TEXT,
    event_type TEXT,
    project TEXT,
    content_hash TEXT,
    priority INTEGER DEFAULT 3,
    referenced_date TEXT,
    entity_id TEXT,
    agent_type TEXT,
    canonical_hash TEXT,
    end_date TEXT,
    extracted_keywords TEXT,
    retrieval_count INTEGER DEFAULT 0,
    memory_type TEXT DEFAULT 'semantic',
    valid_from TEXT,
    valid_until TEXT,
    derived_from TEXT,
    source_uri TEXT,
    status TEXT DEFAULT 'active'
)
```

| # | Column | Type | Constraints | Default | Added in migration | Application status |
|---|---|---|---|---|---|---|
| 1 | `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | — | v1 | Active (rowid alias; used in vec rowid mapping, batch hydration) |
| 2 | `node_id` | TEXT | UNIQUE NOT NULL | — | v1 | Active (public stable identifier; all retrieval paths) |
| 3 | `content` | TEXT | NOT NULL | — | v1 | Active (FTS trigger, all retrieval) |
| 4 | `metadata` | TEXT | — | — | v1 | Active (JSON blob; parsed Python-side for tags, updated_at, and others) |
| 5 | `created_at` | TEXT | NOT NULL | — (no DEFAULT) | v1 | Active (temporal search, ordering, expiry) |
| 6 | `last_accessed` | TEXT | — | — | v1 | Active (LRU eviction, decay factor) |
| 7 | `access_count` | INTEGER | — | 0 | v1 | Active (hot cache, dedup bump, health check) |
| 8 | `ttl_seconds` | INTEGER | — | — | v1 | Active (expiry check: `datetime(created_at, '+' \|\| ttl_seconds \|\| ' seconds')`) |
| 9 | `session_id` | TEXT | — | — | v2 | Active (session retrieval, session DELETE) |
| 10 | `event_type` | TEXT | — | — | v3 | Active (type retrieval, consolidation WHERE clauses) |
| 11 | `project` | TEXT | — | — | v3 | Active (project scoping, WHERE clauses) |
| 12 | `content_hash` | TEXT | — | — | v4 | Active (exact dedup on write: `WHERE content_hash = ?`) |
| 13 | `priority` | INTEGER | — | 3 | v5 | Active (consolidation phase 0: `WHERE COALESCE(priority, 3) < 5`) |
| 14 | `referenced_date` | TEXT | — | — | v5 | Active (temporal search: `WHERE referenced_date BETWEEN ? AND ?`) |
| 15 | `entity_id` | TEXT | — | — | v6 | Active (entity-scoped queries: `WHERE entity_id = ?`) |
| 16 | `agent_type` | TEXT | — | — | v6 | **Written; Python-filtered only** — checked in `_query_phase_boost()` Python code but never appears in a SQL `WHERE` clause. Index `idx_memories_agent_type` is never hit. |
| 17 | `canonical_hash` | TEXT | — | — | v8 | Active (canonical dedup on write: `WHERE canonical_hash = ?`) |
| 18 | `end_date` | TEXT | — | — | v8 | **DEAD — never written or read.** Added v8; superseded by `valid_until` (added v11). Index `idx_memories_end_date` is waste. Safe to drop in a future migration. |
| 19 | `extracted_keywords` | TEXT | — | — | v9 | Active (FTS trigger concatenation; not used in SQL filters) |
| 20 | `retrieval_count` | INTEGER | — | 0 | v10 | **DEAD — never written or read.** `access_count` (column 7) serves the same purpose and is actively used. Index does not exist (no idx on this column). Safe to drop or repurpose. |
| 21 | `memory_type` | TEXT | — | `'semantic'` | v10 | **Written; never SQL-queried.** Set in `store()` via `_MEMORY_TYPE_MAP`. Never appears in SQL `WHERE`, `ORDER BY`, or `GROUP BY`. Index `idx_memories_memory_type` is never hit. |
| 22 | `valid_from` | TEXT | — | — | v11 | Active (bi-temporal filter in `_query_phase_filter()`) |
| 23 | `valid_until` | TEXT | — | — | v11 | Active (bi-temporal filter; `mark_superseded()`) |
| 24 | `derived_from` | TEXT | — | — | v11 | **Written as column AND duplicated as edge.** Column value is returned in `get_node()` but never used in SQL filtering. Edge traversal via `get_related_chain()` uses the `edges` table instead. Column is redundant. |
| 25 | `source_uri` | TEXT | — | — | v11 | **Written; never SQL-filtered.** Returned in `get_node()` result set but no SQL `WHERE` clause uses this column. Index `idx_memories_source_uri` is never hit. |
| 26 | `status` | TEXT | — | `'active'` | v11 | Active (soft-delete lifecycle filter: `WHERE status = ?`, `mark_superseded()`) |

**Implied:** `rowid` aliases to `id` (because `id` is `INTEGER PRIMARY KEY`).

**Important constraint note:** `created_at` has `NOT NULL` but no `DEFAULT`. The application must supply this value on every INSERT or SQLite will raise a constraint violation.

---

#### Table 3: `edges`

**Source:** `src/omega/schema.py` lines 386–396

```sql
CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_id, target_id, edge_type)
)
```

| Column | Type | Constraints | Default | Notes |
|---|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | — | rowid alias |
| `source_id` | TEXT | NOT NULL | — | Starting node_id of directed relationship |
| `target_id` | TEXT | NOT NULL | — | Destination node_id of directed relationship |
| `edge_type` | TEXT | NOT NULL | — | Free-form string; no CHECK or FK constraint |
| `weight` | REAL | — | 1.0 | Relationship strength |
| `metadata` | TEXT | — | — | Optional JSON |
| `created_at` | TEXT | NOT NULL | `datetime('now')` | ISO8601; has DEFAULT unlike `memories.created_at` |

**Table constraint:** `UNIQUE(source_id, target_id, edge_type)` — prevents duplicate typed edges between the same pair.

**Application-used `edge_type` values (exhaustive list from source):**

| Value | Written in | Purpose |
|---|---|---|
| `'causal'` | `_store.py:242` | Causal link between memories |
| `'derived_from'` | `_store.py:250` | Derivation from a parent memory |
| `'contradicts'` | `_store.py:698` | Contradiction relationship |
| `'related'` | `_maintenance.py:977` | General relatedness |
| `'supersedes'` | traversal priority (`_maintenance.py:1025`) | Supersession chain |
| `'evolves'` | traversal priority (`_maintenance.py:1031`) | Semantic evolution |

**No schema constraint enforces these values.** Any string is accepted.

**Application operations on `edges`:**

| Operation | Location | Notes |
|---|---|---|
| INSERT (causal) | `_store.py:240–244` | On new memory with causal context |
| INSERT (derived_from) | `_store.py:248–252` | On new memory with parent |
| INSERT (contradicts) | `_store.py:696–701` | On contradiction detection |
| INSERT (general) | `_maintenance.py:972–995` via `add_edge()` | Any type |
| SELECT (bidirectional traversal) | `_maintenance.py:1067–1075` via `get_related_chain()` | Follows source and target |
| SELECT (by type) | `_maintenance.py:1246–1263` via `get_edges_by_type()` | Filters by edge_type |
| DELETE (cascade on memory delete) | `_store.py:339`, `_maintenance.py:145` | Orphan prevention |
| DELETE (orphan cleanup) | `_maintenance.py:333–343` | Consolidation phase 3 |

**Implied:** `rowid` aliases to `id`.

---

#### Table 4: `forgetting_log`

**Source:** `src/omega/schema.py` lines 405–414 (current DDL); also defined in v4→v5 migration block (`schema.py:108`) with identical columns.

```sql
CREATE TABLE IF NOT EXISTS forgetting_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    content_preview TEXT,
    event_type TEXT,
    reason TEXT NOT NULL,
    deleted_at TEXT NOT NULL,
    metadata TEXT
)
```

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | rowid alias |
| `node_id` | TEXT | NOT NULL | `node_id` of the deleted memory |
| `content_preview` | TEXT | — | Truncated content preview (~200 chars) |
| `event_type` | TEXT | — | Original event type of deleted memory |
| `reason` | TEXT | NOT NULL | Why the memory was deleted (see values below) |
| `deleted_at` | TEXT | NOT NULL | ISO8601 timestamp of deletion |
| `metadata` | TEXT | — | Optional deletion metadata JSON |

**This table is actively used** (contrary to Investigation 1's claim). Write and read operations confirmed in `_maintenance.py`.

**Application-used `reason` values (exhaustive list from source):**

| Value | Written in | Trigger condition |
|---|---|---|
| `'user_deleted'` | `_store.py:335` | Explicit user/API delete |
| `'ttl_expired'` | `_maintenance.py:104` | TTL elapsed |
| `'lru_evicted'` | `_maintenance.py:137` | LRU eviction pass |
| `'consolidation_pruned'` | `_maintenance.py:279` | Consolidation general prune |
| `'consolidation_phase0_pruned'` | `_maintenance.py:243` | Consolidation phase 0 (low priority) |
| `'strength_decay'` | `_maintenance.py:459` | Strength decay pass |
| `'feedback_flagged'` | `_maintenance.py:889` | User negative feedback |
| `'ingest_superseded'` | `_store.py:521` | Superseded during ingest |

**Write sites:**

| File | Line | Operation | Condition |
|---|---|---|---|
| `_maintenance.py` | 39 | INSERT (`OR IGNORE`) | node_id, content_preview, event_type, reason, deleted_at, metadata |
| `_maintenance.py` | 157 | DELETE | `WHERE deleted_at < ?` (periodic purge) |

**Read sites:**

| File | Line | Operation | Condition |
|---|---|---|---|
| `_maintenance.py` | 166 | SELECT all columns | `WHERE reason = ?` |
| `_maintenance.py` | 173 | SELECT all columns | Unconditional (list all) |

---

#### Table 5: `cloud_delete_queue`

**Source:** `src/omega/schema.py` lines 420–425

```sql
CREATE TABLE IF NOT EXISTS cloud_delete_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    local_id INTEGER NOT NULL,
    deleted_at TEXT NOT NULL
)
```

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | rowid alias |
| `local_id` | INTEGER | NOT NULL | Local `id` (`rowid`) of the deleted memory in `memories` |
| `deleted_at` | TEXT | NOT NULL | ISO8601 timestamp |

**Status: Write-only.** INSERTs happen in `_maintenance.py:55`. No code ever SELECTs from or DELETEs from this table. This represents an **incomplete implementation** of local-to-cloud synchronization — the table grows indefinitely and is never drained.

**Missing constraint:** `local_id → memories.id` is not FK-constrained.

---

#### Table 6: `entity_index`

**Source (current DDL):** `src/omega/schema.py` lines 429–440

```sql
CREATE TABLE IF NOT EXISTS entity_index (
    entity_name TEXT NOT NULL PRIMARY KEY,
    entity_type TEXT DEFAULT 'person',
    statement_count INTEGER DEFAULT 0,
    outcome_count INTEGER DEFAULT 0,
    contradiction_score REAL DEFAULT 0.0,
    follow_through_rate REAL DEFAULT 0.0,
    first_seen TEXT NOT NULL DEFAULT (datetime('now')),
    last_updated TEXT NOT NULL DEFAULT (datetime('now')),
    metadata TEXT
)
```

> **⚠ Migration DDL inconsistency (single-source — Investigation 3):** The migration block that first creates this table (`schema.py:128`, v5→v6) defines `first_seen` and `last_updated` as `TEXT NOT NULL` *without* the `DEFAULT (datetime('now'))` clause. The current full-table DDL at line 429 does include the DEFAULT. Fresh installs get the DEFAULT; older databases upgraded through migrations do not — application code must supply these values explicitly.

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `entity_name` | TEXT | NOT NULL, PRIMARY KEY (TEXT — does not alias rowid) | String identifier |
| `entity_type` | TEXT | DEFAULT `'person'` | Classification |
| `statement_count` | INTEGER | DEFAULT 0 | Statements recorded |
| `outcome_count` | INTEGER | DEFAULT 0 | Outcomes tracked |
| `contradiction_score` | REAL | DEFAULT 0.0 | Computed contradiction rate |
| `follow_through_rate` | REAL | DEFAULT 0.0 | Computed completion rate |
| `first_seen` | TEXT | NOT NULL, DEFAULT `(datetime('now'))` | ISO8601 |
| `last_updated` | TEXT | NOT NULL, DEFAULT `(datetime('now'))` | ISO8601 |
| `metadata` | TEXT | — | Optional profile JSON |

**Implied:** `rowid` present (TEXT PRIMARY KEY does not alias it; separate from entity_name).

**Status: Schema-only in practice.** Three helper methods exist in `_maintenance.py` — `write_entity_index()`, `get_entity_index()`, and `get_entity_list()` — but none are imported or called anywhere in standard execution paths. They constitute unreferenced dead code. `migrate_to_sqlite.py` does INSERT into this table during the one-time migration only.

---

#### Table 7: `memory_clusters`

**Source:** `src/omega/schema.py` lines 483–495

```sql
CREATE TABLE IF NOT EXISTS memory_clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cluster_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    member_count INTEGER NOT NULL,
    centroid BLOB,
    representative_keywords TEXT,
    representative_memory_ids TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    superseded INTEGER DEFAULT 0
)
```

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | rowid alias |
| `cluster_id` | INTEGER | NOT NULL | Numeric cluster identifier |
| `label` | TEXT | NOT NULL | Topic label |
| `member_count` | INTEGER | NOT NULL | Count of member memories |
| `centroid` | BLOB | — | Serialized float vector centroid |
| `representative_keywords` | TEXT | — | Space-separated representative terms |
| `representative_memory_ids` | TEXT | — | Serialized list of representative memory IDs |
| `created_at` | TEXT | NOT NULL | ISO8601 |
| `updated_at` | TEXT | NOT NULL | ISO8601 |
| `superseded` | INTEGER | DEFAULT 0 | 1 if cluster has been replaced |

**Status: Schema-only in open-core.** Zero SELECT/INSERT/UPDATE/DELETE found in `src/omega/`. Likely consumed by an `omega_platform` pattern learner (Pro tier).

---

#### Table 8: `thompson_arms`

**Source:** `src/omega/schema.py` lines 501–511

```sql
CREATE TABLE IF NOT EXISTS thompson_arms (
    arm_id TEXT PRIMARY KEY,
    arm_type TEXT NOT NULL,
    alpha REAL DEFAULT 1.0,
    beta REAL DEFAULT 1.0,
    total_trials INTEGER DEFAULT 0,
    total_successes INTEGER DEFAULT 0,
    last_updated TEXT NOT NULL,
    context TEXT
)
```

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `arm_id` | TEXT | PRIMARY KEY | Unique arm identifier |
| `arm_type` | TEXT | NOT NULL | Action selector context type |
| `alpha` | REAL | DEFAULT 1.0 | Bayesian success count |
| `beta` | REAL | DEFAULT 1.0 | Bayesian failure count |
| `total_trials` | INTEGER | DEFAULT 0 | Total execution count |
| `total_successes` | INTEGER | DEFAULT 0 | Positive reinforcement count |
| `last_updated` | TEXT | NOT NULL | ISO8601 |
| `context` | TEXT | — | Serialized configuration metadata |

**Status: Effectively dead in open-core.** Referenced via `omega.thompson.ThompsonBandit` import which does not exist in open-core. Import is wrapped in a `try/except` guard. No standard execution path reads or writes this table.

---

#### Table 9: `maintenance_dlq`

**Source:** `src/omega/schema.py` line 181 (defined inside v9→v10 migration block; not duplicated in top-level DDL)

```sql
CREATE TABLE IF NOT EXISTS maintenance_dlq (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stage_name TEXT NOT NULL,
    error_class TEXT NOT NULL DEFAULT 'transient',
    error_message TEXT,
    remediation_attempts INTEGER DEFAULT 0,
    max_remediation INTEGER DEFAULT 3,
    status TEXT NOT NULL DEFAULT 'pending',
    next_retry_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
```

| Column | Type | Constraints | Default | Notes |
|---|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | — | rowid alias |
| `stage_name` | TEXT | NOT NULL | — | Processing stage where failure occurred |
| `error_class` | TEXT | NOT NULL | `'transient'` | Failure classification |
| `error_message` | TEXT | — | — | Stack trace or description |
| `remediation_attempts` | INTEGER | — | 0 | Retry count |
| `max_remediation` | INTEGER | — | 3 | Max retries allowed |
| `status` | TEXT | NOT NULL | `'pending'` | Processing status |
| `next_retry_at` | TEXT | — | — | ISO8601 scheduled retry |
| `created_at` | TEXT | NOT NULL | — | ISO8601 creation time |
| `updated_at` | TEXT | NOT NULL | — | ISO8601 last modification |

**Status: Schema-only.** Never written to or read from in any application code. Appears in the `omega validate` CLI doctor row counts only. Intended as a dead-letter queue for maintenance pipeline failures; not implemented.

---

#### Table 10: `llm_usage` (separate database: `llm_usage.db`)

**Source:** `src/omega/usage_tracker.py` lines 21–35

```sql
CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    tool_name TEXT NOT NULL,
    model TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'anthropic',
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_write_tokens INTEGER DEFAULT 0,
    estimated_cost_usd REAL DEFAULT 0.0,
    duration_ms INTEGER,
    project TEXT,
    created_at TEXT NOT NULL
)
```

| Column | Type | Constraints | Default | Notes |
|---|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | — | rowid alias |
| `session_id` | TEXT | — | — | Calling session context |
| `tool_name` | TEXT | NOT NULL | — | Name of the calling tool |
| `model` | TEXT | NOT NULL | — | LLM model name |
| `provider` | TEXT | NOT NULL | `'anthropic'` | LLM API provider |
| `input_tokens` | INTEGER | — | 0 | Input token count |
| `output_tokens` | INTEGER | — | 0 | Output token count |
| `cache_read_tokens` | INTEGER | — | 0 | Cache-read token count |
| `cache_write_tokens` | INTEGER | — | 0 | Cache-write token count |
| `estimated_cost_usd` | REAL | — | 0.0 | Computed cost |
| `duration_ms` | INTEGER | — | — | Call duration |
| `project` | TEXT | — | — | Project scope |
| `created_at` | TEXT | NOT NULL | — | ISO8601 timestamp (no DEFAULT) |

**Write site:** `usage_tracker.py:90` — `log_call()` on every LLM API invocation.

**Read sites:** `get_usage()` at `usage_tracker.py:106`, `125`, `143` — aggregates for cost/token reporting.

**Called from:** `_log_tool_usage()` in `mcp_server.py:421–436`.

---

### 1.2 — Virtual Tables

#### Virtual Table 1: `memories_vec`

**Source:** `src/omega/schema.py` lines 366–368

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS memories_vec
USING vec0(embedding float[{embedding_dim}] distance_metric=cosine)
```

- **Extension:** `sqlite-vec`. Created only if `vec_available` is True (extension loaded at startup in `_base.py`).
- **Embedding dimension:** Determined at runtime by `get_embedding_dim()` (`schema.py:306–311`). Default: **384** (bge-small-en-v1.5 model).
- **Distance metric:** Cosine.
- **Implied columns:** `rowid` (maps 1:1 to `memories.id`), `embedding` (BLOB), `distance` (query-time computed).
- **No FK constraint** between `memories_vec.rowid` and `memories.id`.

**Application operations:**

| Operation | Location | Notes |
|---|---|---|
| INSERT | `_store.py:231–233` | After memories INSERT; `rowid = memories.id` |
| MATCH (KNN) | `_search.py:36` | `SELECT rowid, distance FROM memories_vec WHERE embedding MATCH ? AND k = ?` |
| DELETE (with memory) | `_store.py:343`, `_maintenance.py:108` | Must be explicit; no cascade |
| Orphan cleanup | `_maintenance.py:348–365` | `LEFT JOIN memories m ON vec.rowid = m.id WHERE m.id IS NULL` |
| Reembedding | `_maintenance.py:526–575` | Updates vec row when embedding changes |
| Backfill | `_maintenance.py:577–646` | Populates vec for memories missing embeddings |

---

#### Virtual Table 2: `memories_fts`

**Source:** `src/omega/schema.py` lines 376–378

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
USING fts5(content, content='memories', content_rowid='id')
```

- **Extension:** FTS5 (built-in SQLite). External-content table pointing to `memories`.
- **Implied columns:** `rowid` (aliases `memories.id`), `content` (text), `rank` (BM25 score, query-time).
- FTS5 exposes BM25 ranking natively via the `rank` column.

**Application operations:**

| Operation | Location | Notes |
|---|---|---|
| MATCH query | `_search.py:102–123` | `SELECT ... FROM memories_fts f JOIN memories m ON f.rowid = m.id WHERE memories_fts MATCH ? ORDER BY f.rank` |
| Rebuild | `_search.py:170` | `INSERT INTO memories_fts(memories_fts) VALUES('rebuild')` |
| Initial populate | `schema.py:469–476` | Bulk-inserts on schema init |

**Synchronization:** Three triggers keep `memories_fts` in sync with `memories` automatically (see §1.4).

---

### 1.3 — Indices (37 total)

#### On `memories` (20 single-column + 1 compound = 21 total)

| Index name | Column(s) | Type | Query implication | Application status |
|---|---|---|---|---|
| `idx_memories_node_id` | `node_id` | B-tree | Lookups by stable ID | Active |
| `idx_memories_event_type` | `event_type` | B-tree | Type-based retrieval and consolidation | Active |
| `idx_memories_session_id` | `session_id` | B-tree | Session scoping and DELETE | Active |
| `idx_memories_project` | `project` | B-tree | Project-scoped retrieval | Active |
| `idx_memories_created_at` | `created_at` | B-tree | Timeline listing, ordering, decay | Active |
| `idx_memories_content_hash` | `content_hash` | B-tree | Exact-match dedup on write | Active |
| `idx_memories_priority` | `priority` | B-tree | Consolidation phase 0 filtering | Active |
| `idx_memories_referenced_date` | `referenced_date` | B-tree | Temporal range filtering | Active |
| `idx_memories_entity_id` | `entity_id` | B-tree | Entity-scoped queries | Active |
| `idx_memories_canonical_hash` | `canonical_hash` | B-tree | Canonical dedup on write | Active |
| `idx_memories_last_accessed` | `last_accessed` | B-tree | LRU eviction, hot-cache refresh | Active |
| `idx_memories_ttl_seconds` | `ttl_seconds` | B-tree | TTL expiry cleanup pass | Active |
| `idx_memories_valid_from` | `valid_from` | B-tree | Bi-temporal filter | Active |
| `idx_memories_valid_until` | `valid_until` | B-tree | Bi-temporal filter, supersession | Active |
| `idx_memories_status` | `status` | B-tree | Lifecycle filtering (`active`, `superseded`) | Active |
| **`idx_memories_end_date`** | **`end_date`** | B-tree | — | **WASTED — column is dead** |
| **`idx_memories_memory_type`** | **`memory_type`** | B-tree | — | **WASTED — column never used in SQL** |
| **`idx_memories_source_uri`** | **`source_uri`** | B-tree | — | **WASTED — column never SQL-filtered** |
| **`idx_memories_derived_from`** | **`derived_from`** | B-tree | — | **WASTED — column-level filter never used; edges used for traversal instead** |
| **`idx_memories_agent_type`** | **`agent_type`** | B-tree | — | **WASTED — filtering done in Python, not SQL** |
| `idx_memories_event_access` | `(event_type, access_count)` | B-tree, compound | Type + retrieval-rate compound filter | Active |

> **Critical:** 5 of 21 memory indices impose write amplification on every INSERT/UPDATE without ever being consulted by a SQL query.

#### On `edges` (3 indices)

| Index name | Column(s) | Type | Query implication |
|---|---|---|---|
| `idx_edges_source_id` | `source_id` | B-tree | Out-edge traversal from a source node |
| `idx_edges_target_id` | `target_id` | B-tree | In-edge traversal to a target node |
| `idx_edges_edge_type` | `edge_type` | B-tree | Filtering traversal to specific edge types |

#### On `forgetting_log` (3 indices)

| Index name | Column(s) | Type | Query implication |
|---|---|---|---|
| `idx_forgetting_log_deleted_at` | `deleted_at` | B-tree | Periodic purge by date |
| `idx_forgetting_log_reason` | `reason` | B-tree | Filtering by deletion reason |
| `idx_forgetting_log_node_reason` | `(node_id, reason)` | **UNIQUE** | Enforces uniqueness: a memory can only appear once per reason. Accelerates lookups starting with `node_id`. |

#### On `entity_index` (3 indices)

| Index name | Column(s) | Type | Query implication |
|---|---|---|---|
| `idx_entity_index_type` | `entity_type` | B-tree | Filter by entity type |
| `idx_entity_index_score` | `contradiction_score` | B-tree | Order/filter by contradiction rate |
| `idx_entity_index_updated` | `last_updated` | B-tree | Staleness queries |

#### On `maintenance_dlq` (1 index)

| Index name | Column(s) | Type | Query implication |
|---|---|---|---|
| `idx_maintenance_dlq_status` | `status` | B-tree | Status-filtered retry queries |

#### On `memory_clusters` (2 indices)

| Index name | Column(s) | Type | Query implication |
|---|---|---|---|
| `idx_memory_clusters_superseded` | `superseded` | B-tree | Filter active (non-superseded) clusters |
| `idx_memory_clusters_cluster_id` | `cluster_id` | B-tree | Specific cluster retrieval |

#### On `thompson_arms` (1 index)

| Index name | Column(s) | Type | Query implication |
|---|---|---|---|
| `idx_thompson_arms_type` | `arm_type` | B-tree | Fetch arms by algorithm category |

#### On `llm_usage` (3 indices)

| Index name | Column(s) | Type | Query implication |
|---|---|---|---|
| `idx_llm_usage_session` | `session_id` | B-tree | Session-scoped usage lookup |
| `idx_llm_usage_tool` | `(tool_name, created_at)` | B-tree, compound | Per-tool usage over time |
| `idx_llm_usage_created` | `created_at` | B-tree | Date-range reporting |

---

### 1.4 — Triggers (3 total)

All three triggers are created only if FTS5 is available.

#### Trigger: `memories_ai`

**Source:** `schema.py:449–453`

```sql
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content)
    VALUES (new.id, new.content || ' ' || COALESCE(new.extracted_keywords, ''));
END
```

**Fires:** AFTER INSERT ON `memories`
**Effect:** Automatically adds new memory content (plus extracted keywords) to the FTS index. The keyword concatenation means FTS searches against both natural content and pre-extracted terms.

#### Trigger: `memories_ad`

**Source:** `schema.py:455–459`

```sql
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content)
    VALUES ('delete', old.id, old.content || ' ' || COALESCE(old.extracted_keywords, ''));
END
```

**Fires:** AFTER DELETE ON `memories`
**Effect:** Sends an FTS5 delete command for the removed row. Without this, deleted memories would remain searchable.

#### Trigger: `memories_au`

**Source:** `schema.py:461–467`

```sql
CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE OF content ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content)
    VALUES ('delete', old.id, old.content || ' ' || COALESCE(old.extracted_keywords, ''));
    INSERT INTO memories_fts(rowid, content)
    VALUES (new.id, new.content || ' ' || COALESCE(new.extracted_keywords, ''));
END
```

**Fires:** AFTER UPDATE OF `content` ON `memories` (column-specific — only fires when `content` changes, not all updates)
**Effect:** Atomic FTS replace: deletes old index entry, inserts new one. Note: fires on `content` changes only. If `extracted_keywords` changes but `content` does not, the FTS index is not updated.

---

### 1.5 — Views

**Absent.** No `CREATE VIEW` statement found in any source file across all four investigations.

---

### 1.6 — PRAGMA Settings

#### Connection-time PRAGMAs (omega.db, set in `_base.py:417–426`)

| PRAGMA | Value | Purpose |
|---|---|---|
| `journal_mode` | `WAL` | Write-Ahead Logging; enables concurrent readers during writes |
| `synchronous` | `NORMAL` | Reduced fsync in WAL mode; reliable without full-sync overhead |
| `cache_size` | `-4000` (HTTP mode) / `-16000` (stdio mode) | 4 MB or 16 MB page cache; conditional to prevent vmmap leaks under HTTP daemon |
| `mmap_size` | `0` (HTTP mode) / `33554432` (stdio mode) | 0 or 32 MB memory-mapped I/O; disabled under HTTP to avoid process memory bloat |
| `busy_timeout` | `30000` | 30-second wait on lock contention; handles multi-process MCP client scenarios |
| `journal_size_limit` | `8388608` | 8 MB WAL file cap; prevents unbounded disk usage under parallel read/write cycles |
| `foreign_keys` | `ON` | Enables FK enforcement — **however, no FK constraints are declared in any table DDL** (see §4.5) |

#### Runtime PRAGMAs

| PRAGMA | Location | Purpose |
|---|---|---|
| `PRAGMA integrity_check` | `_base.py:335`, `cli.py:1804` | Database integrity validation |
| `PRAGMA wal_checkpoint(PASSIVE)` | `_base.py:347`, `_base.py:508`, `_base.py:711` | Non-blocking WAL flush to database file |
| `PRAGMA wal_checkpoint(TRUNCATE)` | `_base.py:488` | Full WAL flush and truncation |
| `PRAGMA query_only=ON` | `cli.py:2399` | Read-only safety guard in the `omega doctor` command |
| `PRAGMA busy_timeout=5000` | `cli.py:2398`, `cli.py:2493` | Shorter 5-second timeout for CLI doctor and FTS commands |

#### llm_usage.db PRAGMAs (set in `usage_tracker.py:60`)

| PRAGMA | Value | Notes |
|---|---|---|
| `journal_mode` | `WAL` | Only PRAGMA set on this separate connection |

---

### 1.7 — Schema Versioning and Migration History

- **Versioning mechanism:** Application table `schema_version` (not `PRAGMA user_version`). Single row.
- **Current version:** `14` (`SCHEMA_VERSION = 14` at `schema.py:12`).
- **Migration runner:** `init_schema()` in `schema.py`, called by `_init_schema_fn(self._conn, self._vec_available, EMBEDDING_DIM)` in `_base.py:444` on connection init.
- **Runner logic:** Reads `schema_version.version`, compares to `SCHEMA_VERSION`, applies sequential migration blocks.

**Migration history (v1→v14):**

| From → To | Schema changes |
|---|---|
| v1 | Initial schema: `memories` (8 columns), `edges`, `schema_version` |
| v1 → v2 | ADD `session_id` to `memories` |
| v2 → v3 | ADD `event_type`, `project` to `memories` |
| v3 → v4 | ADD `content_hash` to `memories` |
| v4 → v5 | ADD `priority`, `referenced_date` to `memories`; CREATE `forgetting_log` |
| v5 → v6 | ADD `entity_id`, `agent_type` to `memories`; CREATE `entity_index` (without DEFAULT on first_seen/last_updated) |
| v6 → v7 | (details not fully captured in investigations) |
| v7 → v8 | ADD `canonical_hash`, `end_date` to `memories` |
| v8 → v9 | ADD `extracted_keywords` to `memories` |
| v9 → v10 | ADD `retrieval_count`, `memory_type` to `memories`; CREATE `maintenance_dlq` |
| v10 → v11 | ADD `valid_from`, `valid_until`, `derived_from`, `source_uri`, `status` to `memories` |
| v11 → v12 | (details not fully captured in investigations) |
| v12 → v13 | (details not fully captured in investigations) |
| v13 → v14 | UPDATE `memories.status` to `'superseded'` for previously-superseded records (`schema.py:284–288`) |

---

## Phase 2 — Feature Analysis

### 2.1 — Search Capabilities

| Capability | Status | Evidence |
|---|---|---|
| Full-text search (FTS5) | **Schema-defined and application-used** | `memories_fts` virtual table (`schema.py:376`); MATCH queries in `_search.py:108` |
| BM25 ranking (FTS5 built-in) | **Schema-defined** | FTS5 module exposes `rank` column natively; used in `ORDER BY f.rank` at `_search.py:105` |
| Vector / semantic search | **Schema-defined and application-used** | `memories_vec` virtual table (`schema.py:366`); KNN query at `_search.py:36` |
| Vector distance metric | **Schema-defined** | `distance_metric=cosine` in `memories_vec` DDL (`schema.py:367`) |
| Hybrid search (FTS5 + vector combined) | **Absent from schema** | No view, index, or trigger combines them. Intersection done in application space. |
| Exact column match filtering | **Schema-defined and application-used** | Indices on `project`, `session_id`, `event_type`, `status`, `content_hash`, `canonical_hash` |
| Date / time range filtering | **Schema-defined and application-used** | Indices on `created_at`, `referenced_date`, `valid_from`, `valid_until`, `last_accessed` |
| Tag or label filtering | **Absent from schema** | `tags` parsed dynamically from `metadata` JSON blob; no normalized table, no expression index |
| JSON field filtering | **Absent from schema** | No generated columns or expression indices on `metadata` fields |
| Multi-project scoping | **Schema-defined and application-used** | `project` column and `idx_memories_project` |
| Soft-delete / lifecycle filtering | **Schema-defined and application-used** | `status` column (default `'active'`) and `idx_memories_status` |

---

### 2.2 — Memory Identity and Lifecycle

1. **Stable IDs:** `memories.node_id` (`TEXT UNIQUE NOT NULL`) — public stable identifier. `memories.id` is the internal rowid alias used for FTS and vec rowid mapping.
2. **Soft delete:** `memories.status` (`TEXT DEFAULT 'active'`) — lifecycle states set by application.
3. **Known lifecycle states:** `'active'` (default), `'superseded'` (confirmed in migration v13→v14 and `mark_superseded()`).
4. **Timestamps:** `created_at` (NOT NULL, no DEFAULT — application must supply), `last_accessed` (nullable), `valid_from` / `valid_until` (bi-temporal window, nullable), `edges.created_at` (NOT NULL, has DEFAULT `datetime('now')`).
5. **Immutability:** Absent. No triggers, constraints, or schema mechanisms enforce write-once behavior on any column.
6. **TTL-based expiry:** `ttl_seconds` column; expiry computed as `datetime(created_at, '+' || ttl_seconds || ' seconds')` in SQL.

---

### 2.3 — Relationships and Graph

1. **Edge table:** `edges` (§1.1 Table 3).
2. **Edge types:** Free-form string — no CHECK constraint or FK to an enumeration. Six values confirmed in application code (see §1.1 Table 3).
3. **Edge weight:** `REAL DEFAULT 1.0` — relationship strength; unconstrained.
4. **Directionality:** Directed (`source_id` → `target_id`). Both directions checked in traversal (`get_related_chain()` queries both columns).
5. **Self-referential edges:** Allowed — no `CHECK (source_id != target_id)` constraint exists.
6. **Graph depth limit:** None in schema; enforced in Python code only.
7. **Duplicate prevention:** `UNIQUE(source_id, target_id, edge_type)` — only one edge of each type between any pair.

---

### 2.4 — Embedding Storage

1. **Storage location:** `memories_vec.embedding` (separate virtual table).
2. **Type:** `float` array.
3. **Dimensionality:** 384 (default; determined at runtime by `get_embedding_dim()`; bge-small-en-v1.5 model).
4. **Distance metric:** Cosine.
5. **Nullability:** No explicit `NOT NULL` on the vec column. Missing embeddings are represented by the absence of a row in `memories_vec`, not a NULL value. This means embedding coverage is not 100% guaranteed per memory.
6. **Separation:** Embeddings are in `memories_vec`, linked via `rowid = memories.id`. No FK enforces this linkage.

---

### 2.5 — Metadata and Extensibility

1. **JSON column:** `memories.metadata TEXT` — raw text representing a JSON dictionary. Parsed Python-side.
2. **JSON fields indexed:** Absent. No generated columns or expression indices exist on metadata sub-fields.
3. **`event_type` constraint:** None. Free-form string accepted.
4. **`project` constraint:** None. Free-form string accepted.
5. **Tag storage:** `tags` are stored as a JSON array under the `"tags"` key inside `metadata`. They are parsed at `_query.py:815` and `server/handlers.py:268`. No normalized tag table exists.
6. **`updated_at`:** Stored as JSON key inside `metadata`; read at `server/handlers.py:263`. Not a schema column.
7. **Denormalization progression:** Fields originally stored only in `metadata` JSON were progressively promoted to dedicated columns (`session_id`, `event_type`, `project`, `priority`, `entity_id`). The `metadata` JSON blob still carries these same fields in many cases, creating duplication that can drift (see §4.7).

---

### 2.6 — Derivable Capabilities (SQL-ready)

#### Derivable 1: Memory Age

```sql
SELECT node_id, julianday('now') - julianday(created_at) AS age_days
FROM memories
ORDER BY age_days DESC;
```

**Note:** `created_at` is `TEXT NOT NULL` but has no CHECK constraint for ISO8601 format. Malformed values will produce NULL results.

**Currently used:** Yes — in `get_oldest_accessed_since()` at `_search.py:655`.

---

#### Derivable 2: Time Since Last Access

```sql
SELECT node_id, julianday('now') - julianday(last_accessed) AS days_since_access
FROM memories
WHERE last_accessed IS NOT NULL
ORDER BY days_since_access DESC;
```

**Currently used:** Computed in Python via `_compute_decay_factor()`, not in SQL.

---

#### Derivable 3: Effective TTL Expiry Time

```sql
SELECT node_id, datetime(created_at, '+' || ttl_seconds || ' seconds') AS expires_at
FROM memories
WHERE ttl_seconds IS NOT NULL;
```

**Currently used:** Yes — in TTL expiry check SQL.

---

#### Derivable 4: Degree Centrality

```sql
SELECT node_id, COUNT(*) AS degree
FROM (
    SELECT source_id AS node_id FROM edges
    UNION ALL
    SELECT target_id AS node_id FROM edges
)
GROUP BY node_id
ORDER BY degree DESC;
```

**Currently used:** Not computed or cached anywhere. Could inform graph density metrics.

**Limitation:** Duplicate reciprocal edges count separately; only `(source_id, target_id, edge_type)` is unique.

---

#### Derivable 5: Orphaned Edge Detection

```sql
SELECT e.id, e.source_id, e.target_id
FROM edges e
LEFT JOIN memories m1 ON e.source_id = m1.node_id
LEFT JOIN memories m2 ON e.target_id = m2.node_id
WHERE m1.node_id IS NULL OR m2.node_id IS NULL;
```

**Limitation:** No FK constraint exists; orphaned edges are possible after memory deletion if application-side cleanup fails. Orphan cleanup runs in consolidation phase 3 (`_maintenance.py:333–343`).

---

#### Derivable 6: Embedding Coverage Rate

```sql
SELECT
    COUNT(v.rowid) * 1.0 / NULLIF(COUNT(m.id), 0) AS embedding_coverage_pct
FROM memories m
LEFT JOIN memories_vec v ON v.rowid = m.id;
```

**Limitation:** `memories_vec` is only created when `vec_available` is True.

---

#### Derivable 7: Duplicate Content Detection

```sql
SELECT content_hash, COUNT(*) AS duplicate_count
FROM memories
WHERE content_hash IS NOT NULL
GROUP BY content_hash
HAVING COUNT(*) > 1;
```

**Limitation:** No UNIQUE constraint on `content_hash` or `canonical_hash`.

---

#### Derivable 8: Supersession Chains (Recursive)

```sql
WITH RECURSIVE chain(source_id, target_id, depth) AS (
    SELECT source_id, target_id, 1
    FROM edges
    WHERE edge_type = 'supersedes' AND source_id = ?
    UNION ALL
    SELECT e.source_id, e.target_id, chain.depth + 1
    FROM edges e
    JOIN chain ON e.source_id = chain.target_id
    WHERE e.edge_type = 'supersedes'
)
SELECT * FROM chain;
```

**Limitation:** `edge_type` is free-form; schema does not enforce the `'supersedes'` string. Depth is unbounded in schema.

---

## Phase 3 — Application Code Cross-Reference

### 3.1 — `memories` Column Usage Matrix

| Column | Written by | Filtered in SQL? | Indexed | Decision notes |
|---|---|---|---|---|
| `id` | AUTO | `WHERE id IN (?)`, `WHERE id = ?` | PK | Active |
| `node_id` | `store()` | `WHERE node_id = ?` | UNIQUE + idx | Active |
| `content` | `store()`, `update_node()` | FTS5 MATCH | — | Active via FTS |
| `metadata` | `store()`, `update_node()`, contradiction/feedback | `json_extract()` in decay/hot-cache | — | Active; also contains shadow copies of denormalized fields |
| `created_at` | `store()` | `WHERE created_at >= ?`, `ORDER BY` | idx | Active |
| `last_accessed` | `get_node()` | `ORDER BY COALESCE(last_accessed, created_at)` | idx | Active |
| `access_count` | `store()` (dedup bump), `get_node()` | `WHERE access_count = 0`, `ORDER BY access_count DESC` | compound idx | Active |
| `ttl_seconds` | `store()` | `WHERE ttl_seconds IS NOT NULL AND datetime(...)` | idx | Active |
| `session_id` | `store()`, `update_node()` | `WHERE session_id = ?` | idx | Active |
| `event_type` | `store()`, `update_node()` | `WHERE event_type = ?` | idx + compound | Active |
| `project` | `store()`, `update_node()` | `WHERE project = ?` | idx | Active |
| `content_hash` | `store()`, `update_node()` | `WHERE content_hash = ?` | idx | Active |
| `priority` | `store()` | `WHERE COALESCE(priority, 3) < 5` | idx | Active |
| `referenced_date` | `store()` | `WHERE referenced_date BETWEEN ? AND ?` | idx | Active |
| `entity_id` | `store()`, merge | `WHERE entity_id = ?` | idx | Active |
| `agent_type` | `store()` | Never in SQL; Python-only filter | idx | **WASTED INDEX** |
| `canonical_hash` | `store()`, `update_node()` | `WHERE canonical_hash = ?` | idx | Active |
| `end_date` | Never written | Never read | idx | **DEAD COLUMN + WASTED INDEX** |
| `extracted_keywords` | `store()` | Never (used in FTS trigger only) | — | Active (indirectly via FTS) |
| `retrieval_count` | Never written | Never read | — | **DEAD COLUMN** |
| `memory_type` | `store()` | Never in SQL | idx | **WASTED INDEX** |
| `valid_from` | `store()` | `WHERE valid_from > ?` | idx | Active |
| `valid_until` | `mark_superseded()` | `WHERE valid_until < ?` | idx | Active |
| `derived_from` | `store()` | Never in SQL (edges table used for traversal) | idx | **WASTED INDEX; column duplicated as edge** |
| `source_uri` | `store()` | Never in SQL | idx | **WASTED INDEX** |
| `status` | `store()`, `mark_superseded()` | `WHERE status = ?` | idx | Active |

### 3.2 — Locking Model

| Mechanism | Scope | Source |
|---|---|---|
| `threading.RLock` (`self._lock`) | Python-level write serialization across threads | `_base.py` |
| `threading.Lock` (`self._cache_lock`) | In-process hot-cache access serialization | `_base.py` |
| SQLite WAL mode | Multi-process concurrent reads without blocking writes | `PRAGMA journal_mode=WAL` |
| `PRAGMA busy_timeout=30000` | 30-second wait for write locks under multi-process contention | `_base.py:424` |
| `BEGIN EXCLUSIVE` | Atomic import (clear + insert) to prevent partial reads | `_maintenance.py:1360` |

---

## Phase 4 — Gap Analysis

### 4.1 — Dead Columns (never written or read by any code path)

| Column | Table | Added in | Superseded by | Recommendation |
|---|---|---|---|---|
| `end_date` | `memories` | v8 | `valid_until` (added v11) | Safe to DROP in a future migration. Also drop index `idx_memories_end_date`. |
| `retrieval_count` | `memories` | v10 | `access_count` (serves same purpose, actively used) | Safe to DROP or repurpose. No index exists; no migration cost beyond ALTER TABLE. |

### 4.2 — Written-But-Never-SQL-Queried Columns

These columns are written by the application and returned in result sets, but are never used in SQL `WHERE`, `ORDER BY`, or `GROUP BY` clauses. Their indices are pure overhead.

| Column | Table | What happens | Index waste? | Recommendation |
|---|---|---|---|---|
| `memory_type` | `memories` | Set in `store()` via `_MEMORY_TYPE_MAP` to values like `'semantic'`, `'procedural'`, `'episodic'`. Never in any SQL filter or sort. | Yes — `idx_memories_memory_type` | Drop the index. Retain the column if the value may be used in future features. |
| `source_uri` | `memories` | Written in `store()`. Returned in `get_node()` result set. No SQL `WHERE` ever references it. | Yes — `idx_memories_source_uri` | Drop the index. Column may be useful for provenance display. |
| `derived_from` | `memories` | Written in `store()` as a column AND as an `edges` row with `edge_type='derived_from'`. Column value returned in `get_node()` but graph traversal uses `edges` only. | Yes — `idx_memories_derived_from` | Drop the index. Decide whether column or edge is canonical; remove duplication. |
| `agent_type` | `memories` | Written in `store()`. Checked in `_query_phase_boost()` Python code but never used in a SQL `WHERE` clause. | Yes — `idx_memories_agent_type` | Drop the index. If SQL filtering is ever needed, the column can be re-indexed then. |

### 4.3 — Schema-Defined But Application-Unused Tables

| Table | Status detail | Interpretation |
|---|---|---|
| `maintenance_dlq` | Never read, written, or used outside of doctor row counts | Incomplete dead-letter queue system. No producer or consumer is wired up. |
| `memory_clusters` | Zero SELECT/INSERT/UPDATE/DELETE in open-core | Reserved for Pro-tier pattern learner (`omega_platform`). |
| `thompson_arms` | Import guard fails silently; no code path reaches it | Reserved for Pro-tier multi-arm bandit intent router. Dead in open-core. |
| `entity_index` | Helper methods exist in `_maintenance.py` but are never called | Future-reserved entity registry. One-time migration (`migrate_to_sqlite.py`) writes to it; no runtime path does. |
| `cloud_delete_queue` | Written (INSERT) but **never read or drained** | Incomplete cloud sync. Queue grows indefinitely. |

### 4.4 — Index Waste Summary

Five indices exist on columns that are never used in any SQL `WHERE`, `ORDER BY`, or `GROUP BY`:

| Index | Column | Reason wasted |
|---|---|---|
| `idx_memories_end_date` | `end_date` | Column is dead (never written or read) |
| `idx_memories_memory_type` | `memory_type` | Column written but never SQL-queried |
| `idx_memories_source_uri` | `source_uri` | Column written but never SQL-filtered |
| `idx_memories_derived_from` | `derived_from` | Column written but edge traversal used instead; column never SQL-filtered |
| `idx_memories_agent_type` | `agent_type` | Filtering done in Python only, not SQL |

**Impact:** Each of these 5 indices adds write amplification to every `INSERT` and `UPDATE` on `memories`, including the critical hot path in `store()`. They contribute no query performance benefit.

### 4.5 — Foreign Key Gaps

`PRAGMA foreign_keys=ON` is set in `_base.py:426` — **but no FK constraints are declared in any `CREATE TABLE` statement.** The PRAGMA has no effect.

| Missing FK | From | → To | Risk |
|---|---|---|---|
| edges → memories | `edges.source_id` / `edges.target_id` | `memories.node_id` | Orphaned edges accumulate when memories are deleted without application-side cleanup. Consolidation phase 3 handles this, but only periodically. |
| memories_vec → memories | `memories_vec.rowid` | `memories.id` | Orphaned vec rows if a memory is deleted without its vec row. Backfill and orphan cleanup (`_maintenance.py:348–365`) compensate, but it's application-managed. |
| cloud_delete_queue → memories | `cloud_delete_queue.local_id` | `memories.id` | Queue entries can reference deleted memories with no integrity enforcement. Additionally: `local_id` is declared `INTEGER`, meaning it tracks `memories.id` — the `AUTOINCREMENT` rowid — **not** `memories.node_id` (the stable `TEXT` public identifier). Any future cloud-sync consumer draining this queue will couple to internal rowids rather than stable public IDs. If the database is rebuilt from a backup or migrated to a new file, `AUTOINCREMENT` counters reset and old queue entries whose `local_id` values are reassigned to new memories would silently reference the wrong records. The fix is to change `local_id` to a `TEXT` column referencing `memories.node_id`. |

### 4.6 — Application-Assumed But Schema-Unconfirmed Fields

These are **not** missing schema columns — they intentionally live inside the `metadata` JSON blob. The risk is that they are invisible to SQL queries and can drift from the denormalized columns.

| Field | Accessed at | Schema status | Source |
|---|---|---|---|
| `tags` | `_query.py:815`, `server/handlers.py:268` | Absent as column; stored as JSON array under `metadata["tags"]` | Inside `memories.metadata` TEXT blob |
| `updated_at` | `server/handlers.py:263` | Absent as column; stored as JSON key under `metadata["updated_at"]` | Inside `memories.metadata` TEXT blob |

### 4.7 — Metadata JSON vs Denormalized Column Drift

The `memories` table exhibits progressive denormalization: fields originally stored only in `metadata` JSON were later promoted to dedicated columns (`session_id`, `event_type`, `project`, `priority`, `entity_id`). However, the `metadata` JSON blob often still carries these same fields.

**Risk:** The JSON copy and the column copy can drift independently if update paths are inconsistent. Application code generally reads from denormalized columns for SQL queries but parses `metadata` JSON for Python-side access. An update path that modifies the column but not the JSON (or vice versa) produces a silent inconsistency.

**Currently affected pairs:** `session_id`, `event_type`, `project`, `priority`, `entity_id` all exist both as columns and potentially inside `metadata`.

### 4.8 — Missing Schema Constraints

| Column | Missing | Risk |
|---|---|---|
| `memories.event_type` | FK to enumeration or CHECK constraint | NULL or typo values allowed; application must sanitize manually |
| `edges.edge_type` | FK or CHECK constraint | Unstructured types can break graph traversal queries that filter by type string |
| `memories.content_hash` | No UNIQUE constraint | Duplicate hashes possible; dedup relies entirely on application logic |
| `memories.canonical_hash` | No UNIQUE constraint | Same risk as content_hash |
| `entity_index.first_seen` / `last_updated` | In migration DDL: `NOT NULL` without DEFAULT | Databases upgraded through migration v5→v6 (not fresh installs) may fail INSERTs that don't explicitly supply these values |

### 4.9 — Capabilities That Would Require Schema Changes

#### Multi-Tenant / Multi-Workspace Isolation

**What's missing:** A `tenant_id` or `workspace_id` scoping column on `memories` and `edges`.

```sql
ALTER TABLE memories ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default';
ALTER TABLE edges ADD COLUMN tenant_id TEXT NOT NULL DEFAULT 'default';
CREATE INDEX idx_memories_tenant ON memories(tenant_id);
```

**Existing anchor:** `memories.project` provides per-project scoping but not strict tenant isolation.

---

#### Schema-Driven Tag Retrieval

**What's missing:** Normalized tag storage. Currently `tags` are unindexed JSON.

```sql
CREATE TABLE memory_tags (
    memory_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY (memory_id, tag),
    FOREIGN KEY (memory_id) REFERENCES memories(node_id) ON DELETE CASCADE
);
CREATE INDEX idx_memory_tags_tag ON memory_tags(tag);
```

**Existing anchor:** `memories.node_id` as FK reference.

---

#### FK Cascade Enforcement for Edges

**What's missing:** Declared FK constraints. Since SQLite does not support `ALTER TABLE DROP CONSTRAINT`, the `edges` table must be recreated:

```sql
CREATE TABLE edges_new (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL REFERENCES memories(node_id) ON DELETE CASCADE,
    target_id TEXT NOT NULL REFERENCES memories(node_id) ON DELETE CASCADE,
    edge_type TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_id, target_id, edge_type)
);
INSERT INTO edges_new SELECT * FROM edges;
DROP TABLE edges;
ALTER TABLE edges_new RENAME TO edges;
```

---

#### Project Normalization

**What's missing:** A canonical `projects` table to prevent orphaned project references.

```sql
CREATE TABLE projects (
    project TEXT PRIMARY KEY
);
```

Then add a FK: `memories.project REFERENCES projects(project)`.

---

## Appendix A — Full DDL (verbatim, omega.db)

```sql
-- 1. schema_version
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

-- 2. memories
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT UNIQUE NOT NULL,
    content TEXT NOT NULL,
    metadata TEXT,
    created_at TEXT NOT NULL,
    last_accessed TEXT,
    access_count INTEGER DEFAULT 0,
    ttl_seconds INTEGER,
    session_id TEXT,
    event_type TEXT,
    project TEXT,
    content_hash TEXT,
    priority INTEGER DEFAULT 3,
    referenced_date TEXT,
    entity_id TEXT,
    agent_type TEXT,
    canonical_hash TEXT,
    end_date TEXT,
    extracted_keywords TEXT,
    retrieval_count INTEGER DEFAULT 0,
    memory_type TEXT DEFAULT 'semantic',
    valid_from TEXT,
    valid_until TEXT,
    derived_from TEXT,
    source_uri TEXT,
    status TEXT DEFAULT 'active'
);

-- 3. memories_vec (only if vec_available)
CREATE VIRTUAL TABLE IF NOT EXISTS memories_vec
USING vec0(embedding float[384] distance_metric=cosine);

-- 4. memories_fts (only if fts5 available)
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
USING fts5(content, content='memories', content_rowid='id');

-- 5. edges
CREATE TABLE IF NOT EXISTS edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    edge_type TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    metadata TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source_id, target_id, edge_type)
);

-- 6. forgetting_log
CREATE TABLE IF NOT EXISTS forgetting_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    content_preview TEXT,
    event_type TEXT,
    reason TEXT NOT NULL,
    deleted_at TEXT NOT NULL,
    metadata TEXT
);

-- 7. cloud_delete_queue
CREATE TABLE IF NOT EXISTS cloud_delete_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    local_id INTEGER NOT NULL,
    deleted_at TEXT NOT NULL
);

-- 8. entity_index
CREATE TABLE IF NOT EXISTS entity_index (
    entity_name TEXT NOT NULL PRIMARY KEY,
    entity_type TEXT DEFAULT 'person',
    statement_count INTEGER DEFAULT 0,
    outcome_count INTEGER DEFAULT 0,
    contradiction_score REAL DEFAULT 0.0,
    follow_through_rate REAL DEFAULT 0.0,
    first_seen TEXT NOT NULL DEFAULT (datetime('now')),
    last_updated TEXT NOT NULL DEFAULT (datetime('now')),
    metadata TEXT
);

-- 9. memory_clusters
CREATE TABLE IF NOT EXISTS memory_clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cluster_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    member_count INTEGER NOT NULL,
    centroid BLOB,
    representative_keywords TEXT,
    representative_memory_ids TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    superseded INTEGER DEFAULT 0
);

-- 10. thompson_arms
CREATE TABLE IF NOT EXISTS thompson_arms (
    arm_id TEXT PRIMARY KEY,
    arm_type TEXT NOT NULL,
    alpha REAL DEFAULT 1.0,
    beta REAL DEFAULT 1.0,
    total_trials INTEGER DEFAULT 0,
    total_successes INTEGER DEFAULT 0,
    last_updated TEXT NOT NULL,
    context TEXT
);

-- 11. maintenance_dlq (created inside v9→v10 migration block)
CREATE TABLE IF NOT EXISTS maintenance_dlq (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stage_name TEXT NOT NULL,
    error_class TEXT NOT NULL DEFAULT 'transient',
    error_message TEXT,
    remediation_attempts INTEGER DEFAULT 0,
    max_remediation INTEGER DEFAULT 3,
    status TEXT NOT NULL DEFAULT 'pending',
    next_retry_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- FTS triggers (only if fts5 available)
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content)
    VALUES (new.id, new.content || ' ' || COALESCE(new.extracted_keywords, ''));
END;

CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content)
    VALUES ('delete', old.id, old.content || ' ' || COALESCE(old.extracted_keywords, ''));
END;

CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE OF content ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content)
    VALUES ('delete', old.id, old.content || ' ' || COALESCE(old.extracted_keywords, ''));
    INSERT INTO memories_fts(rowid, content)
    VALUES (new.id, new.content || ' ' || COALESCE(new.extracted_keywords, ''));
END;
```

---

## Appendix B — Full DDL (verbatim, llm_usage.db)

```sql
CREATE TABLE IF NOT EXISTS llm_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    tool_name TEXT NOT NULL,
    model TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'anthropic',
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0,
    cache_write_tokens INTEGER DEFAULT 0,
    estimated_cost_usd REAL DEFAULT 0.0,
    duration_ms INTEGER,
    project TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_llm_usage_session ON llm_usage(session_id);
CREATE INDEX IF NOT EXISTS idx_llm_usage_tool ON llm_usage(tool_name, created_at);
CREATE INDEX IF NOT EXISTS idx_llm_usage_created ON llm_usage(created_at);
```

---

## Appendix C — Summary Statistics

| Category | Count |
|---|---|
| Distinct databases | 2 (`omega.db`, `llm_usage.db`) |
| Regular tables in omega.db | 9 (`schema_version`, `memories`, `edges`, `forgetting_log`, `cloud_delete_queue`, `entity_index`, `memory_clusters`, `thompson_arms`, `maintenance_dlq`) |
| Virtual tables in omega.db | 2 (`memories_vec`, `memories_fts`) |
| Tables in llm_usage.db | 1 (`llm_usage`) |
| Triggers | 3 (`memories_ai`, `memories_ad`, `memories_au`) |
| Views | 0 |
| Total indices | 37 |
| Indices on memories | 21 (20 single-column + 1 compound) |
| **Wasted indices** | **5** (`idx_memories_end_date`, `idx_memories_memory_type`, `idx_memories_source_uri`, `idx_memories_derived_from`, `idx_memories_agent_type`) |
| Total columns in memories | 26 |
| **Dead columns** | **2** (`end_date`, `retrieval_count`) |
| **Written-but-never-SQL-queried columns** | **4** (`agent_type`, `memory_type`, `source_uri`, `derived_from`) |
| Schema-only tables (no runtime app code) | 4 (`maintenance_dlq`, `memory_clusters`, `thompson_arms`, `entity_index`) |
| Write-only tables (never read or drained) | 1 (`cloud_delete_queue`) |
| ↳ Combined (§4.3 "application-unused" table) | **5** — the two rows above together account for all 5 rows in §4.3; `cloud_delete_queue` is write-only, not schema-only, and is therefore counted separately |
| Current schema version | 14 |
| Schema migrations tracked | 14 (v1→v14) |
| Declared FK constraints | **0** |
| Active FK enforcement via PRAGMA | **0** (PRAGMA foreign_keys=ON set, but no FKs declared) |
