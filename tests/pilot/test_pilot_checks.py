"""Phase 4 pilot checks: the check engine on the real import (dev DB).

- the flood regression parcels (tests/data/flood_regression.yaml);
- the seed objects (PLAN.md §2.4) as targets, a property among them;
- a 100-object run within the time limit, replayed with the same results.
Runs are stored in the dev DB like any other run (kept, D3).
"""

import time
from pathlib import Path

import psycopg
import pytest
import yaml

from conftest import TEST_DATABASE_URL
from engine.checks import runner, summary
from engine.checks.contract import TargetIn
from engine.checks.modules.flood import NOT_COVERED
from tests.pilot.support import SEEDS

pytestmark = [pytest.mark.pilot, pytest.mark.stack]

ROOT = Path(__file__).resolve().parents[2]
RUN_100_LIMIT_S = 30  # Phase 9 target: 1,000 rows in < 5 min


@pytest.fixture
def conn(live):
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as c:
        yield c


def results(conn, run_id):
    return {
        (r.target_no, r.result.module, r.scope, r.unit_code): r.result
        for r in runner.stored(conn, run_id)
    }


def test_flood_regression_parcels(conn):
    cases = yaml.safe_load((ROOT / "tests/data/flood_regression.yaml").read_text("utf-8"))["cases"]
    targets = [TargetIn(type="parcel", designation=c["parcel"]) for c in cases]
    rid = runner.start_run(conn, targets, ["flood_10y"], origin="test")
    rows = results(conn, rid)
    for no, case in enumerate(cases):
        r = rows[(no, "flood_10y", "target", case["parcel"])]
        assert r.status == case["expect"], (case, r.status, r.items)
        if case["expect"] == "found":
            assert r.items[0]["share"] >= 0.9 and r.risk == "high"
        if case["expect"] == "not_covered":
            assert r.reason == NOT_COVERED and r.risk == "none"
        if case["expect"] == "clear":
            assert r.items == [] and r.risk in ("none", "low")


def test_seed_objects(conn, live):
    targets = [
        TargetIn(type="property", designation="05000041006", given_address="101808322"),
        TargetIn(type="parcel", designation="13000102702", given_address="102485506"),
        TargetIn(type="parcel", designation="09000360220", given_address="101765287"),
    ]
    assert [t.designation for t in targets] == list(SEEDS)
    rid = runner.start_run(conn, targets, origin="test")
    rows = results(conn, rid)
    s = summary.summarize(conn, rid)
    assert s["status"] == "done" and len(s["modules_summary"]) == 8  # modules 1–6, 8 and 14
    for (_no, _module, _scope, _unit), r in rows.items():
        assert r.dataset_version_ids and set(r.dataset_version_ids) <= set(live.values())
        assert r.status != "error", r.reason
    # 05000041006 is a property only; its parcel 05000040014 is checked as a unit.
    units = {k[3] for k in rows if k[0] == 0 and k[2] == "unit"}
    assert "05000040014" in units
    # Tautas iela 11 is the address of a building on the property's parcel (2026-10-11).
    address_match = ["linked_object_address", "own_address", "own_address"]
    for no, code in enumerate(SEEDS):
        assert rows[(no, "cadastre_facts", "target", code)].status == "found"
        m2 = rows[(no, "address_consistency", "target", code)]
        assert (m2.status, m2.match_type) == ("clear", address_match[no]), m2.items
    agg = rows[(0, "encumbrances", "target", "05000041006")]
    assert agg.subject.type == "property"


def test_100_objects_in_time_and_replayable(conn, live):
    codes = [
        r[0]
        for r in conn.execute(
            """SELECT code FROM (
               SELECT p.code, row_number() OVER (PARTITION BY p.atvk ORDER BY md5(p.code)) AS n
               FROM ref.parcel p
               JOIN ref.kk_parcel k ON k.dataset_version_id = %s AND k.code = p.code
               WHERE p.dataset_version_id = %s) x
           WHERE n <= 34 ORDER BY code LIMIT 100""",
            (live["cadastre_spatial"], live["cadastre_text"]),
        )
    ]
    assert len(codes) == 100
    t0 = time.monotonic()
    rid = runner.start_run(
        conn, [TargetIn(type="parcel", designation=c) for c in codes], origin="test"
    )
    elapsed = time.monotonic() - t0
    assert elapsed < RUN_100_LIMIT_S, f"100 objects took {elapsed:.1f} s"
    stored = [r.comparable() for r in runner.stored(conn, rid)]
    assert len(stored) == 800  # 100 parcels x 8 object modules (1–6, 8, 14)
    assert [r.comparable() for r in runner.replay(conn, rid)] == stored
