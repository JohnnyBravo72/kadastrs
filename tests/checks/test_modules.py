"""Modules 1-6 and the spatial rules (PLAN.md §6.1-6.3) on synthetic data.
Fixture layout: tests/checks/conftest.py."""

import pytest

from engine.checks import runner
from engine.checks.contract import TargetIn
from engine.checks.modules.encumbrances import FROZEN_ONLY, ONLY_FROZEN_REASON
from engine.checks.modules.flood import NOT_COVERED

pytestmark = pytest.mark.stack


def check(conn, *targets: TargetIn, sources=None) -> dict:
    """{(target_no, module): {"target": CheckResult, "units": {code: CheckResult}}}"""
    rid = runner.start_run(conn, list(targets), sources, origin="test")
    out: dict = {}
    for row in runner.stored(conn, rid):
        e = out.setdefault((row.target_no, row.result.module), {"target": None, "units": {}})
        if row.scope == "target":
            e["target"] = row.result
        else:
            e["units"][row.unit_code] = row.result
    return out


def parcel(code, **kw) -> TargetIn:
    return TargetIn(type="parcel", designation=code, **kw)


def codes(r) -> list[str]:
    return [w.code for w in r.warnings]


# --- module 4: flood -----------------------------------------------------------------


@pytest.fixture(scope="module")
def flood(engine_db):
    parcels = [
        "09000050400",
        "09000010048",
        "05000010069",
        "09000050401",
        "09000050402",
        "09000050403",
        "09000050404",
        "09000360220",
    ]
    with engine_db() as c:
        res = check(c, *(parcel(p) for p in parcels), sources=["flood_10y"])
    return {p: res[(i, "flood_10y")]["target"] for i, p in enumerate(parcels)}


def test_flood_found_reports_area_and_share(flood):
    r = flood["09000050400"]
    assert r.status == "found"
    assert r.items == [
        {"layer": 0, "layer_name": "Pavasara_palu_010_3_cikls", "overlap_m2": 100.0, "share": 1.0}
    ]
    assert r.risk == "high" and r.rule_ids == ["flood_10y_major"]


def test_flood_clear_inside_the_mask(flood):
    r = flood["09000010048"]
    assert (r.status, r.items, r.risk, r.rule_ids) == ("clear", [], "none", ["flood_clear"])


def test_flood_outside_the_mask_is_not_covered_never_clear(flood):
    for code in ("05000010069", "09000360220"):
        r = flood[code]
        assert r.status == "not_covered"
        assert r.reason == NOT_COVERED
        assert r.risk == "none" and r.rule_ids == ["flood_not_covered"]


def test_flood_partial_coverage_warns(flood):
    r = flood["09000050401"]
    assert r.status == "clear" and "partial_coverage" in codes(r)
    assert r.risk == "none" and "flood_partly_covered" in r.rule_ids


def test_inward_buffer_drops_a_boundary_sliver(flood):
    assert flood["09000050402"].status == "clear"  # 0.3 m strip, 3 m2 without the buffer


def test_overlap_thresholds(flood):
    assert flood["09000050403"].status == "clear"  # 0.81 m2, 0.0081 %
    r = flood["09000050404"]  # 1.44 m2 passes on area although the share is 0.0144 %
    assert r.status == "found" and r.items[0]["overlap_m2"] == pytest.approx(1.44)
    assert r.items[0]["share"] == pytest.approx(0.000144)
    assert r.risk == "low" and r.rule_ids == ["flood_10y_minor"]  # share < 1 %


def test_flood_result_names_its_versions(flood):
    from tests.checks.conftest import V

    r = flood["09000050400"]
    assert r.dataset_version_ids == sorted(
        [V["flood_10y"], V["cadastre_spatial"], V["cadastre_text"]]
    )
    assert r.source.id == "flood_10y" and r.source.dataset_version_id == V["flood_10y"]


# --- module 3: nature ----------------------------------------------------------------


def test_nature_lines_per_kind(conn):
    res = check(
        conn,
        parcel("13000102702"),
        parcel("09000360220"),
        sources=["nature_protected_areas", "nature_microreserves", "nature_habitats"],
    )
    r = res[(0, "nature")]["target"]
    assert r.status == "found"
    assert [(i["kind"], i["overlap_m2"], i["share"]) for i in r.items] == [
        ("microreserve", 50.0, 0.5)  # the 0.3 m habitat sliver is dropped
    ]
    assert r.risk == "high" and r.rule_ids == ["nature_microreserve"]
    r = res[(1, "nature")]["target"]
    assert [i["kind"] for i in r.items] == ["protected_area", "protected_area_zone"]
    assert [i["kind_lv"] for i in r.items] == [
        "Īpaši aizsargājama dabas teritorija",
        "ĪADT funkcionālā zona",
    ]
    area, zone = r.items
    assert (area["category"], area["zoned"], area["decided_by_zone"]) == ("DP", True, True)
    assert (zone["zone_type"], zone["site_name"]) == ("DLZ", "Dabas parks")
    assert r.risk == "high" and r.rule_ids == ["nature_zone_high"]  # the DP rule does not fire


def test_nature_reads_only_selected_layers(conn):
    from tests.checks.conftest import V

    res = check(conn, parcel("13000102702"), sources=["nature_habitats"])
    r = res[(0, "nature")]["target"]
    assert r.status == "clear"
    assert V["nature_microreserves"] not in r.dataset_version_ids
    assert V["nature_habitats"] in r.dataset_version_ids


# --- geometry fallback (§6.3) ------------------------------------------------------------


def test_building_without_geometry_uses_its_parcel(conn):
    res = check(
        conn,
        TargetIn(type="building", designation="09000360220012"),
        sources=["flood_10y", "nature_protected_areas", "cadastre_text"],
    )
    nature = res[(0, "nature")]["target"]
    assert nature.status == "found"  # the parcel lies in the protected area
    assert codes(nature)[:2] == ["no_geometry", "parcel_level"]
    assert nature.warnings[1].message == "pārbaudīts pēc zemes vienības"
    assert res[(0, "cadastre_facts")]["target"].status == "found"


def test_no_geometry_anywhere_is_no_data_never_clear(conn):
    res = check(
        conn,
        TargetIn(type="building", designation="05000040099001"),
        parcel("05000040099"),
        sources=["flood_10y", "nature_microreserves", "cadastre_text"],
    )
    for no in (0, 1):
        for module in ("flood_10y", "nature"):
            r = res[(no, module)]["target"]
            assert (r.status, r.reason, r.risk) == ("no_data", "nav ģeometrijas", "unknown")
            assert "no_geometry" in codes(r)
        assert res[(no, "cadastre_facts")]["target"].status == "found"  # non-spatial still runs


def test_unknown_object_is_no_data(conn):
    res = check(conn, parcel("09000099999"), sources=["flood_10y", "cadastre_text"])
    for module in ("flood_10y", "cadastre_facts"):
        r = res[(0, module)]["target"]
        assert (r.status, r.reason) == ("no_data", "objekts nav atrasts kadastrā")


# --- module 5: BIS -------------------------------------------------------------------------


def test_bis_distinct_cases_and_match_types(conn):
    res = check(
        conn,
        parcel("09000360220"),
        TargetIn(type="building", designation="09000360220002"),
        parcel("13000102702"),
        sources=["bis_cases"],
    )
    p = res[(0, "bis")]["target"]
    assert [(i["case_number"], i["match_type"]) for i in p.items] == [
        ("BIS-A", "building_on_parcel"),
        ("BIS-D", "probable_parcel"),
        ("BIS-B", "same_address_code"),
    ]
    a = p.items[0]
    assert a["row_nos"] == [1, 2]  # duplicate source rows, one case
    assert p.match_type == "building_on_parcel" and p.risk == "medium"
    b = res[(1, "bis")]["target"]
    assert [(i["case_number"], i["match_types"]) for i in b.items] == [
        ("BIS-A", ["exact_building"]),
        ("BIS-B", ["same_address_code"]),
        ("BIS-D", ["same_property"]),  # on the parcel of the same property
    ]
    near = res[(2, "bis")]["target"]
    assert [(i["case_number"], i["match_type"]) for i in near.items] == [("BIS-C", "nearby")]
    assert near.risk == "none" and near.rule_ids == ["bis_weak"]
    assert near.items[0]["match_label"] == "tuvumā (≤ 20 m), nav piesaistīts objektam"


def test_bis_same_property(conn):
    # Building 012 has no case of its own; the cases on its property's parcel and
    # building 002 are "same_property" for it.
    res = check(conn, TargetIn(type="property", designation="09000360220"), sources=["bis_cases"])
    units = res[(0, "bis")]["units"]
    b12 = units["09000360220012"]
    assert [(i["case_number"], i["match_type"]) for i in b12.items] == [
        ("BIS-A", "same_property"),
        ("BIS-D", "same_property"),
    ]


# --- module 6: encumbrances -------------------------------------------------------------------


def test_encumbrances_list_parcel_and_parts(conn):
    res = check(conn, parcel("09000360220"), sources=["cadastre_encumbrances"])
    r = res[(0, "encumbrances")]["target"]
    assert r.status == "found"
    assert [(i["object_code"], i["code"], i["description"]) for i in r.items] == [
        ("09000360220", "7312030100", "Ceļa aizsargjosla (klasifikators)"),
        ("090003602200001", "7312050500", "aizsargjosla ap apakšstaciju"),
    ]
    assert all(i["frozen"] is False for i in r.items)
    # 7312030100 is also current; 7399000000 is frozen-only: a warning line, no risk increase
    frozen = [w.encumbrance_code for w in r.warnings if w.code == "frozen_only"]
    assert frozen == ["7399000000"]
    assert r.risk == "low"
    assert r.rule_ids == ["encumbrance_registered", "encumbrance_frozen_alongside_current"]


def test_all_frozen_only_is_found_with_frozen_items_never_clear(conn):
    res = check(conn, parcel("13000102702"), sources=["cadastre_encumbrances"])
    r = res[(0, "encumbrances")]["target"]
    assert (r.status, r.reason) == ("found", ONLY_FROZEN_REASON)
    assert [
        (i["code"], i["description"], i["establish_date"], i["frozen"], i["flags"]) for i in r.items
    ] == [("7311010000", "vecs apgrūtinājums", "2010-01-01", True, ["frozen"])]
    w = next(w for w in r.warnings if w.code == "frozen_only")
    assert w.message == FROZEN_ONLY
    assert (w.encumbrance_code, w.establish_date) == ("7311010000", "2010-01-01")
    assert r.risk == "unknown" and r.rule_ids == ["encumbrance_frozen_only"]


# --- modules 1 and 2 ---------------------------------------------------------------------------


def test_cadastre_facts(conn):
    res = check(conn, parcel("09000360220"), sources=["cadastre_text"])
    r = res[(0, "cadastre_facts")]["target"]
    item = r.items[0]
    assert item["address"] == "Institūta iela 4, Jelgava, LV-3004"
    assert [b["code"] for b in item["buildings_on_parcel"]] == [
        "09000360220002",
        "09000360220011",
        "09000360220012",
    ]
    assert item["non_existing_excluded"] == 1


def test_address_consistency(conn):
    res = check(
        conn,
        parcel("09000360220", given_address="101765287"),
        parcel("05000040013", given_address="101808322"),
        parcel("09000050405", given_address="101154013"),
        parcel("09000360220"),
        TargetIn(type="property", designation="05000040014", given_address="106228183"),
        sources=["varis_addresses"],
    )
    own, wrong, hist, none, prop = (res[(i, "address_consistency")]["target"] for i in range(5))
    assert (own.status, own.match_type, own.risk) == ("clear", "own_address", "none")
    assert (wrong.status, wrong.reason, wrong.match_type) == ("found", "Neatbilst", "mismatch")
    assert wrong.risk == "medium"
    assert hist.status == "clear" and "historical_address" in codes(hist)
    assert hist.risk == "low"
    assert (none.status, none.reason, none.risk) == ("no_data", "adrese nav norādīta", "none")
    assert prop.status == "clear" and prop.subject.type == "property"
    assert res[(4, "address_consistency")]["units"] == {}  # once per target, no units


def test_technical_encumbrances_are_listed_but_not_findings(conn):
    """Rule set v2 not_findings: 8317* codes keep the object clear (risk none),
    stay in the items with technical: true, and no rule fires on them."""
    from engine.checks import runner as runner_mod
    from engine.checks.contract import TargetIn as T

    rid = runner_mod.start_run(conn, [T(type="parcel", designation="09000050400")], origin="test")
    (enc,) = [r.result for r in runner_mod.stored(conn, rid) if r.result.module == "encumbrances"]
    assert (enc.status, enc.risk, enc.rule_ids) == ("clear", "none", ["encumbrance_clear"])
    assert [(i["code"], i["technical"]) for i in enc.items] == [("8317010100", True)]
