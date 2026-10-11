"""P0-3: the ADK dev-server routes are opt-in and guarded when enabled."""

import pytest
from fastapi.testclient import TestClient

from bondy import fast_api_app

ADK_ROUTES = [
    ("GET", "/list-apps"),
    ("POST", "/run"),
    ("POST", "/run_sse"),
    ("GET", "/apps/bondy/users/u/sessions"),
    ("POST", "/apps/bondy/users/u/sessions"),
]
REMOTE = ("203.0.113.9", 50000)
LOCAL = ("127.0.0.1", 50000)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("BONDY_ENABLE_AGENT_API", raising=False)
    monkeypatch.delenv("BONDY_API_KEY", raising=False)


def _paths(app) -> set[str]:
    return {getattr(r, "path", "") for r in app.routes}


def test_default_app_has_no_adk_routes():
    paths = _paths(fast_api_app.app)
    for forbidden in ("/run", "/run_sse", "/run_live", "/list-apps"):
        assert forbidden not in paths
    assert not any(p.startswith("/apps/") for p in paths)
    assert "/" in paths and "/api/audit" in paths and "/api/apply-fix" in paths


@pytest.mark.parametrize("client", [REMOTE, LOCAL])
@pytest.mark.parametrize(("method", "path"), ADK_ROUTES)
def test_default_app_answers_404_for_adk_routes(client, method, path):
    c = TestClient(fast_api_app.app, client=client)
    assert c.request(method, path, json={}).status_code == 404


def test_default_app_keeps_ui_and_audit_api():
    c = TestClient(fast_api_app.app, client=REMOTE)
    assert c.get("/").status_code == 200
    assert c.get("/api/checks").status_code == 200
    assert c.get("/health").status_code == 200
    # Validation error (missing body) proves the route exists and is reachable.
    assert c.post("/api/audit", json={}).status_code == 422


def test_apply_fix_still_rejects_remote_clients():
    c = TestClient(fast_api_app.app, client=REMOTE)
    r = c.post("/api/apply-fix", json={"file_path": "x", "before": "a", "after": "b"})
    assert r.status_code == 403


@pytest.fixture
def adk_app(monkeypatch):
    monkeypatch.setenv("BONDY_ENABLE_AGENT_API", "1")
    return fast_api_app._build_app()


def test_enabled_flag_mounts_adk_routes(adk_app):
    assert "/run_sse" in _paths(adk_app)


@pytest.mark.parametrize(("method", "path"), ADK_ROUTES)
def test_enabled_adk_routes_denied_from_remote_origin(adk_app, method, path):
    c = TestClient(adk_app, client=REMOTE)
    assert c.request(method, path, json={}).status_code == 403


def test_enabled_docs_denied_from_remote_origin(adk_app):
    c = TestClient(adk_app, client=REMOTE)
    assert c.get("/docs").status_code == 403
    assert c.get("/openapi.json").status_code == 403


def test_enabled_adk_routes_allowed_locally_without_key(adk_app):
    c = TestClient(adk_app, client=LOCAL)
    assert c.get("/list-apps").status_code == 200


def test_enabled_with_api_key_requires_header(adk_app, monkeypatch):
    monkeypatch.setenv("BONDY_API_KEY", "s3cret")
    # Even a local client needs the key once one is configured.
    local = TestClient(adk_app, client=LOCAL)
    assert local.get("/list-apps").status_code == 403
    assert local.get("/list-apps", headers={"X-API-Key": "wrong"}).status_code == 403
    remote = TestClient(adk_app, client=REMOTE)
    assert remote.get("/list-apps", headers={"X-API-Key": "s3cret"}).status_code == 200


def test_enabled_guard_leaves_ui_paths_to_their_own_policy(adk_app):
    # Not guarded: these paths reach the app (which has no such route -> 404,
    # never the guard's 403).
    c = TestClient(adk_app, client=REMOTE)
    assert c.get("/health").status_code != 403
    assert c.get("/api/checks").status_code != 403
    assert c.get("/static/x.css").status_code != 403
