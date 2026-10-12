"""Check runs (PLAN.md §6, Phase 4): start a run, read its summary and results.

Runs are synchronous: the pilot checks 100 objects in a few seconds. Results
are stored and never changed; checking again creates a new run.
"""

from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from api.db import TEST_ORIGINS, run_origin
from engine import links
from engine.checks import grouping, runner, summary
from engine.checks import rules as rules_mod
from engine.checks.contract import TargetIn
from engine.checks.describe import describe
from engine.checks.modules import BY_ID
from engine.map import geo
from engine.resolve.context import SourceUnavailable, resolve_config

router = APIRouter(prefix="/api", tags=["runs"])


class RunRequest(BaseModel):
    """Resolved targets (pick them from POST /api/resolve) and the sources to check.
    `sources` null = the registry's default selection (GET /api/sources)."""

    targets: list[TargetIn] = Field(min_length=1)
    sources: list[str] | None = None


def _summary(conn, run_id: int) -> dict[str, Any]:
    s = summary.summarize(conn, run_id)
    if s is None:
        raise HTTPException(status_code=404, detail=f"pārbaude {run_id} nav atrasta")
    names = {m: BY_ID[m].name_lv for m in s["modules"] if m in BY_ID}
    # object modules (chips, cards, overview columns) vs applicant modules (own section)
    subjects = {m: BY_ID[m].subject for m in s["modules"] if m in BY_ID}
    return s | {"module_names": names, "module_subjects": subjects}


@router.post("/runs", status_code=201)
def create_run(request: Request, body: RunRequest) -> dict[str, Any]:
    limit = resolve_config().max_rows
    if len(body.targets) > limit:
        raise HTTPException(status_code=413, detail=f"ne vairāk kā {limit} objekti vienā pārbaudē")
    with request.app.state.pool.connection() as conn:
        try:
            run_id = runner.start_run(conn, body.targets, body.sources, origin=run_origin("api"))
        except runner.UnknownSources as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except SourceUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return _summary(conn, run_id)


class RerunRequest(BaseModel):
    """kind "sources" (Atjaunot): the run's pinned versions, only the source set
    changes. kind "latest" (Pārbaudīt ar jaunākajiem datiem): live versions.
    `sources` null = the run's own source set."""

    kind: Literal["sources", "latest"]
    sources: list[str] | None = None


class Group(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=200)


class GroupingRequest(BaseModel):
    """The whole grouping: groups in display order and {target_no: group id}.
    "Bez projekta" (id "none") always exists."""

    groups: list[Group]
    assignment: dict[str, str]


# Žurnāls filters. A run's projects are the names of its current grouping (the
# newest work.run_grouping row), else its targets' project numbers.
_JOURNAL_WHERE = """
WHERE (%(tests)s OR r.origin <> ALL(%(test_origins)s))
  AND (%(date_from)s::date IS NULL
       OR (r.created_at AT TIME ZONE 'Europe/Riga')::date >= %(date_from)s::date)
  AND (%(date_to)s::date IS NULL
       OR (r.created_at AT TIME ZONE 'Europe/Riga')::date <= %(date_to)s::date)
  AND (%(project)s::text IS NULL OR
       CASE WHEN EXISTS (SELECT 1 FROM work.run_grouping g WHERE g.run_id = r.id)
       THEN EXISTS (
           SELECT 1 FROM jsonb_array_elements(
               (SELECT g.groups FROM work.run_grouping g WHERE g.run_id = r.id
                ORDER BY g.id DESC LIMIT 1)) e
           WHERE e->>'id' <> 'none' AND e->>'name' ILIKE %(project)s ESCAPE '\\')
       ELSE EXISTS (SELECT 1 FROM work.run_target t
                    WHERE t.run_id = r.id AND t.project_no ILIKE %(project)s ESCAPE '\\')
       END)
"""


def _like(text: str | None) -> str | None:
    if not text or not text.strip():
        return None
    escaped = text.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _journal(
    conn,
    limit: int,
    offset: int,
    tests: bool = False,
    project: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    params = {
        "tests": tests,
        "test_origins": list(TEST_ORIGINS),
        "project": _like(project),
        "date_from": date_from,
        "date_to": date_to,
        "limit": limit,
        "offset": offset,
    }
    total = conn.execute(
        f"SELECT count(*) FROM work.run r {_JOURNAL_WHERE}",  # noqa: S608  (fixed text)
        params,
    ).fetchone()[0]
    runs = conn.execute(
        f"""SELECT r.id, r.created_at, r.origin, r.status, r.sources, r.modules,
                  r.parent_run_id, r.rerun_kind, r.rule_set->'risk_order',
                  (SELECT count(*) FROM work.run_target t WHERE t.run_id = r.id)
           FROM work.run r {_JOURNAL_WHERE}
           ORDER BY r.id DESC LIMIT %(limit)s OFFSET %(offset)s""",  # noqa: S608  (fixed text)
        params,
    ).fetchall()
    ids = [r[0] for r in runs]
    risks: dict[int, set[str]] = {}
    for run_id, risk in conn.execute(
        """SELECT DISTINCT run_id, risk FROM work.check_result
           WHERE run_id = ANY(%s) AND scope IN ('target', 'applicant')
             AND NOT (module = 'address_consistency' AND reason IS NOT DISTINCT FROM %s)""",
        (ids, summary.NOT_GIVEN),
    ):
        risks.setdefault(run_id, set()).add(risk)
    out = []
    for rid, created, origin, status, sources, modules, parent, kind, order, n in runs:
        worst = next((r for r in order or summary.RISKS if r in risks.get(rid, ())), None)
        g = grouping.current(conn, rid)
        used = set(g["assignment"].values())
        projects = [
            x["name"] for x in g["groups"] if x["id"] != grouping.NONE_ID and x["id"] in used
        ]
        out.append(
            {
                "id": rid,
                "created_at": created,
                "origin": origin,
                "status": status,
                "targets": n,
                "projects": projects,
                "risk": worst,
                "sources": sources,
                "modules": modules,
                "parent_run_id": parent,
                "rerun_kind": kind,
                "test": origin in TEST_ORIGINS,
            }
        )
    return {"runs": out, "total": total, "limit": limit, "offset": offset}


@router.get("/runs")
def list_runs(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    tests: bool = False,
    project: str | None = Query(None, max_length=100),
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict[str, Any]:
    """Žurnāls: earlier runs, newest first, a page at a time, with objects,
    projects (current grouping) and the overall risk. Runs of test servers
    (origin test / e2e) only with `tests=true`; `project` matches a project
    name; `date_from` / `date_to` are days in Latvian time. All runs on this
    server until sign-in exists (Phase 10)."""
    with request.app.state.pool.connection() as conn:
        return _journal(conn, limit, offset, tests, project, date_from, date_to)


@router.post("/runs/{run_id}/rerun", status_code=201)
def rerun_run(request: Request, run_id: int, body: RerunRequest) -> dict[str, Any]:
    """A new run with the same targets, linked by parent_run_id; the stored run is
    not changed. The answer lists the sources whose version changed."""
    with request.app.state.pool.connection() as conn:
        _summary(conn, run_id)
        try:
            new_id = runner.rerun(conn, run_id, body.sources, body.kind, origin=run_origin("api"))
        except runner.UnknownSources as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except runner.RunNotFound as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except SourceUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return _summary(conn, new_id) | {"version_changes": runner.version_changes(conn, new_id)}


@router.get("/runs/{run_id}/changes")
def run_changes(request: Request, run_id: int) -> list[dict[str, Any]]:
    """Sources whose pinned version differs from the parent run's."""
    with request.app.state.pool.connection() as conn:
        _summary(conn, run_id)
        return runner.version_changes(conn, run_id)


@router.get("/runs/{run_id}/groups")
def get_groups(request: Request, run_id: int) -> dict[str, Any]:
    """The current project grouping (newest stored row, else from the input's
    project numbers)."""
    with request.app.state.pool.connection() as conn:
        _summary(conn, run_id)
        return grouping.current(conn, run_id)


@router.post("/runs/{run_id}/groups", status_code=201)
def save_groups(request: Request, run_id: int, body: GroupingRequest) -> dict[str, Any]:
    """Store a new grouping row (insert-only); check results are not touched."""
    with request.app.state.pool.connection() as conn:
        _summary(conn, run_id)
        try:
            return grouping.save(
                conn, run_id, [g.model_dump() for g in body.groups], body.assignment
            )
        except grouping.GroupingError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


def _result_json(r, rule_by_id: dict, unit_type: str, unit_code: str, point=None) -> dict[str, Any]:
    return r.model_dump(mode="json") | {
        "summary_status": summary.bucket(r.module, r.status, r.reason),
        "module_name": BY_ID[r.module].name_lv,
        "items_text": [describe(r.module, i) for i in r.items],
        "item_links": [
            [lk.as_json() for lk in links.item_links(r.module, i, unit_type, unit_code, point)]
            for i in r.items
        ],
        "rules": [
            {"id": i, "level": rule_by_id[i].level, "text_lv": rule_by_id[i].text_lv}
            for i in r.rule_ids
            if i in rule_by_id
        ],
    }


@router.get("/runs/{run_id}/applicants")
def get_applicants(request: Request, run_id: int) -> list[dict[str, Any]]:
    """The applicant section (Phase 8a): per applicant reg. no. the targets that
    name it, the results of modules 9 and 17, and the links "Skatīt UR" and
    "Skatīt sankciju sarakstā" (nothing is fetched from those systems)."""
    with request.app.state.pool.connection() as conn:
        _summary(conn, run_id)
        rule_set = conn.execute(
            "SELECT rule_set FROM work.run WHERE id = %s", (run_id,)
        ).fetchone()[0]
        by_id = {r.id: r for r in rules_mod.from_json(rule_set).rules}
        rows = [r for r in runner.stored(conn, run_id) if r.scope == "applicant"]
        out = []
        for entry in summary.applicants(conn, run_id):
            mine = [r for r in rows if r.unit_code == entry["reg_no"]]
            company = next((r.result for r in mine if r.result.module == "applicant_company"), None)
            name = company.items[0].get("name") if company and company.items else None
            out.append(
                entry
                | {
                    "name": name,
                    "results": [
                        _result_json(r.result, by_id, "applicant", r.unit_code)
                        for r in sorted(mine, key=lambda x: x.result.module_no)
                    ],
                    "links": [lk.as_json() for lk in links.applicant_links(entry["reg_no"], name)],
                }
            )
        return out


@router.get("/runs/{run_id}")
def get_run(request: Request, run_id: int) -> dict[str, Any]:
    """Run summary: rule set (version and status), dataset versions, counts per
    module by status and by risk. Module 2 without a given address counts as
    not_applicable."""
    with request.app.state.pool.connection() as conn:
        return _summary(conn, run_id)


@router.get("/runs/{run_id}/targets")
def get_run_targets(request: Request, run_id: int) -> list[dict[str, Any]]:
    with request.app.state.pool.connection() as conn:
        _summary(conn, run_id)
        return summary.targets(conn, run_id)


@router.get("/runs/{run_id}/inputs")
def get_run_inputs(request: Request, run_id: int) -> list[dict[str, Any]]:
    """The batch input rows (cleaned list) with their problems: rows that were not
    checked, an unresolved address, a dropped applicant number ("Neatrasts")."""
    with request.app.state.pool.connection() as conn:
        _summary(conn, run_id)
        return runner.stored_inputs(conn, run_id)


@router.get("/runs/{run_id}/targets/{target_no}")
def get_target_results(request: Request, run_id: int, target_no: int) -> dict[str, Any]:
    """Every result of one target: per module the target-level result (a
    property's aggregate) and, for a property, the result of each unit."""
    with request.app.state.pool.connection() as conn:
        _summary(conn, run_id)
        target = next(
            (t for t in summary.targets(conn, run_id) if t["target_no"] == target_no), None
        )
        if target is None:
            raise HTTPException(status_code=404, detail=f"objekts {target_no} nav šajā pārbaudē")
        rule_set = conn.execute(
            "SELECT rule_set FROM work.run WHERE id = %s", (run_id,)
        ).fetchone()[0]
        by_id = {r.id: r for r in rules_mod.from_json(rule_set).rules}
        rows = [
            r
            for r in runner.stored(conn, run_id)
            if r.target_no == target_no and r.scope != "applicant"
        ]
        points = geo.centres(conn, run_id, [r.unit_code for r in rows])
        modules: dict[str, dict[str, Any]] = {}
        for row in rows:
            r = row.result
            entry = modules.setdefault(
                r.module,
                {"module": r.module, "module_no": r.module_no, "result": None, "units": []},
            )
            data = r.model_dump(mode="json") | {
                "summary_status": summary.bucket(r.module, r.status, r.reason),
                "module_name": BY_ID[r.module].name_lv,
                "items_text": [describe(r.module, i) for i in r.items],
                # "Skatīt avotā": opens the item in the publisher's system (engine/links.py)
                "item_links": [
                    [
                        lk.as_json()
                        for lk in links.item_links(
                            r.module, i, row.unit_type, row.unit_code, points.get(row.unit_code)
                        )
                    ]
                    for i in r.items
                ],
                # the fired rules with their report text (the run's stored rule set)
                "rules": [
                    {"id": i, "level": by_id[i].level, "text_lv": by_id[i].text_lv}
                    for i in r.rule_ids
                    if i in by_id
                ],
            }
            if row.scope == "target":
                entry["result"] = data
            else:
                entry["units"].append(data)
        own = links.object_link(target["type"], target["designation"])
        return target | {
            "results": sorted(modules.values(), key=lambda m: m["module_no"]),
            "links": [own.as_json()] if own else [],
        }
