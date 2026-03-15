"""Multi-process PID registry for OMEGA MCP servers.

Each MCP server process writes ~/.omega/mcp_pids/{pid}.pid on startup.
Used to enrich "database is locked" errors with active process info.
"""

import json
import logging
import os
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("omega.pid_registry")

_PID_DIR = Path.home() / ".omega" / "mcp_pids"


def register_pid(
    transport: str = "stdio",
    port: int | None = None,
) -> None:
    """Register this process in the PID directory."""
    try:
        _PID_DIR.mkdir(parents=True, exist_ok=True)
        pid = os.getpid()
        pid_file = _PID_DIR / f"{pid}.pid"
        data = {
            "pid": pid,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "parent_pid": os.getppid(),
            "transport": transport,
        }
        if port is not None:
            data["port"] = port
        pid_file.write_text(json.dumps(data))
    except Exception as e:
        logger.debug("PID registration failed: %s", e)


def unregister_pid() -> None:
    """Remove this process from the PID directory."""
    try:
        pid_file = _PID_DIR / f"{os.getpid()}.pid"
        pid_file.unlink(missing_ok=True)
    except Exception as e:
        logger.debug("PID unregistration failed: %s", e)


def list_active_pids() -> list:
    """Scan PID directory, return live processes, clean up stale entries."""
    active = []
    if not _PID_DIR.exists():
        return active
    for f in _PID_DIR.iterdir():
        if not f.suffix == ".pid":
            continue
        try:
            data = json.loads(f.read_text())
            pid = data["pid"]
            os.kill(pid, 0)  # Check if alive (signal 0 = no-op)
            data["_path"] = str(f)
            active.append(data)
        except ProcessLookupError:
            # Process is dead — clean up stale PID file
            try:
                f.unlink()
            except Exception:
                pass
        except (json.JSONDecodeError, KeyError, OSError):
            # Corrupt or unreadable file — skip
            continue
    return active


def _get_ppid(pid: int) -> int | None:
    """Get the parent PID of a process. Returns None if unavailable."""
    try:
        result = subprocess.run(
            ["ps", "-o", "ppid=", "-p", str(pid)],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError, FileNotFoundError):
        pass
    return None


def kill_orphaned_servers() -> int:
    """Kill MCP server processes whose parent has exited (ppid=1).

    Scans PID files in the registry. A process with ppid=1 means its parent
    (the Claude session) has died, leaving it orphaned and holding DB locks.

    Returns count of processes killed.
    """
    killed = 0
    if not _PID_DIR.exists():
        return killed
    my_pid = os.getpid()
    for f in _PID_DIR.iterdir():
        if f.suffix != ".pid":
            continue
        try:
            data = json.loads(f.read_text())
            pid = data["pid"]
            if pid == my_pid:
                continue
            # Check if process is still alive
            os.kill(pid, 0)
            # Skip HTTP daemon processes — they run under launchd (ppid=1)
            # and should not be killed as orphans.
            if data.get("transport") == "http":
                continue
            # Alive — check if orphaned (ppid=1 means parent exited)
            ppid = _get_ppid(pid)
            if ppid == 1:
                os.kill(pid, signal.SIGTERM)
                f.unlink(missing_ok=True)
                killed += 1
                logger.warning("Killed orphaned MCP server PID %d (ppid=1)", pid)
        except ProcessLookupError:
            # Process is dead — clean up stale PID file
            try:
                f.unlink(missing_ok=True)
            except Exception:
                pass
        except (json.JSONDecodeError, KeyError, OSError):
            # Corrupt or unreadable file — try to clean up
            try:
                f.unlink(missing_ok=True)
            except Exception:
                pass
    return killed


def format_lock_diagnostic() -> str:
    """Human-readable summary of active OMEGA processes."""
    try:
        pids = list_active_pids()
        if not pids:
            return "No registered OMEGA MCP processes found"
        parts = []
        now = time.time()
        for p in pids:
            pid = p["pid"]
            started = p.get("started_at", "")
            age = ""
            if started:
                try:
                    start_dt = datetime.fromisoformat(started)
                    elapsed_s = now - start_dt.timestamp()
                    if elapsed_s < 3600:
                        age = f"{int(elapsed_s / 60)}m ago"
                    else:
                        age = f"{elapsed_s / 3600:.1f}h ago"
                except (ValueError, OSError):
                    age = "unknown"
            parts.append(f"PID {pid} (started {age})" if age else f"PID {pid}")
        return f"{len(pids)} OMEGA process(es) running: {', '.join(parts)}"
    except Exception as e:
        return f"PID diagnostic unavailable: {e}"
