"""Input resolution endpoints (PLAN.md §5.2)."""

from contextlib import contextmanager
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from engine.resolve import cadastre
from engine.resolve.classify import classify
from engine.resolve.context import SourceUnavailable, live_versions, pilot, resolve_config
from engine.resolve.models import PropertyUnits, SuggestResponse
from engine.resolve.places import load_places

router = APIRouter(prefix="/api", tags=["resolution"])


@contextmanager
def _session(request: Request):
    """A pooled connection plus the live versions it should read."""
    with request.app.state.pool.connection() as conn:
        try:
            versions = live_versions(conn)
        except SourceUnavailable as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        yield conn, versions


@router.get("/suggest", response_model=SuggestResponse)
def suggest(
    request: Request,
    q: str = Query(..., max_length=200),
    kind: Literal["cadastre", "address"] = "cadastre",
) -> SuggestResponse:
    cfg = resolve_config()
    with _session(request) as (conn, v):
        places = load_places(conn, v, pilot())
        if kind == "cadastre":
            items = cadastre.suggest(
                conn, v, q, cfg.cadastre_suggest_limit, places.city_of_territory
            )
            return SuggestResponse(query=q, kind=kind, suggestions=items)
        raise HTTPException(status_code=501, detail="address suggestions: not yet")


@router.get("/property/{number}/units", response_model=PropertyUnits)
def property_units(
    request: Request, number: str, include_non_existing: bool = False
) -> PropertyUnits:
    c = classify(number)
    if c.kind != "cadastre" or c.designation != "property_or_parcel":
        raise HTTPException(
            status_code=422,
            detail=c.reason or f"'{number}' nav īpašuma numurs (11 cipari)",
        )
    with _session(request) as (conn, v):
        units = cadastre.property_units(conn, v, c.value, include_non_existing)
        if units is None:
            f = cadastre.fetch(conn, v, [c.value])
            parcel = f.parcels.get(c.value)
            detail = {"reason": f"īpašums {c.value} nav atrasts", "number": c.value}
            if parcel is not None:
                detail["parcel_of"] = parcel.property_numbers
                detail["reason"] += "; tas ir zemes vienības apzīmējums"
            raise HTTPException(status_code=404, detail=detail)
        units.corrections = c.corrections
        return units
