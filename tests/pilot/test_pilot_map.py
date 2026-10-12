"""Phase 6 pilot map: the results view's data on the real import (dev DB).

- the three flood regression parcels (tests/data/flood_regression.yaml): the
  found one has a flood attention area equal to the engine's overlap; the
  clear and not-covered ones have none; the not-covered one shows "nav plūdu
  kartes" around it;
- a 20-object list: every checked unit with geometry has an outline with a
  risk, and the layers answer for each object's view.
"""

from pathlib import Path

import psycopg
import pytest
import yaml

from conftest import TEST_DATABASE_URL
from engine.batch.plan import run_batch
from engine.batch.reader import read_text
from engine.checks import runner
from engine.map import geo

pytestmark = [pytest.mark.pilot, pytest.mark.stack]

ROOT = Path(__file__).resolve().parents[2]
CASES = yaml.safe_load((ROOT / "tests/data/flood_regression.yaml").read_text(encoding="utf-8"))[
    "cases"
]


@pytest.fixture
def conn(live):
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as c:
        yield c


def pad(box, d=0.004):
    return (box[0] - d, box[1] - d, box[2] + d, box[3] + d)


def flood_items(conn, run_id, target_no):
    rows = [
        r
        for r in runner.stored(conn, run_id)
        if r.target_no == target_no and r.result.module == "flood_10y"
    ]
    if any(r.scope == "unit" for r in rows):
        rows = [r for r in rows if r.scope == "unit"]
    return {(r.unit_code, i["layer"]): i for r in rows for i in r.result.items}


def test_flood_regression_parcels_on_the_map(conn):
    rid = run_batch(conn, read_text("\n".join(c["parcel"] for c in CASES), 1000), origin="test")
    outlines = geo.targets(conn, rid)
    targets = {t.designation: no for no, t in enumerate(runner.load_targets(conn, rid))}
    for case in CASES:
        no = targets[case["parcel"]]
        att = [
            f
            for f in geo.attention(conn, rid, no)["features"]
            if f["properties"]["module"] == "flood_10y"
        ]
        items = flood_items(conn, rid, no)
        if case["expect"] == "found":
            assert att, case
            for f in att:
                p = f["properties"]
                item = next(i for (u, _l), i in items.items() if u == p["unit"])
                assert p["area_m2"] == pytest.approx(item["overlap_m2"], abs=0.05)
                assert p["risk"] == "high" and p["rule_ids"] == ["flood_10y_major"]
        else:
            assert att == [], case
        box = outlines["bbox_by_target"][str(no)]
        kinds = {
            f["properties"]["kind"] for f in geo.layer(conn, rid, "pludi", pad(box))["features"]
        }
        if case["expect"] == "found":
            assert "flood_10y" in kinds
        if case["expect"] == "not_covered":
            assert "no_flood_map" in kinds and "flood_10y" not in kinds


def test_twenty_objects_have_outlines_and_layers(conn, live):
    codes = [
        r[0]
        for r in conn.execute(
            "SELECT code FROM ref.parcel WHERE dataset_version_id = %s"
            " ORDER BY md5(code || 'map') LIMIT 20",
            (live["cadastre_text"],),
        )
    ]
    rid = run_batch(conn, read_text("\n".join(codes), 1000), origin="test")
    outlines = geo.targets(conn, rid)
    with_geom = {f["properties"]["target_no"] for f in outlines["features"]}
    n = len(runner.load_targets(conn, rid))
    assert n >= 20 and len(with_geom) >= n - 2  # a few map-less parcels at most
    assert all(f["properties"]["risk"] for f in outlines["features"])
    for no in sorted(with_geom)[:5]:
        box = pad(outlines["bbox_by_target"][str(no)])
        for name in geo.LAYERS:
            fc = geo.layer(conn, rid, name, box)
            assert fc["sources"], name
        geo.attention(conn, rid, no)
