"""cadastre_encumbrances, atis_classifier and encumbrances_frozen
(docs/data-sources.md §7.2-7.3; migration 20261010120100)."""

from tests.etl import fakes
from tests.etl.test_bis import publish_cadastre

JELGAVA = [
    fakes.encumbrance_item(
        "09000360220",
        rows=[
            fakes.encumbrance_row(),
            fakes.encumbrance_row(
                "7313100100", "mikrolieguma teritorija", date=None, area="1.5", nr="12"
            ),
        ],
    ),
    fakes.encumbrance_item("90003602200001", "PARCEL PART"),  # lost leading zero
    fakes.encumbrance_item("09000360220001", "BUILDING", [fakes.encumbrance_row(area=None)]),
]


def encumbrances(q):
    return q(
        "SELECT row_no, object_code, object_type, file_atvk, kind_id, encumbrance_nr,"
        " establish_date::text, area::text, measure, flags FROM ref.encumbrance_current"
        " ORDER BY row_no"
    )


def test_encumbrances_import(run, server, q):
    fakes.publish_encumbrances(server, fakes.encumbrance_docs(JELGAVA))
    out = run("cadastre_encumbrances")
    assert out.status == "succeeded", out.message
    assert encumbrances(q) == [
        (
            1,
            "05000000001",
            "PARCEL",
            "0002000",
            "7312050201",
            None,
            "2025-08-15",
            "0.012",
            "ha",
            [],
        ),
        (
            2,
            "09000360220",
            "PARCEL",
            "0003000",
            "7312050201",
            None,
            "2025-08-15",
            "0.012",
            "ha",
            [],
        ),
        (3, "09000360220", "PARCEL", "0003000", "7313100100", "12", None, "1.5", "ha", []),
        (
            4,
            "090003602200001",
            "PARCEL PART",
            "0003000",
            "7312050201",
            None,
            "2025-08-15",
            "0.012",
            "ha",
            ["leading_zero_restored"],
        ),
        (
            5,
            "09000360220001",
            "BUILDING",
            "0003000",
            "7312050201",
            None,
            "2025-08-15",
            None,
            None,
            [],
        ),
        (
            6,
            "13000000001",
            "PARCEL",
            "0004000",
            "7312050201",
            None,
            "2025-08-15",
            "0.012",
            "ha",
            [],
        ),
    ]
    assert q("SELECT version_date::text FROM dataset_version WHERE status = 'live'") == [
        ("2026-09-26",)
    ]
    counts = out.row_counts["encumbrance"]
    assert counts["source_items"] == 5 and counts["source_rows"] == 6
    assert counts["items_by_object_type"] == {"PARCEL": 3, "PARCEL PART": 1, "BUILDING": 1}


def test_encumbrances_xml_without_namespace_gives_same_rows(run, server, q):
    fakes.publish_encumbrances(server, fakes.encumbrance_docs(JELGAVA))
    run("cadastre_encumbrances")
    with_ns = encumbrances(q)
    fakes.publish_encumbrances(server, fakes.encumbrance_docs(JELGAVA, namespace=False))
    assert run("cadastre_encumbrances").status == "succeeded"
    assert encumbrances(q) == with_ns


def test_encumbrances_unchanged_by_fingerprint(run, server, q):
    fakes.publish_encumbrances(server)
    assert run("cadastre_encumbrances").status == "succeeded"
    before = len(server.range_requests())
    out = run("cadastre_encumbrances")
    assert out.status == "unchanged" and "fingerprints" in out.message
    assert len(server.range_requests()) - before <= 2  # central directory only, no members
    assert q("SELECT count(*) FROM dataset_version") == [(1,)]


def test_encumbrances_unknown_element_fails(run, server, q):
    item = fakes.encumbrance_item("09000360220").replace(
        "</EncumbranceRowData>", "<EncumbranceSecret>x</EncumbranceSecret></EncumbranceRowData>"
    )
    fakes.publish_encumbrances(server, fakes.encumbrance_docs([item]))
    out = run("cadastre_encumbrances")
    assert out.status == "failed" and "EncumbranceSecret" in out.message
    assert q("SELECT count(*) FROM ref.encumbrance") == [(0,)]


def test_encumbrances_unknown_object_type_fails(run, server):
    fakes.publish_encumbrances(
        server, fakes.encumbrance_docs([fakes.encumbrance_item("09000360220001001", "PREMISE")])
    )
    out = run("cadastre_encumbrances")
    assert out.status == "failed" and "PREMISE" in out.message


def test_classifier_and_current_view(run, server, q):
    fakes.publish_classifier(server)
    fakes.publish_encumbrances(server, fakes.encumbrance_docs(JELGAVA))
    assert run("atis_classifier").status == "succeeded"
    assert run("cadastre_encumbrances").status == "succeeded"
    assert q("SELECT code, restricted_data FROM ref.atis_classifier_current ORDER BY code") == [
        ("7312010300", "Jā"),
        ("7312050201", "Nē"),
        ("7313100100", "Nē"),
    ]
    rows = q(
        "SELECT kind_id, classifier_description FROM ref.encumbrance_current"
        " WHERE object_code = '09000360220' ORDER BY row_no"
    )
    assert rows == [
        (
            "7312050201",
            "ekspluatācijas aizsargjoslas teritorija gar elektrisko tīklu kabeļu līniju",
        ),
        ("7313100100", "mikrolieguma teritorija"),
    ]


def test_classifier_bad_code_fails(run, server):
    fakes.publish_classifier(server, [fakes.classifier_row("73120502", "short")])
    out = run("atis_classifier")
    assert out.status == "failed" and "not 10 digits" in out.message


def test_frozen_import_and_status(run, server, q):
    publish_cadastre(server)  # parcels 09000360220, 09000360221
    fakes.publish_encumbrances(server, fakes.encumbrance_docs(JELGAVA))
    fakes.publish_frozen(server)
    for sid in ("cadastre_text", "cadastre_encumbrances", "encumbrances_frozen"):
        out = run(sid)
        assert out.status == "succeeded", (sid, out.message)
    rows = q(
        "SELECT file_role, row_no, object_code, object_kind, code, establish_date::text,"
        " area::text, frozen_as_of::text, flags FROM ref.encumbrance_frozen"
        " ORDER BY file_role, row_no"
    )
    assert rows == [
        (
            "latgale_parcel",
            1,
            "05000010002",
            "parcel",
            "7314020102",
            "2009-10-12",
            "0.05",
            "2025-01-31",
            ["frozen"],
        ),
        (
            "riga_parcel",
            1,
            "13000102702",
            "parcel",
            "7311010100",
            "2009-10-12",
            "0.05",
            "2025-01-31",
            ["frozen"],
        ),
        (
            "zemgale_parcel",
            1,
            "09000360220",
            "parcel",
            "7312050201",
            "2009-10-12",
            "0.05",
            "2025-01-31",
            ["frozen"],
        ),
        (
            "zemgale_parcel",
            2,
            "09000360220",
            "parcel",
            "7312010300",
            "2009-10-12",
            "0.05",
            "2025-01-31",
            ["frozen"],
        ),
        # code as published (old 6-digit code), designation zero restored
        (
            "zemgale_parcel",
            3,
            "09000360221",
            "parcel",
            "020401",
            None,
            "0.05",
            "2025-01-31",
            ["frozen", "leading_zero_restored"],
        ),
        (
            "zemgale_parcel",
            4,
            "09000999999",
            "parcel",
            "7312010300",
            "2009-10-12",
            "0.05",
            "2025-01-31",
            ["frozen"],
        ),
        # row 5 (Jelgavas novads, 5400…) is outside the pilot
        (
            "zemgale_part",
            1,
            "090003602200001",
            "parcel_part",
            "14010103",
            "2009-10-12",
            None,
            "2025-01-31",
            ["frozen"],
        ),
    ]
    assert q(
        "SELECT version_date::text FROM dataset_version WHERE source_id = 'encumbrances_frozen'"
    ) == [("2025-01-31",)]
    status = q(
        "SELECT file_role, row_no, in_current, object_in_cadastre, frozen_only"
        " FROM ref.encumbrance_frozen_current WHERE file_role = 'zemgale_parcel'"
        " ORDER BY row_no"
    )
    assert status == [
        ("zemgale_parcel", 1, True, True, False),
        ("zemgale_parcel", 2, False, True, True),
        ("zemgale_parcel", 3, False, True, True),
        ("zemgale_parcel", 4, False, False, False),
    ]
    assert run("encumbrances_frozen").status == "unchanged"


def test_frozen_files_with_different_dates_fail(run, server):
    fakes.publish_frozen(server)
    fakes.publish_frozen(server, files={"riga_part": []}, date="20250215")
    out = run("encumbrances_frozen")
    assert out.status == "failed" and "different dates" in out.message
