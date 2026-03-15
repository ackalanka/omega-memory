"""OMEGA Remote MCP Server -- FastMCP HTTP server exposing 5 curated tools.

Exposes a mobile-friendly subset of OMEGA tools via FastMCP's HTTP transport.
Each tool wraps the existing async handler from handlers.py, converting between
FastMCP's typed parameters and the handler's dict-based interface.

Usage (dev):
    python -m omega.server.remote_server

Production (ASGI):
    uvicorn omega.server.remote_server:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from fastmcp import FastMCP

from omega.exceptions import ValidationError as _ValidationError
from omega.server.handlers import (
    handle_omega_memory,
    handle_omega_profile,
    handle_omega_query,
    handle_omega_remind_composite,
    handle_omega_store,
)

logger = logging.getLogger("omega.server.remote")

# ---------------------------------------------------------------------------
# FastMCP app
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "omega-remote",
    instructions=(
        "OMEGA persistent memory system. "
        "Store, query, and manage memories across sessions."
    ),
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_text(result: dict) -> str:
    """Pull the text string from a handler response dict.

    Handler responses have the shape:
        {"content": [{"type": "text", "text": "..."}]}
    or on error:
        {"content": [{"type": "text", "text": "Error: ..."}], "isError": True}
    """
    content = result.get("content", [])
    if content and isinstance(content, list):
        return content[0].get("text", "")
    return str(result)


def _check_error(result: dict) -> None:
    """Raise _ValidationError if the handler result indicates an error."""
    if result.get("isError"):
        text = _extract_text(result)
        raise _ValidationError(text)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool
async def omega_store(
    content: str,
    event_type: str = "memory",
    metadata: Optional[dict] = None,
    project: Optional[str] = None,
    priority: Optional[int] = None,
    entity_id: Optional[str] = None,
    agent_type: Optional[str] = None,
    session_id: Optional[str] = None,
) -> str:
    """Store a memory with optional type and metadata.

    Use event_type to categorize: memory, decision, lesson_learned,
    user_preference, etc. Priority ranges from 1 (low) to 5 (critical).
    """
    args: dict = {"content": content, "event_type": event_type}
    if metadata is not None:
        args["metadata"] = metadata
    if project is not None:
        args["project"] = project
    if priority is not None:
        args["priority"] = priority
    if entity_id is not None:
        args["entity_id"] = entity_id
    if agent_type is not None:
        args["agent_type"] = agent_type
    if session_id is not None:
        args["session_id"] = session_id

    result = await handle_omega_store(args)
    _check_error(result)
    return _extract_text(result)


@mcp.tool
async def omega_query(
    query: str = "",
    mode: str = "semantic",
    limit: int = 10,
    event_type: Optional[str] = None,
    project: Optional[str] = None,
    entity_id: Optional[str] = None,
    days: Optional[int] = None,
    session_id: Optional[str] = None,
) -> str:
    """Search memories by semantic similarity, phrase match, timeline, or browse.

    Modes: semantic (default), phrase, timeline, browse, trace.
    For timeline mode, use 'days' to control the lookback window.
    """
    args: dict = {"query": query, "mode": mode, "limit": limit}
    if event_type is not None:
        args["event_type"] = event_type
    if project is not None:
        args["project"] = project
    if entity_id is not None:
        args["entity_id"] = entity_id
    if days is not None:
        args["days"] = days
    if session_id is not None:
        args["session_id"] = session_id

    result = await handle_omega_query(args)
    _check_error(result)
    return _extract_text(result)


@mcp.tool
async def omega_memory(
    action: str,
    memory_id: Optional[str] = None,
    new_content: Optional[str] = None,
    rating: Optional[str] = None,
    reason: Optional[str] = None,
    target_id: Optional[str] = None,
    edge_type: str = "related",
    limit: int = 5,
) -> str:
    """Manage individual memories: edit, delete, feedback, similar, traverse, link, flagged, check_contradictions, supersede.

    Requires memory_id for most actions. Use 'flagged' to list low-rated
    or contradicted memories without a memory_id.
    """
    args: dict = {"action": action, "limit": limit, "edge_type": edge_type}
    if memory_id is not None:
        args["memory_id"] = memory_id
    if new_content is not None:
        args["new_content"] = new_content
    if rating is not None:
        args["rating"] = rating
    if reason is not None:
        args["reason"] = reason
    if target_id is not None:
        args["target_id"] = target_id

    result = await handle_omega_memory(args)
    _check_error(result)
    return _extract_text(result)


@mcp.tool
async def omega_remind(
    action: str = "set",
    text: Optional[str] = None,
    duration: Optional[str] = None,
    context: Optional[str] = None,
    reminder_id: Optional[str] = None,
    status: Optional[str] = None,
    entity_id: Optional[str] = None,
) -> str:
    """Manage reminders: set, list, or dismiss.

    For 'set': provide text and duration (e.g. '1h', '30m', '2d').
    For 'dismiss': provide reminder_id.
    For 'list': optionally filter by status.
    """
    args: dict = {"action": action}
    if text is not None:
        args["text"] = text
    if duration is not None:
        args["duration"] = duration
    if context is not None:
        args["context"] = context
    if reminder_id is not None:
        args["reminder_id"] = reminder_id
    if status is not None:
        args["status"] = status
    if entity_id is not None:
        args["entity_id"] = entity_id

    result = await handle_omega_remind_composite(args)
    _check_error(result)
    return _extract_text(result)


@mcp.tool
async def omega_profile(
    action: str = "read",
    update: Optional[dict] = None,
) -> str:
    """Read or update the user profile, or list learned preferences.

    Actions: read (default), update, list_preferences.
    For 'update': provide a dict of fields to merge into the profile.
    """
    args: dict = {"action": action}
    if update is not None:
        args["update"] = update

    result = await handle_omega_profile(args)
    _check_error(result)
    return _extract_text(result)


# ---------------------------------------------------------------------------
# ASGI app factory
# ---------------------------------------------------------------------------


def create_app():
    """Create the full ASGI app with MCP + auth + health endpoints.

    Mounts:
        /mcp -- FastMCP Streamable HTTP endpoint
        /.well-known/oauth-protected-resource -- RFC 9470 discovery
        /health -- Health check
    """
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def well_known(request):
        """RFC 9470 OAuth Protected Resource Metadata."""
        try:
            from omega.server.auth import build_well_known_response

            return JSONResponse(build_well_known_response())
        except (ValueError, _ValidationError) as e:
            logger.error("well-known metadata error: %s", e)
            return JSONResponse(
                {"error": "Internal server error"}, status_code=500
            )

    async def health(request):
        """Health check endpoint."""
        return JSONResponse({"status": "ok"})

    mcp_app = mcp.http_app(path="/mcp")

    routes = [
        Route(
            "/.well-known/oauth-protected-resource",
            well_known,
            methods=["GET"],
        ),
        Route("/health", health, methods=["GET"]),
    ]

    from omega.server.auth import JWTAuthMiddleware

    outer_app = Starlette(routes=routes, lifespan=mcp_app.lifespan)
    outer_app.mount("/", mcp_app)
    outer_app.add_middleware(JWTAuthMiddleware)
    return outer_app


app = create_app()

# ---------------------------------------------------------------------------
# Dev entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    is_dev = os.environ.get("OMEGA_ENV", "development") == "development"
    uvicorn.run(
        "omega.server.remote_server:app",
        host="0.0.0.0",
        port=port,
        reload=is_dev,
    )
