# OMEGA Usage Examples

Practical examples for common workflows using the CLI and Python API.

## Table of Contents

- [Storing Memories](#storing-memories)
- [Querying Context](#querying-context)
- [Checkpoint and Resume](#checkpoint-and-resume)
- [Maintenance](#maintenance)
- [Reminders](#reminders)
- [Import and Export](#import-and-export)
- [Scripting and Automation](#scripting-and-automation)

---

## Storing Memories

### CLI

```bash
# Store a decision
omega store "We chose PostgreSQL over MongoDB for ACID transaction support" --type decision

# Store a user preference
omega store "Always use early returns, never nest more than 2 levels" --type user_preference

# Store a lesson learned from debugging
omega store "Docker node_modules volume mount shadows container deps -- use anonymous volume" --type lesson

# Store with tags for better retrieval
omega store "API rate limit is 100 req/min per user" --type decision --tags api,rate-limit
```

### Python API

```python
from omega import store, remember

# Store a decision
store("We chose PostgreSQL over MongoDB for ACID transaction support", "decision")

# Store a preference (shorthand -- auto-tags as user_preference)
remember("Always use early returns, never nest more than 2 levels")

# Store with metadata
store(
    "API uses JWT tokens with 15-minute expiry, refresh tokens last 7 days",
    "decision",
    metadata={"tags": ["auth", "jwt"], "project": "backend-api"},
)

# Batch store multiple memories at once
from omega import batch_store

batch_store([
    {"content": "Use pnpm, not npm", "event_type": "user_preference"},
    {"content": "CI runs on GitHub Actions", "event_type": "decision"},
    {"content": "Flaky test: retry network calls in test_sync.py", "event_type": "lesson"},
])
```

---

## Querying Context

### CLI

```bash
# Semantic search -- finds relevant memories even with different wording
omega query "database choice for orders"

# Filter by type
omega query "auth" --type decision

# View recent memory timeline
omega timeline

# View timeline for last 14 days
omega timeline --days 14

# Check what OMEGA knows about a topic
omega query "Docker deployment gotchas"
```

### Python API

```python
from omega import query, timeline, find_similar_memories

# Basic semantic search
results = query("database choice for orders")
print(results)

# Filter by type and limit results
results = query("deployment", event_type="lesson", limit=5)

# Search with tag filter -- only memories tagged "auth"
results = query("token expiry", filter_tags=["auth"])

# View recent timeline
print(timeline(days=7))

# Find memories similar to an existing one
similar = find_similar_memories("memory-id-here", limit=3)
```

---

## Checkpoint and Resume

Use checkpoints to save task state mid-work and resume in a later session.

### In Claude Code (via MCP tools)

During a session, tell Claude:

> "Checkpoint this -- I'm halfway through migrating auth to the new middleware pattern. Files changed: auth.py, middleware.py. Still need to update tests and the login route."

Claude calls `omega_checkpoint` automatically. In your next session:

> "Resume the auth middleware migration."

Claude calls `omega_resume_task` and picks up with full context.

### CLI

```bash
# List recent activity to find checkpointed tasks
omega activity

# Query for checkpointed tasks
omega query "auth middleware migration" --type checkpoint
```

### Python API

```python
from omega import store, query

# Store a checkpoint manually
store(
    "Migrating auth middleware: auth.py and middleware.py updated. "
    "TODO: update tests in test_auth.py and login route in routes/auth.py",
    "checkpoint",
    metadata={"task": "auth-middleware-migration", "progress": "50%"},
)

# Resume by querying for the checkpoint
results = query("auth middleware migration", event_type="checkpoint", limit=1)
print(results)
```

---

## Maintenance

### CLI

```bash
# Check installation health
omega doctor

# View memory stats
omega stats

# Deduplicate and prune old session summaries
omega consolidate

# Cluster and summarize related memories
omega compact

# Back up the database (keeps last 5 backups)
omega backup

# Validate database integrity
omega validate

# View hook errors
omega logs
```

### Python API

```python
from omega import check_health, consolidate, compact, status, type_stats

# Quick status check
print(status())
# => {'node_count': 142, 'db_size_mb': 4.2, 'backend': 'sqlite', ...}

# Health check
print(check_health())

# Memory type breakdown
print(type_stats())

# Consolidate (deduplicate + prune)
print(consolidate(prune_days=30))

# Compact (cluster + summarize)
print(compact())
```

---

## Reminders

### CLI

```bash
# Reminders are managed through Claude via the omega_remind MCP tool.
# Ask Claude: "Remind me to update the API docs before the release next Friday"
```

### Python API

```python
from omega import create_reminder, list_reminders, get_due_reminders, dismiss_reminder

# Create a reminder
create_reminder(
    content="Update API docs before release",
    due_at="2026-03-15T09:00:00Z",
)

# List all active reminders
reminders = list_reminders()
for r in reminders:
    print(f"{r['due_at']}: {r['content']}")

# Check what's due now
due = get_due_reminders(mark_fired=True)

# Dismiss a reminder
dismiss_reminder(reminder_id="reminder-id-here")
```

---

## Import and Export

### CLI

```bash
# Export all memories to JSON
omega export memories.json

# Import memories from JSON (replaces existing)
omega import memories.json
```

### Python API

```python
from omega import export_memories, import_memories

# Export
export_memories("/tmp/omega-backup.json")

# Import (clears existing memories first by default)
import_memories("/tmp/omega-backup.json")

# Import without clearing existing
import_memories("/tmp/omega-backup.json", clear_existing=False)
```

---

## Scripting and Automation

### CI/CD: Store deployment context

```python
#!/usr/bin/env python3
"""Post-deploy hook: store deployment context in OMEGA."""
import os
from omega import store

store(
    f"Deployed {os.environ['GIT_SHA'][:8]} to {os.environ['DEPLOY_ENV']}. "
    f"Branch: {os.environ.get('GIT_BRANCH', 'unknown')}",
    "decision",
    metadata={
        "tags": ["deploy", os.environ["DEPLOY_ENV"]],
        "project": os.environ.get("PROJECT_NAME", "unknown"),
    },
)
```

### Pre-commit: Auto-capture decisions from commit messages

```bash
#!/bin/sh
# .git/hooks/post-commit
MSG=$(git log -1 --pretty=%B)
# Store architectural decisions (commits starting with "decision:" or "ADR:")
case "$MSG" in
  decision:*|ADR:*)
    omega store "$MSG" --type decision
    ;;
esac
```

### Session bootstrap script

```python
#!/usr/bin/env python3
"""Print a quick context briefing for the current project."""
from omega import query, status

s = status()
print(f"OMEGA: {s['node_count']} memories, {s['db_size_mb']:.1f} MB")

# Surface key decisions for this project
results = query("key decisions and preferences", event_type="decision", limit=5)
print(results)
```
