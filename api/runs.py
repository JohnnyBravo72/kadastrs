"""Check runs (PLAN.md §6, Phase 4): start a run, read its summary and results.

Runs are synchronous: the pilot checks 100 objects in a few seconds. Results
are stored and never changed; checking again creates a new run.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from engine.checks import runner, summary
from engine.checks.contract import TargetIn
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
    return s


@router.post("/runs", status_code=201)
def create_run(request: Request, body: RunRequest) -> dict[str, Any]:
    limit = resolve_config().max_rows
    if len(body.targets) > limit:
        raise HTTPException(status_code=413, detail=f"ne vairāk kā {limit} objekti vienā pārbaudē")
    with request.app.state.pool.connection() as conn:
        try:
            run_id = runner.start_run(conn, body.targets, body.sources, origin="api")
        except runner.UnknownSources as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except SourceUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return _summary(conn, run_id)


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
        modules: dict[str, dict[str, Any]] = {}
        for row in runner.stored(conn, run_id):
            if row.target_no != target_no:
                continue
            r = row.result
            entry = modules.setdefault(
                r.module,
                {"module": r.module, "module_no": r.module_no, "result": None, "units": []},
            )
            data = r.model_dump(mode="json") | {
                "summary_status": summary.bucket(r.module, r.status, r.reason)
            }
            if row.scope == "target":
                entry["result"] = data
            else:
                entry["units"].append(data)
        return target | {"results": sorted(modules.values(), key=lambda m: m["module_no"])}
