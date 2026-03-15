# OMEGA Architecture

This document provides a deep dive into OMEGA's internal architecture, covering the search pipeline, memory lifecycle, hook system, and storage layer.

## Overview

OMEGA is a local-first memory system for AI agents that stores, retrieves, and manages memories across sessions. The architecture is designed around a single SQLite database with vector search capabilities, running entirely on your machine with no external dependencies.

```
               +---------------------+
               |    Claude Code       |
               |  (or any MCP host)   |
               +----------+----------+
                          | stdio/MCP
               +----------v----------+
               |   OMEGA MCP Server   |
               |   12 memory tools    |
               +----------+----------+
                          |
               +----------v----------+
               |    omega.db (SQLite) |
               | memories | edges |   |
               |     embeddings       |
               +----------------------+
```

## Search Pipeline

OMEGA uses a six-stage search pipeline to retrieve relevant memories. This multi-stage approach combines semantic similarity, keyword matching, and contextual signals to achieve high recall and precision.

### Stage 1: Vector Similarity

**Technology:** sqlite-vec with cosine distance  
**Model:** bge-small-en-v1.5 (384-dimensional embeddings)  
**Purpose:** Semantic similarity matching

The query text is embedded using the same bge-small-en-v1.5 model that was used to embed stored memories. The sqlite-vec extension performs cosine similarity search over the 384-dimensional embedding vectors, returning the top-K candidates ranked by similarity.

**Why vectors?** Embeddings capture semantic meaning, so queries like "Docker volume mount issue" will match memories about "container networking problems" even when the exact words differ.

**Minimum similarity threshold:** 0.60 (memories below this are filtered out)

### Stage 2: Full-Text Search (FTS5)

**Technology:** SQLite FTS5 virtual table  
**Purpose:** Fast keyword matching for exact terms

While embeddings handle semantic similarity, they can miss specific technical terms, error codes, package names, or configuration keys. FTS5 provides fast keyword matching (O(log n) vs O(n) for LIKE queries).

**Features:**
- OR-matching of query words
- Bigram phrase matching for queries with 3+ words (improves precision)
- Automatic synchronization with the main memories table via triggers

**Why both?** The two-source approach (vectors + FTS5) gives better recall than either alone. Embeddings handle semantic similarity, while FTS5 catches exact terms that embeddings might miss.

### Stage 3: Type-Weighted Scoring

**Purpose:** Prioritize high-value memory types

Not all memories are equally important. When you ask "what should I know about the orders service?", a prior architectural decision is almost always more relevant than a session summary from three weeks ago.

**Type weights:**
- `reminder`: 3.0x
- `checkpoint`: 2.5x
- `decision`, `lesson_learned`, `error_pattern`, `user_preference`: 2.0x
- `task_completion`: 1.4x
- `session_summary`: 1.2x
- `coordination_snapshot`: 0.2x
- `file_summary`: 0.05x

**Implementation:** Each memory's relevance score is multiplied by its type weight before ranking.

### Stage 4: Contextual Re-ranking

**Purpose:** Boost memories that match the current context

Pure vector similarity can return semantically similar but contextually irrelevant results. Contextual re-ranking uses three signals to boost relevant memories:

1. **Tag matching:** 10% boost per matching tag
2. **Project matching:** 15% boost if the memory's project matches the current project
3. **Content overlap:** 5% boost per matching context word (capped at 3 words)

**Example:** When editing `auth.py`, memories tagged with `python` or mentioning `auth` in their content are boosted, even if they weren't the top vector matches.

**Context sources:**
- `context_file`: The file being edited (extracts tags from file extension)
- `context_tags`: Explicit tags (e.g., `["python", "auth"]`)
- `project_path`: Current project directory

### Stage 5: Time-Decay Weighting

**Purpose:** Prioritize recently accessed memories

Old, unaccessed memories gradually lose ranking weight over time, reflecting that they may be less relevant to current work.

**Mechanism:**
- Unaccessed memories lose ranking weight over time
- **Floor:** 0.35 (memories never drop below 35% of their original score)
- **Exemptions:** Preferences and error patterns are exempt from decay (they remain relevant indefinitely)

**Why decay?** Without decay, every query would surface the same old memories, drowning out recent context. Decay ensures that frequently accessed memories (which are likely more relevant) rank higher.

### Stage 6: Deduplication

**Purpose:** Remove near-duplicates from results

The final stage removes semantically similar memories from the result set, ensuring diversity in the returned results.

**Implementation:** Jaccard similarity on word sets, with a threshold tuned to remove true duplicates while preserving distinct memories.

## Memory Lifecycle

OMEGA implements an explicit forgetting system to prevent memory bloat and maintain relevance. Without intelligent forgetting, a memory system eventually drowns in noise, surfacing outdated context that leads the agent astray.

### Deduplication

**Purpose:** Prevent storing duplicate or near-duplicate memories

OMEGA uses three mechanisms to detect duplicates:

1. **SHA256 hash:** Exact content duplicates (same text)
2. **Embedding similarity:** Semantic duplicates (similarity ≥ 0.85)
3. **Jaccard similarity:** Per-type word overlap (catches rewordings of the same concept)

**When:** Deduplication happens at write time (`auto_capture` or `store`). If a duplicate is detected, the existing memory's access count is incremented instead of creating a new entry.

### Evolution

**Purpose:** Evolve existing memories rather than creating duplicates

When new content is 55-95% similar to an existing memory (measured by Jaccard similarity), OMEGA appends the new information to the existing memory rather than creating a new entry.

**Process:**
1. Find similar memories (Jaccard similarity 55-95%)
2. Extract new sentences from the new content (sentences with ≥2 new words)
3. Append up to 2 new sentences to the existing memory
4. Increment evolution counter

**Why evolution?** This is inspired by the Zettelkasten method. Instead of creating many similar memories, one memory evolves to contain all related insights, making it easier to find and maintain.

**Example:**
- Existing: "We use PostgreSQL for the orders service"
- New: "We use PostgreSQL for the orders service because we need ACID transactions"
- Result: The existing memory is updated with the additional context

### TTL (Time To Live)

**Purpose:** Automatically expire stale memories

Not all memories should persist forever. Session summaries are useful for immediate context but become stale quickly.

**TTL rules:**
- **Session summaries:** Expire after 1 day
- **Lessons and preferences:** Permanent (never expire)
- **Other types:** Configurable TTL based on event type

**Implementation:** TTL is stored as `ttl_seconds` in the database. A background cleanup process periodically removes expired memories.

### Auto-Relate

**Purpose:** Create relationship edges between similar memories

When a memory is stored, OMEGA automatically creates `related` edges to the top-3 most similar memories (similarity ≥ 0.45).

**Edge types:**
- `related`: General similarity
- `supersedes`: Newer memory replaces older one
- `contradicts`: Memories that contradict each other

**Why edges?** The relationship graph enables traversal queries (`omega_traverse`), allowing users to explore related memories and understand connections between concepts.

### Compaction

**Purpose:** Cluster and summarize related memories

As the memory graph grows, related memories can be consolidated into summary nodes, reducing noise while preserving key information.

**Process:**
1. Cluster memories by Jaccard similarity (threshold 0.60, minimum cluster size 3)
2. Generate a consolidated summary of each cluster
3. Create a new memory node with the summary
4. Mark original memories as `superseded` with a `superseded_by` edge

**When:** Run manually via `omega compact` or `omega_maintain` tool. Compaction is conservative — it only clusters memories of the same event type and requires a minimum cluster size.

**Quality scoring:** Consolidated memories get a quality score (1.0 to 3.0) based on cluster size, reflecting how much information was condensed.

### Decay

**Purpose:** Reduce ranking weight of unaccessed memories

Memories that haven't been accessed in a while gradually lose ranking weight, ensuring that frequently accessed (and likely more relevant) memories rank higher.

**Mechanism:**
- Unaccessed memories lose ranking weight over time
- **Floor:** 0.35 (memories never drop below 35% of their original score)
- **Exemptions:** Preferences and error patterns are exempt from decay

**Why decay?** Without decay, every query would surface the same old memories. Decay ensures recency and relevance in search results.

### Conflict Detection

**Purpose:** Detect and handle contradicting memories

When a new decision contradicts an existing one, OMEGA detects it automatically and handles it appropriately.

**Detection:** Embedding similarity + keyword analysis to identify contradicting content.

**Resolution:**
- **Decisions:** Auto-resolve (newer decision wins, old one marked as superseded)
- **Lessons:** Flagged for review (both memories kept, `contradicts` edge created)

**Why different handling?** Decisions are explicit choices that can change over time. Lessons are learned facts that shouldn't be automatically overwritten — contradictions may indicate a misunderstanding that needs human review.

## Hook System

OMEGA's hook system enables automatic memory capture and surfacing without explicit user commands. Hooks integrate with Claude Code's hook infrastructure to detect decisions, lessons, and relevant context automatically.

### Architecture

All hooks dispatch via `fast_hook.py` with fail-open semantics (if a hook fails, it doesn't break the editor session).

**Fast hook daemon:** Hooks route through a Unix Domain Socket (UDS) to a daemon running inside the MCP server process, keeping hook execution fast (~50ms startup). If the daemon is unavailable, hooks fall back to direct execution.

**Hook types:**
- `SessionStart`: Fires when a new Claude Code session begins
- `Stop`: Fires when a session ends
- `UserPromptSubmit`: Fires on every user prompt
- `PostToolUse`: Fires after tool execution (Edit, Write, Read, Bash, etc.)

### Auto-Capture Hook

**Hook:** `UserPromptSubmit` → `auto_capture.py`  
**Purpose:** Automatically detect and store decisions and lessons from user prompts

**Detection patterns:**

**Decisions:**
- "let's use/go with/switch to..."
- "I decided/chose/picked..."
- "we should/will use..."
- "from now on..."
- "remember that..."

**Lessons:**
- "I learned that..."
- "turns out..."
- "the trick is..."
- "note to self..."
- "the fix was..."
- "never again..."
- "always remember..."

**Quality gates:**
- Minimum prompt length: 20 characters (decisions), 60 characters (lessons)
- Lessons require ≥8 words and technical signals (code snippets, file paths, error messages)
- Maximum 20 captures per session (prevents runaway storage)

**Output:** When a decision or lesson is captured, OMEGA prints a confirmation: `[OMEGA] Captured: decision — summary text`

### Surfacing Hook

**Hook:** `PostToolUse` → `surface_memories.py`  
**Purpose:** Surface relevant memories when editing or reading files

**Triggers:**
- **File edits** (`Edit`, `Write`, `NotebookEdit`): Surfaces memories related to the file
- **File reads** (`Read`): Lightweight surfacing (no lessons)
- **Bash failures:** Auto-captures error patterns

**Process:**
1. Extract file path and derive context tags from file extension
2. Query memories with file name, directory, and tags as context
3. Apply confidence boost (high confidence = 1.2x, low = 0.7x)
4. Filter low-relevance results (relevance < 0.20)
5. Display top 3-5 memories with relevance scores and attribution
6. Traverse linked memories from top result (up to 2 additional memories)

**Attribution:** Memories show when they were created and which session/task they came from: `(2d ago, from "implementing auth")`

**Error recall:** When a Bash command fails, OMEGA proactively searches for past errors and lessons related to the same error pattern, displaying them before auto-capturing the new error.

### Session Lifecycle Hooks

**SessionStart** (`session_start.py`):
- Provides a welcome briefing with recent memories
- Shows user profile and operating protocols
- Surfaces checkpointed tasks that can be resumed

**Stop** (`session_stop.py`):
- Generates a session summary
- Captures key outcomes and decisions made during the session
- Updates memory access counts for surfaced memories

## Storage Layer

OMEGA uses SQLite as its storage backend, with sqlite-vec for vector search and FTS5 for full-text search. Everything runs in a single process with no external dependencies.

### Why SQLite?

**Access pattern:** One machine, one user, mostly reads with occasional writes. The entire database fits in a few megabytes (~10 MB for ~250 memories).

**Concurrency:** SQLite's WAL (Write-Ahead Logging) mode handles concurrent reads from multiple MCP server processes. OMEGA includes retry logic with exponential backoff for rare write contention under heavy multi-process usage.

**Why not a vector database?** For a system that stores hundreds (not millions) of vectors, adding a separate database process felt like overengineering. `sqlite-vec` provides cosine similarity search in the same process with zero external dependencies.

### Database Schema

**Main tables:**
- `memories`: Core memory nodes (content, metadata, embeddings)
- `edges`: Relationship edges between memories (related, supersedes, contradicts)
- `memories_vec`: Virtual table for vector search (sqlite-vec)
- `memories_fts`: Virtual table for full-text search (FTS5)

**Key columns:**
- `node_id`: Unique identifier (UUID)
- `content`: Memory text
- `metadata`: JSON metadata (event_type, tags, project, etc.)
- `created_at`, `last_accessed`: Timestamps
- `access_count`: Number of times accessed
- `ttl_seconds`: Time to live
- `content_hash`: SHA256 hash for deduplication
- `canonical_hash`: Normalized hash for semantic deduplication

**Indexes:** Indexes on `node_id`, `event_type`, `session_id`, `project`, `created_at`, `content_hash`, `last_accessed`, and compound indexes for frequent query patterns.

### Vector Search (sqlite-vec)

**Extension:** sqlite-vec (loads at runtime)  
**Virtual table:** `memories_vec`  
**Embedding dimension:** 384  
**Distance metric:** Cosine similarity

**How it works:**
1. Embeddings are stored as float32 arrays in the virtual table
2. Query embeddings are generated using the same bge-small-en-v1.5 model
3. sqlite-vec performs cosine similarity search, returning top-K results
4. Results are joined with the main `memories` table to get full memory data

**Fallback:** If sqlite-vec is not available, OMEGA falls back to brute-force similarity calculation (slower but functional).

### Full-Text Search (FTS5)

**Virtual table:** `memories_fts`  
**Content:** Synchronized with `memories.content` via triggers

**Features:**
- OR-matching of query words
- Bigram phrase matching for multi-word queries
- Automatic synchronization (INSERT/UPDATE/DELETE triggers)

**Fallback:** If FTS5 is not available, OMEGA falls back to LIKE queries (slower but functional).

### WAL Mode

SQLite runs in WAL (Write-Ahead Logging) mode for better concurrency:
- Multiple readers can access the database simultaneously
- Writers don't block readers
- Better performance for read-heavy workloads

### Retry Logic

Under heavy multi-process usage (3+ MCP server processes), write contention can occur. OMEGA includes retry logic with exponential backoff:
- **Attempts:** 3 retries
- **Base delay:** 1.0 seconds
- **Backoff:** Exponential (1s, 2s, 4s)

This handles the rare case where `busy_timeout` expires before a write completes.

## MCP Tools Reference

OMEGA exposes 12 MCP tools for memory management:

| Tool | What it does |
|------|-------------|
| `omega_store` | Store typed memory (decision, lesson, error, preference, summary) |
| `omega_query` | Semantic or phrase search with tag filters and contextual re-ranking |
| `omega_lessons` | Cross-session lessons ranked by access count |
| `omega_welcome` | Session briefing with recent memories and profile |
| `omega_protocol` | Retrieve operating rules and behavioral guidelines |
| `omega_profile` | Read or update the user profile |
| `omega_checkpoint` | Save task state for cross-session continuity |
| `omega_resume_task` | Resume a previously checkpointed task |
| `omega_memory` | Manage a specific memory (edit, delete, feedback, similar, traverse) |
| `omega_remind` | Set, list, or dismiss time-based reminders |
| `omega_maintain` | System housekeeping (health, consolidate, compact, backup, restore) |
| `omega_stats` | Analytics: type breakdown, session stats, weekly digest, access rates |

## CLI Reference

| Command | Description |
|---------|-------------|
| `omega setup` | Create dirs, download model, register MCP, install hooks |
| `omega doctor` | Verify installation health |
| `omega status` | Memory count, store size, model status |
| `omega query <text>` | Search memories by semantic similarity |
| `omega store <text>` | Store a memory with a specified type |
| `omega timeline` | Show memory timeline grouped by day |
| `omega activity` | Show recent session activity overview |
| `omega stats` | Memory type distribution and health summary |
| `omega consolidate` | Deduplicate, prune, and optimize memory |
| `omega compact` | Cluster and summarize related memories |
| `omega backup` | Back up omega.db (keeps last 5) |
| `omega validate` | Validate database integrity |
| `omega logs` | Show recent hook errors |
| `omega migrate-db` | Migrate legacy JSON to SQLite |

## Memory Footprint

**Startup:** ~31 MB RSS (Python interpreter + SQLite)  
**After first query:** ~337 MB RSS (ONNX model loaded into memory)  
**Database:** ~10.5 MB for ~242 memories

**Breakdown:**
- ONNX embedding model: ~90 MB on disk, ~306 MB in RAM when loaded
- SQLite database: ~10.5 MB (includes embeddings, metadata, indexes)
- Python overhead: ~31 MB

**Why this matters:** OMEGA is designed to run in the background without impacting system performance. The memory footprint is reasonable for a local-first system with no external dependencies.

## Install from Source

```bash
git clone https://github.com/omega-memory/omega-memory.git
cd omega-memory
uv venv && uv pip install -e ".[server,dev]"   # recommended (fast, isolated)
# or: pip3 install -e ".[server,dev]"           # traditional pip
omega setup
```

`omega setup` will:
1. Create `~/.omega/` directory
2. Download the ONNX embedding model (~90 MB) to `~/.cache/omega/models/`
3. Register `omega-memory` as an MCP server in `~/.claude.json`
4. Install session hooks in `~/.claude/settings.json`
5. Add a managed `<!-- OMEGA:BEGIN -->` block to `~/.claude/CLAUDE.md`

All changes are idempotent (safe to run multiple times).
