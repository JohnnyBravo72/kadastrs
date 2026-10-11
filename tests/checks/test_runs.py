"""Runs: property aggregate, rules, immutability, determinism, replay after a new
import, source availability and the API (PLAN.md §6.3-6.5, CLAUDE.md rule 3)."""

import psycopg
import pytest

from engine.checks import rules as rules_mod
from engine.checks import runner, summary
from engine.checks.contract import TargetIn
from tests.checks.conftest import V, add_flood

pytestmark = pytest.mark.stack

TARGETS = [
    TargetIn(type="property", designation="09000360220", given_address="101765287"),
    TargetIn(type="parcel", designation="09000050400", input="9000050400"),
    TargetIn(type="parcel", designation="13000102702"),
    TargetIn(type="premise_group", designation="05000041006001001"),
]


def by_key(rows):
    return {(r.target_no, r.result.module, r.scope, r.unit_code): r.result for r in rows}


# --- property aggregate ---------------------------------------------------------------------


def test_property_results_per_unit_plus_aggregate(conn):
    rid = runner.start_run(conn, TARGETS[:1], origin="test")
    rows = by_key(runner.stored(conn, rid))
    units = {k[3] for k in rows if k[2] == "unit" and k[1] == "nature"}
    # 010 is marked non-existing (left out); 011 belongs to another property
    assert units == {"09000360220", "09000360220002", "09000360220012"}
    agg = rows[(0, "nature", "target", "09000360220")]
    assert agg.subject.type == "property" and agg.status == "found"
    unit_risks = [rows[(0, "nature", "unit", u)].risk for u in units]
    rules = rules_mod.load()
    assert agg.risk == rules.worst(unit_risks)
    assert {i["unit"] for i in agg.items} <= units
    # The aggregate of a property whose units differ names them.
    flood = rows[(0, "flood_10y", "target", "09000360220")]
    assert flood.status == "not_covered"
    enc = rows[(0, "encumbrances", "target", "09000360220")]
    statuses = {rows[(0, "encumbrances", "unit", u)].status for u in units}
    assert enc.status == "found" and statuses == {"found", "clear"}
    assert any(w.code == "units_partial" for w in enc.warnings)


def test_worst_risk_order_comes_from_the_rules():
    rules = rules_mod.load()
    assert rules.risk_order == ["high", "medium", "unknown", "low", "none"]
    assert rules.worst(["low", "unknown", "none"]) == "unknown"
    assert rules.worst(["medium", "unknown"]) == "medium"


# --- stored results -----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def first_run(engine_db):
    with engine_db() as c:
        return runner.start_run(c, TARGETS, origin="test")


def test_every_result_names_pinned_versions(conn, first_run):
    pinned = dict(
        conn.execute(
            "SELECT source_id, dataset_version_id FROM work.run_version WHERE run_id = %s",
            (first_run,),
        ).fetchall()
    )
    assert pinned == V
    for row in runner.stored(conn, first_run):
        r = row.result
        assert r.dataset_version_ids and set(r.dataset_version_ids) <= set(V.values())
        assert {s.dataset_version_id for s in r.sources} == set(r.dataset_version_ids)
    bis = by_key(runner.stored(conn, first_run))[(1, "bis", "target", "09000050400")]
    assert set(bis.dataset_version_ids) == {
        V["bis_cases"],
        V["cadastre_text"],
        V["cadastre_spatial"],
    }
    enc = by_key(runner.stored(conn, first_run))[(1, "encumbrances", "target", "09000050400")]
    assert set(enc.dataset_version_ids) == {
        V["cadastre_encumbrances"],
        V["cadastre_text"],
        V["encumbrances_frozen"],
        V["atis_classifier"],
    }


def test_run_records_the_rule_set(conn, first_run):
    s = summary.summarize(conn, first_run)
    assert s["status"] == "done"
    assert s["rule_set"]["version"] == "1" and s["rule_set"]["status"] == "agreed"
    assert s["rule_set"]["sha256"] == rules_mod.load().sha256


def test_premise_group_is_checked_on_its_building(conn, first_run):
    rows = by_key(runner.stored(conn, first_run))
    r = rows[(3, "cadastre_facts", "target", "05000041006001")]
    assert r.warnings[0].code == "premise_group_to_building"


def test_stored_result_cannot_be_updated(conn, first_run):
    with pytest.raises(psycopg.errors.RestrictViolation, match="never changed"):
        conn.execute("UPDATE work.check_result SET risk = 'none' WHERE run_id = %s", (first_run,))
    with pytest.raises(psycopg.errors.RestrictViolation):
        conn.execute("UPDATE work.run SET sources = '{}' WHERE id = %s", (first_run,))


def test_same_inputs_and_versions_give_the_same_results(conn, first_run):
    second = runner.start_run(conn, TARGETS, origin="test")
    assert second != first_run
    a = [r.comparable() for r in runner.stored(conn, first_run)]
    b = [r.comparable() for r in runner.stored(conn, second)]
    assert a == b


def test_old_run_is_reproducible_after_a_new_import(conn, first_run):
    before = [r.comparable() for r in runner.stored(conn, first_run)]
    # A newer flood version: finding A moves onto 09000010048 (was clear).
    conn.execute(
        "UPDATE dataset_version SET status = 'superseded' WHERE id = %s", (V["flood_10y"],)
    )
    conn.execute(
        "INSERT INTO dataset_version (id, source_id, version_date, checksum, status)"
        " OVERRIDING SYSTEM VALUE VALUES (50, 'flood_10y', '2026-10-11', %s, 'live')",
        ("sha256:" + "5" * 64,),
    )
    try:
        add_flood(
            conn,
            50,
            [
                (0, "finding", "A2", (473990, 272990, 474020, 273020)),
                (3, "coverage_mask", "M", (472000, 272000, 476000, 276000)),
            ],
        )
        replayed = [r.comparable() for r in runner.replay(conn, first_run)]
        assert replayed == before
        assert [r.comparable() for r in runner.stored(conn, first_run)] == before
        new = runner.start_run(
            conn,
            [
                TargetIn(type="parcel", designation="09000010048"),
                TargetIn(type="parcel", designation="09000050400"),
            ],
            ["flood_10y"],
            origin="test",
        )
        rows = by_key(runner.stored(conn, new))
        assert rows[(0, "flood_10y", "target", "09000010048")].status == "found"
        assert rows[(1, "flood_10y", "target", "09000050400")].status == "clear"
        assert rows[(0, "flood_10y", "target", "09000010048")].dataset_version_ids[-1] == 50
    finally:
        for table in ("ref.flood_zone_part", "ref.flood_zone"):
            conn.execute(f"DELETE FROM {table} WHERE dataset_version_id = 50")  # noqa: S608
        conn.execute("UPDATE dataset_version SET status = 'failed' WHERE id = 50")
        conn.execute("UPDATE dataset_version SET status = 'live' WHERE id = %s", (V["flood_10y"],))


def test_replay_of_a_run_with_properties_and_addresses(conn, first_run):
    before = [r.comparable() for r in runner.stored(conn, first_run)]
    assert [r.comparable() for r in runner.replay(conn, first_run)] == before


# --- availability and selection -----------------------------------------------------------------


def test_missing_source_is_source_unavailable(conn):
    conn.execute("UPDATE dataset_version SET status = 'failed' WHERE id = %s", (V["bis_cases"],))
    try:
        rid = runner.start_run(conn, TARGETS[1:2], ["bis_cases"], origin="test")
    finally:
        conn.execute("UPDATE dataset_version SET status = 'live' WHERE id = %s", (V["bis_cases"],))
    r = by_key(runner.stored(conn, rid))[(0, "bis", "target", "09000050400")]
    assert (r.status, r.reason, r.risk) == (
        "source_unavailable",
        "avots nav importēts: bis_cases",
        "unknown",
    )


def test_only_selected_modules_run(conn):
    rid = runner.start_run(conn, TARGETS[1:2], ["flood_10y"], origin="test")
    assert {r.result.module for r in runner.stored(conn, rid)} == {"flood_10y"}


def test_unknown_source_is_rejected(conn):
    with pytest.raises(runner.UnknownSources):
        runner.start_run(conn, TARGETS[1:2], ["nope"], origin="test")


# --- API -------------------------------------------------------------------------------------


def test_api_run_summary_and_results(client):
    body = {"targets": [t.model_dump(mode="json") for t in TARGETS]}
    r = client.post("/api/runs", json=body)
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["targets"] == 4 and s["rule_set"]["status"] == "agreed"
    m2 = next(m for m in s["modules_summary"] if m["module"] == "address_consistency")
    # Three targets have no given address: not applicable, not a data gap.
    assert m2["status"]["not_applicable"] == 3 and m2["status"]["no_data"] == 0
    assert m2["status"]["clear"] == 1
    run_id = s["id"]
    assert client.get(f"/api/runs/{run_id}").json()["modules_summary"] == s["modules_summary"]
    targets = client.get(f"/api/runs/{run_id}/targets").json()
    assert [t["designation"] for t in targets] == [t.designation for t in TARGETS]
    assert targets[1]["modules"]["flood_10y"]["status"] == "found"
    assert targets[2]["modules"]["address_consistency"]["summary_status"] == "not_applicable"
    one = client.get(f"/api/runs/{run_id}/targets/0").json()
    nature = next(m for m in one["results"] if m["module"] == "nature")
    assert nature["result"]["subject"]["type"] == "property"
    assert len(nature["units"]) == 3


def test_api_errors(client):
    t = [TARGETS[1].model_dump(mode="json")]
    assert client.post("/api/runs", json={"targets": t, "sources": ["nope"]}).status_code == 422
    assert client.post("/api/runs", json={"targets": []}).status_code == 422
    bad = {"targets": [{"type": "parcel", "designation": "9000050400"}]}
    assert client.post("/api/runs", json=bad).status_code == 422  # codes are 11+ digit text
    assert client.get("/api/runs/999999").status_code == 404
    assert client.get("/api/runs/999999/targets/0").status_code == 404
