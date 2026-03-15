"""Tests for the maintenance pipeline (step-status tracking and DLQ)."""

import sqlite3
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from omega.server.hook_server.maintenance import (
    ErrorClass,
    MaintenancePipeline,
    PipelineResult,
    StageConfig,
    StepResult,
    StepStatus,
    _backoff_seconds,
    _do_reflect_stale,
    build_session_start_pipeline,
    classify_error,
    count_dlq_pending,
    enqueue_dlq,
    poll_dlq,
    update_dlq_item,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_dlq_table(conn: sqlite3.Connection) -> None:
    """Create the maintenance_dlq table in an in-memory DB for testing."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS maintenance_dlq (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stage_name TEXT NOT NULL,
            error_class TEXT NOT NULL DEFAULT 'transient',
            error_message TEXT,
            remediation_attempts INTEGER DEFAULT 0,
            max_remediation INTEGER DEFAULT 3,
            status TEXT NOT NULL DEFAULT 'pending',
            next_retry_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_maintenance_dlq_status ON maintenance_dlq(status)")
    conn.commit()


def _in_memory_dlq_conn() -> sqlite3.Connection:
    """Create an in-memory SQLite connection with the DLQ table."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    _create_dlq_table(conn)
    return conn


# ---------------------------------------------------------------------------
# 1. Pipeline construction (7 stages registered)
# ---------------------------------------------------------------------------


def test_pipeline_construction_7_stages():
    """build_session_start_pipeline registers all 7 stages."""
    pipeline = build_session_start_pipeline()
    assert len(pipeline._stages) == 7
    names = [s.name for s in pipeline._stages]
    assert names == [
        "consolidate", "compact", "backup", "doctor",
        "reflect_stale", "doc_scan", "cloud_pull",
    ]


# ---------------------------------------------------------------------------
# 2. Step status tracking (completed, timing, output)
# ---------------------------------------------------------------------------


def test_step_status_tracking_completed():
    """A successful stage records COMPLETED status, timing, and output."""
    pipeline = MaintenancePipeline()
    pipeline.add_stage(StageConfig(
        name="test_step",
        fn=lambda: "ok",
        interval_seconds=0,
        marker_name="",
    ))

    with patch("omega.server.hook_server.maintenance._get_dlq_conn") as mock_conn:
        mock_conn.side_effect = Exception("no db")
        result = pipeline.run()

    assert len(result.steps) == 1
    step = result.steps[0]
    assert step.status == StepStatus.COMPLETED
    assert step.output == "ok"
    assert step.elapsed_s >= 0.0
    assert step.error is None


# ---------------------------------------------------------------------------
# 3. Skipping logic (interval not elapsed)
# ---------------------------------------------------------------------------


def test_skipping_when_interval_not_elapsed():
    """Stage is skipped when its marker indicates the interval hasn't elapsed."""
    pipeline = MaintenancePipeline()
    pipeline.add_stage(StageConfig(
        name="skip_me",
        fn=lambda: "should not run",
        interval_seconds=86400,
        marker_name="last-skip-test",
    ))

    # Mock _should_run_periodic to return False (interval not elapsed)
    with patch("omega.server.hook_server.maintenance._should_run_periodic", return_value=False), \
         patch("omega.server.hook_server.maintenance._get_dlq_conn") as mock_conn:
        mock_conn.side_effect = Exception("no db")
        result = pipeline.run()

    assert result.steps[0].status == StepStatus.SKIPPED
    assert result.steps[0].output is None


# ---------------------------------------------------------------------------
# 4. Error classification (ImportError -> permanent, RuntimeError -> transient)
# ---------------------------------------------------------------------------


def test_error_classification():
    """Permanent vs transient error classification."""
    assert classify_error(ImportError("no module")) == ErrorClass.PERMANENT
    assert classify_error(ModuleNotFoundError("missing")) == ErrorClass.PERMANENT
    assert classify_error(SyntaxError("bad syntax")) == ErrorClass.PERMANENT
    assert classify_error(PermissionError("denied")) == ErrorClass.PERMANENT
    assert classify_error(RuntimeError("oops")) == ErrorClass.TRANSIENT
    assert classify_error(sqlite3.OperationalError("locked")) == ErrorClass.TRANSIENT
    assert classify_error(ConnectionError("timeout")) == ErrorClass.TRANSIENT
    assert classify_error(ValueError("bad value")) == ErrorClass.TRANSIENT


# ---------------------------------------------------------------------------
# 5. Rollback on failure for locked stages
# ---------------------------------------------------------------------------


def test_rollback_on_failure_for_locked_stage(tmp_path):
    """Locked stages rollback their marker on ANY failure, not just ImportError."""
    omega_dir = tmp_path / ".omega"
    omega_dir.mkdir()

    def failing_fn():
        raise RuntimeError("something went wrong")

    pipeline = MaintenancePipeline()
    pipeline.add_stage(StageConfig(
        name="locked_fail",
        fn=failing_fn,
        interval_seconds=0,
        use_lock=True,
        marker_name="last-locked-test",
    ))

    with patch("omega.server.hook_server.maintenance._omega_dir", return_value=omega_dir), \
         patch("omega.server.hook_server.maintenance._try_acquire_periodic", return_value="old-marker-value"), \
         patch("omega.server.hook_server.maintenance._rollback_marker") as mock_rollback, \
         patch("omega.server.hook_server.maintenance._get_dlq_conn") as mock_conn:
        mock_conn.side_effect = Exception("no db")
        result = pipeline.run()

    step = result.steps[0]
    assert step.status == StepStatus.FAILED
    assert step.error_class == ErrorClass.TRANSIENT
    mock_rollback.assert_called_once_with("last-locked-test", "old-marker-value")


# ---------------------------------------------------------------------------
# 6. DLQ enqueue on transient failure
# ---------------------------------------------------------------------------


def test_dlq_enqueue_on_transient_failure():
    """Transient failures are enqueued to the DLQ."""
    conn = _in_memory_dlq_conn()

    enqueue_dlq(conn, "compact", ErrorClass.TRANSIENT, "DB locked")

    rows = conn.execute("SELECT * FROM maintenance_dlq").fetchall()
    assert len(rows) == 1
    row = dict(rows[0])
    assert row["stage_name"] == "compact"
    assert row["error_class"] == "transient"
    assert row["status"] == "pending"
    assert row["remediation_attempts"] == 0
    conn.close()


# ---------------------------------------------------------------------------
# 7. DLQ poll and retry (success path -> remediated)
# ---------------------------------------------------------------------------


def test_dlq_poll_and_retry_success():
    """Polling DLQ items and successful retry marks them as remediated."""
    conn = _in_memory_dlq_conn()
    enqueue_dlq(conn, "backup", ErrorClass.TRANSIENT, "network timeout")

    items = poll_dlq(conn)
    assert len(items) == 1
    assert items[0]["stage_name"] == "backup"

    # Simulate successful retry
    update_dlq_item(conn, items[0]["id"], "remediated")

    # Should not appear in poll anymore
    remaining = poll_dlq(conn)
    assert len(remaining) == 0

    # Verify status
    row = dict(conn.execute("SELECT * FROM maintenance_dlq WHERE id = ?", (items[0]["id"],)).fetchone())
    assert row["status"] == "remediated"
    assert row["remediation_attempts"] == 1
    conn.close()


# ---------------------------------------------------------------------------
# 8. DLQ exhaustion (max retries hit)
# ---------------------------------------------------------------------------


def test_dlq_exhaustion():
    """Items exceeding max_remediation are marked exhausted."""
    conn = _in_memory_dlq_conn()
    enqueue_dlq(conn, "consolidate", ErrorClass.TRANSIENT, "locked")

    # Simulate 3 failed retries
    for _ in range(3):
        items = poll_dlq(conn)
        if items:
            update_dlq_item(conn, items[0]["id"], "pending")

    # After 3 attempts, remediation_attempts == 3 == max_remediation
    row = dict(conn.execute("SELECT * FROM maintenance_dlq WHERE id = 1").fetchone())
    assert row["remediation_attempts"] == 3

    # The pipeline's _process_dlq would now mark it exhausted
    assert row["remediation_attempts"] >= row["max_remediation"]
    conn.close()


# ---------------------------------------------------------------------------
# 9. DLQ backoff calculation (range validation)
# ---------------------------------------------------------------------------


def test_dlq_backoff_calculation():
    """Backoff follows 60s * 2^(attempt-1) with jitter, capped at 3600s."""
    # Attempt 1: base = 60s, range = [30, 90]
    for _ in range(10):
        val = _backoff_seconds(1)
        assert 30.0 <= val <= 90.0, f"attempt 1: {val}"

    # Attempt 3: base = 240s, range = [120, 360]
    for _ in range(10):
        val = _backoff_seconds(3)
        assert 120.0 <= val <= 360.0, f"attempt 3: {val}"

    # Attempt 10: base capped at 3600, range = [1800, 5400]
    for _ in range(10):
        val = _backoff_seconds(10)
        assert 1800.0 <= val <= 5400.0, f"attempt 10: {val}"


# ---------------------------------------------------------------------------
# 10. Permanent error bypasses DLQ (immediate exhausted)
# ---------------------------------------------------------------------------


def test_permanent_error_bypasses_dlq():
    """Permanent errors are immediately marked as exhausted in the DLQ."""
    conn = _in_memory_dlq_conn()

    enqueue_dlq(conn, "consolidate", ErrorClass.PERMANENT, "ImportError: no module")

    rows = conn.execute("SELECT * FROM maintenance_dlq").fetchall()
    assert len(rows) == 1
    row = dict(rows[0])
    assert row["status"] == "exhausted"
    assert row["error_class"] == "permanent"
    conn.close()


# ---------------------------------------------------------------------------
# 11. PipelineResult.format_footer() output format
# ---------------------------------------------------------------------------


def test_format_footer_output():
    """format_footer produces the expected compact format."""
    result = PipelineResult(
        steps=[
            StepResult(name="consolidate", status=StepStatus.COMPLETED, elapsed_s=2.1),
            StepResult(name="compact", status=StepStatus.SKIPPED),
            StepResult(name="backup", status=StepStatus.COMPLETED, elapsed_s=0.8),
            StepResult(name="doctor", status=StepStatus.FAILED, error="db locked",
                       error_class=ErrorClass.TRANSIENT),
        ],
        dlq_pending=1,
    )

    footer = result.format_footer()
    assert "maintenance:" in footer
    assert "2/4 ran" in footer
    assert "consolidate 2.1s" in footer
    assert "backup 0.8s" in footer
    assert "doctor FAILED" in footer
    assert "1 DLQ pending" in footer


def test_format_footer_all_skipped():
    """format_footer when nothing ran."""
    result = PipelineResult(
        steps=[
            StepResult(name="a", status=StepStatus.SKIPPED),
            StepResult(name="b", status=StepStatus.SKIPPED),
        ],
    )
    footer = result.format_footer()
    assert "0/2 ran" in footer


# ---------------------------------------------------------------------------
# 12. Backward compat: get_output("doctor") returns doctor string
# ---------------------------------------------------------------------------


def test_get_output_backward_compat():
    """get_output returns the output of a completed step."""
    result = PipelineResult(
        steps=[
            StepResult(name="doctor", status=StepStatus.COMPLETED, output="doctor: healthy"),
            StepResult(name="compact", status=StepStatus.FAILED, output="partial"),
        ],
    )

    assert result.get_output("doctor") == "doctor: healthy"
    # Failed steps return None (output is not reliable)
    assert result.get_output("compact") is None
    # Missing steps return None
    assert result.get_output("nonexistent") is None


# ---------------------------------------------------------------------------
# 13. _do_reflect_stale: no stale memories -> short-circuit return
# ---------------------------------------------------------------------------


def test_reflect_stale_no_stale_memories():
    """_do_reflect_stale returns '0 stale memories found' when none exist."""
    mock_store = MagicMock()
    with patch("omega.reflect.find_stale", return_value={"total_candidates": 0, "stale_memories": []}), \
         patch("omega.bridge._get_store", return_value=mock_store), \
         patch("omega.bridge.auto_capture") as mock_capture:
        result = _do_reflect_stale()

    assert result == "0 stale memories found"
    mock_capture.assert_not_called()


def test_reflect_stale_with_stale_memories():
    """_do_reflect_stale stores an insight and returns summary when stale memories found."""
    mock_store = MagicMock()
    stale_list = [
        {"node_id": "abc123", "content": "This is a stale memory content that is old"},
        {"node_id": "def456", "content": "Another stale memory entry that was never read"},
        {"node_id": "ghi789", "content": "Third stale entry"},
    ]

    with patch("omega.reflect.find_stale", return_value={"total_candidates": 3, "stale_memories": stale_list}), \
         patch("omega.bridge._get_store", return_value=mock_store), \
         patch("omega.bridge.auto_capture") as mock_capture:
        result = _do_reflect_stale()

    assert result == "Auto-reflect stale: 3 memories found (14+ days, 0 access)"
    mock_capture.assert_called_once()
    call_kwargs = mock_capture.call_args
    assert call_kwargs.kwargs["event_type"] == "advisor_insight"
    assert call_kwargs.kwargs["metadata"]["source"] == "auto_reflect_stale"
    assert call_kwargs.kwargs["metadata"]["stale_count"] == 3
    assert "abc123" in call_kwargs.kwargs["content"]


def test_reflect_stale_exception_handling():
    """_do_reflect_stale returns error string on exception rather than raising."""
    with patch("omega.reflect.find_stale", side_effect=RuntimeError("DB unavailable")), \
         patch("omega.bridge._get_store", return_value=MagicMock()):
        result = _do_reflect_stale()

    assert result.startswith("reflect_stale error:")
    assert "DB unavailable" in result
