"""OMEGA Embedding Client -- Connects to the shared embedding daemon.

Provides a thin client that talks to the embedding daemon over Unix socket.
Falls back to None (caller uses in-process ONNX) when daemon is unavailable.

Set OMEGA_EMBEDDING_DAEMON=0 to disable daemon usage entirely.
"""

import json
import logging
import os
import struct
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("omega.embedding_client")

_OMEGA_DIR = Path.home() / ".omega"
_SOCK_PATH = _OMEGA_DIR / "embed.sock"
_PID_PATH = _OMEGA_DIR / "embed.pid"

# Timeouts
_CONNECT_TIMEOUT = 2.0
_SINGLE_TIMEOUT = 0.5  # 500ms for single embed
_BATCH_TIMEOUT = 5.0   # 5s for batch

# Singleton client
_client: Optional["EmbeddingClient"] = None
_client_lock = threading.Lock()


class EmbeddingClient:
    """Client for the shared embedding daemon."""

    def __init__(self):
        self._sock = None

    def _connect(self) -> bool:
        """Connect to the daemon socket. Returns True on success."""
        if sys.platform == "win32":
            return False  # Daemon not supported on Windows; caller uses in-process ONNX
        if self._sock is not None:
            return True
        try:
            import socket

            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(_CONNECT_TIMEOUT)
            sock.connect(str(_SOCK_PATH))
            self._sock = sock
            return True
        except Exception:
            self._sock = None
            return False

    def _send_request(self, request: dict, timeout: float) -> Optional[dict]:
        """Send a request and read the response. Returns None on failure."""
        if self._sock is None:
            return None
        try:
            self._sock.settimeout(timeout)
            data = json.dumps(request).encode("utf-8")
            # Length-prefixed: 4-byte big-endian length + JSON
            self._sock.sendall(struct.pack(">I", len(data)) + data)

            # Read 4-byte length prefix
            length_bytes = self._recv_exact(4, timeout)
            if length_bytes is None:
                self.close()
                return None
            length = struct.unpack(">I", length_bytes)[0]

            # Read response
            resp_bytes = self._recv_exact(length, timeout)
            if resp_bytes is None:
                self.close()
                return None
            return json.loads(resp_bytes.decode("utf-8"))
        except Exception:
            self.close()
            return None

    def _recv_exact(self, n: int, timeout: float) -> Optional[bytes]:
        """Receive exactly n bytes from socket."""
        if self._sock is None:
            return None
        chunks = []
        remaining = n
        deadline = time.monotonic() + timeout
        while remaining > 0:
            now = time.monotonic()
            if now >= deadline:
                return None
            self._sock.settimeout(deadline - now)
            try:
                chunk = self._sock.recv(min(remaining, 65536))
                if not chunk:
                    return None
                chunks.append(chunk)
                remaining -= len(chunk)
            except Exception:
                return None
        return b"".join(chunks)

    def embed_single(self, text: str) -> Optional[List[float]]:
        """Embed a single text. Returns None if daemon unavailable."""
        if not self._connect():
            return None
        resp = self._send_request({"op": "embed_single", "text": text}, _SINGLE_TIMEOUT)
        if resp is None:
            return None
        if "error" in resp:
            logger.debug("Daemon error: %s", resp["error"])
            return None
        return resp.get("embedding")

    def embed_batch(self, texts: List[str]) -> Optional[List[List[float]]]:
        """Embed a batch of texts. Returns None if daemon unavailable."""
        if not texts:
            return []
        if not self._connect():
            return None
        resp = self._send_request({"op": "embed_batch", "texts": texts}, _BATCH_TIMEOUT)
        if resp is None:
            return None
        if "error" in resp:
            logger.debug("Daemon error: %s", resp["error"])
            return None
        return resp.get("embeddings")

    def health(self) -> Optional[dict]:
        """Check daemon health. Returns None if unavailable."""
        if not self._connect():
            return None
        return self._send_request({"op": "health"}, _SINGLE_TIMEOUT)

    def info(self) -> Optional[dict]:
        """Get daemon info. Returns None if unavailable."""
        if not self._connect():
            return None
        return self._send_request({"op": "info"}, _SINGLE_TIMEOUT)

    def close(self):
        """Close the connection."""
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None


def _is_daemon_disabled() -> bool:
    """Check if daemon is disabled via env var."""
    return os.environ.get("OMEGA_EMBEDDING_DAEMON") == "0"


def _is_daemon_alive() -> bool:
    """Check if the daemon process is actually running (not just stale files)."""
    if not _PID_PATH.exists():
        return False
    try:
        pid = int(_PID_PATH.read_text().strip())
        os.kill(pid, 0)  # Signal 0 = check if process exists
        return True
    except (ValueError, ProcessLookupError, PermissionError, OSError):
        return False


def _cleanup_stale_daemon():
    """Remove stale socket and PID files from a dead daemon."""
    try:
        _SOCK_PATH.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        _PID_PATH.unlink(missing_ok=True)
    except Exception:
        pass


def _auto_start_daemon() -> bool:
    """Start the embedding daemon if not running. Returns True if daemon is up."""
    if sys.platform == "win32":
        return False  # Daemon not supported on Windows

    # Check if daemon is actually alive, not just if socket file exists
    if _SOCK_PATH.exists() and _is_daemon_alive():
        return True

    # Daemon is dead — clean up stale files before restarting
    if _SOCK_PATH.exists() or _PID_PATH.exists():
        logger.debug("Cleaning up stale daemon files")
        _cleanup_stale_daemon()

    # Start the daemon
    try:
        python = sys.executable or "python3"
        subprocess.Popen(
            [python, "-m", "omega.embedding_daemon"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        # Wait up to 3 seconds for socket to appear
        for _ in range(30):
            time.sleep(0.1)
            if _SOCK_PATH.exists():
                return True
        logger.debug("Daemon auto-start timed out")
        return False
    except Exception as e:
        logger.debug("Failed to auto-start daemon: %s", e)
        return False


def get_client() -> Optional[EmbeddingClient]:
    """Get or create the singleton embedding client.

    Returns None if:
    - Daemon is disabled via OMEGA_EMBEDDING_DAEMON=0
    - Daemon is not running and auto-start fails
    - Connection fails
    """
    global _client

    if _is_daemon_disabled():
        return None

    with _client_lock:
        if _client is not None:
            # Quick health check via connection test
            if _client._sock is not None:
                return _client
            # Socket gone, try reconnect
            if _client._connect():
                return _client
            _client = None

        # Try to connect to existing daemon
        client = EmbeddingClient()
        if client._connect():
            _client = client
            return _client

        # Auto-start daemon
        if _auto_start_daemon():
            client = EmbeddingClient()
            if client._connect():
                _client = client
                return _client

        return None


def reset_client():
    """Reset the singleton client (for testing)."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
