"""Tests for the OMEGA embedding client."""

import json
import os
import struct
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from omega.embedding_client import (
    EmbeddingClient,
    get_client,
    reset_client,
    _is_daemon_disabled,
)


# ---------------------------------------------------------------------------
# 1. EmbeddingClient basics
# ---------------------------------------------------------------------------

class TestEmbeddingClient:
    """Test EmbeddingClient connection and request methods."""

    def test_connect_fails_without_socket(self, tmp_path, monkeypatch):
        """Connection should fail when no socket exists."""
        monkeypatch.setattr("omega.embedding_client._SOCK_PATH", tmp_path / "no.sock")
        client = EmbeddingClient()
        assert client._connect() is False
        assert client._sock is None

    def test_embed_single_returns_none_when_disconnected(self, tmp_path, monkeypatch):
        monkeypatch.setattr("omega.embedding_client._SOCK_PATH", tmp_path / "no.sock")
        client = EmbeddingClient()
        assert client.embed_single("hello") is None

    def test_embed_batch_returns_none_when_disconnected(self, tmp_path, monkeypatch):
        monkeypatch.setattr("omega.embedding_client._SOCK_PATH", tmp_path / "no.sock")
        client = EmbeddingClient()
        assert client.embed_batch(["hello", "world"]) is None

    def test_embed_batch_empty_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr("omega.embedding_client._SOCK_PATH", tmp_path / "no.sock")
        client = EmbeddingClient()
        assert client.embed_batch([]) == []

    def test_health_returns_none_when_disconnected(self, tmp_path, monkeypatch):
        monkeypatch.setattr("omega.embedding_client._SOCK_PATH", tmp_path / "no.sock")
        client = EmbeddingClient()
        assert client.health() is None

    def test_info_returns_none_when_disconnected(self, tmp_path, monkeypatch):
        monkeypatch.setattr("omega.embedding_client._SOCK_PATH", tmp_path / "no.sock")
        client = EmbeddingClient()
        assert client.info() is None

    def test_close_is_idempotent(self):
        client = EmbeddingClient()
        client.close()  # No socket, should not raise
        client.close()  # Call again, still fine

    def test_close_clears_socket(self):
        client = EmbeddingClient()
        client._sock = MagicMock()
        client.close()
        assert client._sock is None


# ---------------------------------------------------------------------------
# 2. Daemon disabled check
# ---------------------------------------------------------------------------

class TestDaemonDisabled:
    """Test OMEGA_EMBEDDING_DAEMON=0 disables client."""

    def test_disabled_by_env_var(self, monkeypatch):
        monkeypatch.setenv("OMEGA_EMBEDDING_DAEMON", "0")
        assert _is_daemon_disabled() is True

    def test_enabled_by_default(self, monkeypatch):
        monkeypatch.delenv("OMEGA_EMBEDDING_DAEMON", raising=False)
        assert _is_daemon_disabled() is False

    def test_enabled_with_other_values(self, monkeypatch):
        monkeypatch.setenv("OMEGA_EMBEDDING_DAEMON", "1")
        assert _is_daemon_disabled() is False

    def test_get_client_returns_none_when_disabled(self, monkeypatch, tmp_path):
        monkeypatch.setenv("OMEGA_EMBEDDING_DAEMON", "0")
        monkeypatch.setattr("omega.embedding_client._SOCK_PATH", tmp_path / "no.sock")
        reset_client()
        assert get_client() is None


# ---------------------------------------------------------------------------
# 3. get_client / reset_client singleton
# ---------------------------------------------------------------------------

class TestGetClient:
    """Test singleton client management."""

    def test_get_client_returns_none_no_daemon(self, tmp_path, monkeypatch):
        """When no daemon is running and auto-start is mocked to fail."""
        monkeypatch.setattr("omega.embedding_client._SOCK_PATH", tmp_path / "no.sock")
        monkeypatch.setattr("omega.embedding_client._PID_PATH", tmp_path / "no.pid")
        monkeypatch.delenv("OMEGA_EMBEDDING_DAEMON", raising=False)
        # Prevent actual auto-start
        monkeypatch.setattr("omega.embedding_client._auto_start_daemon", lambda: False)
        reset_client()
        assert get_client() is None

    def test_reset_client_clears_singleton(self, monkeypatch, tmp_path):
        import omega.embedding_client as mod
        monkeypatch.setattr("omega.embedding_client._SOCK_PATH", tmp_path / "no.sock")
        # Set a fake client
        fake = EmbeddingClient()
        fake._sock = MagicMock()
        mod._client = fake
        reset_client()
        assert mod._client is None


# ---------------------------------------------------------------------------
# 4. send_request / recv_exact edge cases
# ---------------------------------------------------------------------------

class TestSendRequest:
    """Test request sending with mocked sockets."""

    def test_send_request_returns_none_without_socket(self):
        client = EmbeddingClient()
        assert client._send_request({"op": "health"}, 1.0) is None

    def test_recv_exact_returns_none_without_socket(self):
        client = EmbeddingClient()
        assert client._recv_exact(4, 1.0) is None

    def test_send_request_closes_on_error(self):
        client = EmbeddingClient()
        mock_sock = MagicMock()
        mock_sock.sendall.side_effect = ConnectionError("broken")
        client._sock = mock_sock
        result = client._send_request({"op": "health"}, 1.0)
        assert result is None
        assert client._sock is None  # Socket was cleaned up


# ---------------------------------------------------------------------------
# 5. Integration with a real Unix socket (no ONNX model needed)
# ---------------------------------------------------------------------------

class TestIntegrationWithMockDaemon:
    """Integration tests using a real Unix socket with a mock daemon."""

    @pytest.fixture
    def mock_daemon(self):
        """Start a minimal mock daemon that responds to health/info."""
        import asyncio
        import tempfile
        import threading

        # Use /tmp directly to avoid macOS AF_UNIX 104-char path limit
        tmpdir = tempfile.mkdtemp(prefix="omega_test_")
        sock_path = Path(tmpdir) / "e.sock"

        async def handle_conn(reader, writer):
            try:
                while True:
                    length_bytes = await reader.readexactly(4)
                    length = struct.unpack(">I", length_bytes)[0]
                    data = await reader.readexactly(length)
                    request = json.loads(data.decode("utf-8"))

                    op = request.get("op")
                    if op == "health":
                        response = {"status": "ok", "model_loaded": True, "backend": "mock", "uptime_s": 1}
                    elif op == "info":
                        response = {"protocol_version": 1, "model": "mock", "backend": "mock",
                                    "cache_size": 0, "cache_max": 2048, "request_count": 0,
                                    "uptime_s": 1, "pid": os.getpid()}
                    elif op == "embed_single":
                        response = {"embedding": [0.1] * 384}
                    elif op == "embed_batch":
                        texts = request.get("texts", [])
                        response = {"embeddings": [[0.1] * 384 for _ in texts]}
                    elif op == "shutdown":
                        response = {"status": "shutting_down"}
                    else:
                        response = {"error": f"unknown: {op}"}

                    resp_bytes = json.dumps(response).encode("utf-8")
                    writer.write(struct.pack(">I", len(resp_bytes)) + resp_bytes)
                    await writer.drain()
            except asyncio.IncompleteReadError:
                pass
            finally:
                writer.close()

        async def run_server():
            server = await asyncio.start_unix_server(handle_conn, path=str(sock_path))
            return server

        loop = asyncio.new_event_loop()
        server = loop.run_until_complete(run_server())

        def serve():
            loop.run_forever()

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()

        yield str(sock_path)

        # Cleanup
        loop.call_soon_threadsafe(server.close)
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2)
        loop.close()
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_health_check(self, mock_daemon, monkeypatch):
        monkeypatch.setattr("omega.embedding_client._SOCK_PATH", Path(mock_daemon))
        client = EmbeddingClient()
        assert client._connect() is True
        resp = client.health()
        assert resp is not None
        assert resp["status"] == "ok"
        client.close()

    def test_info(self, mock_daemon, monkeypatch):
        monkeypatch.setattr("omega.embedding_client._SOCK_PATH", Path(mock_daemon))
        client = EmbeddingClient()
        assert client._connect() is True
        resp = client.info()
        assert resp is not None
        assert resp["model"] == "mock"
        client.close()

    def test_embed_single(self, mock_daemon, monkeypatch):
        monkeypatch.setattr("omega.embedding_client._SOCK_PATH", Path(mock_daemon))
        client = EmbeddingClient()
        result = client.embed_single("hello")
        assert result is not None
        assert len(result) == 384
        client.close()

    def test_embed_batch(self, mock_daemon, monkeypatch):
        monkeypatch.setattr("omega.embedding_client._SOCK_PATH", Path(mock_daemon))
        client = EmbeddingClient()
        result = client.embed_batch(["hello", "world"])
        assert result is not None
        assert len(result) == 2
        assert len(result[0]) == 384
        client.close()

    def test_multiple_requests_on_same_connection(self, mock_daemon, monkeypatch):
        """Persistent connection should handle multiple requests."""
        monkeypatch.setattr("omega.embedding_client._SOCK_PATH", Path(mock_daemon))
        client = EmbeddingClient()
        for _ in range(5):
            resp = client.health()
            assert resp is not None
            assert resp["status"] == "ok"
        client.close()

    def test_get_client_returns_client_with_mock_daemon(self, mock_daemon, monkeypatch):
        monkeypatch.setattr("omega.embedding_client._SOCK_PATH", Path(mock_daemon))
        monkeypatch.delenv("OMEGA_EMBEDDING_DAEMON", raising=False)
        reset_client()
        client = get_client()
        assert client is not None
        resp = client.health()
        assert resp["status"] == "ok"
        reset_client()
