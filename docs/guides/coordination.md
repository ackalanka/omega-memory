# Multi-Agent Coordination

## Overview

When multiple Claude Code agents work on the same codebase simultaneously, OMEGA prevents conflicts through file locking, branch claims, task management, intent broadcasting, and agent-to-agent messaging.

All coordination is **fail-open**: if OMEGA is unavailable, agents can still work. No coordination operation blocks code execution. This design ensures that the coordination layer is purely additive --- it prevents conflicts when available but never causes them.

Coordination state lives in SQLite alongside memory data. Sessions auto-expire after 10 minutes of inactivity (no heartbeat). File claims auto-expire after 10 minutes. The system is designed for 2-6 concurrent agents on a single machine.

## Quick Example

```
# Agent 1: Register and claim files
omega_session_register(session_id="agent-1", capabilities=["code", "test"], task="Implement auth module")
omega_file_claim(session_id="agent-1", file_path="/src/auth.py", task="Adding OAuth flow")

# Agent 2: Check before editing
omega_file_check(file_path="/src/auth.py")
# Returns: claimed by agent-1 for "Adding OAuth flow"

# Agent 2: Work on something else, send a message
omega_send_message(session_id="agent-2", to_session="agent-1", subject="Need auth.py soon", msg_type="request")

# Agent 1: Check inbox, release when done
omega_inbox(session_id="agent-1")
omega_file_release(session_id="agent-1", file_path="/src/auth.py")
```

## Tools Reference

### Sessions

| Tool | Purpose |
|------|---------|
| `omega_session_register` | Register agent with capabilities (e.g., `["code", "test", "review"]`) and task description |
| `omega_session_heartbeat` | Signal activity; resets the 10-minute expiry. Called automatically by PostToolUse hooks. |
| `omega_session_deregister` | End session cleanly, releasing all file claims, branch claims, and intents |
| `omega_sessions_list` | List all active agent sessions with their tasks and capabilities |
| `omega_session_snapshot` | Snapshot session state (claims, intents, task) before risky operations |
| `omega_session_recover` | Recover context from a crashed predecessor's most recent snapshot |

### Files and Branches

| Tool | Purpose |
|------|---------|
| `omega_file_claim` | Claim exclusive access to a file. Returns conflict info if another agent owns it. Supports `force=True` as a last resort. |
| `omega_file_release` | Release your claim on a file so other agents can access it |
| `omega_file_check` | Check who owns a file (if anyone). Use before editing to avoid conflicts. |
| `omega_branch_claim` | Claim exclusive access to a git branch. Protected branches (`main`, `master`, `develop`, `release`) are blocked. |
| `omega_branch_release` | Release your claim on a branch |
| `omega_branch_check` | Check who owns a branch (if anyone). Use before branch operations. |

### Tasks

| Tool | Purpose |
|------|---------|
| `omega_task_create` | Create a task with title, description, priority, project, and `depends_on` (list of task IDs) |
| `omega_task_claim` | Claim a pending task. Only unclaimed tasks can be claimed. |
| `omega_task_complete` | Mark a task done with a result summary. Unblocks dependent tasks. |
| `omega_task_fail` | Mark a task as failed with a reason. Does NOT unblock dependents. |
| `omega_task_cancel` | Cancel a task. Only the owning session or creator can cancel. Does NOT unblock dependents. |
| `omega_task_progress` | Update progress (0-100%) with an optional status note |
| `omega_task_deps` | View the dependency graph for a task: what blocks it and what it blocks |
| `omega_tasks_list` | List tasks with optional project and status filters (`pending`, `in_progress`, `completed`, `failed`, `canceled`) |

### Intents and Messaging

| Tool | Purpose |
|------|---------|
| `omega_intent_announce` | Broadcast planned work: description, target files, target branch, TTL (default 30 minutes) |
| `omega_intent_check` | Check if your announced files/branch overlap with other agents' intents |
| `omega_send_message` | Send a message to a specific agent or broadcast to all on the project. Types: `request`, `inform`, `acknowledge`, `reject`, `complete`. |
| `omega_inbox` | Check your inbox. Marks fetched unread messages as read. Filter by type. |
| `omega_find_agents` | Find active agents with a matching capability (e.g., `"test"`, `"review"`, `"deploy"`) |

### Dashboard and Audit

| Tool | Purpose |
|------|---------|
| `omega_coord_status` | Full coordination dashboard: active sessions, file/branch claims, intents, detected conflicts |
| `omega_audit` | Query the coordination audit log: recent tool calls with session, arguments, and results |
| `omega_git_events` | Recent git events tracked by coordination: pushes, divergence warnings, merges |

## Common Workflows

### Session Lifecycle

Every agent session follows the same pattern:

1. **Register** at session start (handled automatically by the SessionStart hook):
   ```
   omega_session_register(
       session_id="agent-1",
       capabilities=["code", "test"],
       task="Implement payment processing",
       project="/Users/me/Projects/myapp"
   )
   ```

2. **Heartbeat** during work (handled automatically by PostToolUse hooks):
   ```
   omega_session_heartbeat(session_id="agent-1")
   ```

3. **Deregister** at session end (handled automatically by the Stop hook):
   ```
   omega_session_deregister(session_id="agent-1")
   ```

If a session crashes without deregistering, it will auto-expire after 10 minutes of no heartbeat. The next agent can recover its context:
```
omega_session_recover(project="/Users/me/Projects/myapp")
```

### File Claims

Files are automatically claimed when you edit them (via the PostToolUse hook on Edit/Write/NotebookEdit). The PreToolUse hook on Edit/Write/NotebookEdit checks for conflicts before allowing edits.

**Manual claim** (for planning ahead):
```
omega_file_claim(session_id="agent-1", file_path="/src/models/user.py", task="Adding email validation")
```

**Check before editing**:
```
omega_file_check(file_path="/src/models/user.py")
```

**Release when done**:
```
omega_file_release(session_id="agent-1", file_path="/src/models/user.py")
```

**Force-claim as last resort** (audited):
```
omega_file_claim(session_id="agent-2", file_path="/src/models/user.py", force=True)
```

When a `[DEADLOCK]` alert appears (circular wait detected), release one of your claimed files to break the cycle:
```
omega_file_release(session_id="agent-1", file_path="/src/shared/utils.py")
```

### Branch Claims

Claim a branch before pushing to prevent divergence:

```
omega_branch_claim(session_id="agent-1", project="/Users/me/Projects/myapp", branch="feature/payments")
```

Protected branches (`main`, `master`, `develop`, `release`) cannot be claimed --- this prevents accidental direct pushes.

The PreToolUse hook on Bash guards `git push` commands: it checks for branch claims and warns about divergence.

Check branch ownership:
```
omega_branch_check(project="/Users/me/Projects/myapp", branch="feature/payments")
```

Release when done:
```
omega_branch_release(session_id="agent-1", project="/Users/me/Projects/myapp", branch="feature/payments")
```

### Task Management

Tasks enable formal work decomposition with dependency chains.

**Create a task chain**:
```
# Independent task
task1 = omega_task_create(session_id="agent-1", title="Write database schema", project="/myapp", priority=2)

# Dependent task (blocked until task1 completes)
task2 = omega_task_create(session_id="agent-1", title="Implement API endpoints", project="/myapp", depends_on=[task1.id])

# Another dependent
task3 = omega_task_create(session_id="agent-1", title="Write integration tests", project="/myapp", depends_on=[task2.id])
```

**Claim and work**:
```
omega_task_claim(task_id=1, session_id="agent-1")
omega_task_progress(task_id=1, session_id="agent-1", progress=50, status_note="Schema for users and orders done")
omega_task_complete(task_id=1, session_id="agent-1", result="Created 4 tables: users, orders, products, inventory")
# task2 is now unblocked and available for claiming
```

**View dependencies**:
```
omega_task_deps(task_id=2)
# Shows: blocked by task1 (completed), blocks task3 (pending)
```

**List tasks**:
```
omega_tasks_list(project="/myapp", status="pending")
```

### Intent Broadcasting

Before starting a block of work, announce what you plan to do:

```
omega_intent_announce(
    session_id="agent-1",
    description="Refactoring authentication module",
    target_files=["/src/auth.py", "/src/middleware.py", "/tests/test_auth.py"],
    target_branch="feature/auth-refactor",
    ttl_minutes=30
)
```

Other agents check for overlaps:
```
omega_intent_check(session_id="agent-2")
# Returns overlaps with agent-1's announced files
```

### Agent Messaging

**Request help**:
```
omega_send_message(
    session_id="agent-2",
    to_session="agent-1",
    subject="Need auth.py released",
    body="I need to update the JWT validation in auth.py. Can you release it when you're done?",
    msg_type="request"
)
```

**Broadcast to all agents on the project**:
```
omega_send_message(
    session_id="agent-1",
    subject="Breaking change in user model",
    body="Added required email_verified field to User. Update your code accordingly.",
    msg_type="inform"
)
```

**Check inbox**:
```
omega_inbox(session_id="agent-1", unread_only=True)
```

**Find a specialist**:
```
omega_find_agents(capability="test", project="/myapp")
```

### Conflict Resolution

When coordination detects conflicts, it surfaces alerts:

- **`[DEADLOCK]`** --- Two agents are waiting on each other's files. Release one file to break the cycle.
- **`[COORD]`** --- Peer roster shown at session start. Check before advising or starting work.
- **`[INBOX]`** --- Messages waiting from other agents. Check with `omega_inbox`.

For persistent conflicts:
1. Check the full dashboard: `omega_coord_status`
2. Review the audit log: `omega_audit(limit=20)`
3. Check git events: `omega_git_events(project="/myapp")`
4. As a last resort, force-claim the file: `omega_file_claim(..., force=True)` (this is audited)

### Snapshot and Recovery

Before risky operations (rebases, large refactors):
```
omega_session_snapshot(session_id="agent-1", reason="Before rebase onto main")
```

If a predecessor crashed:
```
omega_session_recover(project="/Users/me/Projects/myapp")
# Returns the most recent snapshot: claims, intents, task, and state
```

## Tips

- **Hooks handle most coordination automatically.** Session registration, heartbeats, file claims on edit, and pre-edit conflict checks all happen via hooks. You rarely need to call coordination tools manually.
- **Check before advising.** Do not just check coordination before editing --- check before recommending what to work on. Run `omega_coord_status` to see what peers are doing.
- **File claims expire in 10 minutes.** If an agent goes silent, its claims expire. You do not need to force-claim unless there is an active conflict.
- **Protected branches are sacred.** `main`, `master`, `develop`, and `release` cannot be branch-claimed. Work on feature branches and merge through PRs.
- **Use task dependencies for ordered work.** The `depends_on` parameter ensures tasks execute in the right order across agents.
- **Intent announcements have TTLs.** Default is 30 minutes. For longer work, set a higher `ttl_minutes` or re-announce periodically.
- **Messages support threading.** Use `context_id` to group related messages into a conversation thread.
- **Force-claim is audited.** Every force-claim is logged in the audit trail. Use it only when coordination has broken down and communication has failed.
- **Fail-open means safe fallback.** If OMEGA coordination is down, all guards return "allowed." You can always work --- you just lose conflict detection temporarily.
- **Nicknames make agents readable.** Each session gets a deterministic nature-word nickname (e.g., "Cedar", "Falcon") derived from the session ID, making logs and alerts easier to scan.
