"""OMEGA Embedding Daemon -- Shared embedding model over Unix socket.

Single long-lived process loads the ONNX model once and serves all MCP server
instances over a Unix domain socket. Eliminates per-process model duplication
(each copy costs ~170MB with ONNX, or 7.5GB if PyTorch fallback was triggered).

Protocol: length-prefixed JSON (4-byte big-endian length + JSON payload).
Socket: ~/.omega/embed.sock
PID file: ~/.omega/embed.pid

Operations: embed_single, embed_batch, health, info, shutdown
"""

import asyncio
import json
import logging
import os
import signal
import struct
import sys
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("omega.embedding_daemon")

OMEGA_DIR = Path.home() / ".omega"
SOCK_PATH = OMEGA_DIR / "embed.sock"
PID_PATH = OMEGA_DIR / "embed.pid"

_IDLE_TIMEOUT_S = 1800  # 30 minutes (longer than per-process since shared)
_CACHE_MAX = 2048
_PROTOCOL_VERSION = 1


class EmbeddingDaemon:
    """Shared embedding daemon serving ONNX embeddings over Unix socket."""

    def __init__(self, no_idle_timeout: bool = False):
        self._model = None
        self._backend: Optional[str] = None
        self._model_name: str = "unknown"
        self._cache: OrderedDict = OrderedDict()
        self._state_lock = threading.Lock()
        self._server: Optional[asyncio.Server] = None
        self._last_activity: float = time.monotonic()
        self._request_count: int = 0
        self._start_time: float = time.monotonic()
        self._shutdown_event = asyncio.Event()
        self._pid_fd: Optional[int] = None
        self._no_idle_timeout = no_idle_timeout

    def _load_model(self) -> bool:
        """Load the ONNX embedding model. Returns True on success.

        The model can be overridden at runtime via the ``OMEGA_EMBEDDING_MODEL``
        environment variable.  Set it to a model name (e.g. ``NV-Embed-v2``,
        ``bge-small-en-v1.5``, ``all-MiniLM-L6-v2``) to select a specific
        backend without modifying source code.  This enables A/B testing of
        retrieval accuracy vs. latency trade-offs (e.g. NV-Embed-v2 at 1.3B
        params vs. the default lightweight ONNX model).
        """
        # Allow runtime model override for A/B testing without code changes.
        # Example: OMEGA_EMBEDDING_MODEL=NV-Embed-v2 omega-embedding-daemon
        model_override = os.environ.get("OMEGA_EMBEDDING_MODEL", "").strip()
        if model_override:
            logger.info(
                "OMEGA_EMBEDDING_MODEL override detected: %r", model_override
            )

        try:
            from omega.embedding import _check_onnx_runtime, _get_onnx_model_dir

            if not _check_onnx_runtime():
                logger.error("onnxruntime not available")
                return False

            onnx_dir = _get_onnx_model_dir(model_override or None)
            if not onnx_dir:
                logger.error("No ONNX model directory found")
                return False

            import onnxruntime as ort
            from tokenizers import Tokenizer as FastTokenizer

            tokenizer = FastTokenizer.from_file(f"{onnx_dir}/tokenizer.json")
            tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
            tokenizer.enable_truncation(max_length=512)

            sess_opts = ort.SessionOptions()
            sess_opts.log_severity_level = 4
            sess_opts.log_verbosity_level = 0
            sess_opts.enable_cpu_mem_arena = False

            import contextlib
            import io

            providers = ["CPUExecutionProvider"]
            with contextlib.redirect_stderr(io.StringIO()):
                session = ort.InferenceSession(
                    f"{onnx_dir}/model.onnx",
                    sess_options=sess_opts,
                    providers=providers,
                )

            self._model = (tokenizer, session)
            self._backend = "onnx"
            # Determine model name: env override takes precedence, then infer
            # from the directory path so the ``info`` op always reflects the
            # model actually in use (important for A/B test attribution).
            if model_override:
                self._model_name = model_override
            elif "bge-small" in onnx_dir:
                self._model_name = "bge-small-en-v1.5"
            elif "MiniLM" in onnx_dir:
                self._model_name = "all-MiniLM-L6-v2"
            elif "NV-Embed" in onnx_dir:
                self._model_name = "NV-Embed-v2"
            else:
                self._model_name = os.path.basename(onnx_dir)

            logger.info("Loaded ONNX model from %s", onnx_dir)
            return True
        except Exception as e:
            logger.error("Failed to load embedding model: %s", e)
            return False

    def _encode(self, texts: List[str]) -> List[List[float]]:
        """Encode texts using the loaded ONNX model."""
        import numpy as np

        tokenizer, session = self._model
        batch = tokenizer.encode_batch(texts)
        ids = np.array([b.ids for b in batch], dtype=np.int64)
        mask = np.array([b.attention_mask for b in batch], dtype=np.int64)
        feed = {"input_ids": ids, "attention_mask": mask}
        input_names = {i.name for i in session.get_inputs()}
        if "token_type_ids" in input_names:
            feed["token_type_ids"] = np.zeros_like(ids)
        outputs = session.run(None, feed)
        embeddings = outputs[1] if len(outputs) > 1 else outputs[0]
        if embeddings.ndim == 3:
            mask_expanded = mask[:, :, np.newaxis].astype(np.float32)
            sum_emb = np.sum(embeddings * mask_expanded, axis=1)
            sum_mask = np.clip(np.sum(mask_expanded, axis=1), a_min=1e-9, a_max=None)
            embeddings = sum_emb / sum_mask
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        normalized = embeddings / np.clip(norms, a_min=1e-9, a_max=None)
        return normalized.tolist()

    def _embed_with_cache(self, texts: List[str]) -> List[List[float]]:
        """Embed texts, using cache for hits and batching misses."""
        import hashlib

        results = [None] * len(texts)
        misses = []  # (index, text) pairs that need embedding
        miss_indices = []

        with self._state_lock:
            for i, text in enumerate(texts):
                cache_key = hashlib.md5(text.encode()).hexdigest()
                if cache_key in self._cache:
                    self._cache.move_to_end(cache_key)
                    results[i] = self._cache[cache_key]
                else:
                    misses.append(text)
                    miss_indices.append(i)

        if misses:
            # Batch encode all cache misses WITHOUT holding the lock
            embeddings = self._encode(misses)
            with self._state_lock:
                for j, (text, emb) in enumerate(zip(misses, embeddings)):
                    idx = miss_indices[j]
                    results[idx] = emb
                    cache_key = hashlib.md5(text.encode()).hexdigest()
                    self._cache[cache_key] = emb
                    while len(self._cache) > _CACHE_MAX:
                        self._cache.popitem(last=False)

        return results

    def _handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle a single request. Returns response dict."""
        op = request.get("op")
        with self._state_lock:
            self._last_activity = time.monotonic()
            self._request_count += 1

        if op == "embed_single":
            text = request.get("text", "")
            if not text:
                return {"error": "missing 'text' field"}
            results = self._embed_with_cache([text])
            return {"embedding": results[0]}

        elif op == "embed_batch":
            texts = request.get("texts", [])
            if not texts:
                return {"embeddings": []}
            results = self._embed_with_cache(texts)
            return {"embeddings": results}

        elif op == "health":
            return {
                "status": "ok",
                "model_loaded": self._model is not None,
                "backend": self._backend,
                "uptime_s": int(time.monotonic() - self._start_time),
            }

        elif op == "info":
            with self._state_lock:
                cache_size = len(self._cache)
                request_count = self._request_count
            return {
                "protocol_version": _PROTOCOL_VERSION,
                "model": self._model_name,
                "backend": self._backend,
                "cache_size": cache_size,
                "cache_max": _CACHE_MAX,
                "request_count": request_count,
                "uptime_s": int(time.monotonic() - self._start_time),
                "pid": os.getpid(),
            }

        elif op == "shutdown":
            self._shutdown_event.set()
            return {"status": "shutting_down"}

        else:
            return {"error": f"unknown op: {op}"}

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """Handle a single client connection using length-prefixed JSON."""
        try:
            while True:
                # Read 4-byte length prefix
                length_bytes = await asyncio.wait_for(reader.readexactly(4), timeout=30.0)
                length = struct.unpack(">I", length_bytes)[0]

                if length > 10_000_000:  # 10MB sanity limit
                    # Send error and close the connection — avoids draining
                    # an arbitrarily large payload that could stall the loop.
                    response = {"error": "request too large"}
                    resp_bytes = json.dumps(response).encode("utf-8")
                    writer.write(struct.pack(">I", len(resp_bytes)) + resp_bytes)
                    await writer.drain()
                    break
                else:
                    data = await asyncio.wait_for(reader.readexactly(length), timeout=30.0)
                    request = json.loads(data.decode("utf-8"))

                    # Run embedding in thread to avoid blocking event loop
                    loop = asyncio.get_running_loop()
                    response = await loop.run_in_executor(None, self._handle_request, request)

                # Write response with length prefix
                resp_bytes = json.dumps(response).encode("utf-8")
                writer.write(struct.pack(">I", len(resp_bytes)) + resp_bytes)
                await writer.drain()
        except asyncio.IncompleteReadError:
            pass  # Client disconnected
        except asyncio.TimeoutError:
            pass  # Client idle
        except Exception as e:
            logger.debug("Connection error: %s", e)
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    def _acquire_pid_lock(self) -> bool:
        """Acquire exclusive lock on PID file. Returns True if we got the lock."""
        if sys.platform == "win32":
            return False  # Daemon not supported on Windows
        OMEGA_DIR.mkdir(parents=True, exist_ok=True)
        try:
            import fcntl
            self._pid_fd = os.open(str(PID_PATH), os.O_CREAT | os.O_RDWR, 0o644)
            fcntl.flock(self._pid_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            os.ftruncate(self._pid_fd, 0)
            os.lseek(self._pid_fd, 0, os.SEEK_SET)
            os.write(self._pid_fd, str(os.getpid()).encode())
            return True
        except (OSError, IOError):
            if self._pid_fd is not None:
                os.close(self._pid_fd)
                self._pid_fd = None
            return False

    def _release_pid_lock(self):
        """Release PID file lock and clean up."""
        if sys.platform == "win32":
            return
        if self._pid_fd is not None:
            try:
                import fcntl
                fcntl.flock(self._pid_fd, fcntl.LOCK_UN)
                os.close(self._pid_fd)
            except Exception:
                pass
            self._pid_fd = None
        try:
            PID_PATH.unlink(missing_ok=True)
        except Exception:
            pass

    def _cleanup(self):
        """Remove socket and PID file."""
        try:
            SOCK_PATH.unlink(missing_ok=True)
        except Exception:
            pass
        self._release_pid_lock()

    async def _idle_watchdog(self):
        """Shut down after _IDLE_TIMEOUT_S of inactivity (unless disabled)."""
        if self._no_idle_timeout:
            return  # Managed by launchd/systemd — never idle-exit
        while not self._shutdown_event.is_set():
            await asyncio.sleep(60)
            with self._state_lock:
                idle = time.monotonic() - self._last_activity
            if idle > _IDLE_TIMEOUT_S:
                logger.info("Idle timeout (%ds), shutting down", _IDLE_TIMEOUT_S)
                self._shutdown_event.set()
                break

    async def run(self):
        """Start the daemon and serve until shutdown."""
        if sys.platform == "win32":
            logger.info("Embedding daemon not supported on Windows, skipping")
            return

        # Acquire PID lock (prevents double-start)
        if not self._acquire_pid_lock():
            logger.info("Another embedding daemon is already running")
            return

        # Load model
        if not self._load_model():
            logger.error("Failed to load embedding model, exiting")
            self._cleanup()
            return

        # Remove stale socket
        SOCK_PATH.unlink(missing_ok=True)

        # Start server
        self._server = await asyncio.start_unix_server(
            self._handle_connection,
            path=str(SOCK_PATH),
        )

        # Set socket permissions (owner-only, matches hook.sock)
        SOCK_PATH.chmod(0o600)

        logger.info("Embedding daemon started (PID %d, socket %s)", os.getpid(), SOCK_PATH)

        # Install signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._shutdown_event.set)

        # Start idle watchdog
        watchdog = asyncio.create_task(self._idle_watchdog())

        # Wait for shutdown
        await self._shutdown_event.wait()

        # Clean shutdown
        logger.info("Shutting down embedding daemon")
        self._server.close()
        await self._server.wait_closed()
        watchdog.cancel()
        self._cleanup()


def is_daemon_running() -> bool:
    """Check if an embedding daemon is already running."""
    if sys.platform == "win32":
        return False
    if not PID_PATH.exists():
        return False
    try:
        pid = int(PID_PATH.read_text().strip())
        os.kill(pid, 0)  # Check if process exists
        return True
    except (ValueError, ProcessLookupError, PermissionError, OSError):
        return False


def get_daemon_pid() -> Optional[int]:
    """Get the PID of the running daemon, or None."""
    if not PID_PATH.exists():
        return None
    try:
        pid = int(PID_PATH.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (ValueError, ProcessLookupError, PermissionError, OSError):
        return None


def stop_daemon() -> bool:
    """Stop the running daemon. Returns True if a daemon was stopped."""
    if sys.platform == "win32":
        return False
    pid = get_daemon_pid()
    if pid is None:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
        # Wait up to 5 seconds for clean exit
        for _ in range(50):
            try:
                os.kill(pid, 0)
                time.sleep(0.1)
            except ProcessLookupError:
                break
        # Check if still alive after SIGTERM poll
        try:
            os.kill(pid, 0)  # Still alive after SIGTERM
            os.kill(pid, signal.SIGKILL)
            time.sleep(0.5)
            try:
                os.kill(pid, 0)
                return False  # Still alive even after SIGKILL
            except ProcessLookupError:
                pass  # SIGKILL worked
        except ProcessLookupError:
            pass  # SIGTERM worked
        return True
    except (ProcessLookupError, PermissionError):
        return False


def main():
    """Entry point for the embedding daemon process."""
    import argparse

    parser = argparse.ArgumentParser(description="OMEGA shared embedding daemon")
    parser.add_argument(
        "--no-idle-timeout",
        action="store_true",
        help="Disable idle timeout (use when managed by launchd/systemd)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Kill any existing daemon before starting (use with launchd)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    if args.force:
        stopped = stop_daemon()
        if stopped:
            logger.info("Stopped existing daemon (--force)")
            # Wait for clean shutdown
            time.sleep(0.5)
        # Clean up stale files regardless
        SOCK_PATH.unlink(missing_ok=True)
        PID_PATH.unlink(missing_ok=True)

    daemon = EmbeddingDaemon(no_idle_timeout=args.no_idle_timeout)
    asyncio.run(daemon.run())


if __name__ == "__main__":
    main()
