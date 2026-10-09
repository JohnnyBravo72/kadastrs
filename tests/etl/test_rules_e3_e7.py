"""T-E3 (CSV), T-E4 (XML), T-E5 (geometry), T-E6 (OBJECTCODE), T-E7 (versions)."""

import csv
import io
import json

import pytest

from etl.spatial import normalise_into
from etl.textio import detect_encoding
from tests.etl import fakes
from tests.etl.test_import_sources import publish_all


def live(q, source):
    return q(
        "SELECT id, checksum, version_date::text FROM dataset_version"
        " WHERE source_id = %s AND status = 'live'",
        source,
    )


# --- T-E3: CSV --------------------------------------------------------------------


def test_e3_quoted_values_keep_their_quotes_and_round_trip(run, server, q):
    publish_all(server)
    raw = server.files[
        server.resources[fakes.etl_config().files["varis_addresses"]["aw_eka"]]["url"]
    ]
    assert b'"""4"""' in raw and '"""Elektriķi 2"""'.encode() in raw  # as VZD writes them
    assert run("varis_addresses").status == "succeeded"
    names = dict(q("SELECT code, name FROM ref.address"))
    assert names["101000001"] == '"4"'
    assert names["101000002"] == '"Elektriķi 2"'
    for value, written in [('"4"', '"""4"""'), ('"Elektriķi 2"', '"""Elektriķi 2"""')]:
        buf = io.StringIO()
        csv.writer(buf, lineterminator="").writerow([value])
        assert buf.getvalue() == written  # byte-exact round trip


def test_e3_bom_file_with_iso_metadata_reads_as_utf8(tmp_path, run, server, q):
    p = tmp_path / "aw_eka.csv"
    p.write_bytes(fakes.varis_files()["aw_eka.csv"])
    codec, note = detect_encoding(p, declared="ISO-8859-1")
    assert codec == "utf-8-sig" and "ISO-8859-1" in note
    publish_all(server)
    assert run("varis_addresses").status == "succeeded"
    texts = [r[0] for r in q("SELECT full_text FROM ref.address")]
    assert "Elektriķu iela 4, Jelgava, LV-3001" in texts
    assert not any("�" in t for t in texts)


def test_e3_non_utf8_file_fails_loudly(run, server, q):
    publish_all(server)
    bad = (
        fakes.varis_files()["aw_iela.csv"]
        .removeprefix(b"\xef\xbb\xbf")
        .decode("utf-8")
        .encode("cp1257")
    )
    server.publish("varis_addresses", "aw_iela", "aw_iela.csv", bad)
    out = run("varis_addresses")
    assert out.status == "failed" and "UnicodeDecodeError" in out.message
    assert live(q, "varis_addresses") == []


# --- T-E4: XML --------------------------------------------------------------------


def _building_rows(q, version):
    return q(
        "SELECT code, file_atvk, name, use_kind_name, area_m2::text, not_exist, flags"
        " FROM ref.building WHERE dataset_version_id = %s ORDER BY code",
        version,
    )


def test_e4_same_rows_with_and_without_namespace(run, server, q):
    publish_all(server)
    assert run("cadastre_text").status == "succeeded"
    v1 = live(q, "cadastre_text")[0][0]
    for role in ("parcel", "parcelpart", "building", "property"):
        server.publish(
            "cadastre_text",
            role,
            f"{role}.zip",
            fakes.text_zip(role, fakes.default_text_docs(role, namespace=False)),
        )
    assert run("cadastre_text").status == "succeeded"
    v2 = live(q, "cadastre_text")[0][0]
    assert v1 != v2
    assert _building_rows(q, v1) == _building_rows(q, v2)


def test_e4_text_fields_are_normalised(run, server, q):
    publish_all(server, building_name="Māja&#13;&#10;ar&#9;šķūni \\2 ")
    assert run("cadastre_text").status == "succeeded"
    name = q("SELECT name FROM ref.building WHERE code = '09000000001001'")[0][0]
    assert name == "Māja ar šķūni \\2"  # CR LF -> one space, tab -> space, backslash kept
    # The Excel round trip of T-E4 is tested with the exporter (Phase 5).


# --- T-E5: geometry ---------------------------------------------------------------

BOWTIE = [[0, 0], [10, 10], [10, 0], [0, 10], [0, 0]]  # self-intersecting
SPIKE = [[0, 0], [0, 10], [10, 10], [10, 0], [5, 0], [5, -5], [5, 0], [0, 0]]  # polygon + line


def _shift(ring, dx, dy):
    return [[x + dx, y + dy] for x, y in ring]


def test_e5_geometry_normalisation(run, server, q):
    publish_all(server)
    x0, y0 = 480000, 270000
    layers = {
        "KKParcel": [
            (fakes.kk_rec("09000000001", "7201060310"), [_shift(BOWTIE, x0, y0)]),
            (fakes.kk_rec("09000000002", "7201060310"), [_shift(SPIKE, x0 + 100, y0)]),
            (fakes.kk_rec("09000000003", "7201060310"), [fakes.square(x0 + 200, y0)]),
        ],
        "KKWayRestriction": [
            (
                fakes.kk_rec("09000000000900000001", "7401060310", "09000000001"),
                [fakes.square(x0, y0, 2)],
            ),
            (
                fakes.kk_rec("09000000000900000001", "7401060310", "09000000002"),
                [fakes.square(x0 + 100, y0, 2)],
            ),
        ],
    }
    other = {
        "ExportCadGroup_0900002": {
            "KKParcel": [
                (
                    fakes.kk_rec("09000000003", "7201060310", group="0900002"),
                    [fakes.square(x0 + 300, y0)],
                )
            ],  # second piece of the same CODE
            "KKWayRestriction": [
                (
                    fakes.kk_rec("09000000000900000001", "7401060310", "09000000001"),
                    [fakes.square(x0 + 3, y0, 2)],
                )
            ],
        }
    }
    server.publish(
        "cadastre_spatial",
        "0003000",
        "0003000_kk_shp.zip",
        fakes.kk_zip(layers, extra_folders=other),
    )
    out = run("cadastre_spatial")
    assert out.status == "succeeded", out.message
    rows = q(
        "SELECT code, parts, ST_NumGeometries(geom), ST_Area(geom), GeometryType(geom),"
        " ST_IsValid(geom) FROM ref.kk_parcel ORDER BY code"
    )
    expected = {
        "09000000001": (1, 2, 50.0),
        "09000000002": (1, 1, 100.0),
        "09000000003": (2, 2, 200.0),
    }
    for code, parts, ngeom, area, gtype, valid in rows:
        exp_parts, exp_n, exp_area = expected[code]
        assert (parts, ngeom, gtype, valid) == (exp_parts, exp_n, "MULTIPOLYGON", True), code
        assert abs(area - exp_area) / exp_area < 0.0001, (code, area)
    assert out.row_counts["kk_parcel"]["invalid_repaired"] == 2
    # Servitudes: key CODE + PARCELCODE; the two pieces on parcel …001 are merged.
    serv = q("SELECT code, parcel_code, parts FROM ref.kk_servitude ORDER BY parcel_code")
    assert serv == [
        ("09000000000900000001", "09000000001", 2),
        ("09000000000900000001", "09000000002", 1),
    ]


def test_e5_lks92_source_is_transformed_with_the_grid(etl_db):
    """A 3059 source goes through lks92_to_lks2020() (EPSG:10838 grid), nothing else."""
    from tests.test_crs import ODUKALNS_3059, ODUKALNS_10306

    x, y = ODUKALNS_3059
    ring = [[x - 1, y - 1], [x - 1, y + 1], [x + 1, y + 1], [x + 1, y - 1], [x - 1, y - 1]]
    with etl_db() as c, c.transaction(force_rollback=True):
        c.execute(
            "INSERT INTO source (id, name_lv, name_en, owner, source_group, display_order,"
            " type, subject_kinds, default_selected, max_age, datagov_dataset_ids, config)"
            " VALUES ('t3059', 't', 't', 't', 't', 1, 'check', '{object}', true, '1 day',"
            " '{x}', '{}')"
        )
        vid = c.execute(
            "INSERT INTO dataset_version (source_id, version_date, checksum)"
            " VALUES ('t3059', '2026-01-01', 'sha256:' || repeat('0', 64))"
            " RETURNING id"
        ).fetchone()[0]
        c.execute("CREATE TEMP TABLE st (code text, object_code text, flags text, geojson text)")
        c.execute(
            "INSERT INTO st VALUES ('09000000001', '7', NULL, %s)",
            (json.dumps({"type": "Polygon", "coordinates": [ring]}),),
        )
        normalise_into(
            c,
            stage="st",
            target="ref.kk_parcel",
            version_id=vid,
            keys=["code"],
            aggregates={
                "object_code": "min(object_code)",
                "zip_atvk": "'x'",
                "flags": "'{}'::text[]",
            },
            source_srid=3059,
        )
        d = c.execute(
            "SELECT ST_Distance(ST_Centroid(geom), ST_SetSRID(ST_MakePoint(%s, %s), 10306))"
            " FROM ref.kk_parcel WHERE dataset_version_id = %s",
            (*ODUKALNS_10306, vid),
        ).fetchone()[0]
    assert d < 0.01  # with the grid; a plain reprojection would be ~9.5 cm off


# --- T-E6: OBJECTCODE -------------------------------------------------------------


@pytest.mark.parametrize(
    ("layer", "objectcode"),
    [("KKParcel", "9201060310"), ("KKParcel", "5201060310"), ("KKBuilding", "7201011110")],
)
def test_e6_wrong_objectcode_fails_loudly(run, server, q, layer, objectcode):
    publish_all(server)
    assert run("cadastre_spatial").status == "succeeded"
    before = live(q, "cadastre_spatial")
    pc = "09000000001" if layer != "KKParcel" else None
    server.publish(
        "cadastre_spatial",
        "0003000",
        "0003000_kk_shp.zip",
        fakes.kk_zip(
            {
                layer: [
                    (
                        fakes.kk_rec(
                            "09000000001001" if layer == "KKBuilding" else "09000000001",
                            objectcode,
                            pc,
                        ),
                        [fakes.square(480000, 270000)],
                    )
                ]
            }
        ),
    )
    out = run("cadastre_spatial")
    assert out.status == "failed" and "E6" in out.message
    assert live(q, "cadastre_spatial") == before  # the last good version stays live


# --- T-E7: versions ----------------------------------------------------------------


def test_e7_same_data_same_version_with_source_date(run, server, q):
    publish_all(server)
    first = run("admin_boundaries")
    second = run("admin_boundaries")  # a later run date, same file
    assert (first.status, second.status) == ("succeeded", "unchanged")
    assert q("SELECT count(*) FROM dataset_version") == [(1,)]
    assert live(q, "admin_boundaries")[0][2] == "2026-01-15"  # CKAN last_modified, not the run date


def test_e7_changed_file_new_version_and_revert_reactivates(run, server, q):
    publish_all(server)
    v1 = run("admin_boundaries").version_id
    server.publish(
        "admin_boundaries",
        "aw_shp",
        "aw_shp.zip",
        fakes.admin_zip(novads_name="Cits"),
        last_modified="2026-02-01T08:00:00",
    )
    v2 = run("admin_boundaries").version_id
    assert v2 != v1
    assert dict(q("SELECT id, status FROM dataset_version")) == {v1: "superseded", v2: "live"}
    assert live(q, "admin_boundaries")[0][2] == "2026-02-01"
    server.publish("admin_boundaries", "aw_shp", "aw_shp.zip", fakes.admin_zip())
    out = run("admin_boundaries")
    assert out.version_id == v1 and out.status == "succeeded"
    assert dict(q("SELECT id, status FROM dataset_version")) == {v1: "live", v2: "superseded"}


def test_e7_import_log_rows(run, server, q):
    publish_all(server)
    run("admin_boundaries")
    run("admin_boundaries")
    rows = q(
        "SELECT status, dataset_version_id IS NOT NULL, checksum IS NOT NULL, licence,"
        " finished_at IS NOT NULL FROM import_log ORDER BY id"
    )
    assert rows == [
        ("succeeded", True, True, "CC-BY-4.0", True),
        ("unchanged", True, True, "CC-BY-4.0", True),
    ]
