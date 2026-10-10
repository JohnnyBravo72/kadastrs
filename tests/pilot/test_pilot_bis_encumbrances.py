"""Pilot checks for BIS cases and encumbrances (real data; marker `pilot`).

Rows are recounted from the raw files of the live versions with plain `csv`
and regular expressions, independent of the importers. See docs/data-sources.md
§7 for the numbers these checks were written against.
"""

import csv
import re

import pytest

pytestmark = [pytest.mark.pilot, pytest.mark.stack]

from tests.pilot.support import PILOT_CITIES, one, raw_files  # noqa: E402

TERRITORY = {"0500": "0002000", "0900": "0003000", "1300": "0004000"}
SHORT_ATVK = {a.lstrip("0") for a in PILOT_CITIES}


def _rows(path):
    enc = "utf-8-sig" if path.read_bytes()[:3] == b"\xef\xbb\xbf" else "utf-8"
    with open(path, encoding=enc, newline="") as f:
        yield from csv.DictReader(f)


def _restored(raw: str) -> str:
    """Rule E2 on a parcel or parcel-part designation: one lost leading zero."""
    return "0" + raw if raw.isdigit() and len(raw) in (10, 14) else raw


def _bis_raw(db_conn, live):
    r = raw_files(db_conn, "bis_cases", live["bis_cases"])
    paths = {f["role"]: r["base"] / f["path"] for f in r["files"]}
    pilot = {}
    for row_no, row in enumerate(_rows(paths["objects"]), start=1):
        des = row["Buves_kadastra_apzimejums"].strip()
        des = "0" + des if des.isdigit() and len(des) in (13, 16) else des
        if row["Administrativas_teritorijas_kods"] in SHORT_ATVK or des[:4] in TERRITORY:
            pilot[row_no] = (row, des or None)
    return paths, pilot


# --- BIS ---------------------------------------------------------------------------


def test_bis_counts_from_raw_files(db_conn, live):
    paths, pilot = _bis_raw(db_conn, live)
    vid = live["bis_cases"]
    assert one(
        db_conn, "SELECT count(*) FROM ref.bis_object WHERE dataset_version_id = %s", vid
    ) == len(pilot)
    cases = {row["Buvniecibas_lietas_numurs"].strip() for row, _ in pilot.values()}
    listed = sum(1 for r in _rows(paths["cases"]) if r["Buvniecibas_lietas_numurs"] in cases)
    assert (
        one(db_conn, "SELECT count(*) FROM ref.bis_case WHERE dataset_version_id = %s", vid)
        == listed
    )
    assert listed == len(cases)  # every pilot case is in the case list (§7.1)
    assert len(pilot) > 30_000  # 39,448 on 2026-10-10: the DataStore copy would give far fewer


def test_bis_no_designation_lost_a_leading_zero(db_conn, live):
    _, pilot = _bis_raw(db_conn, live)
    stored = dict(
        db_conn.execute(
            "SELECT row_no, designation FROM ref.bis_object WHERE dataset_version_id = %s",
            (live["bis_cases"],),
        ).fetchall()
    )
    assert stored == {n: des for n, (_, des) in pilot.items()}
    with_zero = sum(1 for _, des in pilot.values() if des and des.startswith("0"))
    assert with_zero > 0
    assert (
        one(
            db_conn,
            "SELECT count(*) FROM ref.bis_object WHERE dataset_version_id = %s"
            " AND designation LIKE '0%%'",
            live["bis_cases"],
        )
        == with_zero
    )
    bad = one(
        db_conn,
        "SELECT count(*) FROM ref.bis_object WHERE dataset_version_id = %s AND"
        " (length(designation) NOT IN (14, 17) OR length(atvk) <> 7"
        "  OR (length(designation) = 17) <> ('room_group_cut' = ANY (flags)))",
        live["bis_cases"],
    )
    assert bad == 0


def test_bis_atvk_padded_like_the_raw_file(db_conn, live):
    _, pilot = _bis_raw(db_conn, live)
    stored = dict(
        db_conn.execute(
            "SELECT row_no, atvk FROM ref.bis_object WHERE dataset_version_id = %s",
            (live["bis_cases"],),
        ).fetchall()
    )
    atvk = {n: row["Administrativas_teritorijas_kods"] for n, (row, _) in pilot.items()}
    assert stored == {n: (a.zfill(7) if a else None) for n, a in atvk.items()}


def test_bis_join_report(db_conn, live):
    """How many distinct pilot cases join exactly, probably, only by address, or not at
    all (printed by `etl bis-links`; numbers recorded in docs/data-sources.md §7.6).
    Counts are per distinct case, never per raw row (the CSV has duplicate rows)."""
    counts = dict(
        db_conn.execute(
            "SELECT best_match, count(*) FROM ref.bis_case_best_match(%s, %s) GROUP BY 1",
            (live["bis_cases"], live["cadastre_text"]),
        ).fetchall()
    )
    cases = one(
        db_conn,
        "SELECT count(DISTINCT case_number) FROM ref.bis_object WHERE dataset_version_id = %s",
        live["bis_cases"],
    )
    assert sum(counts.values()) == cases
    assert set(counts) <= {"exact", "probable", "address_only", "none"}
    for kind in ("exact", "probable", "address_only", "none"):
        assert counts.get(kind, 0) > 0, (kind, counts)
    # Phase 0 (Jelgava): the cadastre knows ~94% of designated buildings
    with_designation = one(
        db_conn,
        "SELECT count(DISTINCT case_number) FROM ref.bis_object WHERE dataset_version_id = %s"
        " AND building_code IS NOT NULL",
        live["bis_cases"],
    )
    assert counts["exact"] > 0.8 * with_designation, counts


def test_bis_links_are_distinct_and_cover_the_rules(db_conn, live):
    """One link row per case and target; exact_building links equal the distinct
    (case, building) pairs found in the cadastre text; probable_parcel never points
    at a building the cadastre knows."""
    bis, cad = live["bis_cases"], live["cadastre_text"]
    total, distinct, duplicated_rows = db_conn.execute(
        "SELECT count(*), count(DISTINCT (case_number, route, match_type, building_code,"
        " parcel_code)), count(*) FILTER (WHERE cardinality(row_nos) > 1)"
        " FROM ref.bis_links(%s, %s)",
        (bis, cad),
    ).fetchone()
    assert total == distinct
    assert duplicated_rows > 0  # duplicate source rows collapse into one link (§7.1)
    exact = one(
        db_conn,
        "SELECT count(*) FROM ref.bis_links(%s, %s) WHERE match_type = 'exact_building'",
        bis,
        cad,
    )
    found = one(
        db_conn,
        "SELECT count(DISTINCT (o.case_number, o.building_code)) FROM ref.bis_object o"
        " JOIN ref.building b ON b.dataset_version_id = %s AND b.code = o.building_code"
        " WHERE o.dataset_version_id = %s",
        cad,
        bis,
    )
    assert exact == found
    assert (
        one(
            db_conn,
            "SELECT count(*) FROM ref.bis_links(%s, %s) l JOIN ref.building b"
            " ON b.dataset_version_id = %s AND b.code = l.building_code"
            " WHERE l.match_type = 'probable_parcel'",
            bis,
            cad,
            cad,
        )
        == 0
    )


# --- encumbrances ----------------------------------------------------------------------

_ITEM = re.compile(rb"<(?:\w+:)?EncumbranceItemData>")
_ROW = re.compile(rb"<(?:\w+:)?EncumbranceRowData>")
_OBJ = re.compile(rb"<(?:\w+:)?ObjectCadastreNr>([^<]*)<")


def test_encumbrance_counts_from_raw_xml(db_conn, live):
    vid = live["cadastre_encumbrances"]
    r = raw_files(db_conn, "cadastre_encumbrances", vid)
    items = rows = 0
    objects = set()
    for f in r["files"]:
        for m in f["members"]:
            data = (r["base"] / m["path"]).read_bytes()
            items += len(_ITEM.findall(data))
            rows += len(_ROW.findall(data))
            objects |= {o.decode().strip() for o in _OBJ.findall(data)}
    assert (
        one(db_conn, "SELECT count(*) FROM ref.encumbrance WHERE dataset_version_id = %s", vid)
        == rows
    )
    assert (
        one(
            db_conn,
            "SELECT count(DISTINCT (object_code, object_type)) FROM ref.encumbrance"
            " WHERE dataset_version_id = %s",
            vid,
        )
        <= items
    )
    stored = {
        o
        for (o,) in db_conn.execute(
            "SELECT DISTINCT object_code FROM ref.encumbrance WHERE dataset_version_id = %s", (vid,)
        ).fetchall()
    }
    assert stored == objects  # designations exactly as in the files: no zero lost
    assert rows > 200_000  # 278,798 on the 2026-09-26 files


def test_encumbered_objects_exist_in_the_cadastre_text(db_conn, live):
    """Same PreparedDate -> every encumbered parcel, part and building is in the cadastre
    text (true for all 45,297 objects of 2026-09-26)."""
    dates = db_conn.execute(
        "SELECT source_id, version_date FROM dataset_version WHERE id = ANY(%s)",
        ([live["cadastre_encumbrances"], live["cadastre_text"]],),
    ).fetchall()
    if len({d for _, d in dates}) != 1:
        pytest.fail(f"encumbrance and cadastre text versions differ in date: {dates}; import both")
    missing = one(
        db_conn,
        "SELECT count(DISTINCT object_code) FROM ref.encumbrance e"
        " WHERE e.dataset_version_id = %s AND NOT EXISTS ("
        "  SELECT 1 FROM ref.parcel WHERE dataset_version_id = %s AND code = e.object_code"
        "  UNION ALL SELECT 1 FROM ref.parcel_part WHERE dataset_version_id = %s"
        "   AND code = e.object_code"
        "  UNION ALL SELECT 1 FROM ref.building WHERE dataset_version_id = %s"
        "   AND code = e.object_code)",
        live["cadastre_encumbrances"],
        *[live["cadastre_text"]] * 3,
    )
    assert missing == 0


def test_encumbrance_object_codes_match_their_type(db_conn, live):
    bad = one(
        db_conn,
        "SELECT count(*) FROM ref.encumbrance WHERE dataset_version_id = %s AND NOT ("
        " (object_type = 'PARCEL' AND object_code ~ '^[0-9]{11}$') OR"
        " (object_type = 'PARCEL PART' AND object_code ~ '^[0-9]{15}$') OR"
        " (object_type = 'BUILDING' AND object_code ~ '^[0-9]{14}$'))",
        live["cadastre_encumbrances"],
    )
    assert bad == 0


def test_classifier_counts_and_every_code_known(db_conn, live):
    vid = live["atis_classifier"]
    r = raw_files(db_conn, "atis_classifier", vid)
    (f,) = r["files"]
    assert one(
        db_conn, "SELECT count(*) FROM ref.atis_classifier WHERE dataset_version_id = %s", vid
    ) == sum(1 for _ in _rows(r["base"] / f["path"]))
    unknown = one(
        db_conn,
        "SELECT count(DISTINCT kind_id) FROM ref.encumbrance WHERE dataset_version_id = %s"
        " AND kind_id NOT IN (SELECT code FROM ref.atis_classifier WHERE dataset_version_id = %s)",
        live["cadastre_encumbrances"],
        vid,
    )
    assert unknown == 0


def test_frozen_counts_from_raw_files(db_conn, live):
    vid = live["encumbrances_frozen"]
    r = raw_files(db_conn, "encumbrances_frozen", vid)
    expected = 0
    for f in r["files"]:
        for row in _rows(r["base"] / f["path"]):
            cad = _restored(row["CAD_NR"].strip())
            if cad[:4] in TERRITORY:
                expected += 1
                assert row["ADMTKIND"] == PILOT_CITIES[TERRITORY[cad[:4]]], row
    assert (
        one(
            db_conn,
            "SELECT count(*) FROM ref.encumbrance_frozen WHERE dataset_version_id = %s",
            vid,
        )
        == expected
    )
    assert expected > 70_000  # 79,960 pilot rows (§7.3)
    assert (
        one(
            db_conn,
            "SELECT count(*) FROM ref.encumbrance_frozen WHERE dataset_version_id = %s AND"
            " (NOT 'frozen' = ANY (flags) OR frozen_as_of <> date '2025-01-31'"
            "  OR length(object_code) NOT IN (11, 15))",
            vid,
        )
        == 0
    )


def test_frozen_only_encumbrances_exist(db_conn, live):
    """The reason the frozen list is imported (§7.3): some of it is not in the current list."""
    frozen_only = one(
        db_conn,
        "SELECT count(*) FROM ref.encumbrance_frozen_status(%s, %s, %s) WHERE frozen_only",
        live["encumbrances_frozen"],
        live["cadastre_encumbrances"],
        live["cadastre_text"],
    )
    assert frozen_only > 0


def test_dap_atis_codes_are_classifier_codes(db_conn, live):
    """§7.4: DAP ATIS_CODE and cadastre encumbrance codes are one code system."""
    rows = db_conn.execute(
        "SELECT count(*), count(*) FILTER (WHERE c.code IS NULL)"
        " FROM ref.nature_area_current n"
        " LEFT JOIN ref.atis_classifier c ON c.dataset_version_id = %s AND c.code = n.atis_code"
        " WHERE coalesce(n.atis_code, '') <> ''",
        (live["atis_classifier"],),
    ).fetchone()
    assert rows[0] > 20_000 and rows[1] == 0, rows
