#!/usr/bin/env python3
"""One-time import of historical Claude Code session data into Supabase session_usage.

Data sources:
  ~/.claude/session-summaries.jsonl  — per-session records (cost, tokens, duration)
  ~/.claude/cost-history.json        — daily aggregates with model-level cost breakdown

Usage:
  python3.11 scripts/import-session-usage.py [--dry-run]
"""
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
DRY_RUN = "--dry-run" in sys.argv


def load_env():
    """Try loading from .env.local if env vars are missing."""
    global SUPABASE_URL, SUPABASE_KEY
    if SUPABASE_URL and SUPABASE_KEY:
        return
    env_file = Path(__file__).parent.parent / "website" / ".env.local"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key == "SUPABASE_URL" and not SUPABASE_URL:
            SUPABASE_URL = val
        elif key == "SUPABASE_SERVICE_ROLE_KEY" and not SUPABASE_KEY:
            SUPABASE_KEY = val


def supabase_upsert(rows: list[dict]) -> dict:
    """Upsert rows into session_usage via Supabase REST API."""
    if not rows:
        return {"status": "empty"}

    url = f"{SUPABASE_URL}/rest/v1/session_usage?on_conflict=session_id"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates",
    }

    body = json.dumps(rows).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return {"status": resp.status, "count": len(rows)}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        return {"status": e.code, "error": error_body}


def load_session_summaries() -> list[dict]:
    """Parse ~/.claude/session-summaries.jsonl into session_usage rows."""
    path = Path.home() / ".claude" / "session-summaries.jsonl"
    if not path.exists():
        print(f"  Not found: {path}")
        return []

    rows = []
    for i, line in enumerate(path.read_text().splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            s = json.loads(line)
        except json.JSONDecodeError as e:
            print(f"  Skipping line {i+1}: {e}")
            continue

        session_id = s.get("sessionId") or s.get("id", f"unknown-{i}")
        start_time = s.get("startTime")
        end_time = s.get("endTime")
        duration = s.get("duration", 0)

        row = {
            "session_id": session_id,
            "project_name": s.get("projectName"),
            "project_path": s.get("projectPath"),
            "total_cost_usd": s.get("totalCost", 0),
            "input_tokens": s.get("inputTokens", 0),
            "output_tokens": s.get("outputTokens", 0),
            "duration_seconds": round(duration, 2) if duration else None,
            "files_modified": json.dumps(s.get("filesModified", [])),
            "tasks_completed": json.dumps(s.get("tasksCompleted", [])),
            "git_commits": json.dumps(s.get("gitCommits", [])),
            "final_state": s.get("finalState"),
            "session_start": start_time,
            "session_end": end_time,
            "cost_by_model": "{}",
        }
        rows.append(row)

    return rows


def enrich_with_cost_history(rows: list[dict]):
    """Add model-level cost breakdown from cost-history.json where dates overlap."""
    path = Path.home() / ".claude" / "cost-history.json"
    if not path.exists():
        print(f"  Not found: {path}")
        return

    data = json.loads(path.read_text())
    entries = data.get("entries", [])
    if not entries:
        return

    # Build date-to-costByModel lookup
    date_costs = {}
    for entry in entries:
        date_str = entry.get("date", "")[:10]  # YYYY-MM-DD
        if date_str and entry.get("costByModel"):
            date_costs[date_str] = entry["costByModel"]

    # Enrich rows whose session_start falls on a date we have cost-by-model data for
    enriched = 0
    for row in rows:
        start = row.get("session_start", "")
        if not start:
            continue
        date_key = start[:10]
        if date_key in date_costs:
            row["cost_by_model"] = json.dumps(date_costs[date_key])
            enriched += 1

    if enriched:
        print(f"  Enriched {enriched} rows with model cost breakdown")


def main():
    load_env()

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Error: SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set.")
        print("  Set them as env vars or place them in website/.env.local")
        sys.exit(1)

    print("Loading session summaries...")
    rows = load_session_summaries()
    print(f"  Found {len(rows)} sessions")

    if rows:
        enrich_with_cost_history(rows)

    # Dedupe by session_id (keep last occurrence — most recent data)
    seen = {}
    for row in rows:
        seen[row["session_id"]] = row
    rows = list(seen.values())
    print(f"  After dedup: {len(rows)} unique sessions")

    if DRY_RUN:
        print(f"\n[DRY RUN] Would upsert {len(rows)} rows. Sample:")
        if rows:
            sample = rows[0]
            for k, v in sample.items():
                print(f"  {k}: {v}")
        return

    # Upsert in batches of 50
    batch_size = 50
    total_ok = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        result = supabase_upsert(batch)
        if result.get("status") in (200, 201, "empty"):
            total_ok += len(batch)
            print(f"  Upserted batch {i // batch_size + 1}: {len(batch)} rows")
        else:
            print(f"  Error on batch {i // batch_size + 1}: {result}")
            sys.exit(1)

    print(f"\nDone! Imported {total_ok} sessions into session_usage.")


if __name__ == "__main__":
    main()
