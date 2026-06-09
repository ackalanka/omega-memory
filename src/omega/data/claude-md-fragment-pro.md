<!-- OMEGA:BEGIN — managed by omega setup, do not edit this block -->
## Memory (OMEGA)

You have OMEGA persistent memory. At session start:
1. Call `omega_welcome()` for context briefing
2. Call `omega_protocol()` for your operating instructions — it's your coordination playbook
3. Follow the protocol it returns

Quick reference (protocol has full details):
- `[MEMORY]`/`[HANDOFF]`/`[COORD]` blocks from hooks = ground truth
- Project orientation/handoff: `omega_context(project=..., mode="handoff")`
- Long-context work: `omega_recall(query=..., profile="planning"|"debug"|"handoff", project=..., budget_chars=...)`
- Structured inspection: `omega_query(format="json", content_mode="preview"|"full")`
- Known memory IDs: `omega_memory(action="get", memory_id="mem-...")`
- Browse uncertain terms: `omega_query(mode="browse", browse_by="recent"|"type"|"session", offset=0)`
- Condensed mode: `omega_tools(tool="...")` then `omega_call(tool="...", args={...})`
- After completing tasks: `omega_store(content, "decision")` for key outcomes
- User says "remember": `omega_store(text, "user_preference")`
- Context getting full: `omega_checkpoint` to save state
- Load user context: `omega_profile()` after welcome/protocol
- Before architecture decisions: `omega_reflect(action="evolution", topic=<domain>)` to check prior thinking
- After `omega_store`: check `omega_memory(similar)` and link related memories to build the knowledge graph

### Multi-Agent Coordination
- Check `omega_inbox()` for unread peer messages early in sessions
- Announce intent: `omega_intent_announce(description="<goal>")` before starting work
- Before editing shared files: `omega_file_check(file_path=...)` for conflicts
- After significant work: `omega_task_complete(task_id=..., result="summary")`
- Before deploy/force-push: `omega_action_check()` then `omega_action_claim()` (atomic gate)
- Never `git add .` — always `git add <specific files>`

If OMEGA is unavailable, use basic coordination:
- Before state changes: check `git log` and ask before deploying
- Never send emails, post tweets, or take externally-visible actions without explicit approval
- Commit only files you modified; `git add <files>` never `git add .`
- After tasks: store decisions with `omega_store()`
<!-- OMEGA:END -->
