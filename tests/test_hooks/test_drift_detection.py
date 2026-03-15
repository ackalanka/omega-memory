"""Test goal drift detection — session-end and periodic auto-drift check."""

from unittest.mock import patch, MagicMock


def test_drift_detected_when_no_overlap():
    from hooks.coord_session_stop import _detect_drift
    result = _detect_drift(
        original_task="Fix the login bug in auth.py",
        files_modified=["website/components/Dashboard.tsx", "website/styles/global.css"],
        commits=["refactor: redesign dashboard layout"],
    )
    assert result["drifted"] is True
    assert result["confidence"] > 0.5


def test_no_drift_when_aligned():
    from hooks.coord_session_stop import _detect_drift
    result = _detect_drift(
        original_task="Fix the login bug in auth.py",
        files_modified=["src/auth.py", "tests/test_auth.py"],
        commits=["fix: resolve login validation error"],
    )
    assert result["drifted"] is False


def test_drift_no_task():
    from hooks.coord_session_stop import _detect_drift
    result = _detect_drift(original_task=None, files_modified=["src/auth.py"], commits=["fix: something"])
    assert result["drifted"] is False


# ── Auto drift check (periodic PostToolUse) ──────────────────────────


def test_auto_drift_counter_increments():
    """Counter increments on each call."""
    from omega.server.hook_server import _drift_check_counter
    from omega.server.hook_server.memory import _auto_drift_check

    _drift_check_counter.clear()
    sid = "test-counter-inc"

    _auto_drift_check(sid, "/tmp/project")
    assert _drift_check_counter[sid] == 1

    _auto_drift_check(sid, "/tmp/project")
    assert _drift_check_counter[sid] == 2

    _drift_check_counter.clear()


def test_auto_drift_only_fires_on_interval():
    """Drift check only fires on multiples of DRIFT_CHECK_INTERVAL."""
    from omega.server.hook_server import _drift_check_counter, DRIFT_CHECK_INTERVAL
    from omega.server.hook_server.memory import _auto_drift_check

    _drift_check_counter.clear()
    sid = "test-interval"

    # Calls 1 through DRIFT_CHECK_INTERVAL-1 should return None without checking goals
    with patch("omega.coordination.get_manager") as mock_mgr:
        for i in range(1, DRIFT_CHECK_INTERVAL):
            result = _auto_drift_check(sid, "/tmp/project")
            assert result is None, f"Should not fire at call {i}"
        # get_manager should never have been called (we return early before import)
        mock_mgr.assert_not_called()

    _drift_check_counter.clear()


def test_auto_drift_returns_none_when_no_goals():
    """Returns None when no active goals exist."""
    from omega.server.hook_server import _drift_check_counter, DRIFT_CHECK_INTERVAL
    from omega.server.hook_server.memory import _auto_drift_check

    _drift_check_counter.clear()
    sid = "test-no-goals"
    # Set counter to just before the interval
    _drift_check_counter[sid] = DRIFT_CHECK_INTERVAL - 1

    mock_mgr = MagicMock()
    mock_mgr.list_goals.return_value = []

    with patch("omega.coordination.get_manager", return_value=mock_mgr):
        result = _auto_drift_check(sid, "/tmp/project")
    assert result is None

    _drift_check_counter.clear()


def test_auto_drift_returns_warning_on_high_score():
    """Returns a [DRIFT WARNING] string when drift score > 0.5."""
    from omega.server.hook_server import _drift_check_counter, DRIFT_CHECK_INTERVAL
    from omega.server.hook_server.memory import _auto_drift_check

    _drift_check_counter.clear()
    sid = "test-high-drift"
    _drift_check_counter[sid] = DRIFT_CHECK_INTERVAL - 1

    mock_mgr = MagicMock()
    mock_mgr.list_goals.return_value = [{"id": 42, "title": "Fix auth", "priority": 5}]
    mock_mgr.check_drift.return_value = {
        "goal_id": 42,
        "drift_score": 0.65,
        "alert_level": "warning",
        "drift_type": "scope_creep",
    }

    with patch("omega.coordination.get_manager", return_value=mock_mgr):
        result = _auto_drift_check(sid, "/tmp/project")

    assert result is not None
    assert "[DRIFT WARNING]" in result
    assert "65%" in result
    assert "scope_creep" in result

    _drift_check_counter.clear()


def test_auto_drift_returns_critical_on_high_score():
    """Returns a [DRIFT CRITICAL] string when alert_level is critical."""
    from omega.server.hook_server import _drift_check_counter, DRIFT_CHECK_INTERVAL
    from omega.server.hook_server.memory import _auto_drift_check

    _drift_check_counter.clear()
    sid = "test-critical-drift"
    _drift_check_counter[sid] = DRIFT_CHECK_INTERVAL - 1

    mock_mgr = MagicMock()
    mock_mgr.list_goals.return_value = [{"id": 10, "title": "Deploy", "priority": 9}]
    mock_mgr.check_drift.return_value = {
        "goal_id": 10,
        "drift_score": 0.85,
        "alert_level": "critical",
        "drift_type": "stall",
    }

    with patch("omega.coordination.get_manager", return_value=mock_mgr):
        result = _auto_drift_check(sid, "/tmp/project")

    assert result is not None
    assert "[DRIFT CRITICAL]" in result
    assert "85%" in result

    _drift_check_counter.clear()


def test_auto_drift_returns_none_on_low_score():
    """Returns None when drift score <= 0.5 (watch or none level)."""
    from omega.server.hook_server import _drift_check_counter, DRIFT_CHECK_INTERVAL
    from omega.server.hook_server.memory import _auto_drift_check

    _drift_check_counter.clear()
    sid = "test-low-drift"
    _drift_check_counter[sid] = DRIFT_CHECK_INTERVAL - 1

    mock_mgr = MagicMock()
    mock_mgr.list_goals.return_value = [{"id": 5, "title": "Test goal", "priority": 3}]
    mock_mgr.check_drift.return_value = {
        "goal_id": 5,
        "drift_score": 0.25,
        "alert_level": "none",
        "drift_type": "none",
    }

    with patch("omega.coordination.get_manager", return_value=mock_mgr):
        result = _auto_drift_check(sid, "/tmp/project")

    assert result is None

    _drift_check_counter.clear()


def test_auto_drift_fails_silently_on_import_error():
    """Returns None if coordination module is not available."""
    from omega.server.hook_server import _drift_check_counter, DRIFT_CHECK_INTERVAL
    from omega.server.hook_server.memory import _auto_drift_check

    _drift_check_counter.clear()
    sid = "test-import-fail"
    _drift_check_counter[sid] = DRIFT_CHECK_INTERVAL - 1

    with patch("omega.coordination.get_manager", side_effect=ImportError("no coordination")):
        result = _auto_drift_check(sid, "/tmp/project")

    assert result is None

    _drift_check_counter.clear()


def test_auto_drift_returns_none_for_empty_session_id():
    """Returns None immediately if session_id is empty."""
    from omega.server.hook_server.memory import _auto_drift_check

    result = _auto_drift_check("", "/tmp/project")
    assert result is None
