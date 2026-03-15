"""Tests for Auth0 OAuth 2.1 integration (omega.server.auth).

Covers configuration loading, RFC 9470 well-known response, bearer token
extraction, and validation entry points. JWT crypto validation is not tested
here (requires a real JWKS endpoint); instead we verify the surface area:
correct config parsing, error paths, and token extraction logic.
"""

import pytest

from omega.exceptions import ValidationError
from omega.server.auth import (
    build_well_known_response,
    extract_bearer_token,
    get_auth_config,
    is_auth_enabled,
    validate_token,
    _get_jwks_client,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_auth_caches():
    """Clear lru_cache singletons between tests to avoid cross-contamination."""
    _get_jwks_client.cache_clear()
    yield
    _get_jwks_client.cache_clear()


# ---------------------------------------------------------------------------
# get_auth_config
# ---------------------------------------------------------------------------


def test_auth_config_from_env(monkeypatch):
    """Config reads AUTH0_DOMAIN and AUTH0_AUDIENCE correctly."""
    monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
    monkeypatch.setenv("AUTH0_AUDIENCE", "https://api.example.com")

    config = get_auth_config()

    assert config["domain"] == "test.auth0.com"
    assert config["audience"] == "https://api.example.com"
    assert config["issuer"] == "https://test.auth0.com/"
    assert config["jwks_uri"] == "https://test.auth0.com/.well-known/jwks.json"
    assert config["algorithms"] == ["RS256"]


def test_auth_config_missing_domain_raises(monkeypatch):
    """ValueError when AUTH0_DOMAIN not set."""
    monkeypatch.delenv("AUTH0_DOMAIN", raising=False)
    monkeypatch.setenv("AUTH0_AUDIENCE", "https://api.example.com")

    with pytest.raises(ValidationError, match="AUTH0_DOMAIN"):
        get_auth_config()


def test_auth_config_missing_audience_raises(monkeypatch):
    """ValueError when AUTH0_AUDIENCE not set."""
    monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
    monkeypatch.delenv("AUTH0_AUDIENCE", raising=False)

    with pytest.raises(ValidationError, match="AUTH0_AUDIENCE"):
        get_auth_config()


# ---------------------------------------------------------------------------
# build_well_known_response
# ---------------------------------------------------------------------------


def test_well_known_response_format(monkeypatch):
    """Correct RFC 9470 structure."""
    monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
    monkeypatch.setenv("AUTH0_AUDIENCE", "https://api.example.com")

    response = build_well_known_response()

    assert response["resource"] == "https://api.example.com"
    assert response["authorization_servers"] == ["https://test.auth0.com/"]
    # RFC 9470 requires exactly these two fields
    assert set(response.keys()) == {"resource", "authorization_servers"}


# ---------------------------------------------------------------------------
# extract_bearer_token
# ---------------------------------------------------------------------------


def test_bearer_prefix_extracted():
    """'Bearer abc123' -> 'abc123'."""
    assert extract_bearer_token("Bearer abc123") == "abc123"


def test_bearer_case_insensitive():
    """'bearer abc123' -> 'abc123'."""
    assert extract_bearer_token("bearer abc123") == "abc123"


def test_bearer_mixed_case():
    """'BEARER abc123' -> 'abc123'."""
    assert extract_bearer_token("BEARER abc123") == "abc123"


def test_extract_empty_header_raises():
    """Empty string raises ValueError."""
    with pytest.raises(ValidationError, match="missing or empty"):
        extract_bearer_token("")


def test_extract_non_bearer_scheme_raises():
    """Non-Bearer scheme raises ValueError."""
    with pytest.raises(ValidationError, match="Bearer scheme"):
        extract_bearer_token("Basic dXNlcjpwYXNz")


def test_extract_no_token_after_bearer_raises():
    """'Bearer' with no token raises ValueError."""
    with pytest.raises(ValidationError, match="Bearer scheme"):
        extract_bearer_token("Bearer")


# ---------------------------------------------------------------------------
# validate_token -- error paths (no real JWKS needed)
# ---------------------------------------------------------------------------


def test_missing_token_raises():
    """validate_token(None) raises ValueError."""
    with pytest.raises(ValidationError, match="required"):
        validate_token(None)


def test_malformed_token_raises():
    """validate_token('NotBearer xyz') raises ValueError."""
    with pytest.raises(ValidationError, match="Bearer scheme"):
        validate_token("NotBearer xyz")


# ---------------------------------------------------------------------------
# Integration: well-known and health endpoints via create_app()
# ---------------------------------------------------------------------------


@pytest.fixture
def app_client():
    """Starlette TestClient wrapping the full ASGI app."""
    from starlette.testclient import TestClient

    from omega.server.remote_server import create_app

    return TestClient(create_app())


class TestWellKnownEndpoint:
    """Tests for GET /.well-known/oauth-protected-resource."""

    def test_well_known_returns_rfc9470_json(self, app_client, monkeypatch):
        monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
        monkeypatch.setenv("AUTH0_AUDIENCE", "https://api.example.com")

        resp = app_client.get("/.well-known/oauth-protected-resource")

        assert resp.status_code == 200
        body = resp.json()
        assert body["resource"] == "https://api.example.com"
        assert body["authorization_servers"] == ["https://test.auth0.com/"]

    def test_well_known_returns_500_when_unconfigured(
        self, app_client, monkeypatch
    ):
        monkeypatch.delenv("AUTH0_DOMAIN", raising=False)
        monkeypatch.delenv("AUTH0_AUDIENCE", raising=False)

        resp = app_client.get("/.well-known/oauth-protected-resource")

        assert resp.status_code == 500
        assert "error" in resp.json()


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_returns_ok(self, app_client):
        resp = app_client.get("/health")

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


# ---------------------------------------------------------------------------
# is_auth_enabled
# ---------------------------------------------------------------------------


class TestIsAuthEnabled:
    """Tests for the is_auth_enabled() helper."""

    def test_enabled_when_both_vars_set(self, monkeypatch):
        monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
        monkeypatch.setenv("AUTH0_AUDIENCE", "https://api.example.com")
        assert is_auth_enabled() is True

    def test_disabled_when_domain_missing(self, monkeypatch):
        monkeypatch.delenv("AUTH0_DOMAIN", raising=False)
        monkeypatch.setenv("AUTH0_AUDIENCE", "https://api.example.com")
        assert is_auth_enabled() is False

    def test_disabled_when_audience_missing(self, monkeypatch):
        monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
        monkeypatch.delenv("AUTH0_AUDIENCE", raising=False)
        assert is_auth_enabled() is False

    def test_disabled_when_both_missing(self, monkeypatch):
        monkeypatch.delenv("AUTH0_DOMAIN", raising=False)
        monkeypatch.delenv("AUTH0_AUDIENCE", raising=False)
        assert is_auth_enabled() is False


# ---------------------------------------------------------------------------
# JWTAuthMiddleware -- integration tests via create_app()
# ---------------------------------------------------------------------------


class TestJWTAuthMiddleware:
    """Tests for the JWT auth middleware wired into the ASGI app."""

    def test_public_paths_always_allowed(self, app_client, monkeypatch):
        """Health and well-known endpoints bypass auth even when auth is configured."""
        monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
        monkeypatch.setenv("AUTH0_AUDIENCE", "https://api.example.com")

        # Health should pass without any auth header
        resp = app_client.get("/health")
        assert resp.status_code == 200

        # well-known should also pass
        resp = app_client.get("/.well-known/oauth-protected-resource")
        assert resp.status_code == 200

    def test_mcp_allowed_when_auth_disabled(self, monkeypatch):
        """When AUTH0_DOMAIN is not set, /mcp requests pass through without auth.

        Uses raise_server_exceptions=False because FastMCP's task group isn't
        initialized in TestClient, but we only care that the middleware didn't
        return 401 -- any other error (500) means the request reached FastMCP.
        """
        from starlette.testclient import TestClient

        from omega.server.remote_server import create_app

        monkeypatch.delenv("AUTH0_DOMAIN", raising=False)
        monkeypatch.delenv("AUTH0_AUDIENCE", raising=False)

        client = TestClient(create_app(), raise_server_exceptions=False)
        resp = client.post("/mcp", json={"jsonrpc": "2.0", "method": "initialize", "id": 1})
        # Not 401 means middleware passed through; 500 is expected from FastMCP lifespan
        assert resp.status_code != 401

    def test_mcp_rejected_without_token_when_auth_enabled(self, app_client, monkeypatch):
        """When auth is enabled, /mcp without Authorization header returns 401."""
        monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
        monkeypatch.setenv("AUTH0_AUDIENCE", "https://api.example.com")

        resp = app_client.post("/mcp", json={"jsonrpc": "2.0", "method": "tools/list", "id": 1})

        assert resp.status_code == 401
        assert resp.json() == {"error": "Unauthorized"}
        assert "Bearer" in resp.headers.get("www-authenticate", "")

    def test_mcp_rejected_with_invalid_token_when_auth_enabled(self, app_client, monkeypatch):
        """When auth is enabled, /mcp with bad Bearer token returns 401."""
        monkeypatch.setenv("AUTH0_DOMAIN", "test.auth0.com")
        monkeypatch.setenv("AUTH0_AUDIENCE", "https://api.example.com")

        resp = app_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "method": "tools/list", "id": 1},
            headers={"Authorization": "Bearer invalid-token-xyz"},
        )

        assert resp.status_code == 401
        assert "www-authenticate" in resp.headers
