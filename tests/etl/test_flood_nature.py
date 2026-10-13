"""Phase 2b importers on synthetic data: flood (fake ArcGIS service, D1 E7) and DAP nature."""

from dataclasses import replace

import pytest

from etl.importers import IMPORTERS
from etl.run import run_import
from etl.settings import etl_config
from etl.sources import load_config
from tests.etl import fakes
from tests.etl.test_import_sources import publish_all
from tests.etl.test_rules_e3_e7 import BOWTIE, live

JX, JY = fakes.CITY_XY["0003000"]  # Jelgava square in the fake admin data


def ring(x, y, s=10.0):
    return fakes.square(x, y, s)


@pytest.fixture
def run_fast(etl_db, server, tmp_path):
    """Like `run`, with no pauses between ArcGIS requests or retries."""
    base = etl_config()
    options = {
        **base.options,
        "flood_10y": {**base.options["flood_10y"], "request_pause_s": 0, "retry_pauses": [0, 0, 0]},
    }
    cfg = replace(base, ckan_api=fakes.API, options=options)

    def _run(source_id):
        with server.client() as client:
            return run_import(
                IMPORTERS[source_id](),
                conn_factory=etl_db,
                client=client,
                cfg=cfg,
                registry=load_config(),
                raw_root=tmp_path / "raw",
            )

    return _run


def publish_flood(server, layer0=None, layer3=None):
    server.arcgis = {
        0: fakes.arcgis_layer(
            0,
            layer0
            if layer0 is not None
            else {
                1: ring(JX + 100, JY + 100),  # inside Jelgava's extent
                2: [[x + JX + 300, y + JY + 300] for x, y in BOWTIE],  # self-intersecting
                3: ring(JX + 50000, JY + 50000),  # far away: not fetched
            },
        ),
        1: fakes.arcgis_layer(1, {}),
        3: fakes.arcgis_layer(3, layer3 if layer3 is not None else {7: ring(JX, JY, 800)}),
    }


# --- flood -------------------------------------------------------------------------


def test_flood_import(run_fast, server, q):
    publish_all(server)
    publish_flood(server)
    assert run_fast("admin_boundaries").status == "succeeded"
    out = run_fast("flood_10y")
    assert out.status == "succeeded", out.message
    rows = q(
        "SELECT layer, object_id, role, GeometryType(geom), ST_SRID(geom), ST_IsValid(geom)"
        " FROM ref.flood_zone ORDER BY layer, object_id"
    )
    assert rows == [
        (0, "1", "finding", "MULTIPOLYGON", 10306, True),
        (0, "2", "finding", "MULTIPOLYGON", 10306, True),
        (3, "7", "coverage_mask", "MULTIPOLYGON", 10306, True),
    ]
    assert out.row_counts["flood_zone"]["invalid_repaired"] == 1
    assert out.row_counts["flood_zone"]["validated"] == 3
    assert q("SELECT count(*) FROM ref.flood_10y_current") == [(2,)]
    # subdivided copy covers exactly the same area
    assert q("SELECT round(sum(ST_Area(geom))::numeric, 3) FROM ref.flood_zone_part") == q(
        "SELECT round(sum(ST_Area(geom))::numeric, 3) FROM ref.flood_zone"
    )
    assert q("SELECT count(*) FROM ref.flood_coverage_current") == [(1,)]
    # Every geometry request: 3059, 1 cm simplification, batches of at most 25.
    assert server.arcgis_batches
    for _layer, ids, params in server.arcgis_batches:
        assert params["outSR"] == "3059" and params["maxAllowableOffset"] == "0.01"
        assert len(ids) <= 25
    # Version: dated by the data.gov.lv listing; E7 processing notes recorded.
    v = q(
        "SELECT version_date::text, processing, licence FROM dataset_version WHERE status = 'live'"
        " AND source_id = 'flood_10y'"
    )[0]
    assert v[0] == "2026-08-19" and v[2] == "CC0-1.0"
    ids = {p["id"] for p in v[1]}
    assert {
        "import_extent",
        "coverage_mask",
        "simplify_1cm",
        "make_valid",
        "reproject",
        "repair_counts",
    } <= ids


def test_flood_geometry_goes_through_the_grid_transform(run_fast, server, q):
    publish_all(server)
    publish_flood(server, layer0={1: ring(JX + 100, JY + 100)}, layer3={})
    run_fast("admin_boundaries")
    assert run_fast("flood_10y").status == "succeeded"
    x0, y0, x1, y1 = JX + 100, JY + 100, JX + 110, JY + 110
    wkt = f"MULTIPOLYGON((({x0} {y0},{x0} {y1},{x1} {y1},{x1} {y0},{x0} {y0})))"
    d = q(
        "SELECT ST_HausdorffDistance(geom,"
        " lks92_to_lks2020(ST_SetSRID(ST_GeomFromText(%s), 3059))) FROM ref.flood_zone",
        wkt,
    )[0][0]
    assert d < 0.001


def test_flood_second_run_is_unchanged(run_fast, server, q):
    publish_all(server)
    publish_flood(server)
    run_fast("admin_boundaries")
    assert run_fast("flood_10y").status == "succeeded"
    server.metadata_modified[fakes.DATASETS["flood_10y"]] = "2026-09-30T00:00:00"  # metadata only
    out = run_fast("flood_10y")
    assert out.status == "unchanged", out.message
    assert q("SELECT count(*) FROM dataset_version WHERE source_id = 'flood_10y'") == [(1,)]


def test_flood_failing_batch_is_fetched_one_by_one(run_fast, server, q):
    publish_all(server)
    publish_flood(server, layer0={i: ring(JX + 20 * i, JY) for i in range(1, 31)}, layer3={})
    server.arcgis_fail_in_batch = {5}  # a huge polygon that breaks multi-object requests
    run_fast("admin_boundaries")
    out = run_fast("flood_10y")
    assert out.status == "succeeded", out.message
    assert q("SELECT count(*) FROM ref.flood_zone") == [(30,)]
    assert any(ids == [5] for _, ids, _ in server.arcgis_batches)


def test_flood_needs_admin_boundaries(run_fast, server, q):
    publish_flood(server)
    out = run_fast("flood_10y")
    assert out.status == "failed" and "import admin_boundaries first" in out.message


def test_flood_layer_schema_change_stops_the_import(run_fast, server, q):
    publish_all(server)
    publish_flood(server)
    run_fast("admin_boundaries")
    assert run_fast("flood_10y").status == "succeeded"
    before = live(q, "flood_10y")
    server.arcgis[0]["info"]["fields"].append(
        {"name": "depth_class", "type": "esriFieldTypeString"}
    )
    out = run_fast("flood_10y")
    assert out.status == "failed" and "layer 0 differs" in out.message
    assert live(q, "flood_10y") == before


# --- DAP nature ----------------------------------------------------------------------


def publish_nature(server, source_id, records):
    fname = fakes.DAP_FILES[source_id][0]
    server.publish(
        source_id,
        "shp",
        fname,
        fakes.dap_zip(source_id, records),
        last_modified="2026-04-07T04:59:54",
    )


NATURE_CASES = {
    "nature_protected_areas": {
        "IADT_pamatteritorijas": [
            (
                fakes.dap_record(
                    "IADT_pamatteritorijas",
                    "{A1}",
                    ID=11,
                    NAME="Lielupes palienes pļavas",
                    CATEGORY="Dabas liegums",
                    ATIS_CODE="7311030100",
                ),
                [ring(JX, JY, 100)],
            )
        ],
        "IADT_zonejums": [
            (
                fakes.dap_record("IADT_zonejums", "{A2}", ID=12, NAME="Dabas lieguma zona"),
                [[[x + JX + 200, y + JY] for x, y in BOWTIE]],
            )
        ],
    },
    "nature_microreserves": {
        "Mikroliegumi": [
            (fakes.dap_record("Mikroliegumi", "{M1}", MRCODE=4321, MR_TYPE=2), [ring(JX, JY)])
        ],
        "MikroliegumuBuferzonas": [
            (
                fakes.dap_record("MikroliegumuBuferzonas", "{M2}", MRCODE=4321),
                [ring(JX - 20, JY - 20, 50)],
            ),
            (fakes.dap_record("MikroliegumuBuferzonas", "{M3}", MRCODE=4322), []),
        ],  # null shape
    },
    "nature_monuments": {
        "IADT_dabas_pieminekli": [
            (
                fakes.dap_record(
                    "IADT_dabas_pieminekli",
                    "{P1}",
                    ID=5,
                    CATEGORY="Dižkoks",
                    LOCALNAME="Dižozols",
                    SPECIES_LV="Parastais ozols",
                ),
                [ring(JX + 5, JY + 5, 2)],
            )
        ],
    },
    "nature_habitats": {
        "Biotopi": [
            (
                fakes.dap_record("Biotopi", "{H1}", ID=1, CODE_EC="6450", NAME_LV="Palieņu zālāji"),
                [ring(JX, JY, 300)],
            ),
            (fakes.dap_record("Biotopi", "{H2}", ID=1, CODE_EC="9010"), [ring(JX + 400, JY, 50)]),
        ],  # ID not unique
    },
}


@pytest.mark.parametrize("source_id", list(NATURE_CASES))
def test_nature_import(run_fast, server, q, source_id):
    publish_nature(server, source_id, NATURE_CASES[source_id])
    out = run_fast(source_id)
    assert out.status == "succeeded", out.message
    rows = q(
        "SELECT global_id, kind, GeometryType(geom), ST_SRID(geom), ST_IsValid(geom)"
        " FROM ref.nature_area_current"
        " ORDER BY global_id"
    )
    expected_ids = sorted(
        rec["GlobalID"] for recs in NATURE_CASES[source_id].values() for rec, rings in recs if rings
    )
    assert [r[0] for r in rows] == expected_ids
    assert all(r[2:] == ("MULTIPOLYGON", 10306, True) for r in rows)
    v = q(
        "SELECT version_date::text, processing FROM dataset_version WHERE source_id = %s", source_id
    )[0]
    assert v[0] == "2026-04-07" and {p["id"] for p in v[1]} == {"make_valid", "reproject"}


def test_nature_fields_and_repairs(run_fast, server, q):
    for sid in ("nature_protected_areas", "nature_microreserves", "nature_habitats"):
        publish_nature(server, sid, NATURE_CASES[sid])
        assert run_fast(sid).status == "succeeded"
    row = q(
        "SELECT kind, dap_id, name, category, atis_code, attributes->>'NAME' FROM ref.nature_area"
        " WHERE global_id = '{A1}'"
    )[0]
    assert row == (
        "protected_area",
        "11",
        "Lielupes palienes pļavas",
        "Dabas liegums",
        "7311030100",
        "Lielupes palienes pļavas",
    )
    assert q("SELECT mrcode, kind FROM ref.nature_area WHERE global_id = '{M2}'") == [
        ("4321", "microreserve_buffer")
    ]
    assert q(
        "SELECT row_counts->'nature_area'->>'invalid_repaired' FROM import_log"
        " WHERE source_id = 'nature_protected_areas'"
    ) == [("1",)]
    assert q(
        "SELECT row_counts->'nature_area'->>'keys_without_geometry' FROM import_log"
        " WHERE source_id = 'nature_microreserves'"
    ) == [("1",)]
    assert q(
        "SELECT count(*), count(DISTINCT dap_id) FROM ref.nature_area WHERE kind = 'habitat'"
    ) == [(2, 1)]
    assert q("SELECT count(*) FROM ref.nature_area WHERE attributes ? 'Shape_Area'") == [(0,)]


def test_nature_duplicate_globalid_fails(run_fast, server, q):
    recs = {
        "Biotopi": [
            (fakes.dap_record("Biotopi", "{H1}"), [ring(JX, JY)]),
            (fakes.dap_record("Biotopi", "{H1}"), [ring(JX + 50, JY)]),
        ]
    }
    publish_nature(server, "nature_habitats", recs)
    out = run_fast("nature_habitats")
    assert out.status == "failed" and "GlobalID not unique" in out.message


def test_nature_rings_pyshp_cannot_assemble_are_rebuilt(run_fast, server, q, monkeypatch):
    """Like the one DAP habitat (Phase 0): pyshp raises, PostGIS builds the area."""
    import shapefile

    original = shapefile.Shape.__geo_interface__

    def flaky(self):
        if self.points and abs(self.points[0][0] - (JX + 900)) < 1e-6:
            raise shapefile.ShapefileException("Unable to find a ring sample point")
        return original.fget(self)

    monkeypatch.setattr(shapefile.Shape, "__geo_interface__", property(flaky))
    outer = ring(JX + 900, JY, 100)
    hole = [
        [JX + 920, JY + 20],
        [JX + 940, JY + 20],
        [JX + 940, JY + 40],
        [JX + 920, JY + 40],
        [JX + 920, JY + 20],
    ]
    publish_nature(
        server,
        "nature_habitats",
        {"Biotopi": [(fakes.dap_record("Biotopi", "{R1}"), [outer, hole])]},
    )
    out = run_fast("nature_habitats")
    assert out.status == "succeeded", out.message
    assert out.row_counts["nature_area"]["rings_rebuilt_by_layer"] == {"Biotopi": 1}
    area, flags = q("SELECT ST_Area(geom), flags FROM ref.nature_area WHERE global_id = '{R1}'")[0]
    assert abs(area - (100 * 100 - 20 * 20)) < 1  # the hole is kept
    assert flags == ["rings_rebuilt"]


def test_nature_second_run_is_unchanged(run_fast, server, q):
    publish_nature(server, "nature_monuments", NATURE_CASES["nature_monuments"])
    assert run_fast("nature_monuments").status == "succeeded"
    assert run_fast("nature_monuments").status == "unchanged"


def test_nature_offshore_object_is_flagged_outside_grid(run_fast, server, q):
    """Marine protected areas reach beyond the LĢIA grid: zero shift there, flagged."""
    sea = ring(200000, 300000, 100)  # EPSG:3059, Baltic Sea
    recs = {
        "IADT_pamatteritorijas": [
            (fakes.dap_record("IADT_pamatteritorijas", "{S1}", NAME="Jūras teritorija"), [sea]),
            (
                fakes.dap_record("IADT_pamatteritorijas", "{L1}", NAME="Sauszemes teritorija"),
                [ring(JX, JY)],
            ),
        ]
    }
    publish_nature(server, "nature_protected_areas", recs)
    out = run_fast("nature_protected_areas")
    assert out.status == "succeeded", out.message
    assert out.row_counts["nature_area"]["outside_grid"] == 1
    rows = dict(q("SELECT global_id, flags FROM ref.nature_area"))
    assert rows == {"{S1}": ["outside_grid"], "{L1}": []}
    xmin = q("SELECT ST_XMin(geom) FROM ref.nature_area WHERE global_id = '{S1}'")[0][0]
    assert abs(xmin - 200000) < 1e-6  # zero shift outside the grid
