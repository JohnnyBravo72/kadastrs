"""Shared pytest fixtures.

The suite normally runs in the `tests` container:
    docker compose --profile test run --rm tests
which starts the stack and sets the URLs below. Tests marked `stack` need the
stack; they fail, never skip, when it is down (a silently skipped CRS test
would hide a missing grid).
"""

import os

import psycopg
import pytest

TEST_DATABASE_URL = os.environ.get(
    "KADASTRS_TEST_DATABASE_URL", "postgresql://kadastrs:kadastrs-dev@127.0.0.1:5432/kadastrs"
)
API_BASE_URL = os.environ.get("KADASTRS_TEST_API_URL", "http://127.0.0.1:8000")
NOGRID_DATABASE_URL = os.environ.get("KADASTRS_TEST_NOGRID_DATABASE_URL")
STACK_HINT = "run the tests with: docker compose --profile test run --rm tests (docs/runbook.md)"


def _connect(url: str):
    try:
        return psycopg.connect(url, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.fail(f"DB not reachable at {url}: {exc}\n{STACK_HINT}")


@pytest.fixture(scope="session")
def db_url() -> str:
    return TEST_DATABASE_URL


@pytest.fixture
def db_conn(db_url):
    with _connect(db_url) as conn:
        yield conn


@pytest.fixture
def nogrid_conn():
    """The db-nogrid service: same DB image, grid file deleted."""
    if not NOGRID_DATABASE_URL:
        pytest.fail(f"KADASTRS_TEST_NOGRID_DATABASE_URL is not set\n{STACK_HINT}")
    with _connect(NOGRID_DATABASE_URL) as conn:
        yield conn


@pytest.fixture(scope="session")
def api_url() -> str:
    return API_BASE_URL
