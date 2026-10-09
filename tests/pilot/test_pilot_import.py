"""Pilot import checks (real data in the dev DB; marker `pilot`).

Run after importing twice:
    docker compose run --rm etl import all
    docker compose run --rm etl import all
    docker compose --profile test run --rm tests
These tests fail, never skip, when nothing is imported. Row counts are
recounted from the raw files of the live versions (etl_raw volume) by methods
independent of the importers.
"""

import csv
import hashlib
import os
import re
import struct
import zipfile
from pathlib import Path

import pytest

pytestmark = [pytest.mark.pilot, pytest.mark.stack]

SOURCES = ("admin_boundaries", "varis_addresses", "cadastre_spatial", "cadastre_text")
RAW = Path(os.environ.get("KADASTRS_RAW_DIR", "/data/raw"))
HINT = "import first: docker compose run --rm etl import all (twice; docs/runbook.md)"
SEEDS = ("05000041006", "13000102702", "09000360220")
PILOT_CITIES = {"0002000": "Daugavpils", "0003000": "Jelgava", "0004000": "Jūrmala"}


@pytest.fixture
def live(db_conn):
    rows = dict(
        db_conn.execute(
            "SELECT source_id, id FROM dataset_version"
            " WHERE status = 'live' AND source_id = ANY(%s)",
            (list(SOURCES),),
        ).fetchall()
    )
    missing = [s for s in SOURCES if s not in rows]
    if missing:
        pytest.fail(f"no live version for {missing}; {HINT}")
    return rows


def raw_files(db_conn, source, version_id) -> dict:
    files = db_conn.execute(
        "SELECT files FROM dataset_version WHERE id = %s", (version_id,)
    ).fetchone()[0]
    base = RAW / source / str(version_id)
    if not base.is_dir():
        pytest.fail(f"raw files of {source} v{version_id} not in {base}; {HINT}")
    return {"base": base, "files": files}


def one(db_conn, sql, *params):
    return db_conn.execute(sql, params or None).fetchone()[0]


def dbf_count(data: bytes) -> int:
    """Record count from the DBF header (independent of pyshp)."""
    return struct.unpack("<I", data[4:8])[0]


def dbf_counts(zip_path: Path, layer: str) -> int:
    with zipfile.ZipFile(zip_path) as z:
        return sum(
            dbf_count(z.read(n)) for n in z.namelist() if n.rsplit("/", 1)[-1] == f"{layer}.dbf"
        )


# --- versions and raw files -------------------------------------------------------


def test_raw_files_match_recorded_checksums(db_conn, live):
    for source, vid in live.items():
        r = raw_files(db_conn, source, vid)
        for f in r["files"]:
            entries = (
                [(f["path"], f["sha256"])]
                if f.get("sha256")
                else [(m["path"], m["sha256"]) for m in f["members"]]
            )
            for rel, sha in entries:
                data = (r["base"] / rel).read_bytes()
                assert hashlib.sha256(data).hexdigest() == sha, f"{source}/{rel}"


def test_second_run_created_no_new_versions(db_conn, live):
    """The latest import of each source was `unchanged` and pointed at the live version."""
    for source, vid in live.items():
        last = db_conn.execute(
            "SELECT status, dataset_version_id FROM import_log WHERE source_id = %s"
            " ORDER BY id DESC LIMIT 1",
            (source,),
        ).fetchone()
        assert last == ("unchanged", vid), f"{source}: last import {last}; {HINT}"


# --- row counts against the source files -----------------------------------------


def test_admin_counts(db_conn, live):
    r = raw_files(db_conn, "admin_boundaries", live["admin_boundaries"])
    expected = sum(
        dbf_counts(r["base"] / "aw_shp.zip", lyr) for lyr in ("Novadi", "Pilsetas", "Pagasti")
    )
    assert one(db_conn, "SELECT count(*) FROM ref.admin_area_current") == expected


@pytest.mark.parametrize(
    ("table", "layers"),
    [
        ("kk_parcel", ["KKParcel"]),
        ("kk_parcel_part", ["KKParcelPart"]),
        ("kk_building", ["KKBuilding", "KKEngineeringStructurePoly"]),
        ("kk_servitude", ["KKWayRestriction"]),
    ],
)
def test_cadastre_map_counts(db_conn, live, table, layers):
    vid = live["cadastre_spatial"]
    r = raw_files(db_conn, "cadastre_spatial", vid)
    records = sum(dbf_counts(r["base"] / f["path"], lyr) for f in r["files"] for lyr in layers)
    loaded_parts = one(
        db_conn,
        f"SELECT coalesce(sum(parts), 0) FROM ref.{table} WHERE dataset_version_id = %s",
        vid,
    )
    assert loaded_parts == records  # every source record ended up in a row (no empty geometries)


def test_varis_counts_by_independent_text_match(db_conn, live):
    """Pilot addresses recounted by city name at the end of STD (the §5.1 cross-check)."""
    r = raw_files(db_conn, "varis_addresses", live["varis_addresses"])
    names = tuple(PILOT_CITIES.values())
    expected = {"EKS": 0, "DEL": 0}
    codes = set()
    with open(r["base"] / "aw_eka.csv", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            std = row["STD"].rstrip()
            if row["STATUSS"] in expected and any(
                std.endswith(n) or f", {n}," in std for n in names
            ):
                expected[row["STATUSS"]] += 1
                codes.add(row["KODS"])
    got = dict(
        db_conn.execute(
            "SELECT status, count(*) FROM ref.address_current GROUP BY status"
        ).fetchall()
    )
    assert got == expected
    his = 0
    with open(r["base"] / "aw_eka_his.csv", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            his += row["KODS"] in codes or row["KODS_HIS"] in codes
    assert one(db_conn, "SELECT count(*) FROM ref.address_history_current") == his


@pytest.mark.parametrize(
    ("role", "table", "tag"),
    [
        ("parcel", "parcel", "ParcelItemData"),
        ("parcelpart", "parcel_part", "ParcelPartItemData"),
        ("building", "building", "BuildingItemData"),
        ("property", "property", "PropertyItemData"),
        ("property", "property_object", "ObjectData"),
    ],
)
def test_cadastre_text_counts(db_conn, live, role, table, tag):
    vid = live["cadastre_text"]
    r = raw_files(db_conn, "cadastre_text", vid)
    pattern = re.compile(rb"<(?:[\w.-]+:)?" + tag.encode() + rb"[\s>]")
    f = next(f for f in r["files"] if f["role"] == role)
    expected = sum(len(pattern.findall((r["base"] / m["path"]).read_bytes())) for m in f["members"])
    assert (
        one(db_conn, f"SELECT count(*) FROM ref.{table} WHERE dataset_version_id = %s", vid)
        == expected
    )


# --- geometry, keys, object kinds -----------------------------------------------


@pytest.mark.parametrize(
    "table", ["admin_area", "kk_parcel", "kk_parcel_part", "kk_building", "kk_servitude"]
)
def test_polygons_valid_multipolygon_10306(db_conn, live, table):
    bad = one(
        db_conn,
        f"SELECT count(*) FROM ref.{table} t JOIN dataset_version v ON v.id = t.dataset_version_id"
        " AND v.status = 'live' WHERE NOT ST_IsValid(geom)"
        " OR GeometryType(geom) <> 'MULTIPOLYGON' OR ST_SRID(geom) <> 10306",
    )
    assert bad == 0


def test_address_points(db_conn, live):
    bad = one(
        db_conn,
        "SELECT count(*) FROM ref.address_current WHERE status = 'EKS' AND"
        " (geom IS NULL OR GeometryType(geom) <> 'POINT' OR ST_SRID(geom) <> 10306)",
    )
    assert bad == 0


def test_addresses_lie_in_their_city(db_conn, live):
    """Catches swapped KOORD_X/KOORD_Y: every EKS point is inside (or within 50 m of) its city."""
    outside = one(
        db_conn,
        """
        SELECT count(*) FROM ref.address_current a
        JOIN ref.admin_area_current c ON c.level = 'pilseta' AND c.atvk = a.city_atvk
        WHERE a.status = 'EKS' AND NOT ST_DWithin(a.geom, c.geom, 50)""",
    )
    assert outside == 0


def test_servitude_key_unique(db_conn, live):
    n, distinct = db_conn.execute(
        "SELECT count(*), count(DISTINCT (code, parcel_code)) FROM ref.servitude_current"
    ).fetchone()
    assert n == distinct


def test_e6_object_kinds_on_real_data(db_conn, live):
    rows = dict(
        db_conn.execute(
            "SELECT object_kind || ':' || left(object_code, 1), count(*) FROM ref.kk_building"
            " WHERE dataset_version_id = %s GROUP BY 1",
            (live["cadastre_spatial"],),
        ).fetchall()
    )
    assert set(rows) == {"building:5", "engineering_structure:6"}
    for table in ("kk_parcel", "kk_parcel_part", "kk_servitude"):
        assert (
            one(
                db_conn,
                f"SELECT count(*) FROM ref.{table} WHERE dataset_version_id = %s"
                " AND left(object_code, 1) <> '7'",
                live["cadastre_spatial"],
            )
            == 0
        )


# --- seed objects ------------------------------------------------------------------


@pytest.mark.parametrize("seed", SEEDS)
def test_seed_resolves_to_parcel_with_geometry(db_conn, live, seed):
    """As a parcel designation, or as a property number through its land units."""
    parcels = db_conn.execute(
        """
        SELECT p.code, p.has_geometry FROM ref.parcel_current p
        WHERE p.code = %(s)s
           OR p.code IN (SELECT object_code FROM ref.property_object_current
                         WHERE property_number = %(s)s AND object_kind = 'Zemes vienība')
        """,
        {"s": seed},
    ).fetchall()
    assert parcels, f"{seed} resolves to no parcel"
    assert any(has_geom for _, has_geom in parcels), f"{seed}: parcels {parcels} have no geometry"
