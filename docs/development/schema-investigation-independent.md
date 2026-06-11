# OMEGA Schema Investigation

**Investigated by:** Codex GPT-5 schema investigation session  
**Date:** 2026-06-12  
**Commit:** `d7c7590bf78439b9dda8625b845c6008061f31b7`  
**Files read:** 25 files (listed in Phase 0)  
**Tables found:** 10  
**Virtual tables found:** 2  
**Indices found:** 37  
**Triggers found:** 3  
**Views found:** 0  
**Schema-defined but application-unused columns:** 20  
**Application-assumed but schema-unconfirmed fields:** 3

## Phase 0: File Inventory

### Required Command Output

```text
src/omega/usage_tracker.py
src/omega/schema.py
src/omega/server/tool_schemas.py
src/omega/schema.py
src/omega/migrate_to_sqlite.py
src/omega/usage_tracker.py
src/omega/server/mcp_server.py
src/omega/cli.py
src/omega/sqlite_store/_base.py
```

No SQL files were returned by the required `find src/omega/ -name "*.sql" -o -name "*.sql.j2" -o -name "*.ddl"` command.

Distinct inventory files read:

- `src/omega/usage_tracker.py`
- `src/omega/schema.py`
- `src/omega/server/tool_schemas.py`
- `src/omega/migrate_to_sqlite.py`
- `src/omega/server/mcp_server.py`
- `src/omega/cli.py`
- `src/omega/sqlite_store/_base.py`

Additional application-usage files read for Phase 3:

- `src/omega/sqlite_store/_types.py`
- `src/omega/sqlite_store/_store.py`
- `src/omega/sqlite_store/_search.py`
- `src/omega/sqlite_store/_maintenance.py`
- `src/omega/sqlite_store/_query.py`
- `src/omega/bridge.py`
- `src/omega/server/handlers.py`
- `src/omega/obsidian_export.py`
- `src/omega/milestones.py`
- `src/omega/hooks/session_stop.py`
- `src/omega/reflect.py`
- `src/omega/integrations/crewai.py`
- `AGENTS.md`
- `docs/development/live-safe-development.md`
- `docs/development/community-tools-roadmap.md`
- `docs/development/iteration-1-retrieval-research.md`
- `docs/development/iteration-1-future-session-handoff.md`
- `skills/omega-memory/SKILL.md`

## Phase 1: Schema Topology

### 1.1 Tables

### Table: `llm_usage`

**Source:** `src/omega/usage_tracker.py` line 21

**DDL (verbatim):**

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
```

**Columns:**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Defined at `src/omega/usage_tracker.py:22`. |
| `session_id` | TEXT | None | Defined at `src/omega/usage_tracker.py:23`. |
| `tool_name` | TEXT | NOT NULL | Defined at `src/omega/usage_tracker.py:24`. |
| `model` | TEXT | NOT NULL | Defined at `src/omega/usage_tracker.py:25`. |
| `provider` | TEXT | NOT NULL, DEFAULT `'anthropic'` | Defined at `src/omega/usage_tracker.py:26`. |
| `input_tokens` | INTEGER | DEFAULT `0` | Defined at `src/omega/usage_tracker.py:27`. |
| `output_tokens` | INTEGER | DEFAULT `0` | Defined at `src/omega/usage_tracker.py:28`. |
| `cache_read_tokens` | INTEGER | DEFAULT `0` | Defined at `src/omega/usage_tracker.py:29`. |
| `cache_write_tokens` | INTEGER | DEFAULT `0` | Defined at `src/omega/usage_tracker.py:30`. |
| `estimated_cost_usd` | REAL | DEFAULT `0.0` | Defined at `src/omega/usage_tracker.py:31`. |
| `duration_ms` | INTEGER | None | Defined at `src/omega/usage_tracker.py:32`. |
| `project` | TEXT | None | Defined at `src/omega/usage_tracker.py:33`. |
| `created_at` | TEXT | NOT NULL | Defined at `src/omega/usage_tracker.py:34`. |

**Implicit SQLite fields:**
- rowid: Implied because the DDL has no `WITHOUT ROWID`; source anchor is the complete table DDL at `src/omega/usage_tracker.py:21`.

**Schema-level observations:** `provider`, token counters, and `estimated_cost_usd` have defaults; `created_at` has no DEFAULT clause. Evidence: `src/omega/usage_tracker.py:26`, `src/omega/usage_tracker.py:27`, `src/omega/usage_tracker.py:28`, `src/omega/usage_tracker.py:29`, `src/omega/usage_tracker.py:30`, `src/omega/usage_tracker.py:31`, `src/omega/usage_tracker.py:34`.

### Table: `schema_version`

**Source:** `src/omega/schema.py` line 39

**DDL (verbatim):**

```sql
CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
)
```

**Columns:**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `version` | INTEGER | NOT NULL | Defined at `src/omega/schema.py:40`. |

**Implicit SQLite fields:**
- rowid: Implied because the DDL has no `WITHOUT ROWID`; source anchor is the complete table DDL at `src/omega/schema.py:39`.

**Schema-level observations:** The table has one integer column and no PRIMARY KEY or UNIQUE constraint. Evidence: `src/omega/schema.py:39`.

### Table: `forgetting_log` (migration v5 to v6)

**Source:** `src/omega/schema.py` line 108

**DDL (verbatim):**

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

**Columns:**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Defined at `src/omega/schema.py:109`. |
| `node_id` | TEXT | NOT NULL | Defined at `src/omega/schema.py:110`. |
| `content_preview` | TEXT | None | Defined at `src/omega/schema.py:111`. |
| `event_type` | TEXT | None | Defined at `src/omega/schema.py:112`. |
| `reason` | TEXT | NOT NULL | Defined at `src/omega/schema.py:113`. |
| `deleted_at` | TEXT | NOT NULL | Defined at `src/omega/schema.py:114`. |
| `metadata` | TEXT | None | Defined at `src/omega/schema.py:115`. |

**Implicit SQLite fields:**
- rowid: Implied through `id INTEGER PRIMARY KEY AUTOINCREMENT`; source anchor is `src/omega/schema.py:109`.

**Schema-level observations:** The migration DDL and current DDL define the same columns. Current DDL is anchored at `src/omega/schema.py:405`.

### Table: `entity_index` (migration v6 to v7)

**Source:** `src/omega/schema.py` line 128

**DDL (verbatim):**

```sql
CREATE TABLE IF NOT EXISTS entity_index (
    entity_name TEXT NOT NULL PRIMARY KEY,
    entity_type TEXT DEFAULT 'person',
    statement_count INTEGER DEFAULT 0,
    outcome_count INTEGER DEFAULT 0,
    contradiction_score REAL DEFAULT 0.0,
    follow_through_rate REAL DEFAULT 0.0,
    first_seen TEXT NOT NULL,
    last_updated TEXT NOT NULL,
    metadata TEXT
)
```

**Columns:**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `entity_name` | TEXT | NOT NULL, PRIMARY KEY | Defined at `src/omega/schema.py:129`. |
| `entity_type` | TEXT | DEFAULT `'person'` | Defined at `src/omega/schema.py:130`. |
| `statement_count` | INTEGER | DEFAULT `0` | Defined at `src/omega/schema.py:131`. |
| `outcome_count` | INTEGER | DEFAULT `0` | Defined at `src/omega/schema.py:132`. |
| `contradiction_score` | REAL | DEFAULT `0.0` | Defined at `src/omega/schema.py:133`. |
| `follow_through_rate` | REAL | DEFAULT `0.0` | Defined at `src/omega/schema.py:134`. |
| `first_seen` | TEXT | NOT NULL | Defined at `src/omega/schema.py:135`. |
| `last_updated` | TEXT | NOT NULL | Defined at `src/omega/schema.py:136`. |
| `metadata` | TEXT | None | Defined at `src/omega/schema.py:137`. |

**Implicit SQLite fields:**
- rowid: Implied because the DDL has no `WITHOUT ROWID`; source anchor is the complete table DDL at `src/omega/schema.py:128`.

**Schema-level observations:** Migration DDL has NOT NULL `first_seen` and `last_updated` without DEFAULT clauses. Evidence: `src/omega/schema.py:135`, `src/omega/schema.py:136`.

### Table: `maintenance_dlq`

**Source:** `src/omega/schema.py` line 181

**DDL (verbatim):**

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

**Columns:**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Defined at `src/omega/schema.py:182`. |
| `stage_name` | TEXT | NOT NULL | Defined at `src/omega/schema.py:183`. |
| `error_class` | TEXT | NOT NULL, DEFAULT `'transient'` | Defined at `src/omega/schema.py:184`. |
| `error_message` | TEXT | None | Defined at `src/omega/schema.py:185`. |
| `remediation_attempts` | INTEGER | DEFAULT `0` | Defined at `src/omega/schema.py:186`. |
| `max_remediation` | INTEGER | DEFAULT `3` | Defined at `src/omega/schema.py:187`. |
| `status` | TEXT | NOT NULL, DEFAULT `'pending'` | Defined at `src/omega/schema.py:188`. |
| `next_retry_at` | TEXT | None | Defined at `src/omega/schema.py:189`. |
| `created_at` | TEXT | NOT NULL | Defined at `src/omega/schema.py:190`. |
| `updated_at` | TEXT | NOT NULL | Defined at `src/omega/schema.py:191`. |

**Implicit SQLite fields:**
- rowid: Implied through `id INTEGER PRIMARY KEY AUTOINCREMENT`; source anchor is `src/omega/schema.py:182`.

**Schema-level observations:** This table is defined only in the v9 to v10 migration block. Evidence: `src/omega/schema.py:177`.

### Table: `memories`

**Source:** `src/omega/schema.py` line 297

**DDL (verbatim):**

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

**Columns:**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Defined at `src/omega/schema.py:298`. |
| `node_id` | TEXT | UNIQUE, NOT NULL | Defined at `src/omega/schema.py:299`. |
| `content` | TEXT | NOT NULL | Defined at `src/omega/schema.py:300`. |
| `metadata` | TEXT | None | Defined at `src/omega/schema.py:301`. |
| `created_at` | TEXT | NOT NULL | Defined at `src/omega/schema.py:302`. |
| `last_accessed` | TEXT | None | Defined at `src/omega/schema.py:303`. |
| `access_count` | INTEGER | DEFAULT `0` | Defined at `src/omega/schema.py:304`. |
| `ttl_seconds` | INTEGER | None | Defined at `src/omega/schema.py:305`. |
| `session_id` | TEXT | None | Defined at `src/omega/schema.py:306`. |
| `event_type` | TEXT | None | Defined at `src/omega/schema.py:307`. |
| `project` | TEXT | None | Defined at `src/omega/schema.py:308`. |
| `content_hash` | TEXT | None | Defined at `src/omega/schema.py:309`. |
| `priority` | INTEGER | DEFAULT `3` | Defined at `src/omega/schema.py:310`. |
| `referenced_date` | TEXT | None | Defined at `src/omega/schema.py:311`. |
| `entity_id` | TEXT | None | Defined at `src/omega/schema.py:312`. |
| `agent_type` | TEXT | None | Defined at `src/omega/schema.py:313`. |
| `canonical_hash` | TEXT | None | Defined at `src/omega/schema.py:314`. |
| `end_date` | TEXT | None | Defined at `src/omega/schema.py:315`. |
| `extracted_keywords` | TEXT | None | Defined at `src/omega/schema.py:316`. |
| `retrieval_count` | INTEGER | DEFAULT `0` | Defined at `src/omega/schema.py:317`. |
| `memory_type` | TEXT | DEFAULT `'semantic'` | Defined at `src/omega/schema.py:318`. |
| `valid_from` | TEXT | None | Defined at `src/omega/schema.py:319`. |
| `valid_until` | TEXT | None | Defined at `src/omega/schema.py:320`. |
| `derived_from` | TEXT | None | Defined at `src/omega/schema.py:321`. |
| `source_uri` | TEXT | None | Defined at `src/omega/schema.py:322`. |
| `status` | TEXT | DEFAULT `'active'` | Defined at `src/omega/schema.py:323`. |

**Implicit SQLite fields:**
- rowid: Implied through `id INTEGER PRIMARY KEY AUTOINCREMENT`; source anchor is `src/omega/schema.py:298`.

**Schema-level observations:** `node_id` is the only schema-defined UNIQUE memory column; no CHECK constraints or FOREIGN KEY constraints are present in this DDL. Evidence: `src/omega/schema.py:299`, `src/omega/schema.py:297`.

### Table: `edges`

**Source:** `src/omega/schema.py` line 386

**DDL (verbatim):**

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

**Columns:**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Defined at `src/omega/schema.py:387`. |
| `source_id` | TEXT | NOT NULL | Defined at `src/omega/schema.py:388`. |
| `target_id` | TEXT | NOT NULL | Defined at `src/omega/schema.py:389`. |
| `edge_type` | TEXT | NOT NULL | Defined at `src/omega/schema.py:390`. |
| `weight` | REAL | DEFAULT `1.0` | Defined at `src/omega/schema.py:391`. |
| `metadata` | TEXT | None | Defined at `src/omega/schema.py:392`. |
| `created_at` | TEXT | NOT NULL, DEFAULT `(datetime('now'))` | Defined at `src/omega/schema.py:393`. |
| table constraint | n/a | UNIQUE(`source_id`, `target_id`, `edge_type`) | Defined at `src/omega/schema.py:394`. |

**Implicit SQLite fields:**
- rowid: Implied through `id INTEGER PRIMARY KEY AUTOINCREMENT`; source anchor is `src/omega/schema.py:387`.

**Schema-level observations:** The table contains no FOREIGN KEY clause linking `source_id` or `target_id` to `memories.node_id`. Evidence: complete DDL at `src/omega/schema.py:386`.

### Table: `forgetting_log` (current initialization)

**Source:** `src/omega/schema.py` line 405

**DDL (verbatim):**

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

**Columns:** Same as the migration v5 to v6 table definition, with source anchors at `src/omega/schema.py:406` through `src/omega/schema.py:412`.

**Implicit SQLite fields:**
- rowid: Implied through `id INTEGER PRIMARY KEY AUTOINCREMENT`; source anchor is `src/omega/schema.py:406`.

**Schema-level observations:** The current initialization DDL defines no UNIQUE table constraint; the unique index on `(node_id, reason)` is migration-defined at `src/omega/schema.py:259`.

### Table: `cloud_delete_queue`

**Source:** `src/omega/schema.py` line 420

**DDL (verbatim):**

```sql
CREATE TABLE IF NOT EXISTS cloud_delete_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    local_id INTEGER NOT NULL,
    deleted_at TEXT NOT NULL
)
```

**Columns:**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Defined at `src/omega/schema.py:421`. |
| `local_id` | INTEGER | NOT NULL | Defined at `src/omega/schema.py:422`. |
| `deleted_at` | TEXT | NOT NULL | Defined at `src/omega/schema.py:423`. |

**Implicit SQLite fields:**
- rowid: Implied through `id INTEGER PRIMARY KEY AUTOINCREMENT`; source anchor is `src/omega/schema.py:421`.

**Schema-level observations:** The DDL defines no index, foreign key, or uniqueness constraint for `local_id`. Evidence: `src/omega/schema.py:420`.

### Table: `entity_index` (current initialization)

**Source:** `src/omega/schema.py` line 429

**DDL (verbatim):**

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

**Columns:** Same as migration v6 to v7, except `first_seen` and `last_updated` include DEFAULT `(datetime('now'))` at `src/omega/schema.py:436` and `src/omega/schema.py:437`.

**Implicit SQLite fields:**
- rowid: Implied because the DDL has no `WITHOUT ROWID`; source anchor is the complete table DDL at `src/omega/schema.py:429`.

**Schema-level observations:** `entity_name` is the PRIMARY KEY. Evidence: `src/omega/schema.py:430`.

### Table: `memory_clusters`

**Source:** `src/omega/schema.py` line 483

**DDL (verbatim):**

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

**Columns:**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `id` | INTEGER | PRIMARY KEY AUTOINCREMENT | Defined at `src/omega/schema.py:484`. |
| `cluster_id` | INTEGER | NOT NULL | Defined at `src/omega/schema.py:485`. |
| `label` | TEXT | NOT NULL | Defined at `src/omega/schema.py:486`. |
| `member_count` | INTEGER | NOT NULL | Defined at `src/omega/schema.py:487`. |
| `centroid` | BLOB | None | Defined at `src/omega/schema.py:488`. |
| `representative_keywords` | TEXT | None | Defined at `src/omega/schema.py:489`. |
| `representative_memory_ids` | TEXT | None | Defined at `src/omega/schema.py:490`. |
| `created_at` | TEXT | NOT NULL | Defined at `src/omega/schema.py:491`. |
| `updated_at` | TEXT | NOT NULL | Defined at `src/omega/schema.py:492`. |
| `superseded` | INTEGER | DEFAULT `0` | Defined at `src/omega/schema.py:493`. |

**Implicit SQLite fields:**
- rowid: Implied through `id INTEGER PRIMARY KEY AUTOINCREMENT`; source anchor is `src/omega/schema.py:484`.

**Schema-level observations:** The table stores cluster centroid bytes in a BLOB column. Evidence: `src/omega/schema.py:488`.

### Table: `thompson_arms`

**Source:** `src/omega/schema.py` line 501

**DDL (verbatim):**

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

**Columns:**

| Column | Type | Constraints | Notes |
|---|---|---|---|
| `arm_id` | TEXT | PRIMARY KEY | Defined at `src/omega/schema.py:502`. |
| `arm_type` | TEXT | NOT NULL | Defined at `src/omega/schema.py:503`. |
| `alpha` | REAL | DEFAULT `1.0` | Defined at `src/omega/schema.py:504`. |
| `beta` | REAL | DEFAULT `1.0` | Defined at `src/omega/schema.py:505`. |
| `total_trials` | INTEGER | DEFAULT `0` | Defined at `src/omega/schema.py:506`. |
| `total_successes` | INTEGER | DEFAULT `0` | Defined at `src/omega/schema.py:507`. |
| `last_updated` | TEXT | NOT NULL | Defined at `src/omega/schema.py:508`. |
| `context` | TEXT | None | Defined at `src/omega/schema.py:509`. |

**Implicit SQLite fields:**
- rowid: Implied because the DDL has no `WITHOUT ROWID`; source anchor is the complete table DDL at `src/omega/schema.py:501`.

**Schema-level observations:** The table has a text PRIMARY KEY and no CHECK constraints on `alpha`, `beta`, `total_trials`, or `total_successes`. Evidence: `src/omega/schema.py:501`.

### 1.2 Virtual Tables

### Virtual Table: `memories_vec`

**Source:** `src/omega/schema.py` line 366

**DDL (verbatim):**

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS memories_vec
USING vec0(embedding float[{embedding_dim}] distance_metric=cosine)
```

**Module:** `vec0`

**Module parameters (verbatim):**
- `embedding float[{embedding_dim}] distance_metric=cosine` at `src/omega/schema.py:367`.

**Implicit capabilities from module:** Unconfirmed — check sqlite-vec docs for `vec0`.

**Implicit fields:** Application-used KNN SQL reads `rowid` and `distance` from this table: `SELECT rowid, distance FROM memories_vec WHERE embedding MATCH ? AND k = ?` at `src/omega/sqlite_store/_search.py:36`. The module guarantee for `distance` is Unconfirmed — check sqlite-vec docs for `vec0`.

### Virtual Table: `memories_fts`

**Source:** `src/omega/schema.py` line 376

**DDL (verbatim):**

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
USING fts5(content, content='memories', content_rowid='id')
```

**Module:** `sqlite_fts5`

**Module parameters (verbatim):**
- `content`
- `content='memories'`
- `content_rowid='id'`

**Implicit capabilities from module:** FTS5 exposes MATCH queries over `content`; application code uses `WHERE memories_fts MATCH ?` at `src/omega/sqlite_store/_search.py:108`. BM25/rank behavior is Unconfirmed — check SQLite docs for FTS5.

**Implicit fields:** Application code reads `f.rowid` and `f.rank` from the FTS5 alias: `JOIN memories m ON f.rowid = m.id` and `f.rank` at `src/omega/sqlite_store/_search.py:105` through `src/omega/sqlite_store/_search.py:119`.

### 1.3 Indices

### Index: `idx_llm_usage_session`

**Source:** `src/omega/usage_tracker.py` line 36

**DDL (verbatim):**

```sql
CREATE INDEX IF NOT EXISTS idx_llm_usage_session ON llm_usage(session_id);
```

**Type:** B-tree  
**Table:** `llm_usage`  
**Columns indexed:** `session_id`  
**Partial condition:** Absent  
**Query implication:** Can accelerate equality or range predicates on `llm_usage.session_id`; the index definition is anchored at `src/omega/usage_tracker.py:36`.

### Index: `idx_llm_usage_tool`

**Source:** `src/omega/usage_tracker.py` line 37

**DDL (verbatim):**

```sql
CREATE INDEX IF NOT EXISTS idx_llm_usage_tool ON llm_usage(tool_name, created_at);
```

**Type:** B-tree  
**Table:** `llm_usage`  
**Columns indexed:** `tool_name`, `created_at`  
**Partial condition:** Absent  
**Query implication:** Can accelerate predicates beginning with `tool_name`, and ordering/range patterns that also use `created_at`; source anchor is `src/omega/usage_tracker.py:37`.

### Index: `idx_llm_usage_created`

**Source:** `src/omega/usage_tracker.py` line 38

**DDL (verbatim):**

```sql
CREATE INDEX IF NOT EXISTS idx_llm_usage_created ON llm_usage(created_at);
```

**Type:** B-tree  
**Table:** `llm_usage`  
**Columns indexed:** `created_at`  
**Partial condition:** Absent  
**Query implication:** Can accelerate `WHERE created_at ...` predicates; source anchor is `src/omega/usage_tracker.py:38`.

### Index: `idx_memories_<col>` dynamic single-column family

**Source:** `src/omega/schema.py` line 352

**DDL (verbatim):**

```sql
CREATE INDEX IF NOT EXISTS idx_memories_{col}
ON memories({col})
```

**Type:** B-tree  
**Table:** `memories`  
**Columns indexed:** each of `node_id`, `event_type`, `session_id`, `project`, `created_at`, `content_hash`, `priority`, `referenced_date`, `entity_id`, `agent_type`, `canonical_hash`, `end_date`, `last_accessed`, `ttl_seconds`, `memory_type`, `valid_from`, `valid_until`, `derived_from`, `source_uri`, `status` from the hardcoded tuple at `src/omega/schema.py:328` through `src/omega/schema.py:348`.  
**Partial condition:** Absent  
**Query implication:** Each generated index can accelerate a predicate or ordering beginning with its single indexed column; generated DDL is anchored at `src/omega/schema.py:352`.

### Index: `idx_memories_event_access`

**Source:** `src/omega/schema.py` line 358

**DDL (verbatim):**

```sql
CREATE INDEX IF NOT EXISTS idx_memories_event_access
ON memories(event_type, access_count)
```

**Type:** B-tree  
**Table:** `memories`  
**Columns indexed:** `event_type`, `access_count`  
**Partial condition:** Absent  
**Query implication:** Can accelerate predicates beginning with `event_type` and then `access_count`; source anchor is `src/omega/schema.py:358`.

### Index: `idx_edges_<col>` dynamic single-column family

**Source:** `src/omega/schema.py` line 399

**DDL (verbatim):**

```sql
CREATE INDEX IF NOT EXISTS idx_edges_{col}
ON edges({col})
```

**Type:** B-tree  
**Table:** `edges`  
**Columns indexed:** each of `source_id`, `target_id`, `edge_type` from the hardcoded tuple at `src/omega/schema.py:397`.  
**Partial condition:** Absent  
**Query implication:** Each generated index can accelerate equality or range predicates on its single edge column; source anchor is `src/omega/schema.py:399`.

### Index: `idx_forgetting_log_deleted_at`

**Source:** `src/omega/schema.py` line 415

**DDL (verbatim):**

```sql
CREATE INDEX IF NOT EXISTS idx_forgetting_log_deleted_at ON forgetting_log(deleted_at)
```

**Type:** B-tree  
**Table:** `forgetting_log`  
**Columns indexed:** `deleted_at`  
**Partial condition:** Absent  
**Query implication:** Can accelerate `WHERE deleted_at ...` and ordering by `deleted_at`; source anchor is `src/omega/schema.py:415`.

### Index: `idx_forgetting_log_reason`

**Source:** `src/omega/schema.py` line 416

**DDL (verbatim):**

```sql
CREATE INDEX IF NOT EXISTS idx_forgetting_log_reason ON forgetting_log(reason)
```

**Type:** B-tree  
**Table:** `forgetting_log`  
**Columns indexed:** `reason`  
**Partial condition:** Absent  
**Query implication:** Can accelerate `WHERE reason = ?`; source anchor is `src/omega/schema.py:416`.

### Index: `idx_forgetting_log_node_reason`

**Source:** `src/omega/schema.py` line 259

**DDL (verbatim):**

```sql
CREATE UNIQUE INDEX IF NOT EXISTS idx_forgetting_log_node_reason ON forgetting_log(node_id, reason)
```

**Type:** unique  
**Table:** `forgetting_log`  
**Columns indexed:** `node_id`, `reason`  
**Partial condition:** Absent  
**Query implication:** Enforces uniqueness for `(node_id, reason)` and can accelerate predicates beginning with `node_id`; source anchor is `src/omega/schema.py:259`.

### Index: `idx_entity_index_type`

**Source:** `src/omega/schema.py` line 441

**DDL (verbatim):**

```sql
CREATE INDEX IF NOT EXISTS idx_entity_index_type ON entity_index(entity_type)
```

**Type:** B-tree  
**Table:** `entity_index`  
**Columns indexed:** `entity_type`  
**Partial condition:** Absent  
**Query implication:** Can accelerate `WHERE entity_type = ?`; source anchor is `src/omega/schema.py:441`.

### Index: `idx_entity_index_score`

**Source:** `src/omega/schema.py` line 442

**DDL (verbatim):**

```sql
CREATE INDEX IF NOT EXISTS idx_entity_index_score ON entity_index(contradiction_score)
```

**Type:** B-tree  
**Table:** `entity_index`  
**Columns indexed:** `contradiction_score`  
**Partial condition:** Absent  
**Query implication:** Can accelerate `WHERE contradiction_score ...` and ordering by `contradiction_score`; source anchor is `src/omega/schema.py:442`.

### Index: `idx_entity_index_updated`

**Source:** `src/omega/schema.py` line 443

**DDL (verbatim):**

```sql
CREATE INDEX IF NOT EXISTS idx_entity_index_updated ON entity_index(last_updated)
```

**Type:** B-tree  
**Table:** `entity_index`  
**Columns indexed:** `last_updated`  
**Partial condition:** Absent  
**Query implication:** Can accelerate `WHERE last_updated ...` and ordering by `last_updated`; source anchor is `src/omega/schema.py:443`.

### Index: `idx_maintenance_dlq_status`

**Source:** `src/omega/schema.py` line 194

**DDL (verbatim):**

```sql
CREATE INDEX IF NOT EXISTS idx_maintenance_dlq_status ON maintenance_dlq(status)
```

**Type:** B-tree  
**Table:** `maintenance_dlq`  
**Columns indexed:** `status`  
**Partial condition:** Absent  
**Query implication:** Can accelerate `WHERE status = ?`; source anchor is `src/omega/schema.py:194`.

### Index: `idx_memory_clusters_superseded`

**Source:** `src/omega/schema.py` line 496

**DDL (verbatim):**

```sql
CREATE INDEX IF NOT EXISTS idx_memory_clusters_superseded ON memory_clusters(superseded)
```

**Type:** B-tree  
**Table:** `memory_clusters`  
**Columns indexed:** `superseded`  
**Partial condition:** Absent  
**Query implication:** Can accelerate `WHERE superseded = ?`; source anchor is `src/omega/schema.py:496`.

### Index: `idx_memory_clusters_cluster_id`

**Source:** `src/omega/schema.py` line 497

**DDL (verbatim):**

```sql
CREATE INDEX IF NOT EXISTS idx_memory_clusters_cluster_id ON memory_clusters(cluster_id)
```

**Type:** B-tree  
**Table:** `memory_clusters`  
**Columns indexed:** `cluster_id`  
**Partial condition:** Absent  
**Query implication:** Can accelerate `WHERE cluster_id = ?`; source anchor is `src/omega/schema.py:497`.

### Index: `idx_thompson_arms_type`

**Source:** `src/omega/schema.py` line 512

**DDL (verbatim):**

```sql
CREATE INDEX IF NOT EXISTS idx_thompson_arms_type ON thompson_arms(arm_type)
```

**Type:** B-tree  
**Table:** `thompson_arms`  
**Columns indexed:** `arm_type`  
**Partial condition:** Absent  
**Query implication:** Can accelerate `WHERE arm_type = ?`; source anchor is `src/omega/schema.py:512`.

### 1.4 Triggers

### Trigger: `memories_ai`

**Source:** `src/omega/schema.py` line 449

**DDL (verbatim):**

```sql
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content)
    VALUES (new.id, new.content || ' ' || COALESCE(new.extracted_keywords, ''));
END
```

**Fires:** AFTER INSERT ON `memories`  
**Effect:** Inserts `new.id` and `new.content || ' ' || COALESCE(new.extracted_keywords, '')` into `memories_fts`. Evidence: `src/omega/schema.py:449` through `src/omega/schema.py:452`.

### Trigger: `memories_ad`

**Source:** `src/omega/schema.py` line 455

**DDL (verbatim):**

```sql
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content)
    VALUES ('delete', old.id, old.content || ' ' || COALESCE(old.extracted_keywords, ''));
END
```

**Fires:** AFTER DELETE ON `memories`  
**Effect:** Inserts an FTS5 delete command with `old.id` and old content plus extracted keywords into `memories_fts`. Evidence: `src/omega/schema.py:455` through `src/omega/schema.py:458`.

### Trigger: `memories_au`

**Source:** `src/omega/schema.py` line 461

**DDL (verbatim):**

```sql
CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE OF content ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content)
    VALUES ('delete', old.id, old.content || ' ' || COALESCE(old.extracted_keywords, ''));
    INSERT INTO memories_fts(rowid, content)
    VALUES (new.id, new.content || ' ' || COALESCE(new.extracted_keywords, ''));
END
```

**Fires:** AFTER UPDATE OF `content` ON `memories`  
**Effect:** Deletes the old FTS5 row and inserts the new FTS5 row using content plus extracted keywords. Evidence: `src/omega/schema.py:461` through `src/omega/schema.py:466`.

### 1.5 Views

Absent — no `CREATE VIEW` statement was found by the Phase 0 inventory command output, and the full CREATE search returned table, virtual table, index, and trigger statements only. Evidence: Phase 0 output and `src/omega/schema.py:449` through `src/omega/schema.py:512`.

### 1.6 PRAGMA Settings

### PRAGMA: `journal_mode`

**Source:** `src/omega/usage_tracker.py` line 60

**Statement (verbatim):**

```python
self._conn.execute("PRAGMA journal_mode=WAL")
```

**Effect:** Sets the database journal mode to WAL. Evidence: `src/omega/usage_tracker.py:60`.

### PRAGMA: `integrity_check`

**Source:** `src/omega/sqlite_store/_base.py` line 335

**Statement (verbatim):**

```python
result = self._conn.execute("PRAGMA integrity_check").fetchone()
```

**Effect:** Runs SQLite integrity checking and returns an integrity result row. Evidence: `src/omega/sqlite_store/_base.py:335`.

### PRAGMA: `wal_checkpoint(PASSIVE)`

**Source:** `src/omega/sqlite_store/_base.py` line 347

**Statement (verbatim):**

```python
result = self._conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
```

**Effect:** Runs a passive WAL checkpoint. Evidence: `src/omega/sqlite_store/_base.py:347`.

### PRAGMA: `journal_mode`

**Source:** `src/omega/sqlite_store/_base.py` line 417

**Statement (verbatim):**

```python
conn.execute("PRAGMA journal_mode=WAL")
```

**Effect:** Sets the database journal mode to WAL. Evidence: `src/omega/sqlite_store/_base.py:417`.

### PRAGMA: `synchronous`

**Source:** `src/omega/sqlite_store/_base.py` line 418

**Statement (verbatim):**

```python
conn.execute("PRAGMA synchronous=NORMAL")
```

**Effect:** Sets SQLite synchronous behavior to NORMAL. Evidence: `src/omega/sqlite_store/_base.py:418`.

### PRAGMA: `cache_size`

**Source:** `src/omega/sqlite_store/_base.py` line 422

**Statement (verbatim):**

```python
conn.execute(f"PRAGMA cache_size={-4000 if _is_http else -16000}")  # 4MB / 16MB
```

**Effect:** Sets page-cache size; a negative value denotes kibibytes in SQLite. Evidence: `src/omega/sqlite_store/_base.py:422`.

### PRAGMA: `mmap_size`

**Source:** `src/omega/sqlite_store/_base.py` line 423

**Statement (verbatim):**

```python
conn.execute(f"PRAGMA mmap_size={0 if _is_http else 33554432}")  # 0 / 32MB
```

**Effect:** Sets memory-mapped I/O byte limit. Evidence: `src/omega/sqlite_store/_base.py:423`.

### PRAGMA: `busy_timeout`

**Source:** `src/omega/sqlite_store/_base.py` line 424

**Statement (verbatim):**

```python
conn.execute("PRAGMA busy_timeout=30000")  # 30s — handles multi-process contention
```

**Effect:** Sets busy timeout to 30000 milliseconds. Evidence: `src/omega/sqlite_store/_base.py:424`.

### PRAGMA: `journal_size_limit`

**Source:** `src/omega/sqlite_store/_base.py` line 425

**Statement (verbatim):**

```python
conn.execute("PRAGMA journal_size_limit=8388608")  # 8MB — cap WAL growth under multi-process contention
```

**Effect:** Sets journal size limit to 8388608 bytes. Evidence: `src/omega/sqlite_store/_base.py:425`.

### PRAGMA: `foreign_keys`

**Source:** `src/omega/sqlite_store/_base.py` line 426

**Statement (verbatim):**

```python
conn.execute("PRAGMA foreign_keys=ON")
```

**Effect:** Enables SQLite foreign key enforcement for the connection. Evidence: `src/omega/sqlite_store/_base.py:426`.

### PRAGMA: `wal_checkpoint(TRUNCATE)`

**Source:** `src/omega/sqlite_store/_base.py` line 488

**Statement (verbatim):**

```python
result = self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
```

**Effect:** Runs a truncating WAL checkpoint. Evidence: `src/omega/sqlite_store/_base.py:488`.

### PRAGMA: `wal_checkpoint(PASSIVE)`

**Source:** `src/omega/sqlite_store/_base.py` line 508

**Statement (verbatim):**

```python
result = self._conn.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
```

**Effect:** Runs a passive WAL checkpoint. Evidence: `src/omega/sqlite_store/_base.py:508`.

### PRAGMA: `wal_checkpoint(PASSIVE)`

**Source:** `src/omega/sqlite_store/_base.py` line 711

**Statement (verbatim):**

```python
self._conn.execute("PRAGMA wal_checkpoint(PASSIVE)")
```

**Effect:** Runs a passive WAL checkpoint before close. Evidence: `src/omega/sqlite_store/_base.py:711`.

### PRAGMA: `integrity_check`

**Source:** `src/omega/cli.py` line 1804

**Statement (verbatim):**

```python
result = conn.execute("PRAGMA integrity_check").fetchone()[0]
```

**Effect:** Runs SQLite integrity checking. Evidence: `src/omega/cli.py:1804`.

### PRAGMA: `busy_timeout`

**Source:** `src/omega/cli.py` line 2398

**Statement (verbatim):**

```python
_doctor_conn.execute("PRAGMA busy_timeout=5000")
```

**Effect:** Sets busy timeout to 5000 milliseconds. Evidence: `src/omega/cli.py:2398`.

### PRAGMA: `query_only`

**Source:** `src/omega/cli.py` line 2399

**Statement (verbatim):**

```python
_doctor_conn.execute("PRAGMA query_only=ON")
```

**Effect:** Prevents changes through that connection. Evidence: `src/omega/cli.py:2399`.

### PRAGMA: `busy_timeout`

**Source:** `src/omega/cli.py` line 2493

**Statement (verbatim):**

```python
_fts_conn.execute("PRAGMA busy_timeout=5000")
```

**Effect:** Sets busy timeout to 5000 milliseconds. Evidence: `src/omega/cli.py:2493`.

### 1.7 Schema Versioning

1. `user_version` or `schema_version` PRAGMA set on initialization: Absent — no `PRAGMA user_version` or `PRAGMA schema_version` was found in the PRAGMA inventory files. The schema version is an application table: `CREATE TABLE IF NOT EXISTS schema_version` at `src/omega/schema.py:39`.
2. Migrations table or version tracking table: Schema-defined `schema_version`. Evidence: `src/omega/schema.py:39` and `src/omega/schema.py:44` (`row = c.execute("SELECT version FROM schema_version LIMIT 1").fetchone()`).
3. Migration runner: `init_schema()` runs migrations when the stored version is below target; evidence is `if row and row[0] < 2:` at `src/omega/schema.py:53`, repeated current-version checks through `src/omega/schema.py:265`, and `_init_schema_fn(self._conn, self._vec_available, EMBEDDING_DIM)` at `src/omega/sqlite_store/_base.py:444`.
4. Current schema version: `14`. Evidence: `SCHEMA_VERSION = 14` at `src/omega/schema.py:12` and initialization insert `INSERT INTO schema_version (version) VALUES (?)` at `src/omega/schema.py:46`.

## Phase 2: Feature Analysis

### 2.1 Search Capabilities

| Capability | Status | Evidence |
|---|---|---|
| Full-text search (FTS5) | Schema-defined | `memories_fts` virtual table DDL at `src/omega/schema.py:376`; application query uses `WHERE memories_fts MATCH ?` at `src/omega/sqlite_store/_search.py:108`. |
| BM25 ranking (FTS5 built-in) | Unconfirmed | FTS5 `rank` is read at `src/omega/sqlite_store/_search.py:105`; module guarantee is Unconfirmed — check SQLite docs for FTS5. |
| Vector / semantic search | Schema-defined | `memories_vec` virtual table DDL at `src/omega/schema.py:366`; KNN query reads `memories_vec` at `src/omega/sqlite_store/_search.py:36`. |
| Vector distance metric | Schema-defined | `distance_metric=cosine` is in the vec0 DDL at `src/omega/schema.py:367`. |
| Hybrid search (FTS5 + vector combined) | Derivable | Requires `memories_vec` (`src/omega/schema.py:366`) joined/hydrated through `memories` (`src/omega/schema.py:297`) and `memories_fts` (`src/omega/schema.py:376`). No schema-defined view or trigger combines them. |
| Exact column match filtering | Schema-defined | Single-column memory indexes are generated for filter columns at `src/omega/schema.py:328` through `src/omega/schema.py:354`. |
| Date / time range filtering | Schema-defined | `created_at`, `referenced_date`, `valid_from`, `valid_until`, and `last_accessed` are indexed via the dynamic index tuple at `src/omega/schema.py:333`, `src/omega/schema.py:336`, `src/omega/schema.py:344`, `src/omega/schema.py:345`, `src/omega/schema.py:341`. |
| Tag or label filtering | Absent | No `tags` column or tag table is present in the `memories` DDL at `src/omega/schema.py:297`; metadata is TEXT at `src/omega/schema.py:301`. |
| JSON field filtering | Application-used | JSON expressions are used on `metadata`, for example `json_extract(metadata, '$.flagged_for_review')` at `src/omega/server/handlers.py:3694`; no generated column or expression index is schema-defined in the CREATE statements. |
| Multi-project scoping | Schema-defined | `project TEXT` is defined at `src/omega/schema.py:308` and indexed through tuple member `project` at `src/omega/schema.py:332`. |
| Soft-delete / lifecycle filtering | Schema-defined for lifecycle status only | `status TEXT DEFAULT 'active'` at `src/omega/schema.py:323` and indexed through tuple member `status` at `src/omega/schema.py:348`; no `deleted_at` or `is_deleted` column exists in `memories` DDL at `src/omega/schema.py:297`. |

### 2.2 Memory Identity and Lifecycle

1. Stable IDs: `memories.node_id` is the public stable identifier; it is `TEXT UNIQUE NOT NULL`. Evidence: `src/omega/schema.py:299`.
2. Soft delete: Absent — `memories` DDL has no `deleted_at`, `deleted`, or `is_deleted` column. Evidence: complete `memories` DDL at `src/omega/schema.py:297`.
3. Lifecycle states: Schema-defined column `status TEXT DEFAULT 'active'`; the schema has no CHECK constraint enumerating states. Evidence: `src/omega/schema.py:323`. Application tool schemas enumerate `active`, `superseded`, `speculative`, and `archived` at `src/omega/server/tool_schemas.py:53` through `src/omega/server/tool_schemas.py:56`.
4. Timestamps: `memories.created_at TEXT NOT NULL` with no DEFAULT at `src/omega/schema.py:302`; application writes `now` into the insert at `src/omega/sqlite_store/_store.py:202`. `edges.created_at TEXT NOT NULL DEFAULT (datetime('now'))` is schema-set at `src/omega/schema.py:393`. `entity_index.first_seen` and `last_updated` are DEFAULT `(datetime('now'))` in current DDL at `src/omega/schema.py:436` and `src/omega/schema.py:437`; migration DDL had no DEFAULT at `src/omega/schema.py:135` and `src/omega/schema.py:136`. `llm_usage.created_at TEXT NOT NULL` has no DEFAULT at `src/omega/usage_tracker.py:34`; application writes `now` at `src/omega/usage_tracker.py:87`.
5. Immutability: Absent — no trigger or CHECK enforces write-once columns in the DDL blocks. Evidence: complete `memories` DDL at `src/omega/schema.py:297` and triggers limited to FTS sync at `src/omega/schema.py:449`, `src/omega/schema.py:455`, `src/omega/schema.py:461`.

### 2.3 Relationships and Graph

1. Edge table: Schema-defined `edges` table with `source_id`, `target_id`, `edge_type`, `weight`, `metadata`, and `created_at`; DDL anchored at `src/omega/schema.py:386`.
2. Edge types: Free-form strings; `edge_type TEXT NOT NULL` has no CHECK or FK. Evidence: `src/omega/schema.py:390`.
3. Edge weight: Schema-defined as `weight REAL DEFAULT 1.0`; no range CHECK is present in the table DDL. Evidence: `src/omega/schema.py:391`.
4. Directionality: Schema is directed by column names `source_id` and `target_id`; evidence is `src/omega/schema.py:388` and `src/omega/schema.py:389`.
5. Self-referential edges: Absent — no CHECK prevents `source_id = target_id`; complete edge DDL at `src/omega/schema.py:386`.
6. Maximum graph depth: Absent at schema level; traversal clamps `max_hops` in application code at `src/omega/sqlite_store/_maintenance.py:1018`.
7. Derivable graph operations: one-hop outbound lookup via `SELECT target_id FROM edges WHERE source_id = ?` using `idx_edges_source_id` generated at `src/omega/schema.py:399`; one-hop inbound lookup via `SELECT source_id FROM edges WHERE target_id = ?` using `idx_edges_target_id` generated at `src/omega/schema.py:399`; edge-type filtering via `SELECT source_id, target_id FROM edges WHERE edge_type = ?` using `idx_edges_edge_type` generated at `src/omega/schema.py:399`.

### 2.4 Embedding Storage

1. Embeddings are stored in `memories_vec.embedding`. Evidence: DDL at `src/omega/schema.py:366` and insert at `src/omega/sqlite_store/_store.py:232`.
2. Type: `float[{embedding_dim}]` vec0 column. Evidence: `src/omega/schema.py:367`.
3. Dimensionality: The DDL parameter is `embedding_dim`; `_base.py` passes `EMBEDDING_DIM` at `src/omega/sqlite_store/_base.py:444` through `src/omega/sqlite_store/_base.py:445`; `EMBEDDING_DIM = 384` at `src/omega/sqlite_store/_types.py:12`.
4. Distance metric: `cosine`. Evidence: `src/omega/schema.py:367`.
5. Nullability: vec0 nullability is Unconfirmed — check sqlite-vec docs for `vec0`; DDL has no `NOT NULL` token in `embedding float[{embedding_dim}] distance_metric=cosine` at `src/omega/schema.py:367`.
6. Storage location: Separate virtual table, because `memories` DDL has no embedding column at `src/omega/schema.py:297`, and `memories_vec` is a separate virtual table at `src/omega/schema.py:366`.

### 2.5 Metadata and Extensibility

1. JSON or key-value metadata: `memories.metadata TEXT` at `src/omega/schema.py:301`; `edges.metadata TEXT` at `src/omega/schema.py:392`; `forgetting_log.metadata TEXT` at `src/omega/schema.py:412`; `entity_index.metadata TEXT` at `src/omega/schema.py:438`; `cloud_delete_queue` has no metadata column at `src/omega/schema.py:420`.
2. JSON fields indexed: Absent — no generated columns or expression indices appear in CREATE statements; all index DDL is listed in Phase 1.3.
3. `event_type` schema-constrained: free-form `TEXT`; evidence `src/omega/schema.py:307`.
4. `project` schema-constrained: free-form `TEXT`; evidence `src/omega/schema.py:308`.
5. Tags or labels: Absent as normalized schema; no `tags` column is present in `memories` DDL at `src/omega/schema.py:297`. Application output reads `tags` from metadata at `src/omega/server/handlers.py:268`.

### 2.6 Derivable Capabilities

#### Derivable: Memory Age

**Requires:** `memories.created_at` at `src/omega/schema.py:302`.

**SQL sketch:**

```sql
SELECT node_id, julianday('now') - julianday(created_at) AS age_days
FROM memories;
```

**Limitations:** `created_at` is TEXT and has no schema CHECK for ISO format; evidence is `src/omega/schema.py:302`.

#### Derivable: Degree Centrality

**Requires:** `edges.source_id` and `edges.target_id` at `src/omega/schema.py:388` and `src/omega/schema.py:389`.

**SQL sketch:**

```sql
SELECT node_id, COUNT(*) AS degree
FROM (
  SELECT source_id AS node_id FROM edges
  UNION ALL
  SELECT target_id AS node_id FROM edges
)
GROUP BY node_id;
```

**Limitations:** Edge endpoints are not FK-enforced; evidence is complete edge DDL at `src/omega/schema.py:386`.

#### Derivable: Orphaned Edge Detection

**Requires:** `edges`, `memories.node_id`; evidence `src/omega/schema.py:386` and `src/omega/schema.py:299`.

**SQL sketch:**

```sql
SELECT e.id
FROM edges e
LEFT JOIN memories m1 ON e.source_id = m1.node_id
LEFT JOIN memories m2 ON e.target_id = m2.node_id
WHERE m1.node_id IS NULL OR m2.node_id IS NULL;
```

**Limitations:** This query detects missing endpoints because no FK constraint exists in `edges` DDL at `src/omega/schema.py:386`.

#### Derivable: Duplicate Content Detection

**Requires:** `memories.content_hash` and `memories.canonical_hash`; evidence `src/omega/schema.py:309` and `src/omega/schema.py:314`.

**SQL sketch:**

```sql
SELECT content_hash, COUNT(*) AS count
FROM memories
WHERE content_hash IS NOT NULL
GROUP BY content_hash
HAVING COUNT(*) > 1;
```

**Limitations:** No UNIQUE constraint exists on either hash column; evidence is complete `memories` DDL at `src/omega/schema.py:297`.

#### Derivable: Supersession Chains

**Requires:** `edges.edge_type`, `edges.source_id`, `edges.target_id`; evidence `src/omega/schema.py:388`, `src/omega/schema.py:389`, `src/omega/schema.py:390`.

**SQL sketch:**

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

**Limitations:** Edge type is free-form; schema does not enforce `supersedes`. Evidence: `src/omega/schema.py:390`.

#### Derivable: Embedding Coverage Rate

**Requires:** `memories.id` and `memories_vec.rowid`; evidence `src/omega/schema.py:298` and virtual table DDL at `src/omega/schema.py:366`.

**SQL sketch:**

```sql
SELECT
  COUNT(v.rowid) * 1.0 / NULLIF(COUNT(m.id), 0) AS embedding_coverage
FROM memories m
LEFT JOIN memories_vec v ON v.rowid = m.id;
```

**Limitations:** `memories_vec` is created only when `vec_available` is true at `src/omega/schema.py:363`.

#### Derivable: Memory Volume By Event Type

**Requires:** `memories.event_type`; evidence `src/omega/schema.py:307`.

**SQL sketch:**

```sql
SELECT event_type, COUNT(*) AS count
FROM memories
GROUP BY event_type
ORDER BY count DESC;
```

**Limitations:** `event_type` is nullable and free-form. Evidence: `src/omega/schema.py:307`.

#### Derivable: Most-Connected Memories

**Requires:** `edges.source_id`, `edges.target_id`, `memories.node_id`; evidence `src/omega/schema.py:388`, `src/omega/schema.py:389`, `src/omega/schema.py:299`.

**SQL sketch:**

```sql
SELECT m.node_id, COUNT(e.node_id) AS degree
FROM memories m
LEFT JOIN (
  SELECT source_id AS node_id FROM edges
  UNION ALL
  SELECT target_id AS node_id FROM edges
) e ON e.node_id = m.node_id
GROUP BY m.node_id
ORDER BY degree DESC;
```

**Limitations:** Duplicate reciprocal edges count separately; uniqueness only covers `(source_id, target_id, edge_type)` at `src/omega/schema.py:394`.

## Phase 3: Application Code Cross-Reference

### Usage: `llm_usage`

#### Write sites

| File | Line | Operation | Columns written | Condition |
|---|---:|---|---|---|
| `src/omega/usage_tracker.py` | 90 | INSERT | `session_id`, `tool_name`, `model`, `provider`, `input_tokens`, `output_tokens`, `cache_read_tokens`, `cache_write_tokens`, `estimated_cost_usd`, `duration_ms`, `project`, `created_at` | unconditional in `log_call()` |

#### Read sites

| File | Line | Operation | Columns read | Condition |
|---|---:|---|---|---|
| `src/omega/usage_tracker.py` | 106 | SELECT | dynamic group column, `input_tokens`, `output_tokens`, `estimated_cost_usd`, count | `WHERE created_at > datetime('now', '-' || ? || ' days')` |
| `src/omega/usage_tracker.py` | 126 | SELECT | `estimated_cost_usd`, `input_tokens`, `output_tokens`, count | `WHERE created_at > datetime('now', '-' || ? || ' days')` |
| `src/omega/usage_tracker.py` | 143 | SELECT | `tool_name`, token sum, cost sum, count | `WHERE created_at > datetime('now', '-' || ? || ' days') GROUP BY tool_name` |

Column status: `id` is Schema-defined but application-unused; all other columns are Application-used by the insert at `src/omega/usage_tracker.py:90` and reads at `src/omega/usage_tracker.py:106`.

### Usage: `schema_version`

#### Write sites

| File | Line | Operation | Columns written | Condition |
|---|---:|---|---|---|
| `src/omega/schema.py` | 46 | INSERT | `version` | when no row exists |
| `src/omega/schema.py` | 64 | UPDATE | `version` | migration v1 to v2 |
| `src/omega/schema.py` | 288 | UPDATE | `version` | migration v13 to v14 |

#### Read sites

| File | Line | Operation | Columns read | Condition |
|---|---:|---|---|---|
| `src/omega/schema.py` | 44 | SELECT | `version` | `LIMIT 1` |
| `src/omega/schema.py` | 69 | SELECT | `version` | `LIMIT 1` |
| `src/omega/schema.py` | 265 | SELECT | `version` | `LIMIT 1` |

Column status: `version` is Application-used by schema initialization. Evidence: `src/omega/schema.py:44`, `src/omega/schema.py:46`.

### Usage: `memories`

#### Write sites

| File | Line | Operation | Columns written | Condition |
|---|---:|---|---|---|
| `src/omega/sqlite_store/_store.py` | 191 | INSERT | `node_id`, `content`, `metadata`, `created_at`, `access_count`, `ttl_seconds`, `session_id`, `event_type`, `project`, `content_hash`, `priority`, `referenced_date`, `entity_id`, `agent_type`, `canonical_hash`, `extracted_keywords`, `memory_type`, `valid_from`, `derived_from`, `source_uri`, `status` | store new memory |
| `src/omega/sqlite_store/_store.py` | 113 | UPDATE | `access_count` | dedup by `node_id` |
| `src/omega/sqlite_store/_store.py` | 302 | UPDATE | `access_count`, `last_accessed` | `WHERE node_id = ?` |
| `src/omega/sqlite_store/_store.py` | 423 | UPDATE | dynamic `content`, `content_hash`, `canonical_hash`, `metadata`, `event_type`, `session_id`, `project`, `access_count` | `WHERE node_id = ?` |
| `src/omega/sqlite_store/_store.py` | 516 | UPDATE | `valid_until`, `status` | supersede by `node_id` |
| `src/omega/sqlite_store/_maintenance.py` | 116 | DELETE | rows by `id` | expired TTL |
| `src/omega/sqlite_store/_search.py` | 680 | DELETE | rows by `session_id` | clear session |
| `src/omega/integrations/crewai.py` | 344 | DELETE | rows by metadata scope | CrewAI reset |

#### Read sites

| File | Line | Operation | Columns read | Condition |
|---|---:|---|---|---|
| `src/omega/sqlite_store/_store.py` | 105 | SELECT | `node_id`, `id` | `WHERE canonical_hash = ?` and TTL predicate |
| `src/omega/sqlite_store/_store.py` | 124 | SELECT | `node_id`, `id` | `WHERE content_hash = ?` and TTL predicate |
| `src/omega/sqlite_store/_store.py` | 289 | SELECT | `node_id`, `content`, `metadata`, `created_at`, `access_count`, `last_accessed`, `ttl_seconds`, `valid_from`, `valid_until`, `derived_from`, `source_uri`, `status` | `WHERE node_id = ?` |
| `src/omega/sqlite_store/_search.py` | 413 | SELECT | `node_id`, `content`, `metadata`, `created_at`, `access_count`, `last_accessed`, `ttl_seconds` | `WHERE event_type = ?` |
| `src/omega/sqlite_store/_search.py` | 461 | SELECT | plus `valid_from`, `valid_until`, `derived_from`, `source_uri`, `status` | `WHERE project = ?` plus optional filters |
| `src/omega/sqlite_store/_query.py` | 726 | SELECT | `node_id` | validity filter on `valid_from`, `valid_until` |
| `src/omega/bridge.py` | 4048 | SELECT | `node_id`, `content`, `event_type`, `id`, `created_at`, `entity_id`, `status` | recent active candidates |
| `src/omega/server/handlers.py` | 3691 | SELECT | `node_id`, `content`, `metadata`, `created_at`, `access_count`, `last_accessed`, `ttl_seconds` | JSON feedback flags |
| `src/omega/server/mcp_server.py` | 1103 | SELECT | count, distinct JSON event type count | startup instructions |

Column status: All `memories` columns are Application-used except `end_date`, which is present in DDL and index tuple at `src/omega/schema.py:315` and `src/omega/schema.py:340` but has no non-DDL reference in the Phase 3 searches. `id` is used for vec joins and deletes at `src/omega/sqlite_store/_store.py:232`, `src/omega/sqlite_store/_search.py:824`, and `src/omega/sqlite_store/_query.py:1528`.

### Usage: `memories_vec`

#### Write sites

| File | Line | Operation | Columns written | Condition |
|---|---:|---|---|---|
| `src/omega/sqlite_store/_store.py` | 232 | INSERT | `rowid`, `embedding` | when embedding exists and vec is available |
| `src/omega/sqlite_store/_store.py` | 429 | DELETE | `rowid` | before replacing embedding |
| `src/omega/sqlite_store/_maintenance.py` | 560 | DELETE | `rowid` | re-embedding |
| `src/omega/sqlite_store/_maintenance.py` | 562 | INSERT | `rowid`, `embedding` | re-embedding |
| `src/omega/sqlite_store/_maintenance.py` | 1365 | DELETE | all rows | import clear |

#### Read sites

| File | Line | Operation | Columns read | Condition |
|---|---:|---|---|---|
| `src/omega/sqlite_store/_search.py` | 36 | SELECT | `rowid`, `distance` | `WHERE embedding MATCH ? AND k = ?` |
| `src/omega/sqlite_store/_search.py` | 828 | SELECT | `embedding` | `WHERE rowid = ?` |
| `src/omega/sqlite_store/_query.py` | 1527 | SELECT | `m.node_id`, `v.embedding` | join `memories` to `memories_vec` |
| `src/omega/bridge.py` | 4090 | SELECT | `embedding` | `WHERE rowid = ?` |

Column status: `embedding` is Application-used. `rowid` is Implied by module/table usage and Application-used at `src/omega/sqlite_store/_search.py:36`.

### Usage: `memories_fts`

#### Write sites

| File | Line | Operation | Columns written | Condition |
|---|---:|---|---|---|
| `src/omega/schema.py` | 450 | INSERT | `rowid`, `content` | trigger after memory insert |
| `src/omega/schema.py` | 456 | INSERT | FTS delete command | trigger after memory delete |
| `src/omega/schema.py` | 462 | INSERT | FTS delete command, then `rowid`, `content` | trigger after content update |
| `src/omega/sqlite_store/_search.py` | 170 | INSERT | FTS special command | rebuild |
| `src/omega/cli.py` | 1814 | INSERT | FTS special command | integrity check |

#### Read sites

| File | Line | Operation | Columns read | Condition |
|---|---:|---|---|---|
| `src/omega/sqlite_store/_search.py` | 103 | SELECT | `f.rank`, `f.rowid` via join | `WHERE memories_fts MATCH ?` |
| `src/omega/cli.py` | 2481 | SELECT | count | doctor FTS health |

Column status: `content` is Schema-defined and Application-used through triggers. Implied `rowid` and `rank` are Application-used at `src/omega/sqlite_store/_search.py:105` through `src/omega/sqlite_store/_search.py:119`.

### Usage: `edges`

#### Write sites

| File | Line | Operation | Columns written | Condition |
|---|---:|---|---|---|
| `src/omega/sqlite_store/_store.py` | 241 | INSERT | `source_id`, `target_id`, `edge_type`, `created_at` | dependencies |
| `src/omega/sqlite_store/_store.py` | 249 | INSERT | `source_id`, `target_id`, `edge_type`, `created_at` | `derived_from` |
| `src/omega/sqlite_store/_store.py` | 697 | INSERT | `source_id`, `target_id`, `edge_type`, `weight`, `created_at` | contradictions |
| `src/omega/sqlite_store/_maintenance.py` | 986 | INSERT | `source_id`, `target_id`, `edge_type`, `weight`, `metadata`, `created_at` | `add_edge()` |
| `src/omega/migrate_to_sqlite.py` | 345 | INSERT | `source_id`, `target_id`, `edge_type`, `weight`, `metadata` | migrating causal edges |
| `src/omega/sqlite_store/_maintenance.py` | 341 | DELETE | rows by `id` | orphan pruning |

#### Read sites

| File | Line | Operation | Columns read | Condition |
|---|---:|---|---|---|
| `src/omega/sqlite_store/_maintenance.py` | 334 | SELECT | `e.id` | orphan detection joins to `memories` |
| `src/omega/sqlite_store/_maintenance.py` | 1068 | SELECT | `source_id`, `target_id`, `edge_type`, `weight`, `created_at` | traversal by source or target |
| `src/omega/sqlite_store/_maintenance.py` | 1249 | SELECT | `source_id`, `target_id`, `edge_type`, `weight`, `metadata`, `created_at` | `WHERE edge_type = ?` |
| `src/omega/bridge.py` | 4077 | SELECT | `source_id`, `target_id` | candidates in connection discovery |
| `src/omega/server/handlers.py` | 4109 | SELECT | count and `edge_type` counts | graph stats |
| `src/omega/obsidian_export.py` | 65 | SELECT | `source_id`, `target_id`, `edge_type`, `weight` | node export |

Column status: All `edges` columns are Application-used. Evidence: insert at `src/omega/sqlite_store/_maintenance.py:986` writes all non-id columns; `id` is read/deleted at `src/omega/sqlite_store/_maintenance.py:334` and `src/omega/sqlite_store/_maintenance.py:341`.

### Usage: `forgetting_log`

#### Write sites

| File | Line | Operation | Columns written | Condition |
|---|---:|---|---|---|
| `src/omega/sqlite_store/_maintenance.py` | 39 | INSERT | `node_id`, `content_preview`, `event_type`, `reason`, `deleted_at`, `metadata` | deletion/forgetting log |
| `src/omega/sqlite_store/_maintenance.py` | 157 | DELETE | rows by `deleted_at` | prune old log |

#### Read sites

| File | Line | Operation | Columns read | Condition |
|---|---:|---|---|---|
| `src/omega/sqlite_store/_maintenance.py` | 166 | SELECT | `node_id`, `content_preview`, `event_type`, `reason`, `deleted_at`, `metadata` | optional `WHERE reason = ?` |
| `src/omega/bridge.py` | 4392 | API wrapper | entries from store method | `forgetting_log()` |

Column status: `id` is Schema-defined but application-unused; all other columns are Application-used at `src/omega/sqlite_store/_maintenance.py:39` and `src/omega/sqlite_store/_maintenance.py:166`.

### Usage: `cloud_delete_queue`

#### Write sites

| File | Line | Operation | Columns written | Condition |
|---|---:|---|---|---|
| `src/omega/sqlite_store/_maintenance.py` | 55 | INSERT | `local_id`, `deleted_at` | queue cloud delete |

#### Read sites

| File | Line | Operation | Columns read | Condition |
|---|---:|---|---|---|
| n/a | n/a | n/a | n/a | Absent in Phase 3 search |

Column status: `local_id` and `deleted_at` are write-only Application-used; `id` is Schema-defined but application-unused. Evidence: DDL at `src/omega/schema.py:421` and write at `src/omega/sqlite_store/_maintenance.py:55`.

### Usage: `entity_index`

#### Write sites

| File | Line | Operation | Columns written | Condition |
|---|---:|---|---|---|
| `src/omega/sqlite_store/_maintenance.py` | 1146 | INSERT/UPSERT | `entity_name`, `entity_type`, `statement_count`, `outcome_count`, `contradiction_score`, `follow_through_rate`, `first_seen`, `last_updated`, `metadata` | write entity profile |
| `src/omega/migrate_to_sqlite.py` | 369 | INSERT | `entity_id`, `node_id` | migration from JSON entity index |

#### Read sites

| File | Line | Operation | Columns read | Condition |
|---|---:|---|---|---|
| `src/omega/sqlite_store/_maintenance.py` | 1170 | SELECT | all schema columns | `WHERE entity_name = ?` |
| `src/omega/sqlite_store/_maintenance.py` | 1197 | SELECT | `entity_name`, `entity_type`, counts, scores, timestamps | optional entity filters |

Column status: all current DDL columns are Application-used by `_maintenance.py`; `migrate_to_sqlite.py` assumes non-schema fields `entity_id` and `node_id` at `src/omega/migrate_to_sqlite.py:369`.

### Usage: `maintenance_dlq`

#### Write sites

| File | Line | Operation | Columns written | Condition |
|---|---:|---|---|---|
| n/a | n/a | n/a | n/a | Absent in Phase 3 search |

#### Read sites

| File | Line | Operation | Columns read | Condition |
|---|---:|---|---|---|
| n/a | n/a | n/a | n/a | Absent in Phase 3 search |

Column status: all columns are Schema-defined but application-unused: `id`, `stage_name`, `error_class`, `error_message`, `remediation_attempts`, `max_remediation`, `status`, `next_retry_at`, `created_at`, `updated_at`. Evidence: DDL at `src/omega/schema.py:181`.

### Usage: `memory_clusters`

#### Write sites

| File | Line | Operation | Columns written | Condition |
|---|---:|---|---|---|
| n/a | n/a | n/a | n/a | Absent in Phase 3 search |

#### Read sites

| File | Line | Operation | Columns read | Condition |
|---|---:|---|---|---|
| n/a | n/a | n/a | n/a | Direct table usage absent; query code imports `PatternLearner` at `src/omega/sqlite_store/_query.py:1349`. |

Column status: all columns are Schema-defined but application-unused by direct SQL in `src/omega/`: `id`, `cluster_id`, `label`, `member_count`, `centroid`, `representative_keywords`, `representative_memory_ids`, `created_at`, `updated_at`, `superseded`. Evidence: DDL at `src/omega/schema.py:483`; absence check found no direct non-DDL `memory_clusters` usage outside `src/omega/schema.py`.

### Usage: `thompson_arms`

#### Write sites

| File | Line | Operation | Columns written | Condition |
|---|---:|---|---|---|
| n/a | n/a | n/a | n/a | Direct table usage absent in Phase 3 search |

#### Read sites

| File | Line | Operation | Columns read | Condition |
|---|---:|---|---|---|
| n/a | n/a | n/a | n/a | Direct table usage absent; code imports `ThompsonBandit` at `src/omega/sqlite_store/_query.py:1675` and `src/omega/sqlite_store/_maintenance.py:898`. |

Column status: all columns are Schema-defined but application-unused by direct SQL in `src/omega/`: `arm_id`, `arm_type`, `alpha`, `beta`, `total_trials`, `total_successes`, `last_updated`, `context`. Evidence: DDL at `src/omega/schema.py:501`; absence check found no direct non-DDL `thompson_arms` usage outside `src/omega/schema.py`.

## Phase 4: Gap Analysis

### 4.1 Schema-Defined But Unused

- **Object:** `llm_usage.id`  
  **Defined at:** `src/omega/usage_tracker.py` line 22  
  **Application usage:** Absent — confirmed by Phase 3 search  
  **Interpretation:** Unknown intent.
- **Object:** `forgetting_log.id`  
  **Defined at:** `src/omega/schema.py` line 406  
  **Application usage:** Absent — confirmed by Phase 3 search  
  **Interpretation:** Unknown intent.
- **Object:** `cloud_delete_queue.id`  
  **Defined at:** `src/omega/schema.py` line 421  
  **Application usage:** Absent — confirmed by Phase 3 search  
  **Interpretation:** Unknown intent.
- **Object:** `maintenance_dlq.*`  
  **Defined at:** `src/omega/schema.py` line 181  
  **Application usage:** Absent — confirmed by Phase 3 search  
  **Interpretation:** Future-reserved, from table name and migration comment `add maintenance_dlq table` at `src/omega/schema.py:177`.
- **Object:** `memory_clusters.*`  
  **Defined at:** `src/omega/schema.py` line 483  
  **Application usage:** Absent by direct SQL — confirmed by Phase 3 search  
  **Interpretation:** Future-reserved, from comment `Memory clusters table (pattern learner)` at `src/omega/schema.py:481`.
- **Object:** `thompson_arms.*`  
  **Defined at:** `src/omega/schema.py` line 501  
  **Application usage:** Absent by direct SQL — confirmed by Phase 3 search  
  **Interpretation:** Future-reserved, from comment `Thompson sampling arms table` at `src/omega/schema.py:499`.
- **Object:** `memories.end_date`  
  **Defined at:** `src/omega/schema.py` line 315  
  **Application usage:** Absent — confirmed by Phase 3 search  
  **Interpretation:** Unknown intent; migration comment says `add end_date, extracted_keywords` at `src/omega/schema.py:147`.
- **Object:** `idx_maintenance_dlq_status`  
  **Defined at:** `src/omega/schema.py` line 194  
  **Application usage:** Absent — confirmed by Phase 3 search  
  **Interpretation:** Future-reserved with `maintenance_dlq`.
- **Object:** `idx_memory_clusters_superseded`  
  **Defined at:** `src/omega/schema.py` line 496  
  **Application usage:** Absent by direct SQL — confirmed by Phase 3 search  
  **Interpretation:** Future-reserved with `memory_clusters`.
- **Object:** `idx_memory_clusters_cluster_id`  
  **Defined at:** `src/omega/schema.py` line 497  
  **Application usage:** Absent by direct SQL — confirmed by Phase 3 search  
  **Interpretation:** Future-reserved with `memory_clusters`.
- **Object:** `idx_thompson_arms_type`  
  **Defined at:** `src/omega/schema.py` line 512  
  **Application usage:** Absent by direct SQL — confirmed by Phase 3 search  
  **Interpretation:** Future-reserved with `thompson_arms`.

### 4.2 Application-Assumed But Schema-Unconfirmed

- **Field assumed:** `entity_index.entity_id`  
  **Application site:** `src/omega/migrate_to_sqlite.py` line 369 — `"INSERT OR IGNORE INTO entity_index (entity_id, node_id) VALUES (?, ?)",`  
  **Schema status:** Absent from all `entity_index` DDL in Phase 1.  
  **Possible source:** Absent from DDL; no evidence supports a dynamic column.
- **Field assumed:** `entity_index.node_id`  
  **Application site:** `src/omega/migrate_to_sqlite.py` line 369 — `"INSERT OR IGNORE INTO entity_index (entity_id, node_id) VALUES (?, ?)",`  
  **Schema status:** Absent from all `entity_index` DDL in Phase 1.  
  **Possible source:** Absent from DDL; no evidence supports a dynamic column.
- **Field assumed:** table `nodes`  
  **Application site:** `src/omega/server/handlers.py` line 4115 — `node_count = conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]`  
  **Schema status:** Absent from all DDL found in Phase 1.  
  **Possible source:** No `CREATE TABLE nodes` is present in Phase 1; graph stats code also reads `edges` at `src/omega/server/handlers.py:4109`.

### 4.3 Missing Constraints

- **Column:** `edges.source_id`, `edges.target_id`  
  **Role evidence:** orphan pruning joins them to `memories.node_id` at `src/omega/sqlite_store/_maintenance.py:334` through `src/omega/sqlite_store/_maintenance.py:337`.  
  **Missing constraint:** FK  
  **Risk:** NULL is blocked by NOT NULL at `src/omega/schema.py:388` and `src/omega/schema.py:389`; missing FK permits endpoints that have no `memories.node_id`, which application code later deletes as orphaned at `src/omega/sqlite_store/_maintenance.py:341`.
- **Column:** `edges.weight`  
  **Role evidence:** traversal filters `AND weight >= ?` at `src/omega/sqlite_store/_maintenance.py:1071`; tool schema describes min weight `0.0-1.0` at `src/omega/server/tool_schemas.py:313` and edge `weight` `0.0-1.0` at `src/omega/server/tool_schemas.py:317`.  
  **Missing constraint:** CHECK  
  **Risk:** Values outside 0.0 to 1.0 are allowed by schema because `weight REAL DEFAULT 1.0` has no CHECK at `src/omega/schema.py:391`.
- **Column:** `memories.status`  
  **Role evidence:** tool schema enumerates lifecycle states at `src/omega/server/tool_schemas.py:53` through `src/omega/server/tool_schemas.py:56`; project query filters `status = ?` at `src/omega/sqlite_store/_search.py:457`.  
  **Missing constraint:** CHECK  
  **Risk:** Any TEXT value is allowed by schema because `status TEXT DEFAULT 'active'` has no CHECK at `src/omega/schema.py:323`.
- **Column:** `memories.metadata`  
  **Role evidence:** application uses JSON extraction on metadata at `src/omega/server/handlers.py:3694` and `src/omega/integrations/crewai.py:221`.  
  **Missing constraint:** CHECK JSON validity  
  **Risk:** Non-JSON TEXT is allowed by schema because `metadata TEXT` has no CHECK at `src/omega/schema.py:301`; JSON extraction expressions then operate on that column.
- **Column:** `memories.event_type`  
  **Role evidence:** application filters `WHERE event_type = ?` at `src/omega/sqlite_store/_search.py:415` and groups by event type at `src/omega/sqlite_store/_search.py:545`.  
  **Missing constraint:** CHECK or FK  
  **Risk:** NULL and arbitrary TEXT are allowed by schema at `src/omega/schema.py:307`.
- **Column:** `memories.project`  
  **Role evidence:** application scopes with `project = ?` at `src/omega/sqlite_store/_search.py:452`.  
  **Missing constraint:** FK to projects table  
  **Risk:** arbitrary TEXT project values are allowed; no projects table is schema-defined in Phase 1.

### 4.4 Capabilities That Would Require Schema Changes

- **Capability:** Enforced soft delete  
  **What's missing:** A `deleted_at` or `is_deleted` column in `memories`.  
  **Minimum schema change:** `ALTER TABLE memories ADD COLUMN deleted_at TEXT; CREATE INDEX IF NOT EXISTS idx_memories_deleted_at ON memories(deleted_at);`  
  **Existing schema anchor:** lifecycle `status TEXT DEFAULT 'active'` at `src/omega/schema.py:323`.
- **Capability:** Normalized tag filtering  
  **What's missing:** tag table or `memory_tags` join table.  
  **Minimum schema change:** `CREATE TABLE memory_tags (node_id TEXT NOT NULL, tag TEXT NOT NULL, PRIMARY KEY(node_id, tag)); CREATE INDEX idx_memory_tags_tag ON memory_tags(tag);`  
  **Existing schema anchor:** `memories.node_id TEXT UNIQUE NOT NULL` at `src/omega/schema.py:299`.
- **Capability:** Indexed JSON metadata fields  
  **What's missing:** generated columns or expression indexes over JSON paths.  
  **Minimum schema change:** `CREATE INDEX idx_memories_metadata_scope ON memories(json_extract(metadata, '$.scope'));`  
  **Existing schema anchor:** application JSON scope query at `src/omega/integrations/crewai.py:297`.
- **Capability:** FK-enforced edge integrity  
  **What's missing:** foreign keys from `edges.source_id` and `edges.target_id` to `memories.node_id`.  
  **Minimum schema change:** recreate `edges` with `FOREIGN KEY(source_id) REFERENCES memories(node_id)` and `FOREIGN KEY(target_id) REFERENCES memories(node_id)`.  
  **Existing schema anchor:** `edges` DDL at `src/omega/schema.py:386`.
- **Capability:** Schema-defined hybrid search object  
  **What's missing:** view or table combining FTS and vector candidates.  
  **Minimum schema change:** `CREATE VIEW memory_search_base AS SELECT m.node_id, m.content, m.metadata, m.created_at FROM memories m;` plus application query plan for FTS/vector fusion.  
  **Existing schema anchor:** `memories_fts` at `src/omega/schema.py:376` and `memories_vec` at `src/omega/schema.py:366`.
- **Capability:** Project catalog with project constraints  
  **What's missing:** `projects` table and FK from `memories.project`.  
  **Minimum schema change:** `CREATE TABLE projects (project TEXT PRIMARY KEY);` plus edge migration to reference it.  
  **Existing schema anchor:** `memories.project TEXT` at `src/omega/schema.py:308`.

## Appendix: Full DDL Dump

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

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_memories_priority ON memories(priority);
CREATE INDEX IF NOT EXISTS idx_memories_referenced_date ON memories(referenced_date);
CREATE INDEX IF NOT EXISTS idx_memories_entity_id ON memories(entity_id);
CREATE INDEX IF NOT EXISTS idx_memories_agent_type ON memories(agent_type);
CREATE INDEX IF NOT EXISTS idx_memories_canonical_hash ON memories(canonical_hash);

CREATE TABLE IF NOT EXISTS forgetting_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    content_preview TEXT,
    event_type TEXT,
    reason TEXT NOT NULL,
    deleted_at TEXT NOT NULL,
    metadata TEXT
);
CREATE INDEX IF NOT EXISTS idx_forgetting_log_deleted_at ON forgetting_log(deleted_at);
CREATE INDEX IF NOT EXISTS idx_forgetting_log_reason ON forgetting_log(reason);

CREATE TABLE IF NOT EXISTS entity_index (
    entity_name TEXT NOT NULL PRIMARY KEY,
    entity_type TEXT DEFAULT 'person',
    statement_count INTEGER DEFAULT 0,
    outcome_count INTEGER DEFAULT 0,
    contradiction_score REAL DEFAULT 0.0,
    follow_through_rate REAL DEFAULT 0.0,
    first_seen TEXT NOT NULL,
    last_updated TEXT NOT NULL,
    metadata TEXT
);
CREATE INDEX IF NOT EXISTS idx_entity_index_type ON entity_index(entity_type);
CREATE INDEX IF NOT EXISTS idx_entity_index_score ON entity_index(contradiction_score);
CREATE INDEX IF NOT EXISTS idx_entity_index_updated ON entity_index(last_updated);

CREATE INDEX IF NOT EXISTS idx_memories_end_date ON memories(end_date);

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
CREATE INDEX IF NOT EXISTS idx_maintenance_dlq_status ON maintenance_dlq(status);

CREATE INDEX IF NOT EXISTS idx_memories_memory_type ON memories(memory_type);
CREATE INDEX IF NOT EXISTS idx_memories_valid_from ON memories(valid_from);
CREATE INDEX IF NOT EXISTS idx_memories_valid_until ON memories(valid_until);
CREATE UNIQUE INDEX IF NOT EXISTS idx_forgetting_log_node_reason ON forgetting_log(node_id, reason);
CREATE INDEX IF NOT EXISTS idx_memories_derived_from ON memories(derived_from);
CREATE INDEX IF NOT EXISTS idx_memories_source_uri ON memories(source_uri);
CREATE INDEX IF NOT EXISTS idx_memories_status ON memories(status);

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

CREATE INDEX IF NOT EXISTS idx_memories_{col}
ON memories({col});

CREATE INDEX IF NOT EXISTS idx_memories_event_access
ON memories(event_type, access_count);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_vec
USING vec0(embedding float[{embedding_dim}] distance_metric=cosine);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
USING fts5(content, content='memories', content_rowid='id');

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

CREATE INDEX IF NOT EXISTS idx_edges_{col}
ON edges({col});

CREATE TABLE IF NOT EXISTS forgetting_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    content_preview TEXT,
    event_type TEXT,
    reason TEXT NOT NULL,
    deleted_at TEXT NOT NULL,
    metadata TEXT
);
CREATE INDEX IF NOT EXISTS idx_forgetting_log_deleted_at ON forgetting_log(deleted_at);
CREATE INDEX IF NOT EXISTS idx_forgetting_log_reason ON forgetting_log(reason);

CREATE TABLE IF NOT EXISTS cloud_delete_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    local_id INTEGER NOT NULL,
    deleted_at TEXT NOT NULL
);

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
CREATE INDEX IF NOT EXISTS idx_entity_index_type ON entity_index(entity_type);
CREATE INDEX IF NOT EXISTS idx_entity_index_score ON entity_index(contradiction_score);
CREATE INDEX IF NOT EXISTS idx_entity_index_updated ON entity_index(last_updated);

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
CREATE INDEX IF NOT EXISTS idx_memory_clusters_superseded ON memory_clusters(superseded);
CREATE INDEX IF NOT EXISTS idx_memory_clusters_cluster_id ON memory_clusters(cluster_id);

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
CREATE INDEX IF NOT EXISTS idx_thompson_arms_type ON thompson_arms(arm_type);
```
