"""Bearer-token gate (Phase 10)."""

from starlette.testclient import TestClient

from api.auth import BearerAuthMiddleware, auth_token
from api.main import app


def test_middleware_registered():
    assert BearerAuthMiddleware in [m.cls for m in app.user_middleware]


def test_open_when_token_unset(monkeypatch):
    monkeypatch.delenv("KADASTRS_AUTH_TOKEN", raising=False)
    assert auth_token() is None
    with TestClient(app) as c:
        r = c.get("/health")
        assert r.status_code != 401
        assert r.status_code != 403


def test_requires_bearer_when_token_set(monkeypatch):
    monkeypatch.setenv("KADASTRS_AUTH_TOKEN", "secret-test-token")
    with TestClient(app) as c:
        # /openapi.json needs no DB; proves the gate accepts a valid token.
        assert c.get("/openapi.json").status_code == 401
        assert c.get("/openapi.json", headers={"Authorization": "Bearer wrong"}).status_code == 403
        ok = c.get("/openapi.json", headers={"Authorization": "Bearer secret-test-token"})
        assert ok.status_code == 200
        assert c.get("/health").status_code != 401


def test_auth_token_strips_whitespace(monkeypatch):
    monkeypatch.setenv("KADASTRS_AUTH_TOKEN", "  abc  ")
    assert auth_token() == "abc"
    monkeypatch.setenv("KADASTRS_AUTH_TOKEN", "   ")
    assert auth_token() is None
