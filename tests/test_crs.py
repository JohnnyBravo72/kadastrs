"""CRS tests (PLAN.md Phase 1, decision D9).

Fails if the grid is missing, PROJ < 9.8, SRID 10306 is unknown, or the EPSG
sample point Odukalns does not transform LKS-92 -> LKS-2020 within 1 cm, on both
the geographic path and the projected path that imports use (EPSG:3059 ->
EPSG:10306). The `db-nogrid` service (same image, grid deleted) proves the 1 cm
checks really depend on the grid.
"""

import hashlib
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[1]

GRID_NAME = "lv_lgia_lks92to2020.tif"
GRID_SHA256 = "6be363d4796bb3038e751da00e2344593edbb149ed193fc31b9c200688b31498"
GRID_SIZE = 20235

TOLERANCE_M = 0.01  # 1 cm

# EPSG sample point for EPSG:10838, Odukalns (lon, lat).
ODUKALNS_LKS92 = (24.2727688, 56.8283960)  # EPSG:4661
ODUKALNS_LKS2020 = (24.2727679, 56.8283967)  # EPSG:10305

# The same point projected to Latvia TM, without any datum change (pure map
# projection, sub-mm exact). Derived with PROJ 9.8.1; re-derived in
# test_projected_sample_is_derived_from_epsg_sample.
ODUKALNS_3059 = (516646.2934, 298317.1952)  # LKS-92 / Latvia TM
ODUKALNS_10306 = (516646.2382, 298317.2729)  # LKS-2020 / Latvia TM (expected)

pytestmark = pytest.mark.stack


def _point(xy: tuple[float, float], srid: int) -> str:
    return f"ST_SetSRID(ST_MakePoint({xy[0]}, {xy[1]}), {srid})"


def _distance_to_expected_m(conn, geom_sql: str) -> float:
    """Distance in metres between a 10306 geometry and the expected 10306 point."""
    sql = f"SELECT ST_Distance(({geom_sql}), {_point(ODUKALNS_10306, 10306)})"
    return conn.execute(sql).fetchone()[0]


def _migration_up_sql(name: str) -> str:
    text = (ROOT / "infra" / "migrations" / name).read_text(encoding="utf-8")
    return text.split("-- migrate:up", 1)[1].split("-- migrate:down", 1)[0]


GEOGRAPHIC_PATH = f"ST_Transform(ST_Transform({_point(ODUKALNS_LKS92, 4661)}, 10305), 10306)"
PROJECTED_PATH = f"ST_Transform({_point(ODUKALNS_3059, 3059)}, 10306)"
IMPORT_FUNCTION_PATH = f"lks92_to_lks2020({_point(ODUKALNS_3059, 3059)})"


# --- grid file ---------------------------------------------------------------


def test_committed_grid_matches_pin():
    data = (ROOT / "infra" / "db" / GRID_NAME).read_bytes()
    assert len(data) == GRID_SIZE
    assert hashlib.sha256(data).hexdigest() == GRID_SHA256


def test_grid_present_in_db_image(db_conn):
    path = f"/usr/share/proj/{GRID_NAME}"
    size, sha = db_conn.execute(
        "SELECT (pg_stat_file(%s, true)).size, encode(sha256(pg_read_binary_file(%s)), 'hex')",
        (path, path),
    ).fetchone()
    assert size == GRID_SIZE, f"{path} missing or wrong size in the DB image"
    assert sha == GRID_SHA256


def test_dockerfile_pins_same_checksum():
    dockerfile = (ROOT / "infra" / "db" / "Dockerfile").read_text(encoding="utf-8")
    assert f"LKS_GRID_SHA256={GRID_SHA256}" in dockerfile


# --- PROJ and SRIDs ----------------------------------------------------------


def test_proj_at_least_9_8(db_conn):
    proj = db_conn.execute("SELECT split_part(postgis_proj_version(), ' ', 1)").fetchone()[0]
    major, minor = (int(p) for p in proj.split(".")[:2])
    assert (major, minor) >= (9, 8), f"PROJ {proj} < 9.8 does not know EPSG:10306 / 10838"


@pytest.mark.parametrize("srid", [3059, 4661, 10305, 10306])
def test_srid_known(db_conn, srid):
    row = db_conn.execute(
        "SELECT auth_name, auth_srid FROM spatial_ref_sys WHERE srid = %s", (srid,)
    ).fetchone()
    assert row == ("EPSG", srid)


# --- the Odukalns sample, with the grid ---------------------------------------


def test_projected_sample_is_derived_from_epsg_sample(db_conn):
    """The hard-coded projected coordinates are the EPSG sample, projected."""
    src = db_conn.execute(
        f"SELECT ST_Distance(ST_Transform({_point(ODUKALNS_LKS92, 4661)}, 3059),"
        f" {_point(ODUKALNS_3059, 3059)})"
    ).fetchone()[0]
    exp = db_conn.execute(
        f"SELECT ST_Distance(ST_Transform({_point(ODUKALNS_LKS2020, 10305)}, 10306),"
        f" {_point(ODUKALNS_10306, 10306)})"
    ).fetchone()[0]
    assert src < 0.001
    assert exp < 0.001


@pytest.mark.parametrize(
    "path_sql",
    [GEOGRAPHIC_PATH, PROJECTED_PATH, IMPORT_FUNCTION_PATH],
    ids=["geographic 4661->10305", "projected 3059->10306", "lks92_to_lks2020()"],
)
def test_odukalns_within_1cm(db_conn, path_sql):
    error = _distance_to_expected_m(db_conn, path_sql)
    assert error < TOLERANCE_M, f"off by {error * 100:.2f} cm (grid missing?)"


def test_import_function_rejects_other_srid(db_conn):
    with pytest.raises(psycopg.errors.RaiseException, match="expects SRID 3059"):
        db_conn.execute(f"SELECT lks92_to_lks2020({_point(ODUKALNS_LKS92, 4661)})")


# --- the same checks without the grid must fail -------------------------------


@pytest.fixture
def nogrid(nogrid_conn):
    """db-nogrid with the CRS migration applied, rolled back afterwards."""
    path = f"/usr/share/proj/{GRID_NAME}"
    size = nogrid_conn.execute("SELECT (pg_stat_file(%s, true)).size", (path,)).fetchone()[0]
    assert size is None, "db-nogrid still has the grid file"
    with nogrid_conn.transaction(force_rollback=True):
        nogrid_conn.execute(_migration_up_sql("20261009120000_extensions_and_crs.sql"))
        nogrid_conn.execute(_migration_up_sql("20261010080000_lks_transform_outside_grid.sql"))
        yield nogrid_conn


@pytest.mark.parametrize(
    "path_sql",
    [GEOGRAPHIC_PATH, PROJECTED_PATH],
    ids=["geographic 4661->10305", "projected 3059->10306"],
)
def test_without_grid_st_transform_misses_1cm(nogrid, path_sql):
    # PROJ silently falls back to a null shift: no error, ~9.5 cm off.
    error = _distance_to_expected_m(nogrid, path_sql)
    assert error > TOLERANCE_M, f"only {error * 100:.2f} cm off without the grid"


def test_without_grid_import_function_raises(nogrid):
    with pytest.raises(psycopg.errors.InternalError), nogrid.transaction():
        nogrid.execute(f"SELECT {IMPORT_FUNCTION_PATH}")


# --- lks92_to_lks2020_checked: zero shift outside the LĢIA grid, never without it ------

OFFSHORE_3059 = (200000.0, 300000.0)  # Baltic Sea west of Latvia, outside the grid


def test_checked_transform_equals_strict_inside_the_grid(db_conn):
    d, outside = db_conn.execute(
        f"SELECT ST_Distance((t).geom, {IMPORT_FUNCTION_PATH}), (t).outside_grid"
        f" FROM (SELECT lks92_to_lks2020_checked({_point(ODUKALNS_3059, 3059)}) t) s"
    ).fetchone()
    assert d == 0 and outside is False


def test_checked_transform_zero_shift_outside_the_grid(db_conn):
    with pytest.raises(psycopg.errors.InternalError, match="outside grid"), db_conn.transaction():
        db_conn.execute(f"SELECT lks92_to_lks2020({_point(OFFSHORE_3059, 3059)})")
    x, y, outside = db_conn.execute(
        f"SELECT ST_X((t).geom), ST_Y((t).geom), (t).outside_grid"
        f" FROM (SELECT lks92_to_lks2020_checked({_point(OFFSHORE_3059, 3059)}) t) s"
    ).fetchone()
    assert (round(x, 6), round(y, 6), outside) == (*OFFSHORE_3059, True)


def test_without_grid_checked_transform_raises(nogrid):
    with pytest.raises(psycopg.errors.InternalError), nogrid.transaction():
        nogrid.execute(f"SELECT lks92_to_lks2020_checked({_point(ODUKALNS_3059, 3059)})")
