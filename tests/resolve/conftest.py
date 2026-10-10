"""Synthetic pilot data for the resolution tests (kadastrs_test DB, runs in CI).

Mirrors cases found in the real pilot data (2026-10-10):
- 05000041006 is only a property; its parcel 05000040014 is also the number of
  another property (property / parcel ambiguity).
- 05000010003 is a property whose own parcel is 05000010010, while parcel
  05000010003 belongs to property 05000010010 (ambiguous).
- 09000360220 and 13000102702 are both a property and that property's parcel.
- Sesavas iela 28A was earlier Prohorova iela 28A; deleted Salnas iela 22A is
  linked to Salnas iela 22; deleted Kalnciema ceļš 80 to two addresses; deleted
  Cukura iela 6A to none.
- Map-only parcel 44600040001 lies outside Daugavpils (outside_pilot).
"""

from functools import partial

import psycopg
import pytest
from fastapi.testclient import TestClient

from engine.resolve import address, places
from etl.sources import load_config, sync_registry
from tests.etl.conftest import ETL_DB, RESET

V = {"admin_boundaries": 1, "varis_addresses": 2, "cadastre_spatial": 3, "cadastre_text": 4}

# City squares in EPSG:10306 (x0, y0); 10 km each.
CITIES = {
    "Daugavpils": ("0002000", "100003011", 600000, 150000, "pilseta"),
    "Jelgava": ("0003000", "100003028", 470000, 270000, "pilseta"),
    "Jūrmala": ("0004000", "100003036", 480000, 310000, "pilseta"),
    "Rīga": ("0001000", "100003003", 500000, 300000, "pilseta"),
    "Ventspils": ("0027000", "100003100", 310000, 380000, "pilseta"),
    "Jelgavas nov.": ("0030000", "100009001", 440000, 250000, "novads"),
    "Augšdaugavas nov.": ("0040000", "100009002", 620000, 140000, "novads"),
    "Valgundes pag.": ("0030010", "100010001", 450000, 260000, "pagasts"),
}
CITY_XY = {name: (x, y) for name, (_, _, x, y, _) in CITIES.items()}

# code, status, full_text, city
ADDRESSES = [
    ("101808322", "EKS", "Tautas iela 11, Daugavpils, LV-5404", "Daugavpils"),
    ("106228183", "EKS", "Tautas iela 11A, Daugavpils, LV-5404", "Daugavpils"),
    ("101808323", "EKS", "Tautas iela 13, Daugavpils, LV-5404", "Daugavpils"),
    ("101000003", "EKS", "Lielā iela 5, Daugavpils, LV-5401", "Daugavpils"),
    ("101000008", "EKS", "Ventspils iela 70, Daugavpils, LV-5401", "Daugavpils"),
    ("101000001", "EKS", "Lielā iela 3, Jelgava, LV-3001", "Jelgava"),
    ("101000002", "EKS", "Lielā iela 5, Jelgava, LV-3001", "Jelgava"),
    ("101000004", "EKS", "Sesavas iela 28A, Jelgava, LV-3002", "Jelgava"),
    ("101000005", "EKS", "Salnas iela 22, Jelgava, LV-3008", "Jelgava"),
    ("101000006", "EKS", "Druvu iela 27, Jelgava, LV-3002", "Jelgava"),
    ("101000007", "EKS", "Druvu iela 29, Jelgava, LV-3002", "Jelgava"),
    ("101765287", "EKS", "Institūta iela 4, Jelgava, LV-3004", "Jelgava"),
    ("101000010", "EKS", "Druvu iela 31, Jelgava, LV-3002", "Jelgava"),
    ("101061534", "EKS", "Ganību iela 86, Jelgava, LV-3007", "Jelgava"),
    ("105979687", "EKS", "Ganību iela 86A, Jelgava, LV-3007", "Jelgava"),
    ("101000011", "EKS", "Druvu iela 31, Jelgava, LV-3002", "Jelgava"),
    ("102485506", "EKS", "Strēlnieku prospekts 28, Jūrmala, LV-2015", "Jūrmala"),
    ("102485599", "EKS", "Lauku iela 4, Jūrmala, LV-2015", "Jūrmala"),
    ("102400001", "EKS", "Ārijas iela 3, Jūrmala, LV-2008", "Jūrmala"),
    ("102400002", "EKS", "Marijas iela 3, Jūrmala, LV-2008", "Jūrmala"),
    ("101154013", "DEL", "Salnas iela 22A, Jelgava, LV-3008", "Jelgava"),
    ("101766801", "DEL", "Kalnciema ceļš 80, Jelgava, LV-3002", "Jelgava"),
    ("105632385", "DEL", "Cukura iela 6A, Jelgava, LV-3002", "Jelgava"),
]
# code, code_his, earlier full text
HISTORY = [
    ("101000004", None, "Prohorova iela 28A, Jelgava, LV-3002"),
    ("101000004", None, "Sesavas iela 28a, Jelgava"),
    ("101154013", "101000005", "Salnas iela 22A, Jelgava, LV-3008"),  # DEL -> EKS
    ("101000006", "101766801", "Druvu iela 27, Jelgava, LV-3002"),  # EKS -> DEL
    ("101000007", "101766801", "Druvu iela 29, Jelgava, LV-3002"),
    ("105979687", None, "Ganību iela 86, Jelgava, LV-3007"),  # 86 was split, 86A kept the text
]
# number, kind, name, [(object, object_kind)]
PROPERTIES = [
    ("05000041006", "Zemes un būvju īpašums", "Tautas iela 11", [("05000040014", "Zemes vienība")]),
    ("05000040014", "Zemes un būvju īpašums", None,
     [("05000040013", "Zemes vienība"), ("05000041006001", "Būve")]),
    ("05000010003", "Zemes un būvju īpašums", "Kandavas iela", [("05000010010", "Zemes vienība")]),
    ("05000010010", "Zemes un būvju īpašums", None, [("05000010003", "Zemes vienība")]),
    ("05000049999", "Dzīvokļa īpašums", None, [("05000041006001001", "Telpu grupa")]),
    ("09000360220", "Zemes un būvju īpašums", "Institūta iela 4",
     [("09000360220", "Zemes vienība"), ("09000360220002", "Būve"),
      ("09000360220010", "Būve"), ("09000360220012", "Būve")]),
    ("09000360299", "Būvju īpašums", None, [("09000360220011", "Būve")]),
    ("13000102702", "Zemes un būvju īpašums", None, [("13000102702", "Zemes vienība")]),
]  # fmt: skip
# code, atvk, varis, map (x, y) or None
PARCELS = [
    ("05000040014", "0002000", None, (601000, 151000)),
    ("05000040013", "0002000", "106228183", (601100, 151000)),
    ("05000010003", "0002000", None, (602000, 152000)),
    ("05000010010", "0002000", None, (602100, 152000)),
    ("09000360220", "0003000", "101765287", (471000, 271000)),
    ("13000102702", "0004000", "102485506", (481000, 311000)),
]
MAP_ONLY_PARCELS = [
    ("44600040001", "0002000", (640000, 150000)),  # outside the Daugavpils square
    ("09000030450", "0003000", (472000, 272000)),  # inside Jelgava
]
# code, atvk, name, not_exist, prereg, varis, parcels, map (x, y) or None
BUILDINGS = [
    ("05000041006001", "0002000", "Muzejs-bibliotēka", False, False, "106228183",
     ["05000040013"], (601105, 151005)),
    ("09000360220002", "0003000", "Skola", False, False, "101765287", ["09000360220"],
     (471002, 271002)),
    ("09000360220010", "0003000", "Šķūnis", True, False, None, ["09000360220"], (471004, 271004)),
    ("09000360220011", "0003000", "Garāža", False, False, None, ["09000360220"], (471006, 271006)),
    ("09000360220012", "0003000", "Nojume", False, True, None, ["09000360220"], None),
]  # fmt: skip
PARCEL_PARTS = [("090003602200001", "09000360220", (471001, 271001))]


def _sq(x, y, size=10):
    return f"ST_Multi(ST_MakeEnvelope({x}, {y}, {x + size}, {y + size}, 10306))"


def seed(conn) -> None:
    places._cache.clear()
    address._vocabulary.clear()
    conn.execute(RESET)
    sync_registry(conn, load_config())
    for source, vid in V.items():
        conn.execute(
            "INSERT INTO dataset_version (id, source_id, version_date, checksum, status)"
            " OVERRIDING SYSTEM VALUE VALUES (%s, %s, '2026-10-10', %s, 'live')",
            (vid, source, "sha256:" + f"{vid:064x}"),
        )
    for name, (atvk, varis, x, y, level) in CITIES.items():
        conn.execute(
            "INSERT INTO ref.admin_area (dataset_version_id, varis_code, level, name, atvk,"
            f" status, parts, geom) VALUES (%s, %s, %s, %s, %s, 'EKS', 1, {_sq(x, y, 10000)})",
            (V["admin_boundaries"], varis, level, name, atvk),
        )
    for code, status, text, city in ADDRESSES:
        atvk, city_code, x, y, _ = CITIES[city]
        geom = (
            f"ST_SetSRID(ST_MakePoint({x + 500}, {y + 500}), 10306)" if status == "EKS" else "NULL"
        )
        conn.execute(
            "INSERT INTO ref.address (dataset_version_id, code, status, type_code, parent_code,"
            " parent_type, city_code, city_atvk, name, full_text, geom)"
            f" VALUES (%s, %s, %s, '108', '1', '107', %s, %s, %s, %s, {geom})",
            (V["varis_addresses"], code, status, city_code, atvk, text.split(",")[0], text),
        )
    for row_no, (code, code_his, text) in enumerate(HISTORY, 1):
        conn.execute(
            "INSERT INTO ref.address_history (dataset_version_id, row_no, code, code_his,"
            " full_text) VALUES (%s, %s, %s, %s, %s)",
            (V["varis_addresses"], row_no, code, code_his, text),
        )
    t, s = V["cadastre_text"], V["cadastre_spatial"]
    for number, kind, name, objects in PROPERTIES:
        conn.execute(
            "INSERT INTO ref.property (dataset_version_id, number, file_atvk, kind, name)"
            " VALUES (%s, %s, '0000000', %s, %s)",
            (t, number, kind, name),
        )
        for obj, okind in objects:
            conn.execute(
                "INSERT INTO ref.property_object (dataset_version_id, property_number,"
                " object_code, object_kind) VALUES (%s, %s, %s, %s)",
                (t, number, obj, okind),
            )
    for code, atvk, varis, xy in PARCELS:
        conn.execute(
            "INSERT INTO ref.parcel (dataset_version_id, code, atvk, varis_code)"
            " VALUES (%s, %s, %s, %s)",
            (t, code, atvk, varis),
        )
        if xy:
            conn.execute(
                "INSERT INTO ref.kk_parcel (dataset_version_id, code, object_code, zip_atvk,"
                f" parts, geom) VALUES (%s, %s, '7201060110', %s, 1, {_sq(*xy)})",
                (s, code, atvk),
            )
    for code, atvk, xy in MAP_ONLY_PARCELS:
        conn.execute(
            "INSERT INTO ref.kk_parcel (dataset_version_id, code, object_code, zip_atvk,"
            f" parts, geom) VALUES (%s, %s, '7201060110', %s, 1, {_sq(*xy)})",
            (s, code, atvk),
        )
    for code, atvk, name, nx, prereg, varis, parcels, xy in BUILDINGS:
        conn.execute(
            "INSERT INTO ref.building (dataset_version_id, code, file_atvk, name, not_exist,"
            " prereg, varis_code) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (t, code, atvk, name, nx, prereg, varis),
        )
        for i, parcel in enumerate(parcels):
            conn.execute(
                "INSERT INTO ref.building_parcel (dataset_version_id, building_code,"
                " parcel_code, relation) VALUES (%s, %s, %s, %s)",
                (t, code, parcel, "object_relation" if i == 0 else "parcel_list"),
            )
        if xy:
            conn.execute(
                "INSERT INTO ref.kk_building (dataset_version_id, code, object_code, object_kind,"
                f" parcel_code, zip_atvk, parts, geom) VALUES (%s, %s, '5201011110', 'building',"
                f" %s, %s, 1, {_sq(*xy, size=4)})",
                (s, code, parcels[0], atvk),
            )
    for code, parcel, xy in PARCEL_PARTS:
        conn.execute(
            "INSERT INTO ref.parcel_part (dataset_version_id, code, parcel_code, file_atvk)"
            " VALUES (%s, %s, %s, '0003000')",
            (t, code, parcel),
        )
        conn.execute(
            "INSERT INTO ref.kk_parcel_part (dataset_version_id, code, object_code, parcel_code,"
            f" zip_atvk, parts, geom) VALUES (%s, %s, '7201060120', %s, '0003000', 1, {_sq(*xy)})",
            (s, code, parcel),
        )


@pytest.fixture(scope="module")
def seeded():
    try:
        with psycopg.connect(ETL_DB, connect_timeout=3) as conn:
            seed(conn)
    except psycopg.OperationalError as exc:
        pytest.fail(f"test DB not reachable at {ETL_DB}: {exc}")
    return partial(psycopg.connect, ETL_DB)


@pytest.fixture(scope="module")
def client(seeded):
    mp = pytest.MonkeyPatch()
    mp.setenv("DATABASE_URL", ETL_DB)
    from api.main import app

    with TestClient(app) as c:
        yield c
    mp.undo()
