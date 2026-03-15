"""Auth0 OAuth 2.1 integration for the OMEGA Remote MCP Server.

Provides JWT validation against Auth0 and OAuth Protected Resource Metadata
(RFC 9470) for Claude Mobile Custom Connectors with Dynamic Client
Registration (DCR).

Auth0 handles the DCR flow; this module:
- Serves discovery metadata (/.well-known/oauth-protected-resource)
- Validates JWTs on protected endpoints (tools/list, tools/call)
- Leaves `initialize` unauthenticated so the MCP handshake can proceed

Configuration via environment variables:
    AUTH0_DOMAIN   -- Auth0 tenant domain (e.g. "myapp.auth0.com")
    AUTH0_AUDIENCE -- API identifier (e.g. "https://omega.example.com")
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Optional

import jwt
from jwt import PyJWKClient

from omega.exceptions import ValidationError as _ValidationError

logger = logging.getLogger("omega.server.auth")

# Paths that never require authentication
_PUBLIC_PATHS = frozenset({"/health", "/.well-known/oauth-protected-resource"})


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def get_auth_config() -> dict:
    """Read Auth0 configuration from environment variables.

    Returns dict with keys: domain, audience, issuer, jwks_uri, algorithms.

    Raises:
        ValueError: If AUTH0_DOMAIN or AUTH0_AUDIENCE is not set.
    """
    domain = os.environ.get("AUTH0_DOMAIN")
    audience = os.environ.get("AUTH0_AUDIENCE")

    if not domain:
        raise _ValidationError(
            "AUTH0_DOMAIN environment variable is required but not set"
        )
    if not audience:
        raise _ValidationError(
            "AUTH0_AUDIENCE environment variable is required but not set"
        )

    return {
        "domain": domain,
        "audience": audience,
        "issuer": f"https://{domain}/",
        "jwks_uri": f"https://{domain}/.well-known/jwks.json",
        "algorithms": ["RS256"],
    }


# ---------------------------------------------------------------------------
# OAuth Protected Resource Metadata (RFC 9470)
# ---------------------------------------------------------------------------


def build_well_known_response() -> dict:
    """Build RFC 9470 OAuth Protected Resource Metadata response.

    Intended for ``GET /.well-known/oauth-protected-resource``.

    Returns:
        Dict with ``resource`` and ``authorization_servers`` fields.
    """
    config = get_auth_config()
    return {
        "resource": config["audience"],
        "authorization_servers": [config["issuer"]],
    }


# ---------------------------------------------------------------------------
# Token extraction and validation
# ---------------------------------------------------------------------------


def extract_bearer_token(authorization: str) -> str:
    """Extract the token from a ``Bearer <token>`` Authorization header.

    Case-insensitive on the "Bearer" prefix.

    Args:
        authorization: The full Authorization header value.

    Returns:
        The bare token string.

    Raises:
        ValueError: If the header is missing, empty, or not Bearer-prefixed.
    """
    if not authorization:
        raise _ValidationError("Authorization header is missing or empty")

    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise _ValidationError(
            "Authorization header must use Bearer scheme "
            "(expected 'Bearer <token>')"
        )

    return parts[1]


@lru_cache(maxsize=1)
def _get_jwks_client() -> PyJWKClient:
    """Return a cached PyJWKClient for the configured Auth0 domain.

    The client caches signing keys internally for up to 3600 seconds.
    """
    config = get_auth_config()
    return PyJWKClient(config["jwks_uri"], cache_keys=True, lifespan=3600)


def validate_token(authorization: Optional[str]) -> dict:
    """Validate a JWT from the Authorization header.

    Extracts the bearer token, fetches the signing key from the Auth0 JWKS
    endpoint (cached), then decodes and validates the JWT against the
    configured audience, issuer, and algorithms.

    Args:
        authorization: The full Authorization header value, or None.

    Returns:
        The decoded JWT payload as a dict.

    Raises:
        ValueError: On missing/malformed header or any JWT validation failure.
    """
    if authorization is None:
        raise _ValidationError("Authorization header is required")

    token = extract_bearer_token(authorization)
    config = get_auth_config()

    try:
        jwks_client = _get_jwks_client()
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=config["algorithms"],
            audience=config["audience"],
            issuer=config["issuer"],
        )
    except jwt.PyJWTError as exc:
        logger.warning("JWT validation failed: %s", exc)
        raise _ValidationError("JWT validation failed") from exc
    except Exception as exc:
        logger.warning("Token validation error: %s", exc)
        raise _ValidationError("Token validation error") from exc

    return payload


# ---------------------------------------------------------------------------
# ASGI Auth Middleware
# ---------------------------------------------------------------------------


def is_auth_enabled() -> bool:
    """Return True if Auth0 credentials are configured."""
    return bool(os.environ.get("AUTH0_DOMAIN") and os.environ.get("AUTH0_AUDIENCE"))


class JWTAuthMiddleware:
    """ASGI middleware that validates JWT Bearer tokens on protected routes.

    Behaviour:
    - If AUTH0_DOMAIN/AUTH0_AUDIENCE are not set, all requests pass through
      (dev mode -- no auth overhead).
    - Paths in _PUBLIC_PATHS are always allowed without a token.
    - All other paths require a valid Bearer token in the Authorization header.
    - Returns 401 with WWW-Authenticate header on failure.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")

        # Public paths -- always allowed
        if path in _PUBLIC_PATHS:
            return await self.app(scope, receive, send)

        # Dev mode -- auth disabled when credentials not configured
        if not is_auth_enabled():
            return await self.app(scope, receive, send)

        # Extract Authorization header from ASGI scope
        headers = dict(scope.get("headers", []))
        auth_header = headers.get(b"authorization", b"").decode("utf-8") or None

        try:
            validate_token(auth_header)
        except _ValidationError as exc:
            logger.warning("Auth rejected for %s: %s", path, exc)
            # Return 401 with WWW-Authenticate
            body = b'{"error": "Unauthorized"}'
            await send({
                "type": "http.response.start",
                "status": 401,
                "headers": [
                    [b"content-type", b"application/json"],
                    [b"www-authenticate", b'Bearer realm="omega"'],
                    [b"content-length", str(len(body)).encode()],
                ],
            })
            await send({
                "type": "http.response.body",
                "body": body,
            })
            return

        return await self.app(scope, receive, send)
