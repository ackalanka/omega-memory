"""Shared input validation helpers for MCP handlers.

Prevents path traversal and injection via session_id, entity_id,
and other user-supplied identifiers.
"""

import logging
import re

logger = logging.getLogger("omega.server.validation")

_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9._-]+$")


def validate_session_id(session_id: str | None) -> str | None:
    """Validate session_id to prevent path traversal.

    Returns cleaned session_id or None if invalid.
    """
    if not session_id:
        return session_id
    if ".." in session_id or "/" in session_id or "\\" in session_id:
        logger.warning("Rejected session_id with path traversal: %s", session_id[:50])
        return None
    if not _SAFE_ID_RE.match(session_id):
        logger.warning("Rejected session_id with invalid chars: %s", session_id[:50])
        return None
    return session_id


def validate_entity_id(entity_id: str | None) -> str | None:
    """Validate entity_id format (alphanumeric, hyphens, dots, underscores).

    Returns cleaned entity_id or None if invalid.
    """
    if not entity_id:
        return entity_id
    if not _SAFE_ID_RE.match(entity_id):
        logger.warning("Rejected entity_id with invalid chars: %s", entity_id[:50])
        return None
    return entity_id
