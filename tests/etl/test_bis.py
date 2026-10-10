"""bis_cases: pilot scope, code repair, version identity and cadastre links
(docs/data-sources.md §7.1; migration 20261010120000)."""

from etl.importers.bis import designation, pad_atvk
from tests.etl import fakes


def publish_cadastre(server):
    for role in ("parcel", "parcelpart", "building", "property"):
        server.publish(
            "cadastre_text",
            role,
            f"{role}.zip",
            fakes.text_zip(role, fakes.bis_cadastre_docs(role)),
        )


def objects(q):
    return q(
        "SELECT row_no, case_number, designation, building_code, address_code, atvk,"
        " in_scope_by, flags FROM ref.bis_object_current ORDER BY row_no"
    )


def test_code_helpers():
    assert pad_atvk("4000") == ("0004000", ["atvk_zero_padded"])
    assert pad_atvk("0003000") == ("0003000", [])
    assert pad_atvk("") == (None, [])
    assert designation("9000360220001") == (
        "09000360220001",
        "09000360220001",
        ["leading_zero_restored"],
    )
    assert designation("9000360220001005") == (
        "09000360220001005",
        "09000360220001",
        ["leading_zero_restored", "room_group_cut"],
    )
    assert designation("  ") == (None, None, [])
    assert designation("12AB") == ("12AB", None, ["invalid_designation"])


def test_bis_import_pilot_rows_codes_and_flags(run, server, q):
    fakes.publish_bis(server)
    out = run("bis_cases")
    assert out.status == "succeeded", out.message
    assert objects(q) == [
        (
            1,
            "BIS-1",
            "09000360220001",
            "09000360220001",
            "101000009",
            "0003000",
            ["atvk", "designation_prefix"],
            ["atvk_zero_padded", "leading_zero_restored"],
        ),
        (
            2,
            "BIS-2",
            "09000360220001005",
            "09000360220001",
            None,
            "0003000",
            ["atvk", "designation_prefix"],
            ["atvk_zero_padded", "room_group_cut"],
        ),
        (
            3,
            "BIS-3",
            "09000360221099",
            "09000360221099",
            None,
            "0003000",
            ["atvk", "designation_prefix"],
            ["atvk_zero_padded"],
        ),
        (4, "BIS-4", None, None, "101000002", "0003000", ["atvk"], ["atvk_zero_padded"]),
        (5, "BIS-5", "05000041006001", "05000041006001", None, None, ["designation_prefix"], []),
        # row 6 (Ādaži) is outside the pilot; row 7 duplicates row 1 and is kept
        (
            7,
            "BIS-1",
            "09000360220001",
            "09000360220001",
            "101000009",
            "0003000",
            ["atvk", "designation_prefix"],
            ["atvk_zero_padded", "leading_zero_restored"],
        ),
        (8, "BIS-7", None, None, None, "0004000", ["atvk"], ["atvk_zero_padded"]),
    ]
    cases = q("SELECT case_number, stage, created_date::text FROM ref.bis_case_current ORDER BY 1")
    assert [c[0] for c in cases] == ["BIS-1", "BIS-2", "BIS-3", "BIS-4", "BIS-5", "BIS-7"]
    assert cases[-1] == ("BIS-7", "Ekspluatācija", "2024-03-01")
    (processing,) = q(
        "SELECT processing FROM dataset_version WHERE source_id = 'bis_cases' AND status = 'live'"
    )[0]
    by_id = {p["id"]: p for p in processing}
    assert by_id["duplicate_rows"]["duplicate_rows"] == 1
    assert by_id["codes"]["room_group_cut"] == 1
    assert by_id["pilot_scope"]["pilot_cases"] == 6
    assert by_id["pilot_scope"]["cases_missing_from_case_list"] == 0


def test_bis_links_and_match_types(run, server, q):
    publish_cadastre(server)
    fakes.publish_bis(server)
    assert run("cadastre_text").status == "succeeded"
    assert run("bis_cases").status == "succeeded"
    links = q(
        "SELECT case_number, route, match_type, building_code, parcel_code, row_nos"
        " FROM ref.bis_object_link_current ORDER BY case_number, route, match_type, parcel_code"
    )
    assert links == [
        # rows 1 and 7 are the same published row: one link per case and target
        ("BIS-1", "building_link", "building_on_parcel", "09000360220001", "09000360220", [1, 7]),
        ("BIS-1", "building_link", "building_on_parcel", "09000360220001", "09000360221", [1, 7]),
        ("BIS-1", "building_link", "exact_building", "09000360220001", None, [1, 7]),
        ("BIS-2", "building_link", "building_on_parcel", "09000360220001", "09000360220", [2]),
        ("BIS-2", "building_link", "building_on_parcel", "09000360220001", "09000360221", [2]),
        ("BIS-2", "building_link", "exact_building", "09000360220001", None, [2]),
        ("BIS-3", "designation_prefix", "probable_parcel", "09000360221099", "09000360221", [3]),
        ("BIS-4", "address_code", "same_address_code", None, "09000360221", [4]),
    ]
    best = q(
        "SELECT case_number, best_match, has_designation FROM ref.bis_case_best_match("
        " ref.live_version('bis_cases'), ref.live_version('cadastre_text'))"
    )
    assert best == [
        ("BIS-1", "exact", True),
        ("BIS-2", "exact", True),
        ("BIS-3", "probable", True),
        ("BIS-4", "address_only", False),
        ("BIS-5", "none", True),
        ("BIS-7", "none", False),
    ]
    # Each link row carries the two version ids a check result must store (PLAN §6.5).
    live = q("SELECT ref.live_version('bis_cases'), ref.live_version('cadastre_text')")
    ids = q(
        "SELECT DISTINCT bis_version_id, cadastre_text_version_id FROM ref.bis_object_link_current"
    )
    assert ids == live and None not in live[0]


def test_bis_links_are_deterministic_per_version(run, server, q):
    """Same version ids -> same links, even after a newer cadastre version is live."""
    publish_cadastre(server)
    fakes.publish_bis(server)
    run("cadastre_text")
    run("bis_cases")
    bis_v, cad_v = q("SELECT ref.live_version('bis_cases'), ref.live_version('cadastre_text')")[0]
    before = q("SELECT * FROM ref.bis_links(%s, %s)", bis_v, cad_v)
    # A new cadastre version without the building: the live view changes, the old pair does not.
    docs = fakes.bis_cadastre_docs("building")
    docs["0003000"] = fakes.xml_doc("building", "0003000", [], prepared="2026-10-03")
    server.publish("cadastre_text", "building", "building.zip", fakes.text_zip("building", docs))
    assert run("cadastre_text").status == "succeeded"
    assert q("SELECT ref.live_version('cadastre_text')")[0][0] != cad_v
    assert q("SELECT * FROM ref.bis_links(%s, %s)", bis_v, cad_v) == before
    assert not q("SELECT 1 FROM ref.bis_object_link_current WHERE route = 'building_link'")


def test_bis_duplicate_rows_kept_raw_but_counted_once(run, server, q):
    """A case whose object row is published three times (plus a second, different
    object): raw rows are kept, links and counts are per distinct case."""
    rows = [
        fakes.bis_object("BIS-1", "09000360220001", "3000"),
        fakes.bis_object("BIS-1", "09000360220001", "3000"),
        fakes.bis_object("BIS-1", "09000360220001", "3000"),
        fakes.bis_object("BIS-1", "", "3000", "101000002"),  # same case, address-only object
        fakes.bis_object("BIS-4", "", "3000", "101000002"),
    ]
    publish_cadastre(server)
    fakes.publish_bis(server, objects=rows)
    run("cadastre_text")
    assert run("bis_cases").status == "succeeded"
    assert q("SELECT count(*) FROM ref.bis_object_current") == [(5,)]  # as published
    (processing,) = q(
        "SELECT processing FROM dataset_version WHERE source_id = 'bis_cases' AND status = 'live'"
    )[0]
    assert {p["id"]: p for p in processing}["duplicate_rows"]["duplicate_rows"] == 2
    exact = q(
        "SELECT case_number, row_nos FROM ref.bis_object_link_current"
        " WHERE match_type = 'exact_building'"
    )
    assert exact == [("BIS-1", [1, 2, 3])]
    assert q(
        "SELECT count(*), count(DISTINCT (case_number, route, match_type, building_code,"
        " parcel_code)) FROM ref.bis_object_link_current"
    ) == [(5, 5)]  # BIS-1: exact, 2 parcels, address; BIS-4: address; none duplicated
    best = q(
        "SELECT best_match, count(*) FROM ref.bis_case_best_match("
        " ref.live_version('bis_cases'), ref.live_version('cadastre_text')) GROUP BY 1 ORDER BY 1"
    )
    assert best == [("address_only", 1), ("exact", 1)]  # 2 cases, not 5 rows


def test_bis_e1_redated_urls_in_two_datasets(run, server, q):
    fakes.publish_bis(server, date="09.10.2026")
    assert run("bis_cases").status == "succeeded"
    fakes.publish_bis(server, date="10.10.2026", last_modified="2026-10-10T00:15:05")
    out = run("bis_cases")
    assert out.status == "unchanged", out.message  # same content under new names
    fetched = [str(r.url) for r in server.requests if "objekti-" in str(r.url)]
    assert fetched[-1].endswith("objekti-10.10.2026.csv")
    datasets = {r.url.params.get("id") for r in server.requests if "package_show" in str(r.url)}
    assert {"bis_jlyakg7hgslonjnwyrwc6w", "bis_tln9s3hrpjlnucmjip9r3g"} <= datasets


def test_bis_change_outside_pilot_makes_no_version(run, server, q):
    fakes.publish_bis(server)
    assert run("bis_cases").status == "succeeded"
    rows = [dict(r) for r in fakes.BIS_OBJECTS]
    rows[5]["Buves_nosaukums"] = "Pārbūvēta māja"  # Ādaži row
    cases = fakes.BIS_CASES + [fakes.bis_case("BIS-99")]  # a case without pilot objects
    fakes.publish_bis(server, objects=rows, cases=cases)
    assert run("bis_cases").status == "unchanged"
    assert q("SELECT count(*) FROM dataset_version WHERE source_id = 'bis_cases'") == [(1,)]
    rows[0]["Buves_nosaukums"] = "Pārbūvēta māja"  # a pilot row
    fakes.publish_bis(server, objects=rows, cases=cases)
    assert run("bis_cases").status == "succeeded"
    assert q("SELECT count(*) FROM dataset_version WHERE source_id = 'bis_cases'") == [(2,)]


def test_bis_schema_change_fails_and_keeps_live_version(run, server, q):
    fakes.publish_bis(server)
    assert run("bis_cases").status == "succeeded"
    body = fakes.csv_bytes("bis_objects", fakes.BIS_OBJECTS).replace(
        b"Buves_objekta_adreses_kods", b"Adreses_kods", 1
    )
    server.publish("bis_cases", "objects", "objekti-11.10.2026.csv", body)
    out = run("bis_cases")
    assert out.status == "failed" and "Adreses_kods" in out.message
    assert q("SELECT count(*) FROM dataset_version WHERE source_id = 'bis_cases'") == [(1,)]
    assert q("SELECT count(*) FROM ref.bis_object_current") == [(7,)]


def test_bis_bad_address_code_fails_loudly(run, server):
    rows = [fakes.bis_object("BIS-1", "09000360220001", "3000", "10100000")]  # 8 digits
    fakes.publish_bis(server, objects=rows)
    out = run("bis_cases")
    assert out.status == "failed" and "not 9 digits" in out.message
