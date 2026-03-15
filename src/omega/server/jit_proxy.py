"""JIT MCP Proxy -- lazy-spawns backend MCP servers on first tool call.

Replaces N rarely-used MCP server entries with a single lightweight proxy.
Backends spawn on first tool call and auto-disconnect after idle timeout.

Usage:
    # Run as MCP server (stdio):
    python3.11 -m omega.server.jit_proxy

    # Generate cached tool manifest:
    python3.11 -m omega.server.jit_proxy --cache-manifest
"""

import asyncio
import json
import logging
import os
import re
import signal
import socket
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from omega.exceptions import ValidationError as _ValidationError
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger("jit-proxy")

_LOG_DIR = Path.home() / ".omega" / "logs"
_DEFAULT_CONFIG = Path.home() / ".omega" / "jit-proxy.yaml"
_DEFAULT_MANIFEST = Path.home() / ".omega" / "jit-proxy-manifest.json"

_ENV_RE = re.compile(r"\$\{([^}]+)\}")

# --- Transport configuration ---
_TRANSPORT = os.environ.get("JIT_PROXY_TRANSPORT", "stdio").lower()
_HTTP_HOST = os.environ.get("JIT_PROXY_HTTP_HOST", "127.0.0.1")
_HTTP_PORT = int(os.environ.get("JIT_PROXY_HTTP_PORT", "8378"))
_start_time = time.monotonic()


async def _noop_validate(_name, _result):
    """No-op replacement for ClientSession._validate_tool_result.

    Neutralizes client-side output schema validation so the proxy's own
    ClientSession doesn't raise when a backend tool declares outputSchema
    but returns TextContent.
    """


def _configure_logging(log_file: Path | None = None):
    log_file = log_file or _LOG_DIR / "jit-proxy.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)

    from logging.handlers import RotatingFileHandler

    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    fh = RotatingFileHandler(str(log_file), maxBytes=2 * 1024 * 1024, backupCount=2)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logging.getLogger("jit-proxy").addHandler(fh)
    logging.getLogger("jit-proxy").setLevel(logging.DEBUG)


def _check_port_available(host: str, port: int) -> bool:
    """Check if a TCP port is available for binding."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind((host, port))
            return True
    except OSError:
        return False


def _get_current_rss_bytes() -> int:
    """Get current process RSS in bytes (macOS/Linux)."""
    try:
        import resource
        # resource.getrusage returns ru_maxrss in bytes on macOS, KB on Linux
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        if sys.platform == "darwin":
            return rss  # Already bytes on macOS
        return rss * 1024  # KB to bytes on Linux
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

@dataclass
class BackendConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)


@dataclass
class ProxyConfig:
    idle_timeout_seconds: int = 300
    log_file: str | None = None
    backends: dict[str, BackendConfig] = field(default_factory=dict)


def _expand_env(value: str) -> str:
    """Expand ${VAR} references from os.environ. Literal values pass through."""
    def replacer(m):
        var = m.group(1)
        return os.environ.get(var, "")
    return _ENV_RE.sub(replacer, value)


def load_config(path: Path | None = None) -> ProxyConfig:
    path = path or _DEFAULT_CONFIG
    with open(path) as f:
        raw = yaml.safe_load(f)

    backends = {}
    for name, bconf in raw.get("backends", {}).items():
        env = {}
        for k, v in (bconf.get("env") or {}).items():
            env[k] = _expand_env(str(v))
        backends[name] = BackendConfig(
            name=name,
            command=bconf["command"],
            args=bconf.get("args", []),
            env=env,
        )

    return ProxyConfig(
        idle_timeout_seconds=raw.get("idle_timeout_seconds", 300),
        log_file=raw.get("log_file"),
        backends=backends,
    )


def load_manifest(path: Path | None = None) -> dict:
    """Load cached tool manifest: {backend_name: [tool_dict, ...]}."""
    path = path or _DEFAULT_MANIFEST
    with open(path) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# BackendConnection
# ---------------------------------------------------------------------------

class BackendConnection:
    """Manages the lifecycle of a single backend MCP server process.

    Uses a dedicated lifecycle task to hold the stdio_client and ClientSession
    context managers. This avoids anyio's "cancel scope in a different task"
    error that occurs when __aenter__/__aexit__ happen in different tasks.

    The session is safe to call from any task (MCP memory streams are task-safe),
    while the lifecycle task owns the context managers and cleans up properly.
    """

    def __init__(self, name: str, config: BackendConfig):
        self.name = name
        self.config = config
        self.session: ClientSession | None = None
        self.last_activity: float = 0.0
        self._spawn_lock = asyncio.Lock()
        self._lifecycle_task: asyncio.Task | None = None
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()

    @property
    def connected(self) -> bool:
        return self.session is not None

    async def _lifecycle(self):
        """Dedicated task that holds the backend context managers open."""
        params = StdioServerParameters(
            command=self.config.command,
            args=self.config.args,
            env=self.config.env if self.config.env else None,
        )
        devnull = open("/dev/null", "w")
        try:
            async with stdio_client(params, errlog=devnull) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    # Disable output schema validation on the proxy's client session.
                    # Backend servers (email, twitter) declare outputSchema on their
                    # tools but return TextContent. MCP SDK 1.26+ validates this and
                    # raises RuntimeError. The proxy strips outputSchema from its own
                    # tool listings, so clients never see it -- but the internal
                    # client session still caches and enforces them. Neutralize it.
                    session._validate_tool_result = _noop_validate
                    self.session = session
                    self.last_activity = time.monotonic()
                    self._ready.set()
                    # Block until stop is signaled
                    await self._stop.wait()
        except asyncio.CancelledError:
            logger.info("[%s] Lifecycle task cancelled", self.name)
        except Exception as e:
            logger.error("[%s] Lifecycle error: %s", self.name, e)
        finally:
            self.session = None
            self._ready.clear()
            devnull.close()
            logger.info("[%s] Backend disconnected", self.name)

    async def ensure_connected(self) -> ClientSession:
        """Spawn backend if not running. Returns active ClientSession."""
        if self.session is not None:
            self.last_activity = time.monotonic()
            return self.session

        async with self._spawn_lock:
            # Double-check after acquiring lock
            if self.session is not None:
                self.last_activity = time.monotonic()
                return self.session

            logger.info("[%s] Spawning backend: %s %s", self.name, self.config.command, self.config.args)
            t0 = time.monotonic()

            self._stop.clear()
            self._ready.clear()
            self._lifecycle_task = asyncio.create_task(self._lifecycle())

            await self._ready.wait()

            elapsed = time.monotonic() - t0
            logger.info("[%s] Backend ready in %.1fs", self.name, elapsed)
            return self.session

    async def disconnect(self):
        """Signal the lifecycle task to exit, which cleans up context managers."""
        if self._lifecycle_task is None:
            return

        logger.info("[%s] Disconnecting backend", self.name)
        self._stop.set()
        try:
            await asyncio.wait_for(self._lifecycle_task, timeout=10)
        except asyncio.TimeoutError:
            logger.warning("[%s] Lifecycle task timed out, cancelling", self.name)
            self._lifecycle_task.cancel()
            try:
                await self._lifecycle_task
            except asyncio.CancelledError:
                pass
        self._lifecycle_task = None

    async def call_tool(self, tool_name: str, arguments: dict | None) -> CallToolResult:
        """Call a tool on this backend, spawning if needed. Retries once on broken pipe."""
        session = await self.ensure_connected()
        try:
            result = await session.call_tool(tool_name, arguments)
            self.last_activity = time.monotonic()
            return result
        except (BrokenPipeError, OSError, Exception) as e:
            if isinstance(e, (BrokenPipeError, OSError)) or "closed" in str(e).lower():
                logger.warning("[%s] Connection broken during %s, retrying: %s", self.name, tool_name, e)
                await self.disconnect()
                session = await self.ensure_connected()
                result = await session.call_tool(tool_name, arguments)
                self.last_activity = time.monotonic()
                return result
            raise


# ---------------------------------------------------------------------------
# JitProxy
# ---------------------------------------------------------------------------

class JitProxy:
    """JIT MCP Proxy server. Serves tool schemas from manifest, spawns backends on demand."""

    def __init__(self, config: ProxyConfig, manifest: dict):
        self.config = config
        self.manifest = manifest
        self.tool_to_backend: dict[str, str] = {}
        self.backends: dict[str, BackendConnection] = {}
        self.server = Server("jit-proxy")

        # Build routing table and backend connections
        self._build_tool_routing()
        for name, bconf in config.backends.items():
            self.backends[name] = BackendConnection(name, bconf)

        # Register MCP handlers
        self.server.list_tools()(self._list_tools)
        self.server.call_tool()(self._call_tool)

    def _build_tool_routing(self):
        """Map each tool name to its backend. Error on collisions."""
        for backend_name, tools in self.manifest.items():
            for tool_dict in tools:
                tool_name = tool_dict["name"]
                if tool_name in self.tool_to_backend:
                    other = self.tool_to_backend[tool_name]
                    raise _ValidationError(
                        f"Tool name collision: '{tool_name}' in both '{other}' and '{backend_name}'"
                    )
                self.tool_to_backend[tool_name] = backend_name

    async def _list_tools(self) -> list[Tool]:
        """Return all tools from manifest. No backend spawn needed."""
        tools = []
        for tools_list in self.manifest.values():
            for tool_dict in tools_list:
                # Strip outputSchema at serve time too (safety net for old manifests)
                td = {k: v for k, v in tool_dict.items() if k != "outputSchema"}
                tools.append(Tool.model_validate(td))
        return tools

    async def _call_tool(self, name: str, arguments: dict | None = None) -> list[TextContent]:
        """Route tool call to the correct backend, spawning if needed."""
        backend_name = self.tool_to_backend.get(name)
        if backend_name is None:
            return [TextContent(type="text", text=f"Error: unknown tool '{name}'")]

        backend = self.backends.get(backend_name)
        if backend is None:
            return [TextContent(type="text", text=f"Error: backend '{backend_name}' not configured")]

        logger.info("[%s] call_tool: %s", backend_name, name)
        try:
            result = await backend.call_tool(name, arguments)
            # MCP SDK 1.26+ server-side output validation: backends that declare
            # outputSchema but return TextContent get their successful result
            # replaced with an isError=True validation error.  The tool DID
            # execute -- the error is a post-execution format mismatch.  Detect
            # this and return a clean success so clients aren't confused.
            if (
                result.isError
                and result.content
                and any(
                    getattr(c, "text", "").startswith("Output validation error:")
                    for c in result.content
                )
            ):
                logger.warning(
                    "[%s] Suppressed server-side outputSchema validation error for %s",
                    backend_name, name,
                )
                return [TextContent(
                    type="text",
                    text=f"Tool '{name}' executed successfully. "
                         f"(Output suppressed due to backend outputSchema mismatch.)",
                )]
            return result.content
        except Exception as e:
            logger.error("[%s] Tool call failed: %s: %s", backend_name, name, e)
            return [TextContent(type="text", text=f"Error calling {name}: {e}")]

    async def _idle_watchdog(self):
        """Periodically check for idle backends and disconnect them."""
        while True:
            await asyncio.sleep(30)
            now = time.monotonic()
            for name, backend in self.backends.items():
                if backend.connected and (now - backend.last_activity > self.config.idle_timeout_seconds):
                    logger.info("[%s] Idle for %ds, disconnecting", name, self.config.idle_timeout_seconds)
                    try:
                        await backend.disconnect()
                    except Exception as e:
                        logger.error("[%s] Error during idle disconnect: %s", name, e)

    async def run(self):
        """Start proxy: idle watchdog + MCP stdio server."""
        # Keep reference to prevent GC
        watchdog = asyncio.create_task(self._idle_watchdog())
        logger.info(
            "JIT proxy starting: %d backends, %d tools, idle timeout %ds",
            len(self.backends),
            len(self.tool_to_backend),
            self.config.idle_timeout_seconds,
        )

        try:
            async with stdio_server() as (read_stream, write_stream):
                await self.server.run(
                    read_stream,
                    write_stream,
                    self.server.create_initialization_options(),
                )
        finally:
            watchdog.cancel()
            # Disconnect all backends on shutdown
            for backend in self.backends.values():
                try:
                    await backend.disconnect()
                except Exception:
                    pass


async def _run_http_transport(proxy: JitProxy) -> None:
    """Run jit-proxy as a Streamable HTTP daemon via uvicorn."""
    try:
        import uvicorn
        from starlette.applications import Starlette
        from starlette.responses import JSONResponse
        from starlette.routing import Mount, Route
        from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    except ImportError as e:
        print(
            f"Error: HTTP transport requires additional packages: {e}\n"
            "Install with: pip install mcp starlette uvicorn",
            file=sys.stderr,
        )
        sys.exit(1)

    if not _check_port_available(_HTTP_HOST, _HTTP_PORT):
        print(
            f"Error: Port {_HTTP_PORT} already in use on {_HTTP_HOST}.\n"
            f"Another jit-proxy daemon may be running. Check: curl http://{_HTTP_HOST}:{_HTTP_PORT}/health",
            file=sys.stderr,
        )
        sys.exit(1)

    session_manager = StreamableHTTPSessionManager(
        app=proxy.server,
        json_response=False,
        stateless=False,
    )

    async def health(request):
        rss = _get_current_rss_bytes()
        backend_status = {}
        for name, backend in proxy.backends.items():
            backend_status[name] = {
                "connected": backend.connected,
                "last_activity_ago_s": round(time.monotonic() - backend.last_activity, 1) if backend.last_activity > 0 else None,
            }
        return JSONResponse({
            "status": "ok",
            "pid": os.getpid(),
            "rss_mb": round(rss / 1024**2, 1),
            "uptime_s": round(time.monotonic() - _start_time, 1),
            "tool_count": len(proxy.tool_to_backend),
            "backend_count": len(proxy.backends),
            "backends": backend_status,
            "transport": "http",
        })

    import contextlib

    @contextlib.asynccontextmanager
    async def lifespan(app):
        async with session_manager.run():
            logger.info(
                "jit-proxy daemon listening on http://%s:%d/mcp",
                _HTTP_HOST, _HTTP_PORT,
            )
            yield
        # Disconnect all backends on shutdown
        for backend in proxy.backends.values():
            try:
                await backend.disconnect()
            except Exception:
                pass

    app = Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Mount("/mcp", app=session_manager.handle_request),
        ],
        lifespan=lifespan,
    )

    config = uvicorn.Config(
        app,
        host=_HTTP_HOST,
        port=_HTTP_PORT,
        log_level="warning",
        timeout_graceful_shutdown=5,
    )
    uv_server = uvicorn.Server(config)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.ensure_future(uv_server.shutdown()))

    await uv_server.serve()


# ---------------------------------------------------------------------------
# Manifest cache CLI
# ---------------------------------------------------------------------------

async def cache_manifest(config_path: Path | None = None, manifest_path: Path | None = None):
    """Spawn each backend temporarily, capture tool schemas, write manifest."""
    config = load_config(config_path)
    manifest_path = manifest_path or _DEFAULT_MANIFEST
    manifest: dict[str, list] = {}

    for name, bconf in config.backends.items():
        print(f"  [{name}] Spawning {bconf.command} {bconf.args}...")
        params = StdioServerParameters(
            command=bconf.command,
            args=bconf.args,
            env=bconf.env if bconf.env else None,
        )

        try:
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    tools = []
                    for t in result.tools:
                        td = t.model_dump(exclude_none=True)
                        # Strip outputSchema -- the proxy returns unstructured
                        # content from backends, which fails MCP validation
                        # if an outputSchema is declared.
                        td.pop("outputSchema", None)
                        tools.append(td)
                    manifest[name] = tools
                    print(f"  [{name}] {len(tools)} tools captured")
        except Exception as e:
            print(f"  [{name}] ERROR: {e}", file=sys.stderr)
            manifest[name] = []

    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    total = sum(len(v) for v in manifest.values())
    print(f"\nManifest written to {manifest_path} ({total} tools from {len(manifest)} backends)")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

async def _main():
    _configure_logging()

    if "--cache-manifest" in sys.argv:
        await cache_manifest()
        return

    config = load_config()
    manifest = load_manifest()
    proxy = JitProxy(config, manifest)

    if _TRANSPORT == "http":
        # Start idle watchdog as background task
        watchdog = asyncio.create_task(proxy._idle_watchdog())
        try:
            await _run_http_transport(proxy)
        finally:
            watchdog.cancel()
    else:
        await proxy.run()


if __name__ == "__main__":
    asyncio.run(_main())
