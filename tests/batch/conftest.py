"""Batch and report tests: the check-engine seed (tests/checks/conftest.py) plus
one building for the T-E4 Excel round trip.

  09000050404001  building on parcel 09000050404; its name was read from XML with
                  CR, LF, tab and a backslash and stored normalised (rule E4)
"""

from functools import partial

import psycopg
import pytest
from fastapi.testclient import TestClient

from etl.textio import clean_text
from tests.checks.conftest import (
    V,
    no_network_freshness,  # noqa: F401  (autouse fixture)
    seed_checks,
)
from tests.etl.conftest import ETL_DB

RAW_NAME = "Noliktava\r\nNr.\t2 \\ korpuss\tA"
STORED_NAME = clean_text(RAW_NAME)  # "Noliktava Nr. 2 \ korpuss A"
TE4_BUILDING = "09000050404001"


def seed_batch(conn) -> None:
    seed_checks(conn)
    t = V["cadastre_text"]
    conn.execute(
        "INSERT INTO ref.building (dataset_version_id, code, file_atvk, name, not_exist, prereg)"
        " VALUES (%s, %s, '0003000', %s, false, false)",
        (t, TE4_BUILDING, STORED_NAME),
    )
    conn.execute(
        "INSERT INTO ref.building_parcel VALUES (%s, %s, '09000050404', 'object_relation')",
        (t, TE4_BUILDING),
    )


@pytest.fixture(scope="module")
def batch_db():
    try:
        with psycopg.connect(ETL_DB, connect_timeout=3) as conn:
            seed_batch(conn)
    except psycopg.OperationalError as exc:
        pytest.fail(f"test DB not reachable at {ETL_DB}: {exc}")
    return partial(psycopg.connect, ETL_DB, autocommit=True)


@pytest.fixture
def conn(batch_db):
    with batch_db() as c:
        yield c


@pytest.fixture(scope="module")
def client(batch_db):
    mp = pytest.MonkeyPatch()
    mp.setenv("DATABASE_URL", ETL_DB)
    from api.main import app

    with TestClient(app) as c:
        yield c
    mp.undo()
