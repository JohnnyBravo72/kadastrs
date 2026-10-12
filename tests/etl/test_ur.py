"""Applicant sources (Phase 8a, docs/data-sources.md §3.9, §3.9a, §3.17): import,
legal-entity scope and the personal-data guards of D10 (CLAUDE.md rule 5).
Natural-person rows in the fixtures carry fake person data (tests/etl/fakes.py);
none of it may reach any table, through the importer or a direct INSERT."""

import psycopg
import pytest

from etl.importers.ur import iso_date, legal_reg_no
from tests.etl import fakes

SOURCES = ("ur_companies", "ur_insolvency", "ur_sanctions", "fid_sanctions")
TABLES = ("ref.ur_company", "ref.ur_insolvency", "ref.ur_sanction", "ref.fid_sanction")
PERSON_DATA = (
    fakes.FAKE_PERSON,
    "Personvārds",
    fakes.FAKE_BIRTH,
    fakes.FAKE_PERSONAL_CODE,
    "01016012345",
    "010160",
)


@pytest.fixture
def imported(run, server):
    fakes.publish_applicant_sources(server)
    for sid in SOURCES:
        out = run(sid)
        assert out.status == "succeeded", (sid, out.message)
    return True


def all_text(q) -> str:
    """Every stored value of the four tables as one text (the guard looks in it)."""
    parts = []
    for t in TABLES:
        parts += [str(r) for r in q(f"SELECT * FROM {t}")]  # noqa: S608  (fixed names)
    return "\n".join(parts)


def test_helpers():
    assert legal_reg_no(" 4000 3000 001") == "40003000001"
    assert legal_reg_no(50003000009) == "50003000009"
    assert legal_reg_no(50003000009.0) == "50003000009"
    assert legal_reg_no("010160-12345") is None
    assert legal_reg_no("32123456789") is None  # new-format personal code
    assert legal_reg_no("1960-01-01") is None
    assert iso_date("2026-09-01 10:00:00", "x").isoformat() == "2026-09-01"
    assert iso_date("", "x") is None
    with pytest.raises(ValueError):
        iso_date("01.09.2026", "x")


def test_companies(imported, q):
    rows = q(
        "SELECT reg_no, name, form, registered, terminated, closed, varis_code, atvk"
        " FROM ref.ur_company_current ORDER BY reg_no"
    )
    by = {r[0]: r for r in rows}
    assert set(by) == {"40003000001", "40003000002", "40003000003", "123456789", "50003000004"}
    assert by["40003000001"][1] == 'SIA "Alfa"' and by["40003000001"][5] is None
    assert by["40003000001"][6] == "101000001" and by["40003000001"][7] == "0003000"
    assert by["40003000002"][5] == "L" and str(by["40003000002"][4]) == "2020-02-02"
    # IK and IND: no name (it is the owner's); ZEM keeps its name
    assert by["40003000003"][1] is None and by["40003000003"][2] == "IK"
    assert by["123456789"][1] is None and by["123456789"][6] is None  # addressid 0
    assert by["50003000004"][1] == 'Zemnieku saimniecība "Kalni"' and by["50003000004"][5] == "R"
    (processing,) = q(
        "SELECT processing FROM dataset_version"
        " WHERE source_id = 'ur_companies' AND status = 'live'"
    )[0]
    pd = next(p for p in processing if p["id"] == "personal_data")
    assert pd["name_not_stored"] == 2 and pd["skipped_reg_no_shape"] == 1


def test_insolvency_legal_entities_only(imported, q):
    rows = q(
        "SELECT proceeding_id, reg_no, started_on, ended_on, form FROM ref.ur_insolvency_current"
        " ORDER BY proceeding_id"
    )
    assert [(r[0], r[1], r[4]) for r in rows] == [
        ("1001", "40003000002", "INSOLVENCY"),
        ("1002", "40003000001", "LEGAL_PROTECTION"),
    ]
    assert rows[1][3] is None  # open proceeding


def test_sanctions_entities_only(imported, q):
    rows = q(
        "SELECT entry_id, entity_type, reg_no, foreign_reg_no, entity_name, subject_reg_no, list"
        " FROM ref.ur_sanction_current ORDER BY entry_id"
    )
    assert rows == [
        ("2", "LEGAL_ENTITY", "40003000006", None, 'SIA "Delta"', None, "ES_SANCTIONS"),
        (
            "3",
            "FOREIGN_ENTITY",
            None,
            "1027700000",
            "OOO Epsilon",
            "40003000007",
            "SDN_OFAC_SANCTIONS",
        ),
    ]
    # option A: the company linked to the natural person (40003000005) is not stored either
    assert "40003000005" not in all_text(q)


def test_fid_rows_with_latvian_reg_no_only(imported, q):
    rows = q(
        "SELECT row_no, reg_no, entity_name, country, basis, legal_act"
        " FROM ref.fid_sanction_current ORDER BY row_no"
    )
    assert rows == [
        (
            1,
            "40003000008",
            'SIA "Theta"',
            "Latvija",
            "Sankciju sarakstā iekļautas personas kontrole",
            "269/2014",
        ),
        (4, "50003000009", 'AS "Kappa"', "Latvija", "Kontrole", "269/2014"),
    ]


def test_no_person_data_anywhere(imported, q):
    text = all_text(q)
    for value in PERSON_DATA:
        assert value not in text, value
    # nor in the import's processing notes or the version metadata
    meta = str(q("SELECT processing, files FROM dataset_version"))
    meta += str(q("SELECT row_counts, message FROM import_log"))
    assert fakes.FAKE_PERSON not in meta and fakes.FAKE_BIRTH not in meta


@pytest.mark.parametrize(
    ("sql", "params"),
    [
        # a personal code as a reg. no.
        (
            "INSERT INTO ref.ur_company (dataset_version_id, reg_no, form) VALUES (%s, %s, 'SIA')",
            ("01016012345",),
        ),
        # an individual merchant with a name
        (
            "INSERT INTO ref.ur_company (dataset_version_id, reg_no, name, form)"
            " VALUES (%s, '40003999999', 'IK Vārds', 'IK')",
            (),
        ),
        (
            "INSERT INTO ref.ur_insolvency (dataset_version_id, proceeding_id, reg_no)"
            " VALUES (%s, '9', %s)",
            ("010160-12345",),
        ),
        # a natural-person sanctions row
        (
            "INSERT INTO ref.ur_sanction (dataset_version_id, entry_id, entity_type)"
            " VALUES (%s, '9', 'NATURAL_PERSON')",
            (),
        ),
        (
            "INSERT INTO ref.fid_sanction (dataset_version_id, row_no, reg_no) VALUES (%s, 9, %s)",
            ("1960-01-01",),
        ),
    ],
)
def test_database_refuses_person_rows(imported, etl_db, q, sql, params):
    (vid,) = q("SELECT max(id) FROM dataset_version")[0]
    with etl_db() as c, pytest.raises(psycopg.errors.CheckViolation):
        c.execute(sql, (vid, *params))


def test_no_person_columns_exist(q):
    """The tables cannot hold a person's name, birth date or personal code (D10)."""
    cols = {
        r[0]
        for r in q(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'ref'"
            " AND table_name IN ('ur_company', 'ur_insolvency', 'ur_sanction', 'fid_sanction')"
        )
    }
    for forbidden in (
        "birth_date",
        "latvian_identity_number_masked",
        "nationality",
        "debtor_name",
        "debtor_address",
        "person_name",
    ):
        assert forbidden not in cols
    assert "name" in cols  # ur_company.name: legal entities only (constraint above)


def test_schema_change_stops_the_import(run, server, q):
    fakes.publish_applicant_sources(server)
    body = fakes.csv_bytes("ur_sanctions", fakes.UR_SANCTIONS, delimiter=";")
    server.publish(
        "ur_sanctions", "sanctions", "sanctions.csv", body.replace(b"birth_date", b"dob", 1)
    )
    out = run("ur_sanctions")
    assert out.status == "failed" and "dob" in out.message
    assert q("SELECT count(*) FROM ref.ur_sanction") == [(0,)]


def test_reimport_is_unchanged(run, server, imported):
    for sid in SOURCES:
        assert run(sid).status == "unchanged"
