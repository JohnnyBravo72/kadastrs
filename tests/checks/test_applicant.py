"""Phase 8a modules: 9 Pieteicējs (UR), 14 Uzņēmumi adresē, 17 Sankcijas
(PLAN.md §6.1, docs/decisions.md D10; rule set v3 draft). Seed: APPLICANTS in
tests/checks/conftest.py."""

import pytest

from engine.checks import runner
from engine.checks.contract import TargetIn
from tests.checks.conftest import APPLICANTS, MASS_ADDRESS, NOT_IN_UR

pytestmark = pytest.mark.stack


def applicant_results(conn, run_id):
    """{(reg_no, module): CheckResult} of the applicant rows."""
    return {
        (r.unit_code, r.result.module): r.result
        for r in runner.stored(conn, run_id)
        if r.scope == "applicant"
    }


@pytest.fixture(scope="module")
def applicant_run(engine_db):
    """One target per applicant (the first applicant also on a second target)."""
    regs = [*APPLICANTS, NOT_IN_UR]
    targets = [
        TargetIn(type="parcel", designation="09000050400", applicant_reg_no=reg) for reg in regs
    ]
    targets.append(TargetIn(type="parcel", designation="09000010048", applicant_reg_no=regs[0]))
    with engine_db() as c:
        return runner.start_run(c, targets, origin="test")


def test_each_applicant_checked_once(conn, applicant_run):
    rows = [r for r in runner.stored(conn, applicant_run) if r.scope == "applicant"]
    keys = [(r.unit_code, r.result.module) for r in rows]
    # Phase 8b adds applicant modules 10–13; count = applicants × applicant modules
    from engine.checks.modules import APPLICANT

    n_app_modules = len(APPLICANT)
    assert len(keys) == len(set(keys)) == (len(APPLICANTS) + 1) * n_app_modules
    first = next(r for r in rows if r.unit_code == "40003100001")
    assert first.target_no == 0 and first.unit_type == "applicant"
    assert first.result.scope == "applicant"
    # applicant modules have no target or unit rows
    assert not [
        r
        for r in runner.stored(conn, applicant_run)
        if r.result.module in APPLICANT and r.scope != "applicant"
    ]


@pytest.mark.parametrize(
    ("reg", "status", "risk", "rule"),
    [
        ("40003100001", "found", "none", "applicant_active"),
        ("40003100002", "found", "high", "applicant_liquidated"),
        ("40003100003", "found", "medium", "applicant_recently_registered"),
        ("40003100004", "found", "high", "applicant_insolvency_open"),
        (NOT_IN_UR, "no_data", "unknown", "applicant_not_in_ur"),
    ],
)
def test_module_9(conn, applicant_run, reg, status, risk, rule):
    r = applicant_results(conn, applicant_run)[(reg, "applicant_company")]
    assert (r.status, r.risk) == (status, risk) and rule in r.rule_ids


def test_module_9_items(conn, applicant_run):
    res = applicant_results(conn, applicant_run)
    alfa = res[("40003100001", "applicant_company")].items[0]
    assert alfa["status_lv"] == "aktīvs" and alfa["registered"] == "2010-01-01"
    assert alfa["open_proceedings"] == [] and alfa["proceedings"][0]["open"] is False
    delta = res[("40003100004", "applicant_company")].items[0]
    assert delta["open_proceeding"] == "INSOLVENCY"
    ik = res[("40003100009", "applicant_company")].items[0]
    assert ik["name"] is None and "nav saglabāts" in ik["name_note"]


@pytest.mark.parametrize(
    ("reg", "status", "risk", "match"),
    [
        ("40003100001", "clear", "none", None),
        ("40003100005", "found", "high", "reg_no"),  # UR LEGAL_ENTITY
        ("40003100006", "found", "high", "reg_no"),  # FID subject
        ("40003100007", "found", "high", "linked_entity"),  # linked foreign entity
    ],
)
def test_module_17(conn, applicant_run, reg, status, risk, match):
    r = applicant_results(conn, applicant_run)[(reg, "sanctions")]
    assert (r.status, r.risk, r.match_type) == (status, risk, match)


def test_module_17_name_only_is_review_not_finding(conn, applicant_run):
    r = applicant_results(conn, applicant_run)[("40003100008", "sanctions")]
    assert (r.status, r.risk) == ("clear", "none")
    assert "sanctions_name_only" in r.rule_ids
    assert [w.code for w in r.warnings] == ["sanctions_name_only"]
    assert r.items[0]["match"] == "name_only" and r.items[0]["review"] is True


def test_module_14_mass_address_in_a_small_house(conn):
    rid = runner.start_run(
        conn, [TargetIn(type="parcel", designation="09000050406")], ["ur_companies"]
    )
    (r,) = [x.result for x in runner.stored(conn, rid) if x.result.module == "companies_at_address"]
    assert (r.status, r.risk) == ("found", "medium")
    assert {"companies_mass_address_residential", "companies_mass_address_small_building"} <= set(
        r.rule_ids
    )
    (item,) = r.items
    assert item["varis_code"] == MASS_ADDRESS and item["active_count"] == 12
    assert item["residential"] is True and item["building_area_m2"] == 180
    assert [w.code for w in r.warnings][:1] == ["legal_address_only"]


def test_module_14_few_companies_and_no_address(conn):
    rid = runner.start_run(
        conn,
        [
            TargetIn(type="building", designation="09000360220002"),
            TargetIn(type="parcel", designation="09000050400"),
        ],
        ["ur_companies"],
    )
    res = {
        x.target_no: x.result
        for x in runner.stored(conn, rid)
        if x.result.module == "companies_at_address"
    }
    school = res[0]
    assert (school.status, school.risk) == ("found", "low")
    assert school.items[0]["active_count"] == 2 and school.items[0]["ended_count"] == 1
    # the IK at that address is listed without a name
    assert any(c["name"] is None and c["form"] == "IK" for c in school.items[0]["companies"])
    no_address = res[1]
    assert (no_address.status, no_address.risk) == ("clear", "none")
    assert [w.code for w in no_address.warnings] == ["no_address"]


def test_unticked_sanction_sources_leave_module_17_out(conn):
    t = [TargetIn(type="parcel", designation="09000050400", applicant_reg_no="40003100005")]
    rid = runner.start_run(conn, t, ["ur_companies"])
    modules = {(r.result.module) for r in runner.stored(conn, rid)}
    assert "sanctions" not in modules and "applicant_company" in modules
    # only FID ticked: module 17 runs, the UR entity row is not read
    rid = runner.start_run(conn, t, ["fid_sanctions"])
    r = applicant_results(conn, rid)[("40003100005", "sanctions")]
    assert r.status == "clear" and {s.id for s in r.sources} == {"fid_sanctions", "ur_companies"}


def test_no_applicant_no_applicant_rows(conn):
    rid = runner.start_run(conn, [TargetIn(type="parcel", designation="09000050400")])
    assert not applicant_results(conn, rid)


def test_replay_and_rerun_unchanged(conn, applicant_run):
    before = [r.comparable() for r in runner.stored(conn, applicant_run)]
    assert [r.comparable() for r in runner.replay(conn, applicant_run)] == before
    child = runner.rerun(conn, applicant_run, None, "sources", origin="test")
    assert [r.comparable() for r in runner.stored(conn, child)] == before
    assert [r.comparable() for r in runner.stored(conn, applicant_run)] == before


def test_api_applicant_section(client, applicant_run):
    body = client.get(f"/api/runs/{applicant_run}/applicants").json()
    by = {a["reg_no"]: a for a in body}
    alfa = by["40003100001"]
    assert alfa["target_nos"] == [0, len(APPLICANTS) + 1] and alfa["name"] == 'SIA "Alfa"'
    assert [r["module"] for r in alfa["results"]] == ["applicant_company", "sanctions"]
    systems = [lk["system"] for lk in alfa["links"]]
    assert systems == ["UR", "FID sankciju saraksti"]
    ur, fid = alfa["links"]
    assert ur["url"] == "https://info.ur.gov.lv/#/data-search" and ur["copy"] == "40003100001"
    assert fid["url"].startswith("https://sankcijas.fid.gov.lv/lv/meklet-sankciju-sarakstos/1/0?")
    assert "searchText=SIA+%22Alfa%22" in fid["url"]
    # an IK has no stored name: the sanctions search runs by the reg. no.
    assert "searchText=40003100009" in by["40003100009"]["links"][1]["url"]
    assert by["40003100005"]["modules"]["sanctions"]["risk"] == "high"
    # the per-object view does not carry applicant rows
    one = client.get(f"/api/runs/{applicant_run}/targets/0").json()
    assert {m["module"] for m in one["results"]} & {"applicant_company", "sanctions"} == set()


def test_excel_applicant_sheet_and_details(conn, applicant_run):
    from reports import excel
    from tests.batch.test_report import open_report

    wb = open_report(excel.load(conn, applicant_run))
    ws = wb["Pieteicēji"]
    rows = {r[0]: r for r in ws.iter_rows(min_row=2, values_only=True) if r[0]}
    assert rows["40003100002"][3] == "likvidēts / izslēgts"
    assert rows["40003100009"][1].startswith("nosaukums nav saglabāts")
    assert rows["40003100001"][8] == f"1, {len(APPLICANTS) + 2}"  # objects Nr. 1 and the last
    header = [c.value for c in ws[1]]
    risk = header.index("Kopējais risks")
    assert rows["40003100005"][risk] == "augsts"
    details = [r for r in wb["Detaļas"].iter_rows(min_row=2, values_only=True)]
    lines = [r for r in details if r[1] == "pieteicējs 40003100005"]
    assert lines and "reģistrācijas numurs sarakstā" in lines[-1][5]
    review = [r for r in details if r[1] == "pieteicējs 40003100008"]
    assert any("pārbaudīt manuāli" in (r[5] or "") for r in review)
    # applicant modules are not Kopsavilkums columns
    assert not any("Sankcijas" in str(c.value) for c in wb["Kopsavilkums"][1])
