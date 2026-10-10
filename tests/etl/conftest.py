"""Fixtures for ETL tests: an empty kadastrs_test database per test, a fake
data.gov.lv, and a helper that runs one import against both."""

import os
from dataclasses import replace
from functools import partial

import psycopg
import pytest

from conftest import STACK_HINT
from etl.importers import IMPORTERS
from etl.run import run_import
from etl.settings import etl_config
from etl.sources import load_config
from tests.etl.fakes import API, FakeServer

ETL_DB = os.environ.get(
    "KADASTRS_TEST_ETL_DATABASE_URL",
    "postgresql://kadastrs:kadastrs-dev@127.0.0.1:5432/kadastrs_test",
)
RESET = """
TRUNCATE ref.admin_area, ref.address, ref.address_history, ref.kk_parcel, ref.kk_parcel_part,
         ref.kk_building, ref.kk_servitude, ref.parcel, ref.parcel_part, ref.building,
         ref.building_parcel, ref.property, ref.property_object,
         ref.bis_case, ref.bis_object, ref.encumbrance, ref.atis_classifier,
         ref.encumbrance_frozen,
         import_log, dataset_version, source, allowed_external_resource RESTART IDENTITY CASCADE
"""


@pytest.fixture
def etl_db():
    """Connection factory for an emptied kadastrs_test database."""
    try:
        with psycopg.connect(ETL_DB, connect_timeout=3) as c:
            c.execute(RESET)
    except psycopg.OperationalError as exc:
        pytest.fail(f"test DB not reachable at {ETL_DB}: {exc}\n{STACK_HINT}")
    return partial(psycopg.connect, ETL_DB)


@pytest.fixture
def server():
    return FakeServer()


@pytest.fixture
def run(etl_db, server, tmp_path):
    """run(source_id) -> Outcome, against the fake server and the test DB."""
    cfg = replace(etl_config(), ckan_api=API)
    registry = load_config()

    def _run(source_id: str):
        with server.client() as client:
            return run_import(
                IMPORTERS[source_id](),
                conn_factory=etl_db,
                client=client,
                cfg=cfg,
                registry=registry,
                raw_root=tmp_path / "raw",
            )

    return _run


@pytest.fixture
def q(etl_db):
    """q(sql, *params) -> all rows, from the test DB."""

    def _q(sql, *params):
        with etl_db() as c:
            return c.execute(sql, params or None).fetchall()

    return _q
