"""OMEGA Hook Server — Unix Domain Socket daemon for fast hook dispatch.

Community edition: core memory hooks only.
Runs inside the MCP server process, reusing warm bridge singletons.
Hooks connect via ~/.omega/hook.sock, send a JSON request, and get a JSON response.
This eliminates ~750ms of cold-start overhead per hook invocation.
"""

import asyncio
import hashlib
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("omega.hook_server")

# Windows uses TCP loopback; Unix uses domain socket
if sys.platform == "win32":
    SOCK_PATH = None
    HOOK_HOST = "127.0.0.1"
    HOOK_PORT = 19876
else:
    SOCK_PATH = Path.home() / ".omega" / "hook.sock"
    HOOK_HOST = None
    HOOK_PORT = None

# ---------------------------------------------------------------------------
# Debounce state (in-memory, reset on server restart)
# ---------------------------------------------------------------------------
_last_heartbeat: dict[str, float] = {}
_last_claim: dict[tuple[str, str], float] = {}
_last_surface: dict[str, float] = {}
_MAX_SURFACE_ENTRIES = 500
_last_overlap_notify: dict[tuple[str, str, str], float] = {}
OVERLAP_NOTIFY_DEBOUNCE_S = 300.0
_last_block_notify: dict[tuple[str, str, str], float] = {}
BLOCK_NOTIFY_DEBOUNCE_S = 300.0
_last_peer_dir_check: dict[str, float] = {}
PEER_DIR_CHECK_DEBOUNCE_S = 300.0
_last_coord_query: dict[str, float] = {}
COORD_QUERY_DEBOUNCE_S = 120.0
_last_reminder_check: float = 0.0
REMINDER_CHECK_DEBOUNCE_S = 300.0

_last_deadlock_push: dict[str, float] = {}
DEADLOCK_PUSH_DEBOUNCE_S = 600.0

HEARTBEAT_DEBOUNCE_S = 30.0
CLAIM_DEBOUNCE_S = 30.0
SURFACE_DEBOUNCE_S = 5.0

_heartbeat_count: dict[str, int] = {}
_peer_snapshot: dict[str, set] = {}
_session_intent: dict[str, str] = {}

# Error dedup state
_error_hashes: set = set()
_MAX_ERROR_HASHES = 200
_error_counts: dict[str, int] = {}
_MAX_ERRORS_PER_SESSION = 5


# ---------------------------------------------------------------------------
# Agent nicknames — deterministic human-readable names from session IDs
# ---------------------------------------------------------------------------

_AGENT_NAMES = [
    "Alder", "Aspen", "Birch", "Briar", "Brook", "Cedar", "Cliff", "Cloud",
    "Coral", "Cove", "Crane", "Creek", "Dale", "Dawn", "Dune", "Echo",
    "Elm", "Ember", "Fern", "Finch", "Flame", "Flint", "Flora", "Fox",
    "Frost", "Glen", "Grove", "Hare", "Haven", "Hawk", "Hazel", "Heath",
    "Heron", "Holly", "Iris", "Ivy", "Jade", "Jay", "Juniper", "Lake",
    "Lark", "Laurel", "Leaf", "Lily", "Maple", "Marsh", "Meadow", "Moss",
    "Myrtle", "Oak", "Olive", "Onyx", "Opal", "Orca", "Osprey", "Otter",
    "Pearl", "Pebble", "Pine", "Plum", "Quail", "Rain", "Raven", "Reed",
    "Ridge", "River", "Robin", "Rook", "Rose", "Rowan", "Rush", "Sage",
    "Shore", "Sky", "Slate", "Sparrow", "Stone", "Storm", "Swift", "Teal",
    "Thorn", "Thyme", "Tide", "Vale", "Vine", "Violet", "Willow", "Wren",
]


def _agent_nickname(session_id: str) -> str:
    """Deterministic human-readable nickname from session ID."""
    if not session_id:
        return "Unknown"
    h = int(hashlib.md5(session_id.encode()).hexdigest()[:8], 16)
    return _AGENT_NAMES[h % len(_AGENT_NAMES)]


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _log_hook_error(hook_name: str, error: Exception) -> None:
    """Log a hook error with traceback."""
    logger.error("Hook %s failed: %s", hook_name, error, exc_info=True)


def _log_timing(hook_name: str, elapsed_ms: float) -> None:
    """Log hook timing for performance monitoring."""
    if elapsed_ms > 500:
        logger.warning("Slow hook %s: %.0fms", hook_name, elapsed_ms)
    elif elapsed_ms > 100:
        logger.debug("Hook %s: %.0fms", hook_name, elapsed_ms)


def _should_run_periodic(marker_name: str, interval_seconds: int) -> bool:
    """Check if a periodic task should run (based on marker file timestamp)."""
    marker_file = Path.home() / ".omega" / f".{marker_name}"
    if not marker_file.exists():
        return True
    try:
        mtime = marker_file.stat().st_mtime
        return (time.time() - mtime) >= interval_seconds
    except Exception:
        return True


def _update_marker(marker_name: str) -> None:
    """Update a periodic task marker file."""
    marker_file = Path.home() / ".omega" / f".{marker_name}"
    try:
        marker_file.parent.mkdir(parents=True, exist_ok=True)
        marker_file.write_text(datetime.now(timezone.utc).isoformat())
    except Exception:
        pass


def _resolve_entity(project: str) -> str | None:
    """Resolve entity from project path. Community edition: no-op."""
    return None


def _secure_append(output: list, text: str) -> None:
    """Append text to output list."""
    output.append(text)


def _ext_to_tags(file_path: str) -> list[str]:
    """Extract tags from file extension."""
    ext = Path(file_path).suffix.lstrip(".").lower()
    ext_map = {
        "py": ["python"], "ts": ["typescript"], "tsx": ["typescript", "react"],
        "js": ["javascript"], "jsx": ["javascript", "react"], "rs": ["rust"],
        "go": ["go"], "java": ["java"], "rb": ["ruby"], "md": ["markdown"],
        "json": ["json"], "yaml": ["yaml"], "yml": ["yaml"], "toml": ["toml"],
        "sql": ["sql"], "sh": ["shell"], "css": ["css"], "html": ["html"],
    }
    return ext_map.get(ext, [ext] if ext else [])


# ---------------------------------------------------------------------------
# Core hook handlers
# ---------------------------------------------------------------------------


def handle_session_start(payload: dict) -> dict:
    """Welcome briefing + periodic maintenance."""
    session_id = payload.get("session_id", "")
    project = payload.get("project", "")
    output = []

    # Auto-consolidation check (max once per 7 days)
    try:
        if _should_run_periodic("last-consolidate", 7 * 86400):
            from omega.bridge import consolidate
            consolidate(prune_days=14, max_summaries=50)
            _update_marker("last-consolidate")
    except Exception as e:
        _log_hook_error("auto_consolidate", e)

    # Auto-backup check (max once per 24 hours)
    try:
        if _should_run_periodic("last-backup", 86400):
            backup_dir = Path.home() / ".omega" / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            dest = backup_dir / f"omega-{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.json"
            from omega.bridge import export_memories
            export_memories(filepath=str(dest))
            # Rotate: keep only last 5
            backups = sorted(backup_dir.glob("omega-*.json"), key=lambda p: p.name, reverse=True)
            for old in backups[5:]:
                old.unlink()
            _update_marker("last-backup")
    except Exception as e:
        _log_hook_error("auto_backup", e)

    # Surface relevant memories for the project
    try:
        from omega.bridge import query_structured
        recent = query_structured(
            query_text="recent decisions and context",
            limit=5,
            project=project,
            surfacing_context="SESSION_START",
        )
        if recent:
            _secure_append(output, "[MEMORY] Recent context:")
            for mem in recent[:5]:
                content = mem.get("content", "") if isinstance(mem, dict) else getattr(mem, "content", "")
                _secure_append(output, f"  - {content[:120]}")
    except Exception as e:
        _log_hook_error("session_start_surface", e)

    # Check for due reminders
    try:
        from omega.bridge import get_due_reminders
        reminders = get_due_reminders()
        if reminders:
            _secure_append(output, "[REMINDERS]")
            for r in reminders[:5]:
                text = r.get("text", "") if isinstance(r, dict) else getattr(r, "content", "")
                _secure_append(output, f"  - {text[:120]}")
    except Exception as e:
        logger.debug("Reminder check failed: %s", e)

    return {"output": "\n".join(output), "exit_code": 0}


def _session_resume(session_id: str, project: str, mgr) -> list[str]:
    """Surface checkpointed tasks for session resume.
    
    Args:
        session_id: Current session ID
        project: Project path
        mgr: Coordination manager (for Pro features, may be None)
    
    Returns:
        List of formatted lines to display, including [CHECKPOINT] blocks.
    """
    lines = []
    
    try:
        from omega.bridge import query_structured
        
        # Query for recent checkpoints in this project
        checkpoints = query_structured(
            query_text="checkpoint",
            limit=5,
            event_type="checkpoint",
            project=project,
        )
        
        if checkpoints:
            lines.append("[CHECKPOINT] Resumable tasks:")
            for cp in checkpoints:
                content = cp.get("content", "")
                metadata = cp.get("metadata", {})
                task_title = metadata.get("task_title", "")
                
                if task_title:
                    lines.append(f"  {task_title}")
                else:
                    # Fallback to content preview
                    preview = content[:80] + "..." if len(content) > 80 else content
                    lines.append(f"  {preview}")
                
                # Add progress if available
                progress = metadata.get("progress", "")
                if progress:
                    lines.append(f"    Progress: {progress}")
                
                # Add next steps if available
                next_steps = metadata.get("next_steps", "")
                if next_steps:
                    lines.append(f"    Next: {next_steps}")
    except Exception as e:
        logger.debug("Session resume checkpoint query failed: %s", e)
    
    # Pro feature: recover session from coordination manager
    if mgr:
        try:
            recovered = mgr.recover_session(project)
            if recovered:
                lines.append("[COORD] Recovered session state from coordination manager")
        except Exception:
            pass  # Coordination unavailable
    
    return lines


def handle_session_stop(payload: dict) -> dict:
    """Generate and store session summary."""
    session_id = payload.get("session_id", "")
    project = payload.get("project", "")

    # Build summary from session events
    summary = "Session ended"
    try:
        from omega.bridge import _get_store, query_structured

        store = _get_store()
        counts = store.get_session_event_counts(session_id) if session_id else {}
        captured = sum(counts.values()) if counts else 0

        decisions = query_structured(
            query_text="decisions made",
            limit=5,
            session_id=session_id,
            project=project,
            event_type="decision",
        )
        tasks = query_structured(
            query_text="completed tasks",
            limit=3,
            session_id=session_id,
            project=project,
            event_type="task_completion",
        )

        parts = []
        if decisions:
            dec_texts = []
            for d in decisions[:3]:
                c = d.get("content", "") if isinstance(d, dict) else getattr(d, "content", "")
                dec_texts.append(c[:80])
            parts.append("Decisions: " + "; ".join(dec_texts))
        if tasks:
            task_texts = []
            for t in tasks[:3]:
                c = t.get("content", "") if isinstance(t, dict) else getattr(t, "content", "")
                task_texts.append(c[:80])
            parts.append("Tasks: " + "; ".join(task_texts))
        if captured:
            parts.append(f"{captured} memories captured")

        if parts:
            summary = " | ".join(parts)

        # Store session summary
        from omega.bridge import store as omega_store
        omega_store(
            content=summary,
            event_type="session_summary",
            metadata={"session_id": session_id, "project": project},
        )
    except Exception as e:
        _log_hook_error("session_stop_summary", e)

    # Clean up session files
    try:
        surfaced = Path.home() / ".omega" / f"session-{session_id}.surfaced"
        if surfaced.exists():
            surfaced.unlink()
        surfaced_json = Path.home() / ".omega" / f"session-{session_id}.surfaced.json"
        if surfaced_json.exists():
            surfaced_json.unlink()
    except Exception:
        pass

    return {"output": f"Session summary saved ({len(summary)} chars)", "exit_code": 0}


def handle_surface_memories(payload: dict) -> dict:
    """Surface relevant memories for the current file being edited."""
    file_path = payload.get("file_path", "")
    session_id = payload.get("session_id", "")
    project = payload.get("project", "")

    if not file_path:
        return {"output": "", "exit_code": 0}

    # Debounce: don't re-surface the same file within 5s
    now = time.monotonic()
    if file_path in _last_surface and (now - _last_surface[file_path]) < SURFACE_DEBOUNCE_S:
        return {"output": "", "exit_code": 0}
    _last_surface[file_path] = now
    # Cap surface cache
    if len(_last_surface) > _MAX_SURFACE_ENTRIES:
        oldest = min(_last_surface, key=_last_surface.get)
        del _last_surface[oldest]

    output = []
    try:
        from omega.bridge import query_structured

        # Get tags from file extension for boosting
        tags = _ext_to_tags(file_path)
        file_name = Path(file_path).name

        results = query_structured(
            query_text=f"working with {file_name}",
            limit=5,
            project=project,
            context_file=file_path,
            context_tags=tags,
            surfacing_context="PRE_EDIT",
        )

        if results:
            _secure_append(output, f"[MEMORY] Context for {file_name}:")
            for mem in results[:5]:
                content = mem.get("content", "") if isinstance(mem, dict) else getattr(mem, "content", "")
                event_type = ""
                if isinstance(mem, dict):
                    event_type = (mem.get("metadata") or {}).get("event_type", "")
                else:
                    event_type = (getattr(mem, "metadata", None) or {}).get("event_type", "")
                prefix = f"[{event_type}] " if event_type else ""
                _secure_append(output, f"  {prefix}{content[:120]}")
    except Exception as e:
        _log_hook_error("surface_memories", e)

    return {"output": "\n".join(output), "exit_code": 0}


_NOISE_PATTERNS = [
    "Running command:",
    "$ ",
    "Checking ",
    "Loading ",
    "Waiting ",
    "Installing ",
    "Downloading ",
]

_CONTENT_BLOCKLIST = frozenset([
    "session_summary", "session_start", "session_end",
    "context_warning", "budget_alert", "coordination_snapshot",
])


def handle_auto_capture(payload: dict) -> dict:
    """Auto-capture decisions, lessons, errors, and user preferences."""
    session_id = payload.get("session_id", "")
    project = payload.get("project", "")
    content = payload.get("content", "")
    event_type = payload.get("event_type", "memory")

    if not content or len(content.strip()) < 10:
        return {"output": "", "exit_code": 0}

    # Block noisy infrastructure events
    if event_type in _CONTENT_BLOCKLIST:
        return {"output": "", "exit_code": 0}

    # Block noise patterns
    content_lower = content[:200].lower()
    if any(p.lower() in content_lower for p in _NOISE_PATTERNS):
        return {"output": "", "exit_code": 0}

    # Dedup: skip if we've seen a very similar content hash recently
    content_hash = hashlib.md5(content[:500].encode()).hexdigest()[:12]
    if content_hash in _error_hashes:
        return {"output": "Deduped", "exit_code": 0}
    _error_hashes.add(content_hash)
    if len(_error_hashes) > _MAX_ERROR_HASHES:
        _error_hashes.clear()

    # Cap captures per session
    count = _error_counts.get(session_id, 0)
    if count >= _MAX_ERRORS_PER_SESSION and event_type == "error_pattern":
        return {"output": "", "exit_code": 0}
    if event_type == "error_pattern":
        _error_counts[session_id] = count + 1

    try:
        from omega.bridge import auto_capture

        result = auto_capture(
            content=content,
            event_type=event_type,
            session_id=session_id,
            project=project,
        )

        if result:
            result_text = result if isinstance(result, str) else str(result)
            if "dedup" in result_text.lower() or "evolved" in result_text.lower():
                return {"output": result_text[:50], "exit_code": 0}
            return {"output": result_text[:100], "exit_code": 0}
    except Exception as e:
        _log_hook_error("auto_capture", e)

    return {"output": "", "exit_code": 0}


# ---------------------------------------------------------------------------
# Handler dispatch table
# ---------------------------------------------------------------------------

HOOK_HANDLERS = {
    "session_start": handle_session_start,
    "session_stop": handle_session_stop,
    "surface_memories": handle_surface_memories,
    "auto_capture": handle_auto_capture,
}

# Load commercial handlers if coordination is available
try:
    import omega.coordination  # noqa: F401
    # Coordination module found — extended hooks will be loaded by plugins
except ImportError:
    pass


def register_hook_handler(name: str, handler):
    """Register a hook handler at runtime (for plugins)."""
    HOOK_HANDLERS[name] = handler


# ---------------------------------------------------------------------------
# UDS/TCP Server
# ---------------------------------------------------------------------------


async def handle_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    """Handle a single hook client connection."""
    t0 = time.monotonic()
    hook_name = "unknown"
    try:
        # Read until EOF — client calls shutdown(SHUT_WR) after sendall()
        chunks = []
        while True:
            chunk = await asyncio.wait_for(reader.read(65536), timeout=10.0)
            if not chunk:
                break
            chunks.append(chunk)
        data = b"".join(chunks)
        if not data:
            writer.close()
            return

        request = json.loads(data.decode("utf-8").strip())

        # Batch mode: {"hooks": ["a", "b", ...], ...}
        hook_names = request.pop("hooks", None)
        if hook_names:
            hook_name = "+".join(hook_names)
            results = []
            for name in hook_names:
                handler = HOOK_HANDLERS.get(name)
                if not handler:
                    results.append({"output": "", "error": f"Unknown hook: {name}"})
                else:
                    try:
                        r = handler(request)
                        results.append(r)
                        if r.get("exit_code"):
                            break
                    except Exception as e:
                        results.append({"output": "", "error": str(e)})
            response = {"results": results}
        else:
            hook_name = request.pop("hook", "unknown")
            handler = HOOK_HANDLERS.get(hook_name)
            if not handler:
                response = {"output": "", "error": f"Unknown hook: {hook_name}"}
            else:
                try:
                    response = handler(request)
                except Exception as e:
                    _log_hook_error(hook_name, e)
                    response = {"output": "", "error": str(e)}

        writer.write(json.dumps(response).encode("utf-8"))
        await writer.drain()
    except (ConnectionResetError, BrokenPipeError):
        logger.debug("Hook client disconnected before response: %s", hook_name)
    except asyncio.TimeoutError:
        try:
            writer.write(json.dumps({"output": "", "error": "timeout"}).encode("utf-8"))
            await writer.drain()
        except Exception:
            pass
    except json.JSONDecodeError as e:
        _log_hook_error(f"connection/{hook_name}", e)
        try:
            writer.write(json.dumps({"output": "", "error": str(e)}).encode("utf-8"))
            await writer.drain()
        except Exception:
            pass
    finally:
        elapsed_ms = (time.monotonic() - t0) * 1000
        _log_timing(hook_name, elapsed_ms)
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:
            pass


_hook_server: asyncio.Server | None = None


async def start_hook_server() -> asyncio.Server | None:
    """Start the hook server. Uses TCP on Windows, Unix domain socket elsewhere."""
    global _hook_server

    try:
        if sys.platform == "win32":
            _hook_server = await asyncio.start_server(
                handle_connection, host=HOOK_HOST, port=HOOK_PORT
            )
            logger.info("Hook server listening on %s:%s", HOOK_HOST, HOOK_PORT)
        else:
            if SOCK_PATH:
                SOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
                if SOCK_PATH.exists():
                    SOCK_PATH.unlink()
                _hook_server = await asyncio.start_unix_server(handle_connection, path=str(SOCK_PATH))
                SOCK_PATH.chmod(0o600)
                logger.info("Hook server listening on %s", SOCK_PATH)
        return _hook_server
    except Exception as e:
        logger.error("Failed to start hook server: %s", e, exc_info=True)
        return None


async def stop_hook_server(srv: asyncio.Server | None = None):
    """Stop the hook server and clean up socket."""
    global _hook_server
    server = srv or _hook_server
    if server:
        server.close()
        await server.wait_closed()
        _hook_server = None

        if sys.platform != "win32" and SOCK_PATH and SOCK_PATH.exists():
            try:
                SOCK_PATH.unlink()
            except Exception as e:
                logger.debug("Socket unlink failed: %s", e)
