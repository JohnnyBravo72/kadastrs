"""Run summaries (GET /api/runs/{id}); later also the Excel report's counts.

Counts use the target-level result of each target and module (a property's
aggregate, not its units). A result that does not apply to the target is
counted as `not_applicable`, never as a data gap: module 2 without a given
address (reason "adrese nav norādīta", agreed 2026-10-11).
"""

from typing import Any

from engine.checks.modules.address_consistency import NOT_GIVEN

NOT_APPLICABLE = {("address_consistency", NOT_GIVEN)}
BUCKETS = [
    "found",
    "clear",
    "not_covered",
    "no_data",
    "not_applicable",
    "source_unavailable",
    "error",
]
RISKS = ["high", "medium", "unknown", "low", "none"]


def bucket(module: str, status: str, reason: str | None) -> str:
    return "not_applicable" if (module, reason) in NOT_APPLICABLE else status


def run_header(conn, run_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT id, created_at, finished_at, status, origin, sources, modules, engine_version,
                  rule_set_version, rule_set_status, rule_set_sha256, rule_set->'risk_order',
                  rule_set->'thresholds', error, parent_run_id, rerun_kind, checked_as_of
           FROM work.run WHERE id = %s""",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    (
        rid,
        created,
        finished,
        status,
        origin,
        sources,
        modules,
        engine,
        rs_version,
        rs_status,
        rs_sha,
        risk_order,
        thresholds,
        error,
        parent_run_id,
        rerun_kind,
        checked_as_of,
    ) = row
    versions = [
        info | {"dataset_version_id": vid}
        for vid, info in conn.execute(
            "SELECT dataset_version_id, source FROM work.run_version WHERE run_id = %s"
            " ORDER BY source_id",
            (run_id,),
        )
    ]
    return {
        "id": rid,
        "created_at": created,
        "finished_at": finished,
        "status": status,
        "origin": origin,
        "sources": sources,
        "modules": modules,
        "engine_version": engine,
        "rule_set": {
            "version": rs_version,
            "status": rs_status,
            "sha256": rs_sha,
            "risk_order": risk_order,
            "thresholds": thresholds,
        },
        "dataset_versions": versions,
        "error": error,
        "parent_run_id": parent_run_id,
        "rerun_kind": rerun_kind,  # sources ("Atjaunot") | latest
        "checked_as_of": checked_as_of,  # evaluation time when not created_at
    }


def applicants(conn, run_id: int) -> list[dict[str, Any]]:
    """One entry per applicant reg. no. (Phase 8a): the targets naming it and per
    applicant module its status and risk (results with scope "applicant")."""
    out: dict[str, dict[str, Any]] = {}
    for tno, reg in conn.execute(
        """SELECT target_no, applicant_reg_no FROM work.run_target
           WHERE run_id = %s AND applicant_reg_no IS NOT NULL ORDER BY target_no""",
        (run_id,),
    ):
        out.setdefault(reg, {"reg_no": reg, "target_nos": [], "modules": {}})
        out[reg]["target_nos"].append(tno)
    for reg, module, status, reason, risk in conn.execute(
        """SELECT unit_code, module, status, reason, risk FROM work.check_result
           WHERE run_id = %s AND scope = 'applicant' ORDER BY unit_code, module_no""",
        (run_id,),
    ):
        entry = out.setdefault(reg, {"reg_no": reg, "target_nos": [], "modules": {}})
        entry["modules"][module] = {
            "status": status,
            "summary_status": bucket(module, status, reason),
            "reason": reason,
            "risk": risk,
        }
    return list(out.values())


def summarize(conn, run_id: int) -> dict[str, Any] | None:
    head = run_header(conn, run_id)
    if head is None:
        return None
    order = head["rule_set"]["risk_order"]
    per_module: dict[str, dict[str, Any]] = {}
    worst: dict[int, str] = {}
    for tno, module, mno, status, reason, risk in conn.execute(
        """SELECT target_no, module, module_no, status, reason, risk FROM work.check_result
           WHERE run_id = %s AND scope IN ('target', 'applicant')
           ORDER BY module_no, target_no""",
        (run_id,),
    ):
        m = per_module.setdefault(
            module,
            {
                "module": module,
                "module_no": mno,
                "status": dict.fromkeys(BUCKETS, 0),
                "risk": dict.fromkeys(RISKS, 0),
            },
        )
        m["status"][bucket(module, status, reason)] += 1
        m["risk"][risk] += 1
        if tno not in worst or order.index(risk) < order.index(worst[tno]):
            worst[tno] = risk
    n_targets = conn.execute(
        "SELECT count(*) FROM work.run_target WHERE run_id = %s", (run_id,)
    ).fetchone()[0]
    return head | {
        "targets": n_targets,
        "modules_summary": sorted(per_module.values(), key=lambda m: m["module_no"]),
        "targets_by_worst_risk": {r: sum(1 for w in worst.values() if w == r) for r in RISKS},
    }


def targets(conn, run_id: int) -> list[dict[str, Any]]:
    """One line per target: input, designation and per module status and risk."""
    out: dict[int, dict[str, Any]] = {}
    for tno, inp, typ, des, addr, pno, warns, units, label, ino, reg in conn.execute(
        """SELECT target_no, input, type, designation, given_address, project_no, warnings, units,
                  label, input_no, applicant_reg_no
           FROM work.run_target WHERE run_id = %s ORDER BY target_no""",
        (run_id,),
    ):
        out[tno] = {
            "target_no": tno,
            "input": inp,
            "type": typ,
            "designation": des,
            "given_address": addr,
            "project_no": pno,
            "warnings": warns,
            "units": units,
            "label": label,  # e.g. "divdomīgs: zemes vienība" (batch input)
            "input_no": ino,
            "applicant_reg_no": reg,  # legal-entity pattern only (CLAUDE.md rule 5)
            "modules": {},
        }
    for tno, module, status, reason, risk in conn.execute(
        """SELECT target_no, module, status, reason, risk FROM work.check_result
           WHERE run_id = %s AND scope = 'target' ORDER BY target_no, module_no""",
        (run_id,),
    ):
        out[tno]["modules"][module] = {
            "status": status,
            "summary_status": bucket(module, status, reason),
            "reason": reason,
            "risk": risk,
        }
    return list(out.values())
