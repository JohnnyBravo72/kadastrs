"""Runs: resolved targets in, stored results out (PLAN.md §6.5, CLAUDE.md rule 3).

start_run() pins the live dataset versions, stores the run, its targets and
one check_result per target, unit and module, then marks the run done, all in
one transaction. replay() recomputes a stored run from its pinned versions and
rule-set snapshot; the results equal the stored ones apart from time stamps,
also after newer imports (superseded versions keep their rows, E8).
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from engine.checks import ENGINE_VERSION
from engine.checks import rules as rules_mod
from engine.checks.context import Pinned, RunContext, load_pinned, pin_live
from engine.checks.contract import CheckResult, TargetIn, Warning_
from engine.checks.modules import BY_ID, MODULES, PER_TARGET
from engine.checks.modules.base import ModuleSpec, make
from engine.checks.rules import RuleSet
from engine.checks.units import Target, Unit, build_geometry, expand

AGGREGATE_GAPS = ["error", "source_unavailable", "no_data", "not_covered"]  # worst first
NO_UNITS = "īpašumam nav pārbaudāmu vienību"


class UnknownSources(ValueError):
    pass


@dataclass
class Row:
    """One stored result."""

    target_no: int
    scope: str  # target | unit
    unit_type: str
    unit_code: str
    result: CheckResult

    def comparable(self) -> dict[str, Any]:
        return {
            "target_no": self.target_no,
            "scope": self.scope,
            "unit_type": self.unit_type,
            "unit_code": self.unit_code,
            "result": self.result.comparable(),
        }


# --- selection ---------------------------------------------------------------------------


def default_sources(conn) -> list[str]:
    return [
        r[0]
        for r in conn.execute(
            "SELECT id FROM source WHERE active AND default_selected ORDER BY display_order, id"
        )
    ]


def check_sources(conn, sources: list[str]) -> None:
    known = {r[0] for r in conn.execute("SELECT id FROM source WHERE active")}
    unknown = sorted(set(sources) - known)
    if unknown:
        raise UnknownSources(f"unknown source id(s): {', '.join(unknown)}")


def modules_for(selected: set[str]) -> list[ModuleSpec]:
    return [m for m in MODULES if set(m.selectors) & selected]


# --- computing ---------------------------------------------------------------------------


def _unavailable(spec: ModuleSpec, ctx: RunContext) -> list[str]:
    missing = [s for s in spec.reads if s not in ctx.pinned]
    if spec.optional and not any(s in ctx.pinned for s in spec.optional if s in ctx.selected):
        missing += [s for s in spec.optional if s in ctx.selected]
    return missing


def _run_module(spec: ModuleSpec, ctx: RunContext, units: list[Unit]) -> dict[str, CheckResult]:
    missing = _unavailable(spec, ctx)
    if missing:
        reason = f"avots nav importēts: {', '.join(missing)}"
        pinned = [s for s in spec.used_sources(ctx) if s in ctx.pinned]
        return {
            u.key: make(spec, ctx, u, "source_unavailable", reason=reason, sources=pinned)
            for u in units
        }
    try:
        with ctx.conn.transaction():  # savepoint: a failing module does not end the run
            return spec.run(ctx, units)
    except Exception as exc:  # noqa: BLE001  (reported as status error, PLAN §6.2)
        reason = f"{type(exc).__name__}: {exc}"[:500]
        return {u.key: make(spec, ctx, u, "error", reason=reason) for u in units}


def _with_target_warnings(r: CheckResult, extra: list[Warning_]) -> CheckResult:
    return r.model_copy(update={"warnings": [*extra, *r.warnings]}) if extra else r


def aggregate(rules: RuleSet, target: Target, unit_rows: list[CheckResult]) -> CheckResult:
    """§6.3: a property's result over its units; the worst risk wins."""
    first = unit_rows[0]
    statuses = [r.status for r in unit_rows]
    if "found" in statuses:
        status = "found"
    elif all(s == "clear" for s in statuses):
        status = "clear"
    else:
        status = next(s for s in AGGREGATE_GAPS if s in statuses)
    reasons = sorted({r.reason for r in unit_rows if r.status == status and r.reason})
    warnings: list[Warning_] = []
    seen = set()
    for r in unit_rows:
        for w in r.warnings:
            key = json.dumps(w.model_dump(), sort_keys=True, ensure_ascii=False)
            if key not in seen:
                seen.add(key)
                warnings.append(w.model_copy(update={"unit": r.subject.id}))
    mixed = sorted(set(statuses))
    if len(mixed) > 1:
        warnings.append(
            Warning_(
                code="units_partial",
                message="vienību statusi atšķiras: "
                + "; ".join(
                    f"{s}: {', '.join(r.subject.id for r in unit_rows if r.status == s)}"
                    for s in mixed
                ),
            )
        )
    rule_ids: list[str] = []
    for r in unit_rows:
        rule_ids += [i for i in r.rule_ids if i not in rule_ids]
    refs = {s.dataset_version_id: s for r in unit_rows for s in r.sources}
    return first.model_copy(
        update={
            "subject": first.subject.model_copy(
                update={"type": "property", "id": target.given.designation}
            ),
            "scope": "target",
            "status": status,
            "reason": "; ".join(reasons) or None,
            "risk": rules.worst([r.risk for r in unit_rows]),
            "rule_ids": rule_ids,
            "items": [i | {"unit": r.subject.id} for r in unit_rows for i in r.items],
            "match_type": None,
            "warnings": warnings,
            "sources": [refs[k] for k in sorted(refs)],
            "dataset_version_ids": sorted(refs),
            "computed_at": datetime.now(UTC),
        }
    )


def compute(
    conn,
    rules: RuleSet,
    run_at: datetime,
    pinned: dict[str, Pinned],
    selected: set[str],
    modules: list[ModuleSpec],
    targets_in: list[TargetIn],
) -> tuple[list[Target], list[Row]]:
    ctx = RunContext(conn, rules, run_at, pinned, selected)
    conn.execute("DROP TABLE IF EXISTS pg_temp.chk_geom, pg_temp.chk_bis")
    targets = expand(ctx, targets_in)
    units: dict[str, Unit] = {}
    for t in targets:
        for u in t.units:
            units.setdefault(u.key, Unit(u.type, u.code, u.obj))
    build_geometry(ctx, list(units.values()))

    rows: list[Row] = []
    for spec in modules:
        if spec.id in PER_TARGET:
            for t in targets:
                lead = t.units[0] if not t.property_units else None
                u = Unit(
                    t.given.type if lead is None else lead.type,
                    t.given.designation if lead is None else lead.code,
                    t.target_obj if lead is None else lead.obj,
                    given_address=t.given.given_address,
                    members=t.units,
                )
                r = _run_module(spec, ctx, [u])[u.key]
                extra = [*t.given.warnings, *(lead.warnings if lead else [])]
                r = rules.apply(_with_target_warnings(r, extra))
                rows.append(Row(t.no, "target", u.type, u.code, r))
            continue
        results = _run_module(spec, ctx, list(units.values()))
        for t in targets:
            per_unit = []
            for u in t.units:
                extra = [*u.warnings] if t.property_units else [*t.given.warnings, *u.warnings]
                r = rules.apply(_with_target_warnings(results[u.key], extra))
                per_unit.append(r.model_copy(update={"scope": "unit"}) if t.property_units else r)
            if not t.property_units:
                rows.append(Row(t.no, "target", t.units[0].type, t.units[0].code, per_unit[0]))
                continue
            for u, r in zip(t.units, per_unit, strict=True):
                rows.append(Row(t.no, "unit", u.type, u.code, r))
            if per_unit:
                agg = aggregate(rules, t, per_unit)
            else:
                pu = Unit("property", t.given.designation, t.target_obj)
                agg = rules.apply(make(spec, ctx, pu, "no_data", reason=NO_UNITS))
            agg = _with_target_warnings(agg, list(t.given.warnings))
            rows.append(Row(t.no, "target", "property", t.given.designation, agg))
    return targets, rows


# --- storing -----------------------------------------------------------------------------

_INSERT_RESULT = """
INSERT INTO work.check_result (run_id, target_no, scope, unit_type, unit_code, module, module_no,
    module_version, status, reason, risk, rule_ids, items, match_type, warnings, source, sources,
    dataset_version_ids, display, computed_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""


def _j(x) -> str:
    return json.dumps(x, ensure_ascii=False)


def start_run(
    conn,
    targets_in: list[TargetIn],
    sources: list[str] | None = None,
    origin: str = "api",
    rules: RuleSet | None = None,
) -> int:
    """Check the targets now and store the run; returns the run id. Commits."""
    rules = rules or rules_mod.load()
    with conn.transaction():
        run_at = conn.execute("SELECT now()").fetchone()[0]
        selected_list = sources if sources is not None else default_sources(conn)
        check_sources(conn, selected_list)
        selected = set(selected_list)
        modules = modules_for(selected)
        pinned = pin_live(conn, run_at)
        run_id = conn.execute(
            """INSERT INTO work.run (created_at, origin, sources, modules, engine_version,
                   rule_set_version, rule_set_status, rule_set_sha256, rule_set)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (
                run_at,
                origin,
                sorted(selected),
                [m.id for m in modules],
                ENGINE_VERSION,
                rules.version,
                rules.status,
                rules.sha256,
                _j(rules.as_json()),
            ),
        ).fetchone()[0]
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO work.run_version VALUES (%s, %s, %s, %s)",
                [(run_id, p.source_id, p.version_id, _j(p.info)) for p in pinned.values()],
            )
        targets, rows = compute(conn, rules, run_at, pinned, selected, modules, targets_in)
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO work.run_target (run_id, target_no, input, type, designation,
                       given_address, project_no, warnings, units)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                [
                    (
                        run_id,
                        t.no,
                        t.given.input,
                        t.given.type,
                        t.given.designation,
                        t.given.given_address,
                        t.given.project_no,
                        _j([w.model_dump() for w in t.given.warnings]),
                        _j(
                            [
                                {
                                    "type": u.type,
                                    "designation": u.code,
                                    "warnings": [w.model_dump() for w in u.warnings],
                                }
                                for u in t.units
                            ]
                        ),
                    )
                    for t in targets
                ],
            )
            cur.executemany(_INSERT_RESULT, [_result_params(run_id, row) for row in rows])
        conn.execute(
            "UPDATE work.run SET status = 'done', finished_at = clock_timestamp() WHERE id = %s",
            (run_id,),
        )
    return run_id


def _result_params(run_id: int, row: Row) -> tuple:
    r = row.result
    return (
        run_id,
        row.target_no,
        row.scope,
        row.unit_type,
        row.unit_code,
        r.module,
        r.module_no,
        r.module_version,
        r.status,
        r.reason,
        r.risk,
        r.rule_ids,
        _j([dict(i) for i in r.items]),
        r.match_type,
        _j([w.model_dump(mode="json") for w in r.warnings]),
        _j(r.source.model_dump(mode="json")) if r.source else None,
        _j([s.model_dump(mode="json") for s in r.sources]),
        r.dataset_version_ids,
        _j(r.display.model_dump(mode="json")),
        r.computed_at,
    )


# --- reading back and replaying ------------------------------------------------------------


def stored(conn, run_id: int) -> list[Row]:
    rows = []
    for rec in conn.execute(
        """SELECT target_no, scope, unit_type, unit_code, module, module_no, module_version,
                  status, reason, risk, rule_ids, items, match_type, warnings, source, sources,
                  dataset_version_ids, display, computed_at
           FROM work.check_result WHERE run_id = %s
           ORDER BY target_no, module_no, scope DESC, unit_code""",
        (run_id,),
    ):
        (
            tno,
            scope,
            utype,
            ucode,
            module,
            mno,
            mver,
            status,
            reason,
            risk,
            rule_ids,
            items,
            match_type,
            warnings,
            source,
            sources,
            dvids,
            display,
            computed_at,
        ) = rec
        r = CheckResult(
            module=module,
            module_no=mno,
            module_version=mver,
            subject={"type": utype, "id": ucode},
            scope=scope,
            status=status,
            reason=reason,
            risk=risk,
            rule_ids=rule_ids,
            items=items,
            match_type=match_type,
            warnings=warnings,
            source=source,
            sources=sources,
            dataset_version_ids=dvids,
            computed_at=computed_at,
            display=display,
        )
        rows.append(Row(tno, scope, utype, ucode, r))
    return rows


def load_targets(conn, run_id: int) -> list[TargetIn]:
    return [
        TargetIn(
            type=typ, designation=d, input=inp, given_address=ga, project_no=pno, warnings=warns
        )
        for typ, d, inp, ga, pno, warns in conn.execute(
            "SELECT type, designation, input, given_address, project_no, warnings"
            " FROM work.run_target WHERE run_id = %s ORDER BY target_no",
            (run_id,),
        )
    ]


def replay(conn, run_id: int) -> list[Row]:
    """Recompute a stored run from its pinned versions and rule-set snapshot.
    Nothing is written."""
    created_at, sources, modules, rule_set = conn.execute(
        "SELECT created_at, sources, modules, rule_set FROM work.run WHERE id = %s", (run_id,)
    ).fetchone()
    rules = rules_mod.from_json(rule_set)
    pinned = load_pinned(conn, run_id)
    with conn.transaction(force_rollback=True):
        _, rows = compute(
            conn,
            rules,
            created_at,
            pinned,
            set(sources),
            [BY_ID[m] for m in modules],
            load_targets(conn, run_id),
        )
    return sort_rows(rows)


def sort_rows(rows: list[Row]) -> list[Row]:
    return sorted(
        rows, key=lambda r: (r.target_no, r.result.module_no, r.scope != "unit", r.unit_code)
    )
