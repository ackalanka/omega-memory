"""
OMEGA Telemetry -- anonymous, local-first usage tracking.

All data is stored locally in ~/.omega/telemetry.json. Network reporting
is OPT-IN only, controlled by the OMEGA_TELEMETRY=1 environment variable.

No PII, no memory content, no file paths are ever collected. Only aggregate
counts and system metadata.

All telemetry operations are failure-safe (wrapped in try/except) and
network calls are non-blocking (fire-and-forget in daemon threads).

Integration points (do not modify other files, wire these up separately):
  - handle_omega_welcome  -> track_event("session_start")
  - handle_omega_store    -> track_tool_call("omega_store")
  - handle_omega_query    -> track_tool_call("omega_query")
  - _maybe_nag()          -> track_nag("periodic")
  - cmd_setup             -> track_event("setup_complete")
  - cmd_upgrade           -> track_event("upgrade_opened")
"""

import json
import os
import platform
import sys
import threading
import time
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

OMEGA_DIR = Path.home() / ".omega"
TELEMETRY_FILE = OMEGA_DIR / "telemetry.json"
TELEMETRY_ENDPOINT = "https://admin.omegamax.co/api/telemetry"

_lock = threading.Lock()


def _default_data() -> dict:
    """Return a blank telemetry structure with sensible defaults."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "install_id": str(uuid.uuid4()),
        "install_date": now,
        "os": platform.system().lower(),
        "python_version": platform.python_version(),
        "omega_version": _get_omega_version(),
        "client": os.environ.get("OMEGA_CLIENT", "unknown"),
        "pro_licensed": False,
        "sessions": {
            "total": 0,
            "last_7d": 0,
        },
        "memories": {
            "total": 0,
            "stored_this_session": 0,
        },
        "tool_calls": {
            "total": 0,
            "by_tool": {},
        },
        "nag_events": {
            "welcome_shown": 0,
            "periodic_shown": 0,
            "milestone_shown": 0,
            "tool_gate_shown": 0,
            "upgrade_clicked": 0,
        },
        "last_active": now,
        "last_reported": None,
    }


def _get_omega_version() -> str:
    """Safely retrieve omega.__version__, returning 'unknown' on failure."""
    try:
        from omega import __version__

        return __version__
    except Exception:
        return "unknown"


def _load() -> dict:
    """Load telemetry data from disk, or create defaults."""
    try:
        if TELEMETRY_FILE.exists():
            text = TELEMETRY_FILE.read_text(encoding="utf-8")
            data = json.loads(text)
            return _ensure_install_id(data)
    except Exception:
        pass
    return _default_data()


def _save(data: dict) -> None:
    """Save telemetry data to disk."""
    try:
        OMEGA_DIR.mkdir(parents=True, exist_ok=True)
        tmp = TELEMETRY_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(TELEMETRY_FILE)
    except Exception:
        pass


def _ensure_install_id(data: dict) -> dict:
    """Ensure install_id exists, create if missing."""
    if not data.get("install_id"):
        data["install_id"] = str(uuid.uuid4())
    if not data.get("install_date"):
        data["install_date"] = datetime.now(timezone.utc).isoformat()
    return data


def track_event(event: str, metadata: dict | None = None) -> None:
    """Track a telemetry event. Non-blocking, never raises.

    Events: session_start, tool_call, nag_shown, nag_clicked,
            milestone_hit, setup_complete, upgrade_opened
    """
    try:
        with _lock:
            data = _load()
            now = datetime.now(timezone.utc).isoformat()
            data["last_active"] = now

            # Update omega_version and client on each event in case they changed
            data["omega_version"] = _get_omega_version()
            data["client"] = os.environ.get("OMEGA_CLIENT", data.get("client", "unknown"))

            if event == "session_start":
                data.setdefault("sessions", {"total": 0, "last_7d": 0})
                data["sessions"]["total"] += 1
                data["sessions"]["last_7d"] += 1
                # Reset per-session counters
                data.setdefault("memories", {"total": 0, "stored_this_session": 0})
                data["memories"]["stored_this_session"] = 0

            elif event == "nag_clicked":
                data.setdefault("nag_events", {})
                data["nag_events"]["upgrade_clicked"] = (
                    data["nag_events"].get("upgrade_clicked", 0) + 1
                )

            _save(data)

        maybe_report()
    except Exception:
        pass


def track_tool_call(tool_name: str) -> None:
    """Increment tool call counter."""
    try:
        with _lock:
            data = _load()
            data["last_active"] = datetime.now(timezone.utc).isoformat()

            data.setdefault("tool_calls", {"total": 0, "by_tool": {}})
            data["tool_calls"]["total"] += 1
            data["tool_calls"]["by_tool"][tool_name] = (
                data["tool_calls"]["by_tool"].get(tool_name, 0) + 1
            )

            # Track memory stores
            if tool_name == "omega_store":
                data.setdefault("memories", {"total": 0, "stored_this_session": 0})
                data["memories"]["total"] += 1
                data["memories"]["stored_this_session"] += 1

            _save(data)

        maybe_report()
    except Exception:
        pass


def track_nag(nag_type: str) -> None:
    """Track when an upgrade nag was shown.

    Types: welcome, periodic, milestone, tool_gate
    """
    try:
        with _lock:
            data = _load()
            data["last_active"] = datetime.now(timezone.utc).isoformat()

            data.setdefault("nag_events", {})
            key = f"{nag_type}_shown"
            if key in data["nag_events"]:
                data["nag_events"][key] += 1

            _save(data)

        maybe_report()
    except Exception:
        pass


def get_summary() -> dict:
    """Return telemetry summary for admin dashboard reporting."""
    try:
        with _lock:
            data = _load()
        return {
            "install_id": data.get("install_id"),
            "install_date": data.get("install_date"),
            "os": data.get("os"),
            "python_version": data.get("python_version"),
            "omega_version": data.get("omega_version"),
            "client": data.get("client"),
            "pro_licensed": data.get("pro_licensed", False),
            "sessions": data.get("sessions", {}),
            "memories": data.get("memories", {}),
            "tool_calls": data.get("tool_calls", {}),
            "nag_events": data.get("nag_events", {}),
            "last_active": data.get("last_active"),
            "last_reported": data.get("last_reported"),
        }
    except Exception:
        return {}


def maybe_report() -> None:
    """If OMEGA_TELEMETRY=1 and last report was >24h ago, send summary to endpoint.

    Runs in background thread. Fire-and-forget.
    """
    try:
        if os.environ.get("OMEGA_TELEMETRY") != "1":
            return

        data = _load()
        last_reported = data.get("last_reported")

        if last_reported:
            try:
                last_ts = datetime.fromisoformat(last_reported)
                now = datetime.now(timezone.utc)
                elapsed = (now - last_ts).total_seconds()
                if elapsed < 86400:  # 24 hours
                    return
            except Exception:
                pass  # If parsing fails, allow reporting

        t = threading.Thread(target=_do_report, args=(data,), daemon=True)
        t.start()
    except Exception:
        pass


def _do_report(data: dict) -> None:
    """Actually send the report. Called in background thread."""
    try:
        payload = json.dumps(
            {
                "install_id": data.get("install_id"),
                "os": data.get("os"),
                "python_version": data.get("python_version"),
                "omega_version": data.get("omega_version"),
                "client": data.get("client"),
                "pro_licensed": data.get("pro_licensed", False),
                "sessions": data.get("sessions", {}),
                "memories": data.get("memories", {}),
                "tool_calls": data.get("tool_calls", {}),
                "nag_events": data.get("nag_events", {}),
                "last_active": data.get("last_active"),
            }
        ).encode("utf-8")

        req = urllib.request.Request(
            TELEMETRY_ENDPOINT,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)

        # Update last_reported on success
        with _lock:
            current = _load()
            current["last_reported"] = datetime.now(timezone.utc).isoformat()
            _save(current)
    except Exception:
        pass
