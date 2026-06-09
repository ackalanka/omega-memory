#!/usr/bin/env python3
"""Isolated promotion smoke for Iteration 1 retrieval MCP tools.

This script is intentionally local-only. It creates no MCP client config,
runs no ``omega setup``, and requires ``OMEGA_HOME`` to point away from the
operator's live ``~/.omega`` directory.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile


LIVE_OMEGA_HOME = Path.home() / ".omega"


def _fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def _assert_isolated_home() -> Path:
    omega_home_raw = os.environ.get("OMEGA_HOME")
    if not omega_home_raw:
        _fail("OMEGA_HOME must be set to an isolated temporary directory")
    omega_home = Path(omega_home_raw).expanduser().resolve()
    live_home = LIVE_OMEGA_HOME.resolve()
    if omega_home == live_home or live_home in omega_home.parents:
        _fail(f"OMEGA_HOME points at the live memory home: {omega_home}")
    omega_home.mkdir(parents=True, exist_ok=True)
    return omega_home


def _assert_repo_import(repo_root: Path) -> None:
    import omega

    omega_path = Path(omega.__file__).resolve()
    if repo_root not in omega_path.parents:
        _fail(f"imported omega from {omega_path}, expected checkout under {repo_root}")


def _extract_mem_id(store_result: str) -> str:
    for part in store_result.replace("`", "").split():
        if part.startswith("mem-"):
            return part
    _fail(f"could not extract memory id from store result: {store_result}")
    raise AssertionError("unreachable")


def _payload(result: dict) -> str:
    if result.get("isError"):
        _fail(result["content"][0]["text"])
    return result["content"][0]["text"]


async def _run_smoke(repo_root: Path, project: str) -> dict:
    _assert_repo_import(repo_root)

    from omega.bridge import reset_memory, store
    from omega.server.handlers import (
        HANDLERS,
        handle_omega_context,
        handle_omega_memory,
        handle_omega_query,
        handle_omega_recall,
    )
    from omega.server.tool_schemas import TOOL_SCHEMAS

    expected_tools = {"omega_query", "omega_recall", "omega_context", "omega_memory"}
    schema_names = {schema["name"] for schema in TOOL_SCHEMAS}
    missing = sorted(expected_tools - schema_names)
    if missing:
        _fail(f"missing tool schemas: {missing}")
    missing_handlers = sorted(name for name in expected_tools if name not in HANDLERS)
    if missing_handlers:
        _fail(f"missing handlers: {missing_handlers}")

    reset_memory()
    long_content = "promotion smoke full memory content " * 24
    memory_id = _extract_mem_id(
        store(
            long_content,
            event_type="checkpoint",
            project=project,
            metadata={"tags": ["promotion-smoke"]},
        )
    )
    store(
        "promotion smoke decision about project context",
        event_type="decision",
        project=project,
        metadata={"tags": ["promotion-smoke"]},
    )
    store(
        "promotion smoke debug lesson about sqlite lock handling",
        event_type="lesson_learned",
        project=project,
        metadata={"tags": ["promotion-smoke"]},
    )

    get_payload = json.loads(
        _payload(
            await handle_omega_memory({
                "action": "get",
                "memory_id": memory_id,
                "format": "json",
                "track_access": False,
            })
        )
    )
    if get_payload["record"]["content"] != long_content:
        _fail("omega_memory(get) did not return full content")

    query_payload = json.loads(
        _payload(
            await handle_omega_query({
                "query": "promotion smoke full memory",
                "format": "json",
                "content_mode": "full",
                "limit": 2,
                "project": project,
            })
        )
    )
    if not query_payload["results"] or not any(r["id"] == memory_id for r in query_payload["results"]):
        _fail("structured omega_query did not return the seeded memory")

    browse_payload = json.loads(
        _payload(
            await handle_omega_query({
                "mode": "browse",
                "browse_by": "type",
                "event_type": "checkpoint",
                "format": "json",
                "limit": 1,
                "offset": 0,
                "content_mode": "preview",
                "preview_chars": 40,
            })
        )
    )
    if browse_payload["count"] != 1 or browse_payload["items"][0]["id"] != memory_id:
        _fail("paginated browse did not return the seeded checkpoint")

    recall_payload = json.loads(
        _payload(
            await handle_omega_recall({
                "query": "promotion smoke sqlite lock",
                "profile": "debug",
                "project": project,
                "format": "json",
                "limit": 3,
                "budget_chars": 500,
            })
        )
    )
    if recall_payload["mode"] != "recall" or not recall_payload["results"]:
        _fail("omega_recall returned no results")

    context_payload = json.loads(
        _payload(
            await handle_omega_context({
                "project": project,
                "mode": "debug",
                "query": "sqlite lock",
                "format": "json",
                "limit_per_type": 2,
                "budget_chars": 500,
            })
        )
    )
    if context_payload["project"] != project or not context_payload["sections"]:
        _fail("omega_context returned an empty or wrong-project pack")

    return {
        "memory_id": memory_id,
        "tool_count": len(TOOL_SCHEMAS),
        "query_results": len(query_payload["results"]),
        "browse_count": browse_payload["count"],
        "recall_results": len(recall_payload["results"]),
        "context_items": context_payload["item_count"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project",
        default="/tmp/omega-retrieval-promotion-smoke-project",
        help="Project path to write into isolated smoke memories.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    omega_home = _assert_isolated_home()

    with tempfile.TemporaryDirectory(prefix="omega-retrieval-smoke-") as tmpdir:
        os.environ.setdefault("TMPDIR", tmpdir)
        summary = asyncio.run(_run_smoke(repo_root, args.project))

    db_path = omega_home / "omega.db"
    if not db_path.exists():
        _fail(f"expected isolated smoke database at {db_path}")

    print(json.dumps({
        "status": "ok",
        "omega_home": str(omega_home),
        "db_path": str(db_path),
        **summary,
    }, indent=2))


if __name__ == "__main__":
    main()
