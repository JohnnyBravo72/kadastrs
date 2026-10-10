"""Phase 2b pilot checks: flood (D1 E7) and DAP nature, on the real import.

Raw files, versions and the second-run rule are covered for all sources in
test_pilot_import.py. Regression cases: tests/data/flood_regression.yaml.
"""

import io
import json
import zipfile
from pathlib import Path

import pytest
import shapefile
import yaml

from tests.pilot.support import dbf_counts, one, raw_files

pytestmark = [pytest.mark.pilot, pytest.mark.stack]

ROOT = Path(__file__).resolve().parents[2]
NATURE = {
    "nature_protected_areas": ["IADT_pamatteritorijas", "IADT_zonejums"],
    "nature_microreserves": ["Mikroliegumi", "MikroliegumuBuferzonas"],
    "nature_monuments": ["IADT_dabas_pieminekli"],
    "nature_habitats": ["Biotopi"],
}
# Latvia's land extent from the admin areas; + 150 km covers its sea area.
LAND = "(SELECT ST_SetSRID(ST_Extent(geom)::geometry, 10306) FROM ref.admin_area_current)"
LATVIA = (
    "(SELECT ST_SetSRID(ST_Expand(ST_Extent(geom)::geometry, 150000), 10306)"
    " FROM ref.admin_area_current)"
)


# --- counts against the raw files ---------------------------------------------------


def test_flood_counts(db_conn, live):
    vid = live["flood_10y"]
    r = raw_files(db_conn, "flood_10y", vid)
    for f in r["files"]:
        doc = json.loads((r["base"] / f["path"]).read_text(encoding="utf-8"))
        got = one(
            db_conn,
            "SELECT count(*) FROM ref.flood_zone WHERE dataset_version_id = %s AND layer = %s",
            vid,
            doc["layer"],
        )
        assert got == len(doc["features"]), f"layer {doc['layer']}"


@pytest.mark.parametrize("source", list(NATURE))
def test_nature_counts(db_conn, live, source):
    vid = live[source]
    r = raw_files(db_conn, source, vid)
    zpath = r["base"] / r["files"][0]["path"]
    records = sum(dbf_counts(zpath, layer) for layer in NATURE[source])
    rows = one(db_conn, "SELECT count(*) FROM ref.nature_area WHERE dataset_version_id = %s", vid)
    processing = one(db_conn, "SELECT processing FROM dataset_version WHERE id = %s", vid)
    without = next(p["without_geometry"] for p in processing if p["id"] == "make_valid")
    assert rows + without == records
    assert without <= 5, "more objects without geometry than the known null shape(s)"


# --- geometry -----------------------------------------------------------------------


def test_nature_valid_multipolygon_10306(db_conn, live):
    bad = one(
        db_conn,
        "SELECT count(*) FROM ref.nature_area_current"
        " WHERE NOT ST_IsValid(geom) OR GeometryType(geom) <> 'MULTIPOLYGON'"
        " OR ST_SRID(geom) <> 10306",
    )
    assert bad == 0


def test_flood_valid_multipolygon_10306(db_conn, live):
    """Every flood geometry is valid. Re-checked here for all polygons up to 100,000
    vertices; the few giant ones (over a million vertices, ~20 min each to
    validate) are covered by the import's own check, which runs ST_IsValid on
    every stored row and fails the import otherwise. A version never changes
    after import, so the recorded result stays true."""
    vid = live["flood_10y"]
    bad = one(
        db_conn,
        "SELECT count(*) FROM ref.flood_zone WHERE dataset_version_id = %s"
        " AND (GeometryType(geom) <> 'MULTIPOLYGON' OR ST_SRID(geom) <> 10306"
        " OR (ST_NPoints(geom) <= 100000 AND NOT ST_IsValid(geom)))",
        vid,
    )
    assert bad == 0
    rows = one(db_conn, "SELECT count(*) FROM ref.flood_zone WHERE dataset_version_id = %s", vid)
    processing = one(db_conn, "SELECT processing FROM dataset_version WHERE id = %s", vid)
    validated = next(p.get("validated") for p in processing if p["id"] == "repair_counts")
    assert validated == rows, f"import validated {validated} of {rows} flood rows"


def test_nature_lies_in_latvia(db_conn, live):
    """Within Latvia's land extent + 150 km (marine reefs lie up to ~50 km off the
    coast). Objects flagged outside_grid (zero shift, §6.4) must reach beyond the
    land extent, i.e. lie at sea; the grid itself reaches some km offshore, so the
    reverse does not hold."""
    outside = one(
        db_conn, f"SELECT count(*) FROM ref.nature_area_current WHERE NOT ST_Within(geom, {LATVIA})"
    )
    assert outside == 0
    flagged_on_land = one(
        db_conn,
        f"SELECT count(*) FROM ref.nature_area_current"
        f" WHERE 'outside_grid' = ANY(flags) AND ST_Within(geom, {LAND})",
    )
    assert flagged_on_land == 0


def test_flood_lies_in_the_pilot_extent(db_conn, live):
    outside = one(
        db_conn,
        """
        SELECT count(*) FROM ref.flood_zone f
        WHERE f.dataset_version_id = ref.live_version('flood_10y')
          AND NOT EXISTS (SELECT 1 FROM ref.city_boundary c
                          WHERE c.atvk IN ('0002000', '0003000', '0004000')
                            AND ST_Intersects(f.geom, ST_Expand(ST_Envelope(c.geom), 1100)))""",
    )
    assert outside == 0
    assert one(db_conn, "SELECT count(*) FROM ref.flood_10y_current") > 0
    assert one(db_conn, "SELECT count(*) FROM ref.flood_coverage_current") > 0


def test_flood_geometry_is_the_grid_transform_of_the_raw_feature(db_conn, live):
    vid = live["flood_10y"]
    r = raw_files(db_conn, "flood_10y", vid)
    f = next(f for f in r["files"] if f["role"] == "layer_0")
    doc = json.loads((r["base"] / f["path"]).read_text(encoding="utf-8"))
    feat = min(doc["features"], key=lambda x: len(json.dumps(x["geometry"])))  # a small one
    d = one(
        db_conn,
        """
        SELECT ST_HausdorffDistance(z.geom, lks92_to_lks2020(ST_Multi(ST_CollectionExtract(
                   ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(%s), 3059), 'method=structure'), 3))))
        FROM ref.flood_zone z
        WHERE z.dataset_version_id = %s AND z.layer = 0 AND z.object_id = %s""",
        json.dumps(feat["geometry"]),
        vid,
        str(feat["id"]),
    )
    assert d < 0.001


def test_nature_geometry_is_the_grid_transform_of_the_raw_record(db_conn, live):
    vid = live["nature_monuments"]
    r = raw_files(db_conn, "nature_monuments", vid)
    with zipfile.ZipFile(r["base"] / r["files"][0]["path"]) as z:
        base = next(n[:-4] for n in z.namelist() if n.endswith("IADT_dabas_pieminekli.shp"))
        rd = shapefile.Reader(
            shp=io.BytesIO(z.read(base + ".shp")),
            dbf=io.BytesIO(z.read(base + ".dbf")),
            shx=io.BytesIO(z.read(base + ".shx")),
            encoding="utf-8",
        )
        sr = rd.shapeRecord(0)
    d = one(
        db_conn,
        """
        SELECT ST_HausdorffDistance(n.geom, lks92_to_lks2020(ST_Multi(ST_CollectionExtract(
                   ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(%s), 3059), 'method=structure'), 3))))
        FROM ref.nature_area n WHERE n.dataset_version_id = %s AND n.global_id = %s""",
        json.dumps(sr.shape.__geo_interface__),
        vid,
        sr.record["GlobalID"],
    )
    assert d < 0.001


# --- flood regression cases ---------------------------------------------------------

CASES = yaml.safe_load(
    (ROOT / "tests" / "data" / "flood_regression.yaml").read_text(encoding="utf-8")
)


def classify(db_conn, parcel: str) -> str:
    """found: overlaps the 10-year zone; clear: inside the mask, no overlap;
    not_covered: outside the coverage mask (200-year extent). Plain geometry, no
    thresholds (module 4 adds the PLAN §6.3 rules in Phase 4)."""
    in10, inmask = db_conn.execute(
        """
        SELECT EXISTS (SELECT 1 FROM ref.flood_10y_part_current f
                       WHERE ST_Intersects(f.geom, p.geom)),
               EXISTS (SELECT 1 FROM ref.flood_coverage_part_current m
                       WHERE ST_Intersects(m.geom, p.geom))
        FROM ref.parcel_current p WHERE p.code = %s AND p.has_geometry""",
        (parcel,),
    ).fetchone()
    return "found" if in10 else ("clear" if inmask else "not_covered")


@pytest.mark.parametrize("case", CASES["cases"], ids=[c["expect"] for c in CASES["cases"]])
def test_flood_regression_case(db_conn, live, case):
    assert classify(db_conn, case["parcel"]) == case["expect"], case
