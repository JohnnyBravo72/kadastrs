"""Input resolution endpoints (PLAN.md §5.2)."""

from contextlib import contextmanager
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request

from engine.resolve import address, cadastre, notes
from engine.resolve.classify import classify
from engine.resolve.context import SourceUnavailable, live_versions, pilot, resolve_config
from engine.resolve.models import AddressObjects, AddressRef, PropertyUnits, SuggestResponse
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
        items, notices = address.suggest(conn, v, places, cfg.address, q)
        return SuggestResponse(query=q, kind=kind, suggestions=items, notices=notices)


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


@router.get("/address/{varis_code}/objects", response_model=AddressObjects)
def address_objects(
    request: Request, varis_code: str, include_non_existing: bool = False
) -> AddressObjects:
    code = varis_code.strip()
    if not (len(code) == 9 and code.isdigit()):
        raise HTTPException(status_code=422, detail="VARIS adreses kods ir 9 cipari")
    with _session(request) as (conn, v):
        places = load_places(conn, v, pilot())
        row = conn.execute(
            "SELECT full_text, status, city_atvk FROM ref.address"
            " WHERE dataset_version_id = %s AND code = %s",
            (v.varis_addresses, code),
        ).fetchone()
        if row is None:
            raise HTTPException(
                status_code=404, detail=f"adrese {code} pilota adrešu datos nav atrasta"
            )
        full_text, status, atvk = row
        ref = AddressRef(
            varis_code=code, full_text=full_text, status=status, city=places.city_by_atvk.get(atvk)
        )
        if status == "DEL":
            current = address.links(conn, v, places, code)
            warnings = [notes.historical_address()]
            warnings += [notes.current_address(c.full_text) for c in current] or [
                notes.current_unknown()
            ]
            return AddressObjects(
                address=ref,
                objects=[],
                current_addresses=current,
                non_existing_excluded=0,
                warnings=warnings,
            )
        objects, excluded = cadastre.objects_at_addresses(conn, v, [code], include_non_existing)[
            code
        ]
        warnings = [] if objects or excluded else [notes.no_objects_at_address()]
        return AddressObjects(
            address=ref, objects=objects, non_existing_excluded=excluded, warnings=warnings
        )
