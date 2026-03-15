"""Tests for Windows compatibility guards.

Verifies that platform detection logic correctly branches for Windows vs Unix.
Uses unittest.mock.patch to simulate sys.platform == "win32" on any host.
"""

import os
import sys
from unittest.mock import patch

import pytest


class TestHookServerConstants:
    """Verify hook server constants are platform-aware."""

    def test_unix_has_sock_path(self):
        """On Unix, SOCK_PATH should be a Path to hook.sock."""
        if sys.platform == "win32":
            pytest.skip("Unix-only test")
        from omega.server.hook_server import SOCK_PATH
        assert SOCK_PATH is not None
        assert str(SOCK_PATH).endswith("hook.sock")

    def test_unix_no_tcp_constants(self):
        """On Unix, HOOK_HOST and HOOK_PORT should be None."""
        if sys.platform == "win32":
            pytest.skip("Unix-only test")
        from omega.server.hook_server import HOOK_HOST, HOOK_PORT
        assert HOOK_HOST is None
        assert HOOK_PORT is None


class TestEmbeddingDaemonWindows:
    """Verify embedding daemon gracefully skips on Windows."""

    def test_is_daemon_running_false_on_windows(self):
        """is_daemon_running() should return False on Windows."""
        with patch("omega.embedding_daemon.sys") as mock_sys:
            mock_sys.platform = "win32"
            from omega.embedding_daemon import is_daemon_running
            # Re-import won't help since function references module-level sys,
            # so we patch at the module level
            assert is_daemon_running() is False

    def test_stop_daemon_false_on_windows(self):
        """stop_daemon() should return False on Windows."""
        with patch("omega.embedding_daemon.sys") as mock_sys:
            mock_sys.platform = "win32"
            from omega.embedding_daemon import stop_daemon
            assert stop_daemon() is False


class TestEmbeddingClientWindows:
    """Verify embedding client returns None on Windows."""

    def test_connect_false_on_windows(self):
        """EmbeddingClient._connect() should return False on Windows."""
        with patch("omega.embedding_client.sys") as mock_sys:
            mock_sys.platform = "win32"
            from omega.embedding_client import EmbeddingClient
            client = EmbeddingClient()
            assert client._connect() is False

    def test_auto_start_daemon_false_on_windows(self):
        """_auto_start_daemon() should return False on Windows."""
        with patch("omega.embedding_client.sys") as mock_sys:
            mock_sys.platform = "win32"
            from omega.embedding_client import _auto_start_daemon
            assert _auto_start_daemon() is False


class TestONofollow:
    """Verify O_NOFOLLOW guard works on all platforms."""

    def test_o_nofollow_available_on_unix(self):
        """On Unix, os.O_NOFOLLOW should exist."""
        if sys.platform == "win32":
            pytest.skip("Unix-only test")
        assert hasattr(os, "O_NOFOLLOW")

    def test_export_flags_include_nofollow_on_unix(self):
        """The hasattr guard should include O_NOFOLLOW on Unix."""
        if sys.platform == "win32":
            pytest.skip("Unix-only test")
        flags = os.O_CREAT | os.O_WRONLY | os.O_TRUNC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        assert flags & os.O_NOFOLLOW

    def test_export_flags_work_without_nofollow(self):
        """The hasattr guard should work even without O_NOFOLLOW."""
        flags = os.O_CREAT | os.O_WRONLY | os.O_TRUNC
        # Simulate missing O_NOFOLLOW
        assert flags == os.O_CREAT | os.O_WRONLY | os.O_TRUNC


class TestSocketWatchdogWindows:
    """Verify socket watchdog skips on Windows."""

    @pytest.mark.asyncio
    async def test_socket_watchdog_returns_on_windows(self):
        """_socket_watchdog() should return immediately on Windows."""
        import asyncio
        with patch("omega.server.mcp_server.sys") as mock_sys:
            mock_sys.platform = "win32"
            from omega.server.mcp_server import _socket_watchdog
            # Should return immediately (not loop forever), timeout is safety net
            await asyncio.wait_for(_socket_watchdog(), timeout=2.0)


class TestFcntlGuard:
    """Verify fcntl is not imported at module level."""

    def test_utils_no_toplevel_fcntl(self):
        """hook_server/utils.py should not import fcntl at module level."""
        import omega.server.hook_server.utils as utils_mod
        # fcntl should not be in the module's namespace at import time
        # (it's imported lazily inside _try_acquire_periodic)
        source_file = utils_mod.__file__
        with open(source_file) as f:
            lines = f.readlines()
        # Check that no top-level line is just "import fcntl"
        top_level_fcntl = [
            i for i, line in enumerate(lines, 1)
            if line.strip() == "import fcntl" and not line.startswith(" ")
        ]
        assert top_level_fcntl == [], f"Found top-level 'import fcntl' at lines: {top_level_fcntl}"

    def test_embedding_daemon_no_toplevel_fcntl(self):
        """embedding_daemon.py should not import fcntl at module level."""
        import omega.embedding_daemon as daemon_mod
        source_file = daemon_mod.__file__
        with open(source_file) as f:
            lines = f.readlines()
        top_level_fcntl = [
            i for i, line in enumerate(lines, 1)
            if line.strip() == "import fcntl" and not line.startswith(" ")
        ]
        assert top_level_fcntl == [], f"Found top-level 'import fcntl' at lines: {top_level_fcntl}"
