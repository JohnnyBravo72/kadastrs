"""Batch input -> targets and stored inputs (Phase 5 decisions 1-5, 2026-10-11)."""

import psycopg
import pytest

from engine.batch.plan import prepare, run_batch
from engine.batch.reader import InputRow
from engine.checks import runner

pytestmark = pytest.mark.stack


def rows(*specs) -> list[InputRow]:
    out = []
    for n, s in enumerate(specs, 2):
        s = s if isinstance(s, dict) else {"value": s}
        out.append(InputRow(row_no=n, **s))
    return out


def problems(inp, column="vertiba"):
    return [p for p in inp["problems"] if p["column"] == column]


def test_property_or_parcel_is_checked_both_ways(conn):
    p = prepare(conn, rows("05000040014"))
    assert [(t.type, t.designation, t.label) for t in p.targets] == [
        ("property", "05000040014", "divdomīgs: nekustamais īpašums"),
        ("parcel", "05000040014", "divdomīgs: zemes vienība"),
    ]
    codes = {w.code for w in p.targets[0].warnings}
    assert {"ambiguous_property_parcel", "ambiguous_checked_both"} <= codes
    assert p.inputs[0]["target_nos"] == [0, 1] and p.inputs[0]["problems"] == []


@pytest.mark.parametrize(
    ("kind", "expected"),
    [("zemes vienība", "parcel"), ("Īpašums", "property"), ("nekustamais īpašums", "property")],
)
def test_veids_removes_the_ambiguity(conn, kind, expected):
    p = prepare(conn, rows({"value": "05000040014", "kind": kind}))
    assert [(t.type, t.label) for t in p.targets] == [(expected, None)]


def test_veids_that_does_not_fit_goes_to_neatrasts(conn):
    p = prepare(conn, rows({"value": "05000040014", "kind": "būve"}))
    assert p.targets == []
    (prob,) = problems(p.inputs[0])
    assert prob["status"] == "kind_mismatch" and "būve" in prob["reason"]


def test_unknown_veids_is_ignored_with_a_note(conn):
    p = prepare(conn, rows({"value": "09000050400", "kind": "māja"}))
    assert [t.designation for t in p.targets] == ["09000050400"]
    assert problems(p.inputs[0], "veids")[0]["status"] == "invalid"


def test_address_is_checked_on_every_linked_object(conn):
    p = prepare(conn, rows("Tautas iela 11A, Daugavpils"))
    assert sorted((t.type, t.designation) for t in p.targets) == [
        ("building", "05000041006001"),
        ("parcel", "05000040013"),
    ]
    assert {t.given_address for t in p.targets} == {"106228183"}
    assert all(t.label == "adresei 2 objekti" for t in p.targets)


def test_precision_lost_and_not_found_go_to_neatrasts_with_reasons(conn):
    p = prepare(conn, rows("9.00036022E9", "Neesoša iela 1, Jelgava", "123"))
    assert p.targets == []
    lost, street, bad = (problems(i)[0] for i in p.inputs)
    assert lost["status"] == "ambiguous" and "cipari" in lost["reason"]
    assert lost["suggestions"][0]["designation"] == "09000360220"
    assert street["status"] in ("not_found", "ambiguous") and street["reason"]
    assert bad["status"] == "invalid"


def test_unresolved_adrese_still_checks_the_object(conn):
    p = prepare(conn, rows({"value": "09000050400", "address": "Neesoša iela 1, Jelgava"}))
    (t,) = p.targets
    assert t.given_address is None
    assert any(w.code == "given_address_unresolved" for w in t.warnings)
    assert problems(p.inputs[0], "adrese")[0]["reason"]


def test_adrese_column_is_the_given_address(conn):
    p = prepare(conn, rows({"value": "09000360220", "address": "Institūta iela 4, Jelgava"}))
    assert p.targets[0].given_address == "101765287"


def test_personal_codes_are_never_stored(conn):
    p = prepare(
        conn,
        rows(
            {"value": "09000050400", "applicant": "010190-12345"},
            {"value": "09000050400", "applicant": "4000 3000 000"},
            "010190-12345",
        ),
    )
    a, b, c = p.inputs
    assert a["applicant_reg_no"] is None and problems(a, "pieteicejs_reg_nr")
    assert "010190" not in str(a)
    assert b["applicant_reg_no"] == "40003000000"
    assert c["value"] is None and c["status"] == "not_stored" and "010190" not in str(c)
    assert [t.applicant_reg_no for t in p.targets] == [None, "40003000000"]


def test_duplicates_are_checked_again_with_a_warning(conn):
    p = prepare(conn, rows("09000050400", "9000050400"))
    assert [t.designation for t in p.targets] == ["09000050400", "09000050400"]
    assert any(w.code == "duplicate" for w in p.targets[1].warnings)


def test_run_stores_every_input_row(conn):
    rid = run_batch(conn, rows("09000050400", "123", {"value": "05000040014", "project_no": "P"}))
    inputs = runner.stored_inputs(conn, rid)
    assert [(i["row_no"], i["target_nos"]) for i in inputs] == [(2, [0]), (3, []), (4, [1, 2])]
    targets = runner.load_targets(conn, rid)
    assert [t.input_no for t in targets] == [0, 2, 2]
    assert targets[1].label == "divdomīgs: nekustamais īpašums"
    assert targets[1].project_no == "P"
    origin = conn.execute("SELECT origin FROM work.run WHERE id = %s", (rid,)).fetchone()[0]
    assert origin == "batch"
    with pytest.raises(psycopg.errors.DatabaseError, match="never changed"):
        conn.execute("UPDATE work.run_input SET value = 'x' WHERE run_id = %s", (rid,))


def test_run_with_nothing_checkable_is_still_stored(conn):
    rid = run_batch(conn, rows("123", ""))
    assert runner.load_targets(conn, rid) == []
    assert [i["status"] for i in runner.stored_inputs(conn, rid)] == ["invalid", "empty"]


def test_pinned_sources_carry_coverage_and_processing_notes(conn):
    rid = run_batch(conn, rows("09000050400"))
    info = dict(
        conn.execute(
            "SELECT source_id, source FROM work.run_version WHERE run_id = %s", (rid,)
        ).fetchall()
    )
    assert info["cadastre_text"]["coverage"].startswith("Pilota pilsētas")  # Latvian
    assert info["cadastre_text"]["processing"][0] == "Importēti tikai pilota pilsētu ieraksti."
    flood = info["flood_10y"]["processing"]
    assert flood[0].startswith("Importēti plūdu zonu objekti")  # own note first, then E7
    assert any("1 cm" in n for n in flood)
