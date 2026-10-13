"""config/rules.yaml and its evaluator (PLAN.md §6.4, CLAUDE.md rule 4). No DB."""

import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from engine.checks import rules as rules_mod
from engine.checks.contract import CheckResult, Display, Subject, Warning_
from engine.checks.modules import BY_ID

ROOT = Path(__file__).resolve().parents[2]


def result(module="flood_10y", status="found", items=(), warnings=(), reason=None, match=None):
    return CheckResult(
        module=module,
        module_no=4,
        module_version="1",
        subject=Subject(type="parcel", id="1"),
        status=status,
        reason=reason,
        items=list(items),
        match_type=match,
        warnings=[Warning_(code=c, message=c) for c in warnings],
        display=Display(kind="table"),
    )


def test_rule_set_v4_draft_covers_phase8b_modules():
    rs = rules_mod.load()
    # v4 (Phase 8b modules 7, 10–13, 18) draft 2026-10-13; agree after review (D4)
    assert (rs.version, rs.status) == ("4", "draft")
    assert rs.de_minimis is not None and rs.de_minimis.ceilings["2023/2831"] == 300000
    tap = next(r for r in rs.rules if r.id == "applicant_legal_protection_open")
    assert tap.level == "high" and "grūtībās nonākuša uzņēmuma" in tap.text_lv
    nf = rs.not_findings["encumbrances"]
    assert nf.codes == ["8317010100", "8317020100", "8317030100"] and nf.reason.strip()
    assert all(r.reason.strip() and r.text_lv.strip() for r in rs.rules)
    assert rs.modules() <= set(BY_ID)
    assert rs.modules() == set(BY_ID)  # every module has rules
    assert rs.thresholds.inward_buffer_m == 0.5
    assert (rs.thresholds.min_overlap_m2, rs.thresholds.min_overlap_share) == (1.0, 0.001)
    for mid in (
        "ownership",
        "vid_rating",
        "deminimis",
        "eu_funding",
        "eu_funding_applicant",
        "procurement",
        "fid_frozen_property",
    ):
        assert mid in rs.modules()


def test_conditions():
    rs = rules_mod.load()
    assert rs.evaluate(result(items=[{"share": 0.5}])) == (
        "high",
        ["flood_10y_major"],
    )
    assert rs.evaluate(result(items=[{"share": 0.05}])) == ("medium", ["flood_10y_partial"])
    assert rs.evaluate(result(items=[{"share": 0.005}])) == ("low", ["flood_10y_minor"])
    assert rs.evaluate(result(status="not_covered")) == ("none", ["flood_not_covered"])
    assert rs.evaluate(result(status="clear", warnings=["partial_coverage"])) == (
        "none",
        ["flood_partly_covered", "flood_clear"],
    )
    assert rs.evaluate(
        result(module="address_consistency", status="no_data", reason="adrese nav norādīta")
    ) == ("none", ["address_not_given"])
    assert rs.evaluate(result(module="address_consistency", status="no_data", reason="cits")) == (
        "unknown",
        ["default_no_data"],
    )
    assert rs.evaluate(result(module="bis", items=[{"match_type": "nearby"}])) == (
        "none",
        ["bis_weak"],
    )


def test_unknown_condition_is_rejected(tmp_path):
    data = rules_mod.load().as_json()
    data["rules"][0]["when"] = {"stauts": "found"}
    with pytest.raises(ValidationError, match="unknown condition"):
        rules_mod.from_json(data)
    data = rules_mod.load().as_json()
    del data["defaults"]["error"]
    with pytest.raises(ValidationError, match="defaults"):
        rules_mod.from_json(data)


def test_no_risk_levels_in_engine_code():
    """Risk levels are assigned only by the rules file (CLAUDE.md rule 4)."""
    pattern = re.compile(r"""risk\s*=\s*["'](high|medium|low|none|unknown)["']""")
    for path in (ROOT / "engine").rglob("*.py"):
        assert not pattern.search(path.read_text(encoding="utf-8")), path


def test_nature_category_and_zone_mapping():
    rs = rules_mod.load()

    def nature(*items):
        return rs.evaluate(result(module="nature", items=list(items)))

    def area(cat, decided=False):
        return {"kind": "protected_area", "category": cat, "decided_by_zone": decided}

    def zone(z):
        return {"kind": "protected_area_zone", "zone_type": z}

    assert nature(area("DL")) == ("high", ["nature_area_high"])
    assert nature(area("DP")) == ("medium", ["nature_area_medium"])
    assert nature(area("DPie:ĢĢ")) == ("medium", ["nature_area_medium"])
    assert nature(area("XX")) == ("unknown", ["nature_area_unmapped"])
    assert nature(area(None)) == ("unknown", ["nature_area_unmapped"])
    # a zoned area is decided by its zone
    assert nature(area("DL", decided=True), zone("NZ")) == ("low", ["nature_zone_low"])
    assert nature(area("NP", decided=True), zone("AAZ")) == ("medium", ["nature_zone_medium"])
    assert nature(zone("SRZ")) == ("high", ["nature_zone_high"])
    assert nature(zone("cita")) == ("unknown", ["nature_zone_other"])
    assert nature(zone("ZZZ")) == ("unknown", ["nature_zone_unmapped"])


def test_bis_stage_and_age():
    rs = rules_mod.load()

    def bis(stage, age, mt="exact_building"):
        item = {"match_type": mt, "stage": stage, "age_years": age}
        return rs.evaluate(result(module="bis", items=[item]))

    assert bis("Būvdarbi", 9.0)[0] == "medium"  # active, however old
    assert bis("Ekspluatācija", 2.0)[0] == "medium"  # closed but recent
    assert bis("Ekspluatācija", 7.5) == ("low", ["bis_exact_closed", "bis_weak"])
    assert bis("Izbeigta", 5.0)[0] == "low"
    assert bis("Jauna stadija", 9.0)[0] == "unknown"
    assert bis("Būvdarbi", 1.0, mt="same_address_code")[0] == "low"


def test_encumbrance_codes():
    rs = rules_mod.load()

    def enc(code, frozen=False, technical=False):
        item = {"code": code, "frozen": frozen, "technical": technical}
        return rs.evaluate(result(module="encumbrances", items=[item]))

    assert enc("7311020400")[0] == "medium"  # applūstošā teritorija
    assert enc("7314020102")[0] == "medium"  # kultūras pieminekļa aizsardzības zona
    assert enc("7312050201") == ("low", ["encumbrance_registered"])  # cable line belt
    assert enc("7311020400", frozen=True)[0] == "low"  # default_found: frozen items rate via reason
    # technical (not_findings) items: no rule fires on them
    assert enc("8317010100", technical=True)[1] == ["default_found"]


def test_a_v1_snapshot_keeps_its_shape_and_checksum():
    """Old runs store rule set v1 without not_findings: loading it back adds no key,
    so its JSON and checksum are unchanged and replay uses no technical list."""
    v1 = rules_mod.load().as_json()
    v1.pop("not_findings")
    v1["version"] = "1"
    rs = rules_mod.from_json(v1)
    assert rs.not_findings == {} and "not_findings" not in rs.as_json()
    assert rs.as_json() == v1
