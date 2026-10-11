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


def test_rule_set_v1_is_a_draft_with_a_reason_per_rule():
    rs = rules_mod.load()
    assert (rs.version, rs.status) == ("1", "draft")
    assert all(r.reason.strip() and r.text_lv.strip() for r in rs.rules)
    assert rs.modules() <= set(BY_ID)
    assert rs.modules() == set(BY_ID)  # every module has rules
    assert rs.thresholds.inward_buffer_m == 0.5
    assert (rs.thresholds.min_overlap_m2, rs.thresholds.min_overlap_share) == (1.0, 0.001)


def test_conditions():
    rs = rules_mod.load()
    assert rs.evaluate(result(items=[{"share": 0.5}])) == (
        "high",
        ["flood_10y_major", "flood_10y_minor"],
    )
    assert rs.evaluate(result(items=[{"share": 0.05}])) == ("medium", ["flood_10y_minor"])
    assert rs.evaluate(result(status="clear", warnings=["partial_coverage"])) == (
        "low",
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
