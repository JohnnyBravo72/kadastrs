"""Module 8 TAPIS zoning importer (fake WFS, D1 E4)."""

from dataclasses import replace

import pytest

from etl.importers import IMPORTERS
from etl.run import run_import
from etl.settings import etl_config
from etl.sources import load_config
from tests.etl import fakes
from tests.etl.test_flood_nature import JX, JY
from tests.etl.test_import_sources import publish_all
from tests.etl.test_rules_e3_e7 import live


def _feat(props, x, y, s=20.0):
    ring_coords = fakes.square(x, y, s)
    if ring_coords[0] != ring_coords[-1]:
        ring_coords = [*ring_coords, ring_coords[0]]
    return {
        "type": "Feature",
        "properties": props,
        "geometry": {"type": "Polygon", "coordinates": [ring_coords]},
    }


def publish_zoning(server):
    finding = "tapis_apvienotie:funkcionalais_zonejums"
    mask = "tapis_apvienotie:speka_esosu_planojumu_teritorijas"
    server.wfs = {
        finding: [
            _feat(
                {
                    "tapis_id": 101,
                    "kods": "1010600",
                    "nosaukums": "",
                    "veids": "Rūpnieciskās apbūves teritorija",
                    "indekss": "R",
                    "grupa_kods": "10106",
                    "grupa_nos": "Rūpnieciskās apbūves teritorija",
                    "atvk_kods": "0003000",
                    "dok_id": 1,
                    "dok_nos": "Jelgavas TP",
                },
                JX + 100,
                JY + 100,
            ),
            _feat(
                {
                    "tapis_id": 202,
                    "kods": "1010100",
                    "veids": "Savrupmāju apbūves teritorija",
                    "indekss": "DzS",
                    "grupa_kods": "10101",
                    "grupa_nos": "Savrupmāju apbūves teritorija",
                    "atvk_kods": "0004000",
                    "dok_id": 2,
                    "dok_nos": "Jūrmalas TP",
                },
                fakes.CITY_XY["0004000"][0] + 50,
                fakes.CITY_XY["0004000"][1] + 50,
            ),
        ],
        mask: [
            _feat(
                {
                    "dok_id": 1,
                    "dok_nosaukums": "Jelgavas TP",
                    "atvk_kods": "0003000",
                },
                JX,
                JY,
                800,
            ),
        ],
    }
    server.metadata_modified[fakes.DATASETS["tapis_zoning"]] = "2026-08-19T06:57:02"


@pytest.fixture
def run_zoning(etl_db, server, tmp_path):
    base = etl_config()
    options = {
        **base.options,
        "tapis_zoning": {
            **base.options.get("tapis_zoning", {}),
            "request_pause_s": 0,
            "retry_pauses": [0, 0, 0],
            "page_size": 50,
        },
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


def test_zoning_import(run_zoning, server, q):
    publish_all(server)
    publish_zoning(server)
    out = run_zoning("tapis_zoning")
    assert out.status == "succeeded", out.message
    rows = q(
        "SELECT role, object_id, group_code, zone_index, GeometryType(geom), ST_SRID(geom)"
        " FROM ref.zoning_zone ORDER BY role, object_id"
    )
    assert rows == [
        ("coverage_mask", "1:0003000", None, None, "MULTIPOLYGON", 10306),
        ("finding", "101", "10106", "R", "MULTIPOLYGON", 10306),
        ("finding", "202", "10101", "DzS", "MULTIPOLYGON", 10306),
    ]
    assert q("SELECT count(*) FROM ref.zoning_finding_current") == [(2,)]
    assert q("SELECT count(*) FROM ref.zoning_coverage_current") == [(1,)]
    assert q("SELECT count(*) FROM ref.zoning_zone_part") == [(3,)]
    assert live(q, "tapis_zoning")[0][2] == "2026-08-19"
