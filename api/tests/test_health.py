import platform

import httpx
import pytest
from fastapi.testclient import TestClient

from api.main import app
from conftest import STACK_HINT


def _assert_healthy(body: dict) -> None:
    assert body["status"] == "ok", body
    db = body["db"]
    assert db["ok"] is True
    assert db["postgres"].startswith("18")
    assert db["postgis"].startswith("3.6")
    assert db["proj_ok"] is True, db["proj"]
    assert db["srid_10306"] is True
    assert db["lks_grid"] is True
    assert db["migration"]


@pytest.mark.stack
def test_health_in_process(db_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", db_url)
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200, resp.text
    _assert_healthy(resp.json())


def test_health_reports_503_when_db_unreachable(monkeypatch):
    # Port 1 on localhost: nothing listens there, so the connection is refused.
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody:x@127.0.0.1:1/none")
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "error"
    assert body["db"]["ok"] is False
    assert body["db"]["error"]


@pytest.mark.stack
def test_health_of_running_api_container(api_url):
    try:
        resp = httpx.get(f"{api_url}/health", timeout=10)
    except httpx.HTTPError as exc:
        pytest.fail(f"API not reachable at {api_url}: {exc}\n{STACK_HINT}")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    _assert_healthy(body)
    # The api container and the test runner must run the same Python minor.
    runner = platform.python_version_tuple()[:2]
    image = tuple(body["python"].split(".")[:2])
    assert image == runner, f"api Python {body['python']} != runner {platform.python_version()}"
