"""Map data of a run (PLAN.md §8.2, Phase 6), from its pinned dataset versions only.

GET /api/runs/{id}/map/targets                 outlines of the checked units, worst risk
GET /api/runs/{id}/targets/{no}/attention      overlap areas and BIS objects of the findings
GET /api/runs/{id}/layers/{name}?bbox=…        kadastrs|pludi|daba|zonejums|bis (view box)
                                               (minLon,minLat,maxLon,maxLat, EPSG:4326)
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from engine.map import geo

router = APIRouter(prefix="/api/runs", tags=["map"])


def _bbox(text: str) -> tuple[float, float, float, float]:
    try:
        x0, y0, x1, y1 = (float(v) for v in text.split(","))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="bbox: minLon,minLat,maxLon,maxLat") from exc
    if not (x0 < x1 and y0 < y1 and -180 <= x0 <= 180 and -90 <= y0 <= 90):
        raise HTTPException(status_code=422, detail="bbox: minLon,minLat,maxLon,maxLat")
    return x0, y0, x1, y1


def _call(request: Request, fn, *args) -> dict[str, Any]:
    with request.app.state.pool.connection() as conn:
        try:
            return fn(conn, *args)
        except geo.NotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except geo.BoxTooLarge as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc


@router.get("/{run_id}/map/targets")
def map_targets(request: Request, run_id: int) -> dict[str, Any]:
    return _call(request, geo.targets, run_id)


@router.get("/{run_id}/targets/{target_no}/attention")
def target_attention(request: Request, run_id: int, target_no: int) -> dict[str, Any]:
    return _call(request, geo.attention, run_id, target_no)


@router.get("/{run_id}/layers/{name}")
def run_layer(
    request: Request, run_id: int, name: str, bbox: str = Query(..., max_length=100)
) -> dict[str, Any]:
    return _call(request, geo.layer, run_id, name, _bbox(bbox))
