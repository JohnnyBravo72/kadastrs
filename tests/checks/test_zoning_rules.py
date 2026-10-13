"""Module 8 zoning rules (v5 agreed): TAPIS grupa_kods levels."""

from engine.checks import rules as rules_mod
from engine.checks.contract import CheckResult, Display, Subject, Warning_


def result(status="found", items=(), warnings=(), reason=None):
    return CheckResult(
        module="zoning",
        module_no=8,
        module_version="1",
        subject=Subject(type="parcel", id="09000050400"),
        status=status,
        reason=reason,
        items=list(items),
        warnings=[Warning_(code=c, message=c) for c in warnings],
        display=Display(kind="table"),
    )


def test_rule_set_v5_agreed_covers_zoning():
    rs = rules_mod.load()
    assert (rs.version, rs.status) == ("5", "agreed")
    assert "zoning" in rs.modules()


def test_zoning_group_levels():
    rs = rules_mod.load()
    assert rs.evaluate(result(items=[{"group_code": "10106"}]))[0] == "medium"
    assert rs.evaluate(result(items=[{"group_code": "10108"}]))[0] == "medium"
    assert rs.evaluate(result(items=[{"group_code": "10107"}]))[0] == "low"
    assert rs.evaluate(result(items=[{"group_code": "10104"}]))[0] == "low"
    assert rs.evaluate(result(items=[{"group_code": "10101"}]))[0] == "none"
    assert rs.evaluate(result(items=[{"group_code": "10109"}]))[0] == "none"
    assert rs.evaluate(result(items=[{"group_code": "99999"}]))[0] == "unknown"
    assert rs.evaluate(result(status="not_covered", reason="x"))[0] == "none"
    assert rs.evaluate(result(status="clear"))[0] == "none"
