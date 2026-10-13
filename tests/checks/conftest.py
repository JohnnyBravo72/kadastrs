"""Synthetic data for the check engine tests (kadastrs_test DB, runs in CI).

Builds on the resolution seed (tests/resolve/conftest.py: cities, VARIS,
properties, parcels and buildings) and adds, in EPSG:10306:

Flood (Jelgava; coverage mask = 472000..476000 x 272000..276000):
  09000050400  10x10 m inside finding A                -> found, share 1.0
  09000010048  10x10 m in the mask, far from findings  -> clear
  05000010069  Daugavpils, no mask                     -> not_covered
  09000050401  half inside the mask's east edge        -> clear + partial_coverage
  09000050402  overlaps finding A by a 0.3 m strip     -> clear (inward buffer)
  09000050403  100x100 m with a 0.9x0.9 m finding      -> clear (0.81 m2, 0.008 %)
  09000050404  100x100 m with a 1.2x1.2 m finding      -> found (1.44 m2 >= 1 m2)
  09000360220  outside the mask                        -> not_covered
Nature: 13000102702 half in a microreserve (+ a 0.3 m habitat sliver, dropped);
  09000360220 inside dabas parks (DP) and its dabas lieguma zone (DLZ): two lines,
  the zone decides the area's level.
BIS: case A twice (duplicate rows) on building 09000360220002; case B by the
  address code 101765287; case C a point 5 m from 13000102702 (nearby); case D
  a building 09000360220099 missing from the cadastre (probable parcel).
Encumbrances: 09000360220 and its part have current ones; 09000050400 has only a
  technical one (8317010100, not a finding in rules v2); 13000102702 has only a
  frozen-only one; 09000360220 has one frozen row that is also current and one
  frozen-only (code 7399000000) next to its current ones.
Geometry: building 09000360220012 has none (its parcel has: parcel level);
  parcel 05000040099 and its building 05000040099001 have none (no_data).
Address: 09000050405 has VARIS 101000005, the successor of deleted 101154013.
Applicant (Phase 8a, synthetic; no person data): see APPLICANTS and seed_applicants.
  09000050406 (Druvu iela 27, VARIS 101000006) with house 09000050406001 (use 1110,
  180 m2): 12 active companies + 1 liquidated at its address -> module 14 medium;
  2 active at Institūta iela 4 (101765287, 09000360220 and its school) -> low.
Zoning (TAPIS; same Jelgava mask box as flood):
  09000050400  industrial group 10106 on finding A box -> found, risk medium
  09000010048  in the mask, no zone                     -> clear
  05000010069 / 09000360220 outside the mask           -> not_covered
  09000050401  half inside the mask                    -> clear + partial_coverage
"""

from functools import partial

import psycopg
import pytest
from fastapi.testclient import TestClient

from tests.etl.conftest import ETL_DB, etl_db  # noqa: F401  (fixture)
from tests.resolve.conftest import V as RESOLVE_V
from tests.resolve.conftest import seed

V = RESOLVE_V | {
    "flood_10y": 5,
    "nature_protected_areas": 6,
    "nature_microreserves": 7,
    "nature_habitats": 8,
    "nature_monuments": 9,
    "bis_cases": 10,
    "cadastre_encumbrances": 11,
    "encumbrances_frozen": 12,
    "atis_classifier": 13,
    "ur_companies": 14,
    "ur_insolvency": 15,
    "ur_sanctions": 16,
    "fid_sanctions": 17,
    "tapis_zoning": 18,
}
CHECK_SOURCES = [s for s in V if s not in RESOLVE_V]


def env(x0, y0, x1, y1) -> str:
    return f"ST_Multi(ST_MakeEnvelope({x0}, {y0}, {x1}, {y1}, 10306))"


# code, atvk, varis, (x0, y0, x1, y1) or None
PARCELS = [
    ("09000050400", "0003000", None, (473000, 273000, 473010, 273010)),
    ("09000010048", "0003000", None, (474000, 273000, 474010, 273010)),
    ("05000010069", "0002000", None, (603000, 153000, 603010, 153010)),
    ("09000050401", "0003000", None, (475995, 273000, 476005, 273010)),
    ("09000050402", "0003000", None, (473049.7, 273000, 473059.7, 273010)),
    ("09000050403", "0003000", None, (474100, 274000, 474200, 274100)),
    ("09000050404", "0003000", None, (474300, 274000, 474400, 274100)),
    ("09000050405", "0003000", "101000005", (477000, 277000, 477010, 277010)),
    ("05000040099", "0002000", None, None),
    ("09000050406", "0003000", "101000006", (478000, 278000, 478020, 278020)),
]
BUILDINGS = [("05000040099001", "0002000", "05000040099")]

FLOOD = [  # layer, role, object_id, envelope
    (0, "finding", "A", (472950, 272950, 473050, 273050)),
    (0, "finding", "B", (474150, 274050, 474150.9, 274050.9)),
    (0, "finding", "C", (474350, 274050, 474351.2, 274051.2)),
    (3, "coverage_mask", "M", (472000, 272000, 476000, 276000)),
]
NATURE = [  # version source, global_id, kind, name, envelope
    (
        "nature_microreserves",
        "mr-1",
        "microreserve",
        "Mikroliegums 1",
        (481005, 310990, 481100, 311100),
    ),
    ("nature_habitats", "hab-1", "habitat", "Biotops 1", (480990, 311000, 481000.3, 311010)),
    (
        "nature_protected_areas",
        "pa-1",
        "protected_area",
        "Dabas parks",
        (470500, 270500, 471500, 271500),
    ),
    (
        "nature_protected_areas",
        "pz-1",
        "protected_area_zone",
        "DLZ",  # zone type in NAME; its area in SITE_NAME (set below)
        (470500, 270500, 471500, 271500),
    ),
]
# row_no, case, building_code, address_code, point (x, y) in EPSG:10306 or None
BIS = [
    (1, "BIS-A", "09000360220002", None, None),
    (2, "BIS-A", "09000360220002", None, None),
    (3, "BIS-B", None, "101765287", None),
    (4, "BIS-C", None, None, (481015, 311005)),
    (5, "BIS-D", "09000360220099", None, None),
]
CASES = ["BIS-A", "BIS-B", "BIS-C", "BIS-D"]


def _version(conn, source: str, vid: int, date: str = "2026-10-10", status: str = "live"):
    conn.execute(
        "INSERT INTO dataset_version (id, source_id, version_date, checksum, status)"
        " OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s, %s, %s)",
        (vid, source, date, "sha256:" + f"{vid:064x}", status),
    )


def add_flood(conn, vid: int, rows=FLOOD) -> None:
    for layer, role, oid, box in rows:
        name = "Pavasara_palu_010_3_cikls" if role == "finding" else "Pavasara_palu_200_3_cikls"
        conn.execute(
            "INSERT INTO ref.flood_zone (dataset_version_id, layer, role, layer_name, object_id,"
            f" parts, geom) VALUES (%s, %s, %s, %s, %s, 1, {env(*box)})",
            (vid, layer, role, name, oid),
        )
        conn.execute(
            "INSERT INTO ref.flood_zone_part (dataset_version_id, layer, role, object_id, part_no,"
            f" geom) VALUES (%s, %s, %s, %s, 1, ST_GeometryN({env(*box)}, 1))",
            (vid, layer, role, oid),
        )


def seed_checks(conn) -> None:
    seed(conn)
    t, s = V["cadastre_text"], V["cadastre_spatial"]
    for source in CHECK_SOURCES:
        _version(conn, source, V[source])
    for code, atvk, varis, box in PARCELS:
        conn.execute(
            "INSERT INTO ref.parcel (dataset_version_id, code, atvk, varis_code, area_m2)"
            " VALUES (%s, %s, %s, %s, %s)",
            (t, code, atvk, varis, (box[2] - box[0]) * (box[3] - box[1]) if box else 500),
        )
        if box:
            conn.execute(
                "INSERT INTO ref.kk_parcel (dataset_version_id, code, object_code, zip_atvk,"
                f" parts, geom) VALUES (%s, %s, '7201060110', %s, 1, {env(*box)})",
                (s, code, atvk),
            )
    for code, atvk, parcel in BUILDINGS:
        conn.execute(
            "INSERT INTO ref.building (dataset_version_id, code, file_atvk, name, not_exist,"
            " prereg) VALUES (%s, %s, %s, 'Šķūnis', false, false)",
            (t, code, atvk),
        )
        conn.execute(
            "INSERT INTO ref.building_parcel VALUES (%s, %s, %s, 'object_relation')",
            (t, code, parcel),
        )
    add_flood(conn, V["flood_10y"])
    for source, gid, kind, name, box in NATURE:
        conn.execute(
            "INSERT INTO ref.nature_area (dataset_version_id, global_id, kind, source_layer, name,"
            f" parts, geom) VALUES (%s, %s, %s, 'test', %s, 1, {env(*box)})",
            (V[source], gid, kind, name),
        )
    conn.execute(
        "UPDATE ref.nature_area SET category = 'DP' WHERE global_id = 'pa-1';"
        ' UPDATE ref.nature_area SET attributes = \'{"SITE_NAME": "Dabas parks"}\''
        " WHERE global_id = 'pz-1'"
    )
    b = V["bis_cases"]
    for case in CASES:
        conn.execute(
            "INSERT INTO ref.bis_case (dataset_version_id, case_number, object_name, stage,"
            " construction_kind, created_date) VALUES (%s, %s, %s, 'Būvdarbi', 'Jaunbūve',"
            " '2026-01-15')",
            (b, case, f"Objekts {case}"),
        )
    for row_no, case, building, address, point in BIS:
        lonlat = (
            "ST_X(ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 10306), 4326)),"
            " ST_Y(ST_Transform(ST_SetSRID(ST_MakePoint(%s, %s), 10306), 4326))"
            if point
            else "NULL::float8, NULL::float8"
        )
        conn.execute(
            "INSERT INTO ref.bis_object (dataset_version_id, row_no, case_number, designation,"
            " building_code, address_code, atvk, in_scope_by, lon, lat)"
            f" SELECT %s, %s, %s, %s, %s, %s, '0003000', '{{atvk}}', {lonlat}",
            (b, row_no, case, building, building, address, *((point * 2) if point else ())),
        )
    e = V["cadastre_encumbrances"]
    for row_no, obj, otype, code, name in [
        (1, "09000360220", "PARCEL", "7312030100", "aizsargjosla gar ielu"),
        (2, "090003602200001", "PARCEL PART", "7312050500", "aizsargjosla ap apakšstaciju"),
        # technical (rules v2 not_findings): an assessment area for the cadastral value
        (3, "09000050400", "PARCEL", "8317010100", "kadastrālās vērtības aprēķinam"),
    ]:
        conn.execute(
            "INSERT INTO ref.encumbrance (dataset_version_id, row_no, object_code, object_type,"
            " file_atvk, kind_id, kind_name, establish_date, area, measure)"
            " VALUES (%s, %s, %s, %s, '0003000', %s, %s, '2025-02-01', 0.0022, 'ha')",
            (e, row_no, obj, otype, code, name),
        )
    conn.execute(
        "INSERT INTO ref.atis_classifier (dataset_version_id, code, data_kind, description)"
        " VALUES (%s, '7312030100', 'ATIS', 'Ceļa aizsargjosla (klasifikators)')",
        (V["atis_classifier"],),
    )
    for row_no, obj, code in [
        (1, "13000102702", "7311010000"),
        (2, "09000360220", "7312030100"),
        (3, "09000360220", "7399000000"),
    ]:
        conn.execute(
            "INSERT INTO ref.encumbrance_frozen (dataset_version_id, file_role, row_no,"
            " object_code, object_kind, code, description, establish_date, frozen_as_of, flags)"
            " VALUES (%s, 'zemgale_parcel', %s, %s, 'parcel', %s, 'vecs apgrūtinājums',"
            " '2010-01-01', '2025-01-31', '{frozen}')",
            (V["encumbrances_frozen"], row_no, obj, code),
        )
    seed_applicants(conn)
    seed_zoning(conn)


def seed_zoning(conn) -> None:
    """Synthetic TAPIS zones (module 8): industrial zone on 09000050400; coverage
    mask over the Jelgava flood mask box; Daugavpils parcel left outside the mask."""
    z = V["tapis_zoning"]
    # finding: covers flood parcel 09000050400 (473000..473010 × 273000..273010)
    box = env(472950, 272950, 473050, 273050)
    conn.execute(
        "INSERT INTO ref.zoning_zone (dataset_version_id, role, object_id, group_code,"
        " group_name, zone_code, zone_index, atvk, dok_id, dok_name, parts, geom)"
        " VALUES (%s, 'finding', 'z-1', '10106', 'Rūpnieciskās apbūves teritorija',"
        f" '1010600', 'R', '0003000', '1', 'Jelgavas TP', 1, {box})",
        (z,),
    )
    # coverage mask ≈ Jelgava flood mask
    conn.execute(
        "INSERT INTO ref.zoning_zone (dataset_version_id, role, object_id, atvk, dok_id,"
        " dok_name, parts, geom) VALUES (%s, 'coverage_mask', '1:0003000', '0003000', '1',"
        f" 'Jelgavas TP', 1, {env(472000, 272000, 476000, 276000)})",
        (z,),
    )
    conn.execute(
        "INSERT INTO ref.zoning_zone_part (dataset_version_id, role, object_id, part_no, geom)"
        " SELECT dataset_version_id, role, object_id, 1, (ST_Dump(geom)).geom"
        " FROM ref.zoning_zone WHERE dataset_version_id = %s",
        (z,),
    )


# reg_no -> what it tests (Phase 8a modules 9 and 17)
APPLICANTS = {
    "40003100001": "active, registered 2010",
    "40003100002": "liquidated (L)",
    "40003100003": "active, registered 30 days ago",
    "40003100004": "open insolvency",
    "40003100005": "UR sanctions LEGAL_ENTITY reg. no.",
    "40003100006": "FID frozen-asset subject",
    "40003100007": "linked to a sanctioned foreign entity",
    "40003100008": "name equals a foreign entity on the list (name only)",
    "40003100009": "individual merchant (no name stored)",
}
NOT_IN_UR = "40009999999"
MASS_ADDRESS = "101000006"  # Druvu iela 27: 12 active companies in a 180 m2 house


def seed_applicants(conn) -> None:
    """Synthetic applicant data (legal entities only; IK without a name, D10)."""
    t = V["cadastre_text"]
    conn.execute(
        "INSERT INTO ref.building (dataset_version_id, code, file_atvk, name, use_kind_id,"
        " use_kind_name, area_m2, varis_code, not_exist, prereg)"
        " VALUES (%s, '09000050406001', '0003000', 'Dzīvojamā māja', '1110',"
        " 'Viena dzīvokļa mājas', 180, %s, false, false)",
        (t, MASS_ADDRESS),
    )
    conn.execute(
        "INSERT INTO ref.building_parcel VALUES (%s, '09000050406001', '09000050406',"
        " 'object_relation')",
        (t,),
    )
    c = V["ur_companies"]
    rows = [
        ("40003100001", 'SIA "Alfa"', "SIA", "2010-01-01", None, None, MASS_ADDRESS),
        ("40003100002", 'SIA "Beta"', "SIA", "2005-01-01", "2020-01-01", "L", "101765287"),
        ("40003100003", 'SIA "Gamma"', "SIA", None, None, None, MASS_ADDRESS),
        ("40003100004", 'SIA "Delta"', "SIA", "2012-01-01", None, None, MASS_ADDRESS),
        ("40003100005", 'SIA "Epsilon"', "SIA", "2011-01-01", None, None, MASS_ADDRESS),
        ("40003100006", 'SIA "Zeta"', "SIA", "2013-01-01", None, None, MASS_ADDRESS),
        ("40003100007", 'SIA "Eta"', "SIA", "2014-01-01", None, None, MASS_ADDRESS),
        ("40003100008", "SIA Omega", "SIA", "2015-01-01", None, None, "101765287"),
        ("40003100009", None, "IK", "2016-01-01", None, None, "101765287"),
    ]
    rows += [
        (f"4000320{n:04d}", f'SIA "Masa {n}"', "SIA", "2020-01-01", None, None, MASS_ADDRESS)
        for n in range(1, 7)
    ]
    for reg, name, form, registered, terminated, closed, varis in rows:
        conn.execute(
            "INSERT INTO ref.ur_company (dataset_version_id, reg_no, name, form, form_text,"
            " registered, terminated, closed, address, varis_code)"
            " VALUES (%s, %s, %s, %s, %s, coalesce(%s::date, current_date - 30), %s, %s,"
            " 'Druvu iela 27, Jelgava', %s)",
            (c, reg, name, form, "Sabiedrība ar ierobežotu atbildību" if form == "SIA"
             else "Individuālais komersants", registered, terminated, closed, varis),
        )  # fmt: skip
    conn.execute(
        "INSERT INTO ref.ur_insolvency (dataset_version_id, proceeding_id, reg_no, started_on,"
        " ended_on, form, type) VALUES (%s, '1', '40003100004', '2026-01-10', NULL,"
        " 'INSOLVENCY', 'NATIONAL'), (%s, '2', '40003100001', '2015-01-01', '2016-01-01',"
        " 'LEGAL_PROTECTION', 'NATIONAL')",
        (V["ur_insolvency"], V["ur_insolvency"]),
    )
    s = V["ur_sanctions"]
    conn.execute(
        "INSERT INTO ref.ur_sanction (dataset_version_id, entry_id, entity_type, reg_no,"
        " entity_name, entity_country, list, list_text, program, entry_date, legal_base)"
        " VALUES (%s, '1', 'LEGAL_ENTITY', '40003100005', 'SIA \"Epsilon\"', 'LV',"
        " 'ES_SANCTIONS', 'ES sankciju saraksts', 'UKR', '2022-04-01', '269/2014')",
        (s,),
    )
    conn.execute(
        "INSERT INTO ref.ur_sanction (dataset_version_id, entry_id, entity_type, foreign_reg_no,"
        " entity_name, entity_country, position_text_lv, subject_reg_no, subject_name, list,"
        " program, entry_date) VALUES (%s, '2', 'FOREIGN_ENTITY', '1027700000', 'OOO Theta',"
        " 'RU', 'Dalībnieks', '40003100007', 'SIA \"Eta\"', 'SDN_OFAC_SANCTIONS',"
        " 'RUSSIA-EO14024', '2023-05-01'),"
        " (%s, '3', 'FOREIGN_ENTITY', NULL, 'SIA OMEGA', 'RU', NULL, NULL, NULL, 'ES_SANCTIONS',"
        " 'UKR', '2022-02-28')",
        (s, s),
    )
    conn.execute(
        "INSERT INTO ref.fid_sanction (dataset_version_id, row_no, reg_no, entity_name, country,"
        " asset_kind, basis, sanctions_from, legal_act) VALUES (%s, 1, '40003100006',"
        " 'SIA \"Zeta\"', 'Latvija', 'Kapitāldaļas', 'Sankciju sarakstā iekļautas personas"
        " kontrole', '21.07.2022.', '269/2014')",
        (V["fid_sanctions"],),
    )


@pytest.fixture(scope="module")
def engine_db():
    """Connection factory for the seeded kadastrs_test DB (autocommit)."""
    try:
        with psycopg.connect(ETL_DB, connect_timeout=3) as conn:
            seed_checks(conn)
    except psycopg.OperationalError as exc:
        pytest.fail(f"test DB not reachable at {ETL_DB}: {exc}")
    return partial(psycopg.connect, ETL_DB, autocommit=True)


@pytest.fixture
def conn(engine_db):
    with engine_db() as c:
        yield c


@pytest.fixture(scope="module")
def client(engine_db):
    mp = pytest.MonkeyPatch()
    mp.setenv("DATABASE_URL", ETL_DB)
    from api.main import app

    with TestClient(app) as c:
        yield c
    mp.undo()


def all_current(*_a, **_k):
    """Every source answers "nothing newer than what you have" (no dates)."""
    from etl import freshness

    return {s.id: freshness.Remote(True) for s in freshness.load_config().sources}


@pytest.fixture(scope="package", autouse=True)
def no_network_freshness():
    """Runs look at data.gov.lv for each source's latest release (etl/freshness.py).
    Engine tests never use the network. Package scope: active before the
    module-scoped run fixtures, undone after this package."""
    from etl import freshness

    mp = pytest.MonkeyPatch()
    mp.setattr(freshness, "fetch_remote", all_current)
    yield
    mp.undo()
