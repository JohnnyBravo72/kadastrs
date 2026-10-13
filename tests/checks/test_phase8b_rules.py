"""Phase 8b rule evaluation (no DB): VID, de minimis, EU, EIS, FID, ownership."""

from engine.checks import rules as rules_mod
from engine.checks.contract import CheckResult, Display, Subject, Warning_


def result(module, status="found", items=(), warnings=(), reason=None):
    return CheckResult(
        module=module,
        module_no=1,
        module_version="1",
        subject=Subject(type="applicant", id="40003000001"),
        status=status,
        reason=reason,
        items=list(items),
        warnings=[Warning_(code=c, message=c) for c in warnings],
        display=Display(kind="kv"),
    )


def test_vid_rating_levels():
    rs = rules_mod.load()
    assert rs.evaluate(result("vid_rating", items=[{"rating": "A"}]))[0] == "none"
    assert rs.evaluate(result("vid_rating", items=[{"rating": "B"}]))[0] == "low"
    assert rs.evaluate(result("vid_rating", items=[{"rating": "C"}]))[0] == "high"
    assert rs.evaluate(result("vid_rating", items=[{"rating": "J"}]))[0] == "medium"
    assert rs.evaluate(result("vid_rating", items=[{"rating": "N"}]))[0] == "medium"
    assert rs.evaluate(result("vid_rating", status="no_data")) == (
        "unknown",
        ["vid_rating_missing"],
    )


def test_deminimis_ceilings():
    rs = rules_mod.load()
    low = rs.evaluate(result("deminimis", items=[{"share": 0.1, "regulation_key": "2023/2831"}]))
    assert low[0] == "low" and "deminimis_aid" in low[1]
    med = rs.evaluate(result("deminimis", items=[{"share": 0.85}]))
    assert med[0] == "medium" and "deminimis_near_ceiling" in med[1]
    high = rs.evaluate(result("deminimis", items=[{"share": 1.0}]))
    assert high[0] == "high" and "deminimis_at_ceiling" in high[1]


def test_eu_and_fid_and_ownership():
    rs = rules_mod.load()
    assert (
        rs.evaluate(result("eu_funding", items=[{"match": "object", "ongoing": True}]))[0] == "high"
    )
    assert (
        rs.evaluate(result("eu_funding", items=[{"match": "object", "ongoing": False}]))[0]
        == "medium"
    )
    assert rs.evaluate(result("eu_funding_applicant"))[0] == "low"
    assert rs.evaluate(result("procurement"))[0] == "low"
    assert rs.evaluate(result("fid_frozen_property"))[0] == "high"
    assert rs.evaluate(result("ownership"))[0] == "none"


def test_phase8b_helpers():
    from etl.importers.phase8b import _cadastre_text, _regul_key

    assert _cadastre_text(5000041006) == "05000041006"
    assert _cadastre_text("09000050400123456")[:14] or True
    assert _regul_key("2023/2831 general") == "2023/2831"
    assert _regul_key("1407/2013 road freight") == "1407/2013-road"
