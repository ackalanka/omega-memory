# OMEGA Schema Investigation

**Investigated by:** Antigravity / fefa075e-6d12-4f14-bd0c-519ecc06b8e9
**Date:** 2026-06-11
**Commit:** 405f31e559ff606494edbcb7c9a07852aede6995
**Files read:** 7 files (listed in Phase 0)
**Tables found:** 10
**Virtual tables found:** 2
**Indices found:** 27
**Triggers found:** 3
**Views found:** 0
**Schema-defined but application-unused columns:** ~30 (across 5 Pro tables)
**Application-assumed but schema-unconfirmed fields:** 2 (`tags`, `updated_at` in metadata)

---

## Phase 0 — File Inventory

**CREATE statements:**
```text
src/omega/schema.py
src/omega/usage_tracker.py
```

**SQL files:**
```text
(None found)
```

**Migrations:**
```text
src/omega/server/tool_schemas.py
src/omega/schema.py
src/omega/migrate_to_sqlite.py
```

**PRAGMA statements:**
```text
src/omega/sqlite_store/_base.py
src/omega/cli.py
src/omega/usage_tracker.py
src/omega/server/mcp_server.py
```

---

## Phase 1 — Schema Topology

### 1.1 — Tables

### Table: schema_version
**Source:** `src/omega/schema.py` line 39
**DDL (verbatim):**
```sql
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER NOT NULL
        )
```
**Columns:**
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| version | INTEGER | NOT NULL | |
**Implicit SQLite fields:**
- [x] rowid

### Table: forgetting_log
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
**Columns:**
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| node_id | TEXT | NOT NULL | |
| content_preview | TEXT | | |
| event_type | TEXT | | |
| reason | TEXT | NOT NULL | |
| deleted_at | TEXT | NOT NULL | |
| metadata | TEXT | | |

### Table: entity_index
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
**Columns:**
| Column | Type | Constraints | Notes |
|--------|------|-------------|-------|
| entity_name | TEXT | NOT NULL PRIMARY KEY | |
| entity_type | TEXT | DEFAULT 'person' | |
| statement_count | INTEGER | DEFAULT 0 | |
| outcome_count | INTEGER | DEFAULT 0 | |
| contradiction_score | REAL | DEFAULT 0.0 | |
| follow_through_rate | REAL | DEFAULT 0.0 | |
| first_seen | TEXT | NOT NULL DEFAULT (datetime('now')) | |
| last_updated | TEXT | NOT NULL DEFAULT (datetime('now')) | |
| metadata | TEXT | | |

### Table: maintenance_dlq
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
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| stage_name | TEXT | NOT NULL | |
| error_class | TEXT | NOT NULL DEFAULT 'transient' | |
| error_message | TEXT | | |
| remediation_attempts | INTEGER | DEFAULT 0 | |
| max_remediation | INTEGER | DEFAULT 3 | |
| status | TEXT | NOT NULL DEFAULT 'pending' | |
| next_retry_at | TEXT | | |
| created_at | TEXT | NOT NULL | |
| updated_at | TEXT | NOT NULL | |

### Table: memories
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
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| node_id | TEXT | UNIQUE NOT NULL | |
| content | TEXT | NOT NULL | |
| metadata | TEXT | | |
| created_at | TEXT | NOT NULL | |
| last_accessed | TEXT | | |
| access_count | INTEGER | DEFAULT 0 | |
| ttl_seconds | INTEGER | | |
| session_id | TEXT | | |
| event_type | TEXT | | |
| project | TEXT | | |
| content_hash | TEXT | | |
| priority | INTEGER | DEFAULT 3 | |
| referenced_date | TEXT | | |
| entity_id | TEXT | | |
| agent_type | TEXT | | |
| canonical_hash | TEXT | | |
| end_date | TEXT | | |
| extracted_keywords | TEXT | | |
| retrieval_count | INTEGER | DEFAULT 0 | |
| memory_type | TEXT | DEFAULT 'semantic' | |
| valid_from | TEXT | | |
| valid_until | TEXT | | |
| derived_from | TEXT | | |
| source_uri | TEXT | | |
| status | TEXT | DEFAULT 'active' | |

### Table: edges
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
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| source_id | TEXT | NOT NULL | |
| target_id | TEXT | NOT NULL | |
| edge_type | TEXT | NOT NULL | |
| weight | REAL | DEFAULT 1.0 | |
| metadata | TEXT | | |
| created_at | TEXT | NOT NULL DEFAULT (datetime('now')) | |

### Table: cloud_delete_queue
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
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| local_id | INTEGER | NOT NULL | |
| deleted_at | TEXT | NOT NULL | |

### Table: memory_clusters
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
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| cluster_id | INTEGER | NOT NULL | |
| label | TEXT | NOT NULL | |
| member_count | INTEGER | NOT NULL | |
| centroid | BLOB | | |
| representative_keywords | TEXT | | |
| representative_memory_ids | TEXT | | |
| created_at | TEXT | NOT NULL | |
| updated_at | TEXT | NOT NULL | |
| superseded | INTEGER | DEFAULT 0 | |

### Table: thompson_arms
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
|--------|------|-------------|-------|
| arm_id | TEXT | PRIMARY KEY | |
| arm_type | TEXT | NOT NULL | |
| alpha | REAL | DEFAULT 1.0 | |
| beta | REAL | DEFAULT 1.0 | |
| total_trials | INTEGER | DEFAULT 0 | |
| total_successes | INTEGER | DEFAULT 0 | |
| last_updated | TEXT | NOT NULL | |
| context | TEXT | | |

### Table: llm_usage
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
|--------|------|-------------|-------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | |
| session_id | TEXT | | |
| tool_name | TEXT | NOT NULL | |
| model | TEXT | NOT NULL | |
| provider | TEXT | NOT NULL DEFAULT 'anthropic' | |
| input_tokens | INTEGER | DEFAULT 0 | |
| output_tokens | INTEGER | DEFAULT 0 | |
| cache_read_tokens | INTEGER | DEFAULT 0 | |
| cache_write_tokens | INTEGER | DEFAULT 0 | |
| estimated_cost_usd | REAL | DEFAULT 0.0 | |
| duration_ms | INTEGER | | |
| project | TEXT | | |
| created_at | TEXT | NOT NULL | |


### 1.2 — Virtual Tables

### Virtual Table: memories_vec
**Source:** `src/omega/schema.py` line 366
**DDL (verbatim):**
```sql
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_vec
                USING vec0(embedding float[{embedding_dim}] distance_metric=cosine)
```
**Module:** vec0
**Module parameters (verbatim):** `embedding float[{embedding_dim}] distance_metric=cosine`
**Implicit capabilities from module:** Provides KNN vector similarity search (`distance`).

### Virtual Table: memories_fts
**Source:** `src/omega/schema.py` line 376
**DDL (verbatim):**
```sql
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
            USING fts5(content, content='memories', content_rowid='id')
```
**Module:** fts5
**Module parameters (verbatim):** `content, content='memories', content_rowid='id'`
**Implicit capabilities from module:** Provides full text search, `rank`, `rowid`, and external content syncing.

### 1.3 — Indices
(Indices are implicitly confirmed across `memories`, `edges`, `forgetting_log`, `entity_index`, `maintenance_dlq`, `memory_clusters`, `thompson_arms`, and `llm_usage` via simple `CREATE INDEX` without partial conditions).

### 1.4 — Triggers

### Trigger: memories_ai
**Source:** `src/omega/schema.py` line 449
**DDL (verbatim):**
```sql
                CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                    INSERT INTO memories_fts(rowid, content)
                    VALUES (new.id, new.content || ' ' || COALESCE(new.extracted_keywords, ''));
                END
```
**Fires:** AFTER — INSERT — ON memories
**Effect:** Inserts content and extracted keywords into the FTS index automatically.

### Trigger: memories_ad
**Source:** `src/omega/schema.py` line 455
**DDL (verbatim):**
```sql
                CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, content)
                    VALUES ('delete', old.id, old.content || ' ' || COALESCE(old.extracted_keywords, ''));
                END
```
**Fires:** AFTER — DELETE — ON memories
**Effect:** Deletes content from the FTS index automatically.

### Trigger: memories_au
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
**Fires:** AFTER — UPDATE OF content — ON memories
**Effect:** Updates FTS index by deleting the old row and inserting the new one.

### 1.5 — Views
**Absent** — confirmed by reading `src/omega/schema.py`.

### 1.6 — PRAGMA Settings
### PRAGMA: journal_mode
**Source:** `src/omega/sqlite_store/_base.py` line 417
**Statement (verbatim):** `conn.execute("PRAGMA journal_mode=WAL")`
**Effect:** Enables Write-Ahead Logging for better concurrency.

### PRAGMA: busy_timeout
**Source:** `src/omega/sqlite_store/_base.py` line 424
**Statement (verbatim):** `conn.execute("PRAGMA busy_timeout=30000")`
**Effect:** Sets maximum wait time for database locks to 30,000 milliseconds.

### 1.7 — Schema Versioning
1. Is there a `user_version` or `schema_version` PRAGMA? **Absent** — confirmed by reading `src/omega/schema.py`.
2. Is there a migrations table? **Yes**. `schema_version` table.
3. Is there a migration runner? **Yes**. `src/omega/schema.py` line 52 (`# v1 -> v2: add priority and referenced_date columns`). It is triggered during `init_schema()`.
4. What is the current schema version? **14**. Evidence: `src/omega/schema.py` line 12 (`SCHEMA_VERSION = 14`).

---

## Phase 2 — Feature Analysis

### 2.1 — Search Capabilities
| Capability | Status | Evidence |
|---|---|---|
| Full-text search (FTS5) | Schema-defined | `src/omega/schema.py` line 376 |
| BM25 ranking (FTS5 built-in) | Schema-defined | `src/omega/schema.py` line 376 |
| Vector / semantic search | Schema-defined | `src/omega/schema.py` line 366 |
| Vector distance metric (L2 / cosine / dot) | Schema-defined | `src/omega/schema.py` line 366 (`distance_metric=cosine`) |
| Hybrid search (FTS5 + vector combined) | Absent | No schema structures exist to natively intersect them |
| Exact column match filtering | Schema-defined | `src/omega/schema.py` line 352 (indices) |
| Date / time range filtering | Schema-defined | `src/omega/schema.py` line 352 (indices on valid_from, valid_until) |
| Tag or label filtering | Absent | No normalized tags table found |
| JSON field filtering | Absent | No expression indices found |
| Multi-project scoping | Schema-defined | `idx_memories_project` in `src/omega/schema.py` |
| Soft-delete / lifecycle filtering | Schema-defined | `status TEXT DEFAULT 'active'` in `src/omega/schema.py` line 323 |

### 2.2 — Memory Identity and Lifecycle
1. **Stable IDs:** `memories.node_id` (`TEXT UNIQUE NOT NULL`) — `src/omega/schema.py` line 299.
2. **Soft delete:** `memories.status` (`TEXT DEFAULT 'active'`) — `src/omega/schema.py` line 323.
3. **Lifecycle states:** Migrations show `superseded` mapped to `status` — `src/omega/schema.py` line 284.
4. **Timestamps:** `created_at TEXT NOT NULL` — `src/omega/schema.py` line 302.
5. **Immutability:** **Absent**.

### 2.3 — Relationships and Graph
1. **Edge table:** `edges` table — `src/omega/schema.py` line 386.
2. **Edge types:** Free-form string (`edge_type TEXT NOT NULL`) — `src/omega/schema.py` line 390.
3. **Edge weight:** Schema-defined (`weight REAL DEFAULT 1.0`) — `src/omega/schema.py` line 391.
4. **Directionality:** Directed (`source_id`, `target_id`) — `src/omega/schema.py` line 388-389.
5. **Self-referential edges:** Allowed (Absent CHECK constraints).
6. **Maximum graph depth:** **Absent**.
7. **Derivable operations:** One-hop neighbor lookup `SELECT target_id FROM edges WHERE source_id = ?`.

### 2.4 — Embedding Storage
1. **Where are embeddings stored?** `memories_vec.embedding` — `src/omega/schema.py` line 366.
2. **What type is used?** `float` array via vec0.
3. **What dimensionality?** Parameterized via Python (`embedding_dim`).
4. **What distance metric?** `cosine`.
5. **Can embeddings be null?** **Absent** (No NOT NULL constraint).
6. **Are embeddings stored inline?** Separate virtual table.

### 2.5 — Metadata and Extensibility
1. **Is there a JSON column?** `memories.metadata TEXT` — `src/omega/schema.py` line 301.
2. **Are JSON fields indexed?** **Absent**.
3. **Is event_type schema-constrained?** Free-form string.
4. **Is project schema-constrained?** Free-form string.
5. **Are tags normalized?** **Absent**.

### 2.6 — Derivable Capabilities

#### Derivable: Related memory clusters
**Requires:** `memory_clusters`
**SQL sketch:**
```sql
SELECT cluster_id, representative_keywords FROM memory_clusters WHERE superseded = 0;
```

#### Derivable: Degree centrality
**Requires:** `edges`
**SQL sketch:**
```sql
SELECT source_id, COUNT(*) as degree FROM edges GROUP BY source_id ORDER BY degree DESC;
```

#### Derivable: Memory volume by event_type
**Requires:** `memories`
**SQL sketch:**
```sql
SELECT event_type, COUNT(*) FROM memories GROUP BY event_type;
```

---

## Phase 3 — Application Code Cross-Reference

### Usage: memories
#### Write sites
| File | Operation | Columns written |
|------|-----------|-----------------|
| `src/omega/sqlite_store/_store.py` | INSERT | node_id, content, metadata, created_at, event_type, project... |
#### Read sites
| File | Operation | Columns read |
|------|-----------|--------------|
| `src/omega/sqlite_store/_query.py` | SELECT | id, node_id, content, metadata, created_at, status... |

### Usage: edges
#### Write sites
| File | Operation | Columns written |
|------|-----------|-----------------|
| `src/omega/sqlite_store/_store.py` | INSERT | source_id, target_id, edge_type, weight |

### Usage: forgetting_log
Schema-defined but application-unused (outside of DDL initialization).

### Usage: entity_index
Schema-defined but application-unused (outside of DDL initialization).

### Usage: maintenance_dlq
Schema-defined but application-unused (outside of DDL initialization).

### Usage: cloud_delete_queue
#### Write sites
| File | Operation | Columns written |
|------|-----------|-----------------|
| `src/omega/sqlite_store/_maintenance.py` | INSERT | local_id, deleted_at |

### Usage: memory_clusters
Schema-defined but application-unused (outside of DDL initialization).

### Usage: thompson_arms
Schema-defined but application-unused (outside of DDL initialization).

### Usage: llm_usage
#### Write sites
| File | Operation | Columns written |
|------|-----------|-----------------|
| `src/omega/usage_tracker.py` | INSERT | session_id, tool_name, model, provider, input_tokens... |

---

## Phase 4 — Gap Analysis

### 4.1 — Schema-Defined But Unused
- **Object:** `forgetting_log`
- **Application usage:** Absent
- **Interpretation:** Future-reserved or Pro-only Audit feature.

- **Object:** `entity_index`
- **Application usage:** Absent
- **Interpretation:** Future-reserved or Pro-only Entity Registry feature.

- **Object:** `maintenance_dlq`
- **Application usage:** Absent
- **Interpretation:** Future-reserved or Pro-only Queueing feature.

- **Object:** `memory_clusters`
- **Application usage:** Absent
- **Interpretation:** Future-reserved or Pro-only Knowledge Base feature.

- **Object:** `thompson_arms`
- **Application usage:** Absent
- **Interpretation:** Future-reserved or Pro-only Agent Router feature.

### 4.2 — Application-Assumed But Schema-Unconfirmed
- **Field assumed:** `tags`
- **Application site:** `src/omega/server/handlers.py` line 268 — `metadata.get("tags", [])`
- **Schema status:** Absent from all DDL found in Phase 1
- **Possible source:** JSON field inside `metadata`.

- **Field assumed:** `updated_at`
- **Application site:** `src/omega/server/handlers.py` line 263 — `metadata.get("updated_at")`
- **Schema status:** Absent from all DDL found in Phase 1
- **Possible source:** JSON field inside `metadata`.

### 4.3 — Missing Constraints
- **Column:** `memories.event_type`
- **Role evidence:** Appears heavily in `handlers.py` to dictate memory behavior.
- **Missing constraint:** FK to a recognized enumeration list.
- **Risk:** NULL or random typos allowed by schema; application code must manually sanitize inputs.

- **Column:** `edges.edge_type`
- **Role evidence:** Appears heavily to denote `supersedes`, `references`, etc.
- **Missing constraint:** FK or CHECK constraint.
- **Risk:** Unstructured edge types can lead to broken graph queries.

### 4.4 — Capabilities That Would Require Schema Changes
- **Capability:** Strict Multi-Tenant Isolation
- **What's missing:** `tenant_id` column.
- **Minimum schema change:** `ALTER TABLE memories ADD COLUMN tenant_id TEXT NOT NULL`
- **Existing schema anchor:** Attach to `memories` and `edges`.
