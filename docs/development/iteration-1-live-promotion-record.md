# Iteration 1 Live Promotion Record

This document serves as an immutable audit log detailing the safe promotion of Iteration 1 (Core Retrieval Tools) into the live OMEGA MCP checkout.

## State Prior to Promotion
- **Live Branch (Pre-Promotion):** `0fd7c2a26e760a5d09c3383a41b0d5f323f0af27` (`/home/akalanka/projects/omega-memory`)
- **Dev Branch (Head to Promote):** `e4e13ad35845067bb07b6c2abddb73c01437ba7e` (`/home/akalanka/projects/omega-memory-dev`)
- **Live DB Backup Snapshot:** `/home/akalanka/.omega/backups/omega-20260611-094052.db`

## What Happens During Live Promotion
1. The new Python code and modified tool schemas from the `dev/retrieval-tools` branch are pulled into the live execution checkout (`/home/akalanka/projects/omega-memory`).
2. Because the agent hooks (e.g. Claude/Codex) execute the Python binary and scripts "in-place" directly from that checkout, the code update immediately stages the new behavior.
3. No configuration files or `omega setup` commands are run.
4. The AI clients must be restarted to force them to spawn a fresh background Python process that loads the newly merged modules.

## How to Do the Live Promotion
1. **Take a Live Backup:**
   ```bash
   /home/akalanka/projects/omega-memory/.venv/bin/python3.12 -m omega.cli backup
   ```
2. **Merge the Code (via PR):**
   - A pull request has been opened and approved: https://github.com/ackalanka/omega-memory/pull/1
   - Merge the PR on GitHub.
3. **Pull into Live Checkout:**
   ```bash
   cd /home/akalanka/projects/omega-memory
   git checkout main
   git pull origin main
   ```
4. **Restart the Session:**
   - Restart the Claude, Codex, or Cursor application so the background MCP processes reload the updated schemas.

## How to Roll Back Safely
If the live agents crash or the new code proves unstable in production, the rollback path is immediate and strictly local:

1. **Revert the Codebase:**
   Return the live checkout to its previous pre-promotion state.
   ```bash
   cd /home/akalanka/projects/omega-memory
   git reset --hard 0fd7c2a26e760a5d09c3383a41b0d5f323f0af27
   ```
2. **Restore the Database (If Corrupted):**
   If the unstable code mangled memory nodes in the SQLite database, simply overwrite the live `omega.db` with the pristine snapshot taken before the promotion:
   ```bash
   cp /home/akalanka/.omega/backups/omega-20260611-094052.db /home/akalanka/.omega/omega.db
   ```
3. **Restart the Session:**
   Restart the AI client application. It will immediately boot the stable, pre-promotion codebase against the healthy database snapshot.
