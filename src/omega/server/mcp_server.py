"""OMEGA MCP Server -- Standalone stdio-based MCP server for Claude Code.

Requires the 'server' extra: pip install omega-memory[server]
"""

import atexit
import asyncio
import collections
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
except ImportError:
    print(
        "Error: MCP server requires the 'mcp' package.\n"
        "Install with: pip install omega-memory[server]\n"
        "Or directly: pip install mcp>=1.0.0",
        file=sys.stderr,
    )
    sys.exit(1)

from omega.server.tool_schemas import TOOL_SCHEMAS as _CORE_SCHEMAS
from omega.server.handlers import HANDLERS as _CORE_HANDLERS

# Start with core memory tools
TOOL_SCHEMAS = list(_CORE_SCHEMAS)
HANDLERS = dict(_CORE_HANDLERS)

# Built-in optional modules (coordination, router, profile, knowledge, entity).
# Each is tried in turn; missing modules are silently skipped.
_BUILTIN_MODULES = [
    ("omega.server.coord_schemas", "COORD_TOOL_SCHEMAS", "omega.server.coord_handlers", "COORD_HANDLERS"),
    ("omega.router.tool_schemas", "ROUTER_TOOL_SCHEMAS", "omega.router.handlers", "ROUTER_HANDLERS"),
    ("omega.profile.tool_schemas", "PROFILE_TOOL_SCHEMAS", "omega.profile.handlers", "PROFILE_HANDLERS"),
    ("omega.knowledge.tool_schemas", "KNOWLEDGE_TOOL_SCHEMAS", "omega.knowledge.handlers", "KNOWLEDGE_HANDLERS"),
    ("omega.entity.tool_schemas", "ENTITY_TOOL_SCHEMAS", "omega.entity.handlers", "ENTITY_HANDLERS"),
]

import importlib

for _schema_mod, _schema_attr, _handler_mod, _handler_attr in _BUILTIN_MODULES:
    try:
        _sm = importlib.import_module(_schema_mod)
        _hm = importlib.import_module(_handler_mod)
        TOOL_SCHEMAS = TOOL_SCHEMAS + getattr(_sm, _schema_attr)
        HANDLERS = {**HANDLERS, **getattr(_hm, _handler_attr)}
    except ImportError:
        pass

# Discover external plugins (e.g. omega-pro)
from omega.plugins import discover_plugins

_discovered_plugins = discover_plugins()
for _plugin in _discovered_plugins:
    if _plugin.TOOL_SCHEMAS:
        TOOL_SCHEMAS = TOOL_SCHEMAS + _plugin.TOOL_SCHEMAS
    if _plugin.HANDLERS:
        HANDLERS = {**HANDLERS, **_plugin.HANDLERS}

# Wire plugin retrieval profiles and score modifiers to SQLiteStore (lazy)
def _wire_plugin_retrieval():
    """Register plugin retrieval profiles and score modifiers on the store."""
    try:
        from omega.bridge import _get_store
        store = _get_store()
        for plugin in _discovered_plugins:
            if getattr(plugin, "RETRIEVAL_PROFILES", None):
                store.register_plugin_profiles(plugin.RETRIEVAL_PROFILES)
            for modifier in getattr(plugin, "SCORE_MODIFIERS", []):
                store.register_score_modifier(modifier)
    except Exception:
        pass  # Store not ready yet; profiles will use built-in defaults

# ---------------------------------------------------------------------------
# Dedicated SQLite executor — serializes all blocking DB/hook work onto a
# single thread, preventing the GIL+GC race in _pysqlite_query_execute that
# caused SIGSEGV crashes under concurrent multi-thread SQLite access.
# Also used as the default asyncio executor to cap thread growth.
# ---------------------------------------------------------------------------
_SQLITE_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="omega-db")

# RSS memory watchdog threshold (bytes). Default 2 GB.
# Override with OMEGA_RSS_LIMIT_MB env var.
_RSS_LIMIT_BYTES = int(os.environ.get("OMEGA_RSS_LIMIT_MB", "2048")) * 1024 * 1024

# Idle watchdog: exit after this many seconds without a tool call.
# Override with OMEGA_IDLE_TIMEOUT env var. 0 = disabled.
_IDLE_TIMEOUT = int(os.environ.get("OMEGA_IDLE_TIMEOUT", "3600"))
_last_activity: float = time.monotonic()


def _close_on_exit():
    """Close SQLite store when the MCP server process exits."""
    try:
        from omega.bridge import _close_store

        _close_store()
    except Exception:
        pass


atexit.register(_close_on_exit)

logger = logging.getLogger("omega.server")


_MCP_INSTRUCTIONS = """\
OMEGA gives you persistent memory across conversations. \
You MUST use it automatically in every conversation.

REQUIRED at the start of EVERY conversation:
1. Call omega_welcome() immediately for context briefing
2. Call omega_protocol() for your operating instructions
3. Follow the protocol it returns

During conversations:
- Before non-trivial tasks: call omega_query() to check for prior context and decisions
- After completing tasks: call omega_store(content, "decision") to save key outcomes
- When the user says "remember": call omega_store(text, "user_preference")
- When context is getting full: call omega_checkpoint() to save state

These tools are your memory. Use them proactively without being asked.\
"""


server = Server("omega-memory", instructions=_MCP_INSTRUCTIONS)

# ---------------------------------------------------------------------------
# Rate limiting — sliding-window counters (no new deps)
# ---------------------------------------------------------------------------
_GLOBAL_RATE_LIMIT = int(os.environ.get("OMEGA_RATE_LIMIT_GLOBAL", "300"))  # per minute
_WRITE_RATE_LIMIT = int(os.environ.get("OMEGA_RATE_LIMIT_WRITE", "60"))  # per minute
_RATE_WINDOW_S = 60.0

_global_timestamps: collections.deque = collections.deque()
_write_timestamps: collections.deque = collections.deque()

_WRITE_TOOLS = frozenset({
    "omega_store", "omega_checkpoint", "omega_remind",
    "omega_memory", "omega_maintain", "omega_reflect",
    "omega_profile_set", "omega_entity_create", "omega_entity_update",
    "omega_ingest_document", "omega_task_create",
    "omega_file_claim", "omega_branch_claim",
    "omega_send_message", "omega_intent_announce",
})


def _check_rate_limit(tool_name: str) -> str | None:
    """Return an error message if rate limit exceeded, else None."""
    now = time.monotonic()
    cutoff = now - _RATE_WINDOW_S

    # Prune expired entries
    while _global_timestamps and _global_timestamps[0] < cutoff:
        _global_timestamps.popleft()

    if len(_global_timestamps) >= _GLOBAL_RATE_LIMIT:
        logger.warning("Global rate limit exceeded (%d calls/min)", _GLOBAL_RATE_LIMIT)
        return f"Rate limit exceeded: {_GLOBAL_RATE_LIMIT} calls/min globally. Try again shortly."

    _global_timestamps.append(now)

    # Write-tool tier
    if tool_name in _WRITE_TOOLS:
        while _write_timestamps and _write_timestamps[0] < cutoff:
            _write_timestamps.popleft()
        if len(_write_timestamps) >= _WRITE_RATE_LIMIT:
            logger.warning("Write rate limit exceeded (%d calls/min) for tool=%s", _WRITE_RATE_LIMIT, tool_name)
            return f"Rate limit exceeded: {_WRITE_RATE_LIMIT} write calls/min. Try again shortly."
        _write_timestamps.append(now)

    return None


@server.list_tools()
async def list_tools() -> list[Tool]:
    """Return all OMEGA tools."""
    return [
        Tool(
            name=schema["name"],
            description=schema["description"],
            inputSchema=schema["inputSchema"],
        )
        for schema in TOOL_SCHEMAS
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Dispatch tool call to the appropriate handler."""
    global _last_activity
    _last_activity = time.monotonic()

    # Rate limiting
    rate_err = _check_rate_limit(name)
    if rate_err:
        return [TextContent(type="text", text=rate_err)]

    handler = HANDLERS.get(name)
    if not handler:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]

    try:
        result = await handler(arguments)
        # Extract text from MCP response format
        content_list = result.get("content", [{}])
        text = content_list[0].get("text", str(result)) if content_list else str(result)
        return [TextContent(type="text", text=text)]
    except Exception as e:
        logger.error("Tool %s failed: %s", name, e, exc_info=True)
        return [TextContent(type="text", text=f"Error in {name}: {e}")]


async def _idle_watchdog():
    """Exit the process if no tool call has been received within the timeout."""
    while True:
        await asyncio.sleep(30)
        idle = time.monotonic() - _last_activity
        if idle >= _IDLE_TIMEOUT:
            logger.warning("Idle for %.0fs (limit %ds), shutting down.", idle, _IDLE_TIMEOUT)
            _close_on_exit()
            os._exit(0)


async def _socket_watchdog():
    """Re-create the hook socket if deleted or stale (unresponsive)."""
    if sys.platform == "win32":
        return  # TCP server doesn't need file watchdog

    from omega.server.hook_server import SOCK_PATH, start_hook_server

    while True:
        await asyncio.sleep(15)
        if not SOCK_PATH:
            continue
        if not SOCK_PATH.exists():
            logger.warning("Hook socket deleted, re-creating...")
            await start_hook_server()
        else:
            # Validate socket is actually ours and responsive
            try:
                r, w = await asyncio.wait_for(
                    asyncio.open_unix_connection(path=str(SOCK_PATH)), timeout=2.0
                )
                w.close()
                await w.wait_closed()
            except (OSError, asyncio.TimeoutError):
                logger.warning("Hook socket unresponsive, re-creating...")
                try:
                    SOCK_PATH.unlink()
                except OSError:
                    pass
                await start_hook_server()


_coord_tick_count = 0


def _run_coordination_tick():
    """Sync helper for periodic coordination maintenance."""
    global _coord_tick_count
    _coord_tick_count += 1
    try:
        from omega.coordination import get_manager
        from omega.server.hook_server import (
            _last_deadlock_push,
            DEADLOCK_PUSH_DEBOUNCE_S,
            _agent_nickname,
        )

        mgr = get_manager()

        # Stale cleanup — internally debounced to 5 min
        try:
            mgr._maybe_clean_stale()
        except Exception:
            pass

        # Every 5th tick (~5 min): deadlock detection + push
        if _coord_tick_count % 5 == 0:
            try:
                cycles = mgr.detect_deadlocks()
                if cycles:
                    now_dl = time.monotonic()
                    for cycle in cycles[:2]:
                        cycle_key = str(hash(tuple(sorted(cycle[:-1]))))
                        if cycle_key not in _last_deadlock_push or now_dl - _last_deadlock_push[cycle_key] >= DEADLOCK_PUSH_DEBOUNCE_S:
                            _last_deadlock_push[cycle_key] = now_dl
                            cycle_str = " -> ".join(_agent_nickname(s) for s in cycle)
                            for peer in set(cycle[:-1]):
                                try:
                                    mgr.send_message(
                                        from_session=peer,
                                        subject=f"[DEADLOCK] Circular wait: {cycle_str}",
                                        to_session=peer,
                                        msg_type="inform",
                                        ttl_minutes=30,
                                    )
                                except Exception:
                                    pass
            except Exception:
                pass
    except Exception:
        pass  # All fail-open


async def _coordination_loop():
    """Periodic coordination maintenance — runs even during idle."""
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(60)
        try:
            await loop.run_in_executor(_SQLITE_EXECUTOR, _run_coordination_tick)
        except Exception:
            pass  # All fail-open


def _configure_logging():
    """Set up logging with both stderr and rotating file handler."""
    from logging.handlers import RotatingFileHandler
    from pathlib import Path

    log_dir = Path.home() / ".omega" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    log_file = log_dir / "omega.log"

    # Root logger: WARNING to stderr (default for MCP)
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    # File handler: captures WARNING+ with rotation (5MB, 3 backups)
    file_handler = RotatingFileHandler(
        str(log_file), maxBytes=5 * 1024 * 1024, backupCount=3,
    )
    file_handler.setLevel(logging.WARNING)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logging.getLogger().addHandler(file_handler)


# --- Mach task_info objects (hoisted to module level to avoid per-call leaks) ---
_mach_libc = None
_mach_task_port = None
_MACH_TASK_BASIC_INFO = 20

if sys.platform == "darwin":
    try:
        import ctypes
        import ctypes.util

        _mach_libc = ctypes.CDLL(ctypes.util.find_library("c"))
        _mach_task_port = _mach_libc.mach_task_self()

        class _TaskBasicInfo(ctypes.Structure):
            _fields_ = [
                ("virtual_size", ctypes.c_uint64),
                ("resident_size", ctypes.c_uint64),
                ("resident_size_max", ctypes.c_uint64),
                ("user_time_seconds", ctypes.c_int32),
                ("user_time_microseconds", ctypes.c_int32),
                ("system_time_seconds", ctypes.c_int32),
                ("system_time_microseconds", ctypes.c_int32),
                ("policy", ctypes.c_int32),
                ("suspend_count", ctypes.c_int32),
            ]

        _mach_info_size_words = ctypes.sizeof(_TaskBasicInfo()) // 4
    except Exception:
        _mach_libc = None


def _get_current_rss_bytes() -> int:
    """Get current RSS in bytes using the most accurate OS-specific method.

    On macOS, resource.getrusage ru_maxrss returns *peak* RSS, not current.
    This function uses Mach task_info for accurate current RSS on macOS,
    falling back to ru_maxrss if the Mach call fails.
    """
    if sys.platform == "darwin" and _mach_libc is not None:
        try:
            info = _TaskBasicInfo()
            count = ctypes.c_uint32(_mach_info_size_words)
            ret = _mach_libc.task_info(
                _mach_task_port, _MACH_TASK_BASIC_INFO,
                ctypes.byref(info), ctypes.byref(count),
            )
            if ret == 0:  # KERN_SUCCESS
                return info.resident_size
        except Exception:
            pass

    # Fallback: getrusage (peak RSS, not current — but better than nothing)
    import resource
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    if sys.platform != "darwin":
        rss *= 1024  # KB to bytes on Linux
    return rss


async def _rss_watchdog():
    """Periodically check RSS and gracefully exit if it exceeds the limit.

    Prevents runaway memory growth from crashing the terminal. The MCP
    client (Claude Code) will automatically restart the server on next
    tool call.
    """
    while True:
        await asyncio.sleep(30)
        try:
            rss = _get_current_rss_bytes()

            if rss > _RSS_LIMIT_BYTES:
                msg = (
                    "RSS %.0f MB exceeds limit %.0f MB, shutting down to prevent crash."
                    % (rss / 1024**2, _RSS_LIMIT_BYTES / 1024**2)
                )
                sys.stderr.write(f"WARNING omega.server: {msg}\n")
                sys.stderr.flush()
                logger.warning(msg)
                for handler in logging.getLogger().handlers:
                    try:
                        handler.flush()
                    except Exception:
                        pass
                _close_on_exit()
                os._exit(0)
        except Exception as e:
            logger.debug("RSS watchdog check failed: %s", e)


async def main():
    """Entry point for the OMEGA MCP server."""
    _configure_logging()
    logger.info("Starting OMEGA MCP server...")

    # Cap asyncio's default executor — prevents unbounded thread growth from
    # run_in_executor(None, ...) calls (was reaching 49-64 threads at crash).
    loop = asyncio.get_running_loop()
    loop.set_default_executor(_SQLITE_EXECUTOR)

    # Start UDS hook server for fast hook dispatch
    from omega.server.hook_server import start_hook_server, stop_hook_server

    hook_srv = await start_hook_server()

    # Prewarm embedding model in background — hides 200-500ms ONNX load
    # behind session startup rather than blocking the first user query.
    async def _prewarm():
        try:
            from omega.embedding import preload_embedding_model_async
            await preload_embedding_model_async()
        except Exception:
            pass  # Non-fatal — lazy-load on first query as fallback

    _prewarm_task = asyncio.create_task(_prewarm())

    # Wire plugin retrieval profiles/modifiers to SQLiteStore
    _wire_plugin_retrieval()

    # Start idle watchdog (unless disabled).
    # IMPORTANT: Save reference — unref'd tasks get silently GC'd by asyncio.
    if _IDLE_TIMEOUT > 0:
        _watchdog_task = asyncio.create_task(_idle_watchdog())

    # Socket watchdog — re-creates hook.sock if deleted by another session's stop
    _sock_watchdog_task = asyncio.create_task(_socket_watchdog())

    # Background coordination loop — stale cleanup + deadlock detection even during idle
    _coord_loop_task = asyncio.create_task(_coordination_loop())

    # RSS memory watchdog — graceful exit before memory pressure causes SIGSEGV
    _rss_watchdog_task = asyncio.create_task(_rss_watchdog())

    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(
                read_stream,
                write_stream,
                server.create_initialization_options(),
            )
    finally:
        await stop_hook_server(hook_srv)


if __name__ == "__main__":
    asyncio.run(main())
