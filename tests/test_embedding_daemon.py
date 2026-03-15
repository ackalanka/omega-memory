"""Tests for the OMEGA embedding daemon."""

import json
import os
import struct
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from omega.embedding_daemon import (
    EmbeddingDaemon,
    is_daemon_running,
    get_daemon_pid,
    stop_daemon,
    _PROTOCOL_VERSION,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _send_request(sock_path: str, request: dict, timeout: float = 5.0) -> dict:
    """Send a length-prefixed JSON request to a Unix socket and read response."""
    import socket

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    sock.connect(sock_path)

    data = json.dumps(request).encode("utf-8")
    sock.sendall(struct.pack(">I", len(data)) + data)

    # Read 4-byte length prefix
    length_bytes = b""
    while len(length_bytes) < 4:
        chunk = sock.recv(4 - len(length_bytes))
        if not chunk:
            raise ConnectionError("Connection closed")
        length_bytes += chunk

    length = struct.unpack(">I", length_bytes)[0]

    # Read response
    resp_bytes = b""
    while len(resp_bytes) < length:
        chunk = sock.recv(length - len(resp_bytes))
        if not chunk:
            raise ConnectionError("Connection closed")
        resp_bytes += chunk

    sock.close()
    return json.loads(resp_bytes.decode("utf-8"))


# ---------------------------------------------------------------------------
# 1. PID file and lock management
# ---------------------------------------------------------------------------

class TestPidLock:
    """Test PID file acquisition and release."""

    def test_acquire_pid_lock(self, tmp_path, monkeypatch):
        monkeypatch.setattr("omega.embedding_daemon.OMEGA_DIR", tmp_path)
        monkeypatch.setattr("omega.embedding_daemon.PID_PATH", tmp_path / "embed.pid")
        daemon = EmbeddingDaemon()
        assert daemon._acquire_pid_lock() is True
        # PID file should contain our PID
        pid_content = (tmp_path / "embed.pid").read_text()
        assert pid_content == str(os.getpid())
        daemon._release_pid_lock()

    def test_double_acquire_fails(self, tmp_path, monkeypatch):
        """Second daemon instance should fail to acquire lock."""
        monkeypatch.setattr("omega.embedding_daemon.OMEGA_DIR", tmp_path)
        monkeypatch.setattr("omega.embedding_daemon.PID_PATH", tmp_path / "embed.pid")
        daemon1 = EmbeddingDaemon()
        daemon2 = EmbeddingDaemon()
        assert daemon1._acquire_pid_lock() is True
        assert daemon2._acquire_pid_lock() is False
        daemon1._release_pid_lock()

    def test_release_cleans_up(self, tmp_path, monkeypatch):
        monkeypatch.setattr("omega.embedding_daemon.OMEGA_DIR", tmp_path)
        monkeypatch.setattr("omega.embedding_daemon.PID_PATH", tmp_path / "embed.pid")
        daemon = EmbeddingDaemon()
        daemon._acquire_pid_lock()
        daemon._release_pid_lock()
        assert not (tmp_path / "embed.pid").exists()


# ---------------------------------------------------------------------------
# 2. Request handling (unit tests, no socket)
# ---------------------------------------------------------------------------

class TestRequestHandling:
    """Test _handle_request with a mock model."""

    def _make_daemon_with_mock_model(self):
        daemon = EmbeddingDaemon()
        daemon._model = ("fake_tokenizer", "fake_session")
        daemon._backend = "onnx"
        daemon._model_name = "test-model"
        return daemon

    def test_health_check(self):
        daemon = self._make_daemon_with_mock_model()
        resp = daemon._handle_request({"op": "health"})
        assert resp["status"] == "ok"
        assert resp["model_loaded"] is True
        assert resp["backend"] == "onnx"
        assert "uptime_s" in resp

    def test_info(self):
        daemon = self._make_daemon_with_mock_model()
        resp = daemon._handle_request({"op": "info"})
        assert resp["model"] == "test-model"
        assert resp["protocol_version"] == _PROTOCOL_VERSION
        assert resp["pid"] == os.getpid()
        assert "cache_size" in resp

    def test_shutdown(self):
        daemon = self._make_daemon_with_mock_model()
        resp = daemon._handle_request({"op": "shutdown"})
        assert resp["status"] == "shutting_down"
        assert daemon._shutdown_event.is_set()

    def test_unknown_op(self):
        daemon = self._make_daemon_with_mock_model()
        resp = daemon._handle_request({"op": "nonexistent"})
        assert "error" in resp
        assert "unknown op" in resp["error"]

    def test_embed_single_missing_text(self):
        daemon = self._make_daemon_with_mock_model()
        resp = daemon._handle_request({"op": "embed_single"})
        assert "error" in resp

    def test_embed_batch_empty(self):
        daemon = self._make_daemon_with_mock_model()
        resp = daemon._handle_request({"op": "embed_batch", "texts": []})
        assert resp["embeddings"] == []

    def test_request_increments_count(self):
        daemon = self._make_daemon_with_mock_model()
        assert daemon._request_count == 0
        daemon._handle_request({"op": "health"})
        assert daemon._request_count == 1
        daemon._handle_request({"op": "health"})
        assert daemon._request_count == 2

    def test_request_updates_activity(self):
        daemon = self._make_daemon_with_mock_model()
        old_time = daemon._last_activity
        time.sleep(0.01)
        daemon._handle_request({"op": "health"})
        assert daemon._last_activity > old_time


# ---------------------------------------------------------------------------
# 3. Embedding with cache (unit tests, mocked encode)
# ---------------------------------------------------------------------------

class TestEmbedWithCache:
    """Test _embed_with_cache with a mocked _encode."""

    def test_cache_miss_then_hit(self):
        daemon = EmbeddingDaemon()
        fake_embedding = [[0.1] * 384]
        daemon._encode = MagicMock(return_value=fake_embedding)

        # First call: cache miss
        result1 = daemon._embed_with_cache(["hello"])
        assert daemon._encode.call_count == 1
        assert result1 == fake_embedding

        # Second call: cache hit
        result2 = daemon._embed_with_cache(["hello"])
        assert daemon._encode.call_count == 1  # No additional call
        assert result2 == fake_embedding

    def test_cache_eviction(self):
        daemon = EmbeddingDaemon()
        daemon._encode = MagicMock(side_effect=lambda texts: [[float(i)] * 384 for i, _ in enumerate(texts)])

        # Fill cache beyond max
        import omega.embedding_daemon as mod
        old_max = mod._CACHE_MAX
        mod._CACHE_MAX = 3
        try:
            for i in range(5):
                daemon._embed_with_cache([f"text_{i}"])
            assert len(daemon._cache) <= 3
        finally:
            mod._CACHE_MAX = old_max

    def test_batch_partial_cache(self):
        daemon = EmbeddingDaemon()
        call_count = 0

        def mock_encode(texts):
            nonlocal call_count
            call_count += 1
            return [[0.5] * 384 for _ in texts]

        daemon._encode = mock_encode

        # Prime cache with "alpha"
        daemon._embed_with_cache(["alpha"])
        assert call_count == 1

        # Request batch with alpha (cached) + beta (miss)
        result = daemon._embed_with_cache(["alpha", "beta"])
        assert call_count == 2  # Only one more call for "beta"
        assert len(result) == 2


# ---------------------------------------------------------------------------
# 4. is_daemon_running / get_daemon_pid / stop_daemon
# ---------------------------------------------------------------------------

class TestDaemonStatus:
    """Test status check functions."""

    def test_not_running_no_pid_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("omega.embedding_daemon.PID_PATH", tmp_path / "nonexistent.pid")
        assert is_daemon_running() is False
        assert get_daemon_pid() is None

    def test_stale_pid_file(self, tmp_path, monkeypatch):
        """PID file pointing to non-existent process."""
        pid_file = tmp_path / "embed.pid"
        pid_file.write_text("999999999")  # Very unlikely to exist
        monkeypatch.setattr("omega.embedding_daemon.PID_PATH", pid_file)
        assert is_daemon_running() is False
        assert get_daemon_pid() is None

    def test_running_with_own_pid(self, tmp_path, monkeypatch):
        """PID file pointing to current process (simulates running daemon)."""
        pid_file = tmp_path / "embed.pid"
        pid_file.write_text(str(os.getpid()))
        monkeypatch.setattr("omega.embedding_daemon.PID_PATH", pid_file)
        assert is_daemon_running() is True
        assert get_daemon_pid() == os.getpid()

    def test_stop_daemon_not_running(self, tmp_path, monkeypatch):
        monkeypatch.setattr("omega.embedding_daemon.PID_PATH", tmp_path / "nonexistent.pid")
        assert stop_daemon() is False


# ---------------------------------------------------------------------------
# 5. Model loading
# ---------------------------------------------------------------------------

class TestModelLoading:
    """Test model loading logic."""

    def test_load_fails_without_onnx(self, monkeypatch):
        daemon = EmbeddingDaemon()
        monkeypatch.setattr("omega.embedding._ONNX_CHECKED", True)
        monkeypatch.setattr("omega.embedding._ONNX_AVAILABLE", False)
        assert daemon._load_model() is False
        assert daemon._model is None

    def test_load_fails_without_model_dir(self, monkeypatch, tmp_path):
        daemon = EmbeddingDaemon()
        monkeypatch.setattr("omega.embedding._ONNX_CHECKED", True)
        monkeypatch.setattr("omega.embedding._ONNX_AVAILABLE", True)
        monkeypatch.setattr("omega.embedding._ONNX_MODEL_DIR", None)
        monkeypatch.setattr("omega.embedding._ONNX_DEFAULT_DIR", str(tmp_path / "nope"))
        monkeypatch.setattr("omega.embedding._ONNX_FALLBACK_DIR", str(tmp_path / "nope2"))
        monkeypatch.delenv("OMEGA_ONNX_MODEL_DIR", raising=False)
        assert daemon._load_model() is False


# ---------------------------------------------------------------------------
# 6. Cleanup
# ---------------------------------------------------------------------------

class TestCleanup:
    """Test socket and PID file cleanup."""

    def test_cleanup_removes_socket_and_pid(self, tmp_path, monkeypatch):
        sock = tmp_path / "embed.sock"
        pid = tmp_path / "embed.pid"
        sock.write_text("fake")
        pid.write_text("fake")
        monkeypatch.setattr("omega.embedding_daemon.SOCK_PATH", sock)
        monkeypatch.setattr("omega.embedding_daemon.PID_PATH", pid)
        daemon = EmbeddingDaemon()
        daemon._cleanup()
        assert not sock.exists()
        assert not pid.exists()

    def test_cleanup_tolerates_missing_files(self, tmp_path, monkeypatch):
        monkeypatch.setattr("omega.embedding_daemon.SOCK_PATH", tmp_path / "no.sock")
        monkeypatch.setattr("omega.embedding_daemon.PID_PATH", tmp_path / "no.pid")
        daemon = EmbeddingDaemon()
        daemon._cleanup()  # Should not raise
