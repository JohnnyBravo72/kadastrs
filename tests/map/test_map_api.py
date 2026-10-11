"""Map API (PLAN.md §8.2): outlines, attention overlaps and layers, all from the
run's pinned versions; attention areas equal the engine's stored overlaps."""

import json

import pytest

from engine.batch.plan import run_batch
from engine.batch.reader import read_text
from engine.checks import runner
from tests.checks.conftest import V, add_flood

pytestmark = pytest.mark.stack


@pytest.fixture(scope="module")
def run(batch_db):
    with batch_db() as c:
        return run_batch(c, read_text("09000050400\n13000102702\n09000360220", 1000))


def stored_items(conn, run_id, target_no, module):
    """Items of the results the map shows: a property's units, else the target."""
    rows = [r for r in runner.stored(conn, run_id)
            if r.target_no == target_no and r.result.module == module]  # fmt: skip
    if any(r.scope == "unit" for r in rows):
        rows = [r for r in rows if r.scope == "unit"]
    return [i for r in rows for i in r.result.items]


def wide(box, pad=0.003):
    return ",".join(str(v) for v in (box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad))


def test_targets_outlines_risk_and_wgs84(client, run):
    body = client.get(f"/api/runs/{run}/map/targets").json()
    by_unit = {f["properties"]["unit"]: f for f in body["features"]}
    assert by_unit["09000050400"]["properties"]["risk"] == "high"  # flood ≥ 10 %
    assert by_unit["09000050400"]["properties"]["risk_lv"] == "augsts"
    # a property: one feature per checked unit; the building without geometry
    # is drawn with its parcel's outline (as the engine checked it)
    nojume = by_unit["09000360220012"]["properties"]
    assert nojume["basis"] == "parcel" and nojume["target_no"] == 2
    lon, lat = by_unit["09000050400"]["geometry"]["coordinates"][0][0][0]
    assert 20 < lon < 29 and 55 < lat < 59  # EPSG:4326
    assert set(body["bbox_by_target"]) == {"0", "1", "2"}


def test_flood_attention_equals_the_engine_overlap(client, conn, run):
    feats = client.get(f"/api/runs/{run}/targets/0/attention").json()["features"]
    (flood,) = [f for f in feats if f["properties"]["module"] == "flood_10y"]
    (item,) = stored_items(conn, run, 0, "flood_10y")
    p = flood["properties"]
    assert p["area_m2"] == pytest.approx(item["overlap_m2"], abs=0.01)
    assert (p["rule_ids"], p["risk"], p["share"]) == (["flood_10y_major"], "high", item["share"])
    assert p["rule_texts"] == ["Vismaz 10 % objekta atrodas 10 gadu plūdu zonā."]


def test_nature_and_bis_attention(client, conn, run):
    feats = client.get(f"/api/runs/{run}/targets/1/attention").json()["features"]
    nature = [f["properties"] for f in feats if f["properties"]["module"] == "nature"]
    (item,) = stored_items(conn, run, 1, "nature")  # the habitat sliver is not a finding
    assert [n["kind"] for n in nature] == ["microreserve"]
    assert nature[0]["area_m2"] == pytest.approx(item["overlap_m2"], abs=0.01)
    assert nature[0]["risk"] == "high" and nature[0]["item"].startswith("Mikroliegums")
    bis = [f for f in feats if f["properties"]["module"] == "bis"]
    assert [(b["geometry"]["type"], b["properties"]["match_type"]) for b in bis] == [
        ("Point", "nearby")
    ]


def test_property_attention_per_unit(client, run):
    feats = client.get(f"/api/runs/{run}/targets/2/attention").json()["features"]
    units = {f["properties"]["unit"] for f in feats if f["properties"]["module"] == "nature"}
    assert units == {"09000360220", "09000360220002", "09000360220012"}
    assert client.get(f"/api/runs/{run}/targets/9/attention").status_code == 404


def test_layers_in_a_box(client, run):
    box = client.get(f"/api/runs/{run}/map/targets").json()["bbox_by_target"]["0"]
    kad = client.get(f"/api/runs/{run}/layers/kadastrs", params={"bbox": wide(box)}).json()
    assert "09000050400" in {f["properties"]["code"] for f in kad["features"]}
    assert kad["sources"][0]["id"] == "cadastre_spatial" and kad["truncated"] is False
    flood = client.get(f"/api/runs/{run}/layers/pludi", params={"bbox": wide(box, 0.02)}).json()
    kinds = {f["properties"]["kind"] for f in flood["features"]}
    assert kinds == {"flood_10y", "no_flood_map"}  # the box reaches beyond the mask
    assert flood["sources"][0]["dataset_date"] == "2026-10-10"
    big = client.get(f"/api/runs/{run}/layers/daba", params={"bbox": "21,56,24,57.5"})
    assert big.status_code == 413 and "pietuviniet" in big.json()["detail"]
    assert client.get(f"/api/runs/{run}/layers/x", params={"bbox": wide(box)}).status_code == 404
    assert client.get(f"/api/runs/{run}/layers/bis", params={"bbox": "a"}).status_code == 422


def test_layers_use_the_runs_pinned_version_after_a_newer_import(client, conn, run):
    """A newer flood version moves the zone away; the old run's map still shows
    the zone its results were computed on."""
    targets = client.get(f"/api/runs/{run}/map/targets").json()
    box = targets["bbox_by_target"]["0"]
    parcel = next(f for f in targets["features"] if f["properties"]["unit"] == "09000050400")
    conn.execute(
        "UPDATE dataset_version SET status = 'superseded' WHERE id = %s", (V["flood_10y"],)
    )
    conn.execute(
        "INSERT INTO dataset_version (id, source_id, version_date, checksum, status)"
        " OVERRIDING SYSTEM VALUE VALUES (51, 'flood_10y', '2026-10-11', %s, 'live')",
        ("sha256:" + "6" * 64,),
    )
    try:
        moved = [
            (0, "finding", "A2", (473990, 272990, 474020, 273020)),
            (3, "coverage_mask", "M", (472000, 272000, 476000, 276000)),
        ]
        add_flood(conn, 51, moved)
        flood = client.get(f"/api/runs/{run}/layers/pludi", params={"bbox": wide(box)}).json()
        zone = next(f for f in flood["features"] if f["properties"]["kind"] == "flood_10y")
        inside = conn.execute(
            "SELECT ST_Contains(ST_GeomFromGeoJSON(%s), ST_PointOnSurface(ST_GeomFromGeoJSON(%s)))",
            (json.dumps(zone["geometry"]), json.dumps(parcel["geometry"])),
        ).fetchone()[0]
        assert inside  # the old zone (finding A), not the moved one
        assert flood["sources"][0]["dataset_version_id"] == V["flood_10y"]
        att = client.get(f"/api/runs/{run}/targets/0/attention").json()["features"]
        assert any(f["properties"]["module"] == "flood_10y" for f in att)
    finally:
        for table in ("ref.flood_zone_part", "ref.flood_zone"):
            conn.execute(f"DELETE FROM {table} WHERE dataset_version_id = 51")  # noqa: S608
        conn.execute("UPDATE dataset_version SET status = 'failed' WHERE id = 51")
        conn.execute("UPDATE dataset_version SET status = 'live' WHERE id = %s", (V["flood_10y"],))


def test_target_results_carry_rule_texts(client, run):
    body = client.get(f"/api/runs/{run}/targets/0").json()
    flood = next(m for m in body["results"] if m["module"] == "flood_10y")["result"]
    assert flood["rules"] == [
        {
            "id": "flood_10y_major",
            "level": "high",
            "text_lv": "Vismaz 10 % objekta atrodas 10 gadu plūdu zonā.",
        }
    ]
