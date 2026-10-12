"""Phase 7 engine: the entry dialog's unit selection, unticked sources, new runs
made from a stored run ("Atjaunot" and "Pārbaudīt ar jaunākajiem datiem") and
project groups (PLAN.md §8.1, §8.2; CLAUDE.md rule 3)."""

import psycopg
import pytest

from engine.checks import grouping, runner
from engine.checks.contract import TargetIn, UnitRef
from engine.resolve import cadastre
from engine.resolve.context import live_versions
from reports import excel
from tests.batch.test_report import open_report, values
from tests.checks.conftest import V, add_flood

pytestmark = pytest.mark.stack

PROPERTY = "09000360220"
PARCEL = UnitRef(type="parcel", designation="09000360220")
BUILDING = UnitRef(type="building", designation="09000360220002")


def comparable(conn, run_id):
    return [r.comparable() for r in runner.stored(conn, run_id)]


def units_of(conn, run_id, module="nature"):
    return {
        r.unit_code
        for r in runner.stored(conn, run_id)
        if r.scope == "unit" and r.result.module == module
    }


@pytest.fixture(scope="module")
def parent(batch_db):
    """A stored run with a property (two of its units ticked), a parcel in the
    flood finding and a parcel with a project number."""
    targets = [
        TargetIn(type="property", designation=PROPERTY, unit_selection=[PARCEL, BUILDING]),
        TargetIn(type="parcel", designation="09000050400", project_no="P-1"),
        TargetIn(type="parcel", designation="13000102702", project_no="P-1"),
    ]
    with batch_db() as c:
        return runner.start_run(c, targets, origin="test")


# --- unit selection --------------------------------------------------------------------------


def test_only_ticked_units_are_checked(conn, parent):
    assert units_of(conn, parent) == {PARCEL.designation, BUILDING.designation}
    total = len(cadastre.property_units(conn, live_versions(conn), PROPERTY, False).units)
    agg = next(
        r.result
        for r in runner.stored(conn, parent)
        if r.target_no == 0 and r.scope == "target" and r.result.module == "nature"
    )
    note = next(w for w in agg.warnings if w.code == "units_selected")
    assert note.message.startswith(f"pārbaudītas 2 no {total} ")
    stored = conn.execute(
        "SELECT unit_selection FROM work.run_target WHERE run_id = %s AND target_no = 0", (parent,)
    ).fetchone()[0]
    assert stored == [PARCEL.model_dump(), BUILDING.model_dump()]


def test_all_units_ticked_is_the_whole_property(conn):
    units = cadastre.property_units(conn, live_versions(conn), PROPERTY, False).units
    every = [UnitRef(type=u.type, designation=u.designation) for u in units]
    picked = runner.start_run(
        conn,
        [TargetIn(type="property", designation=PROPERTY, unit_selection=every)],
        ["nature_habitats"],
    )
    whole = runner.start_run(
        conn, [TargetIn(type="property", designation=PROPERTY)], ["nature_habitats"]
    )
    assert units_of(conn, picked) == units_of(conn, whole)
    assert not any(
        w.code == "units_selected" for r in runner.stored(conn, picked) for w in r.result.warnings
    )


def test_unit_selection_replays(conn, parent):
    assert [r.comparable() for r in runner.replay(conn, parent)] == comparable(conn, parent)


def test_selection_warning_reaches_the_excel_report(conn, parent):
    ws = open_report(excel.load(conn, parent))["Kopsavilkums"]
    assert "pārbaudītas 2 no" in str(ws.cell(2, ws.max_column).value)


# --- unticked sources -----------------------------------------------------------------------


def test_unticked_source_module_is_not_run(conn):
    everything = runner.default_sources(conn)
    without = [s for s in everything if s != "bis_cases"]
    rid = runner.start_run(conn, [TargetIn(type="parcel", designation="09000050400")], without)
    modules = conn.execute("SELECT modules FROM work.run WHERE id = %s", (rid,)).fetchone()[0]
    assert "bis" not in modules and "flood_10y" in modules
    assert "bis" not in {r.result.module for r in runner.stored(conn, rid)}


# --- Atjaunot: same pinned versions, new source set ------------------------------------------


def test_atjaunot_reuses_the_parent_versions(conn, parent):
    before = comparable(conn, parent)
    pinned = runner.load_pinned(conn, parent)
    sources = [s for s in runner.default_sources(conn) if s != "flood_10y"]
    # a newer flood import must not reach the Atjaunot run
    _new_flood_version(conn)
    try:
        child = runner.rerun(conn, parent, sources, "sources", origin="test")
    finally:
        _drop_flood_version(conn)
    head = conn.execute(
        "SELECT parent_run_id, rerun_kind, checked_as_of, sources FROM work.run WHERE id = %s",
        (child,),
    ).fetchone()
    parent_at = conn.execute("SELECT created_at FROM work.run WHERE id = %s", (parent,)).fetchone()[
        0
    ]
    assert head[:3] == (parent, "sources", parent_at) and "flood_10y" not in head[3]
    assert runner.load_pinned(conn, child) == pinned
    assert runner.version_changes(conn, child) == []
    # the other modules give exactly the parent's results
    old = {(r["target_no"], r["scope"], r["unit_code"], r["result"]["module"]): r for r in before}
    new = comparable(conn, child)
    assert {r["result"]["module"] for r in new} == {r["result"]["module"] for r in before} - {
        "flood_10y"
    }
    for r in new:
        assert r == old[(r["target_no"], r["scope"], r["unit_code"], r["result"]["module"])]
    # the old run is unchanged and still replays
    assert comparable(conn, parent) == before
    assert [r.comparable() for r in runner.replay(conn, parent)] == before
    assert [r.comparable() for r in runner.replay(conn, child)] == new
    # the unit selection travels with the targets
    assert units_of(conn, child) == {PARCEL.designation, BUILDING.designation}


# --- Pārbaudīt ar jaunākajiem datiem: live versions ------------------------------------------


def _new_flood_version(conn):
    conn.execute(
        "UPDATE dataset_version SET status = 'superseded' WHERE id = %s", (V["flood_10y"],)
    )
    conn.execute(
        "INSERT INTO dataset_version (id, source_id, version_date, checksum, status)"
        " OVERRIDING SYSTEM VALUE VALUES (60, 'flood_10y', '2026-10-12', %s, 'live')"
        " ON CONFLICT (id) DO UPDATE SET status = 'live'",
        ("sha256:" + "6" * 64,),
    )
    if not conn.execute("SELECT 1 FROM ref.flood_zone WHERE dataset_version_id = 60").fetchone():
        add_flood(conn, 60, [(3, "coverage_mask", "M", (472000, 272000, 476000, 276000))])


def _drop_flood_version(conn):
    conn.execute("UPDATE dataset_version SET status = 'failed' WHERE id = 60")
    conn.execute("UPDATE dataset_version SET status = 'live' WHERE id = %s", (V["flood_10y"],))


def test_latest_data_pins_live_versions_and_lists_changes(conn, parent):
    before = comparable(conn, parent)
    _new_flood_version(conn)
    try:
        child = runner.rerun(conn, parent, None, "latest", origin="test")
    finally:
        _drop_flood_version(conn)
    head = conn.execute(
        "SELECT parent_run_id, rerun_kind, checked_as_of, sources FROM work.run WHERE id = %s",
        (child,),
    ).fetchone()
    old_sources = conn.execute("SELECT sources FROM work.run WHERE id = %s", (parent,)).fetchone()[
        0
    ]
    assert head == (parent, "latest", None, old_sources)
    changes = runner.version_changes(conn, child)
    assert [(c["id"], c["old_version_id"], c["new_version_id"]) for c in changes] == [
        ("flood_10y", V["flood_10y"], 60)
    ]
    # the finding A is gone in the new version: 09000050400 is no longer found
    flood = {
        r.target_no: r.result.status
        for r in runner.stored(conn, child)
        if r.result.module == "flood_10y" and r.scope == "target"
    }
    assert flood[1] == "clear"
    assert comparable(conn, parent) == before
    assert [r.comparable() for r in runner.replay(conn, parent)] == before


# --- project groups ---------------------------------------------------------------------------


def test_default_groups_come_from_project_numbers(conn, parent):
    g = grouping.current(conn, parent)
    assert g["id"] is None
    assert [x["name"] for x in g["groups"]] == ["P-1", "Bez projekta"]
    assert g["assignment"] == {"0": "none", "1": "p1", "2": "p1"}


def test_grouping_is_insert_only_and_leaves_results_alone(conn, parent):
    before = comparable(conn, parent)
    first = grouping.save(
        conn,
        parent,
        [{"id": "p1", "name": "P-1"}, {"id": "g2", "name": "Jauns projekts"}],
        {"0": "g2", "1": "p1", "2": "none"},
    )
    second = grouping.save(
        conn, parent, [{"id": "g2", "name": "Pārdēvēts"}], {"0": "g2", "1": "none", "2": "none"}
    )
    assert grouping.current(conn, parent)["id"] == second["id"]
    assert grouping.current(conn, parent, first["id"])["assignment"]["1"] == "p1"
    assert comparable(conn, parent) == before
    for sql in (
        "UPDATE work.run_grouping SET groups = '[]' WHERE id = %s",
        "DELETE FROM work.run_grouping WHERE id = %s",
    ):
        with pytest.raises(psycopg.errors.RestrictViolation):
            conn.execute(sql, (first["id"],))


@pytest.mark.parametrize(
    ("groups", "assignment", "message"),
    [
        ([{"id": "a", "name": "X"}], {"0": "a", "1": "a"}, "tieši vienā"),
        ([{"id": "a", "name": "X"}], {"0": "a", "1": "b", "2": "a"}, "nezināma"),
        (
            [{"id": "a", "name": "X"}, {"id": "b", "name": "x"}],
            {"0": "a", "1": "a", "2": "b"},
            "jau ir",
        ),
        ([{"id": "a", "name": " "}], {"0": "a", "1": "a", "2": "a"}, "nosaukum"),
    ],
)
def test_bad_groupings_are_refused(conn, parent, groups, assignment, message):
    with pytest.raises(grouping.GroupingError, match=message):
        grouping.save(conn, parent, groups, assignment)


def test_report_follows_the_grouping_and_rebuilds_identically(conn, parent):
    g = grouping.save(
        conn,
        parent,
        [{"id": "a", "name": "Projekts A"}, {"id": "b", "name": "Projekts B"}],
        {"0": "a", "1": "b", "2": "b"},
    )
    first = values(open_report(excel.load(conn, parent, grouping_id=g["id"])))
    ws = open_report(excel.load(conn, parent, grouping_id=g["id"]))
    assert [ws["Kopsavilkums"].cell(r, 3).value for r in (2, 3, 4)] == [
        "Projekts A",
        "Projekts B",
        "Projekts B",
    ]
    avoti = [c.value for row in ws["Avoti"].iter_rows() for c in row if c.value is not None]
    assert grouping.label(g) in avoti and f"grupējums nr. {g['id']}" in grouping.label(g)
    # a newer grouping becomes the default, the old row's report stays the same
    grouping.save(conn, parent, [{"id": "c", "name": "Cits"}], {"0": "c", "1": "c", "2": "c"})
    assert values(open_report(excel.load(conn, parent, grouping_id=g["id"]))) == first
    latest = open_report(excel.load(conn, parent))["Kopsavilkums"]
    assert latest.cell(2, 3).value == "Cits"


def test_new_runs_carry_the_grouping_over(conn, parent):
    g = grouping.current(conn, parent)
    child = runner.rerun(conn, parent, None, "sources", origin="test")
    carried = grouping.current(conn, child)
    assert carried["origin"] == "rerun" and carried["id"] != g["id"]
    assert (carried["groups"], carried["assignment"]) == (g["groups"], g["assignment"])
