"""Shared constants and helpers for the pilot tests (fixture `live`: conftest.py)."""

import os
import struct
import zipfile
from pathlib import Path

import pytest

SOURCES = (
    "admin_boundaries",
    "varis_addresses",
    "cadastre_spatial",
    "cadastre_text",
    "flood_10y",
    "nature_protected_areas",
    "nature_microreserves",
    "nature_monuments",
    "nature_habitats",
    "atis_classifier",
    "cadastre_encumbrances",
    "encumbrances_frozen",
    "bis_cases",
    "ur_companies",
    "ur_insolvency",
    "ur_sanctions",
    "fid_sanctions",
)
RAW = Path(os.environ.get("KADASTRS_RAW_DIR", "/data/raw"))
HINT = "import first: docker compose run --rm etl import all (twice; docs/runbook.md)"
SEEDS = ("05000041006", "13000102702", "09000360220")
PILOT_CITIES = {"0002000": "Daugavpils", "0003000": "Jelgava", "0004000": "Jūrmala"}


def live_versions(db_conn):
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
