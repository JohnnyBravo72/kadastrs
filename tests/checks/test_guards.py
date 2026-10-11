"""DB-level guards on runs and results (CLAUDE.md rule 3, migration 20261011090000):
results are never updated or deleted, finished runs never change, results name
only pinned versions."""

import json

import psycopg
import pytest

from etl.sources import load_config, sync_registry

pytestmark = pytest.mark.stack

SHA = "0" * 64


@pytest.fixture
def run_id(etl_db):
    with etl_db() as c:
        sync_registry(c, load_config())
        c.execute(
            "INSERT INTO dataset_version (id, source_id, version_date, checksum, status)"
            " OVERRIDING SYSTEM VALUE VALUES (1, 'flood_10y', '2026-08-19', %s, 'live'),"
            " (2, 'bis_cases', '2026-10-10', %s, 'live')",
            ("sha256:" + "1" * 64, "sha256:" + "2" * 64),
        )
        rid = c.execute(
            "INSERT INTO work.run (origin, sources, modules, engine_version, rule_set_version,"
            " rule_set_status, rule_set_sha256, rule_set) VALUES ('test', '{flood_10y}',"
            " '{flood_10y}', '1', '1', 'draft', %s, '{}') RETURNING id",
            (SHA,),
        ).fetchone()[0]
        c.execute(
            "INSERT INTO work.run_version VALUES (%s, 'flood_10y', 1, '{}')",
            (rid,),
        )
        c.execute(
            "INSERT INTO work.run_target (run_id, target_no, type, designation)"
            " VALUES (%s, 0, 'parcel', '09000050400')",
            (rid,),
        )
        _insert_result(c, rid, [1])
    return rid


def _insert_result(c, rid, versions, unit="09000050400"):
    c.execute(
        "INSERT INTO work.check_result (run_id, target_no, scope, unit_type, unit_code, module,"
        " module_no, module_version, status, risk, rule_ids, items, warnings, sources,"
        " dataset_version_ids, display, computed_at) VALUES (%s, 0, 'target', 'parcel', %s,"
        " 'flood_10y', 4, '1', 'found', 'high', '{r}', '[]', '[]', '[]', %s, %s, now())",
        (rid, unit, versions, json.dumps({"kind": "table"})),
    )


def _fails(etl_db, sql, *params, match="never changed"):
    with etl_db() as c, pytest.raises(psycopg.errors.DatabaseError, match=match):
        c.execute(sql, params or None)


def test_result_update_fails(etl_db, run_id):
    _fails(etl_db, "UPDATE work.check_result SET risk = 'none' WHERE run_id = %s", run_id)


def test_result_delete_fails(etl_db, run_id):
    _fails(etl_db, "DELETE FROM work.check_result WHERE run_id = %s", run_id)


def test_target_and_version_rows_never_change(etl_db, run_id):
    _fails(etl_db, "UPDATE work.run_target SET designation = '09000050401'")
    _fails(etl_db, "DELETE FROM work.run_version")
    _fails(etl_db, "DELETE FROM work.run")


def test_truncate_needs_the_reset_setting(etl_db, run_id):
    _fails(etl_db, "TRUNCATE work.check_result", match="TRUNCATE")


def test_result_names_only_pinned_versions(etl_db, run_id):
    with etl_db() as c, pytest.raises(psycopg.errors.ForeignKeyViolation, match="did not pin"):
        _insert_result(c, run_id, [1, 2], unit="09000050401")


def test_run_allows_only_the_status_transition(etl_db, run_id):
    _fails(etl_db, "UPDATE work.run SET rule_set_version = '2' WHERE id = %s", run_id)
    with etl_db() as c:
        c.execute(
            "UPDATE work.run SET status = 'done', finished_at = now() WHERE id = %s", (run_id,)
        )
    _fails(etl_db, "UPDATE work.run SET status = 'failed' WHERE id = %s", run_id, match="finished")
    with etl_db() as c, pytest.raises(psycopg.errors.DatabaseError, match="not running"):
        _insert_result(c, run_id, [1], unit="09000050401")
