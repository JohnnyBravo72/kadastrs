"""Bulk resolution: raw values in, one ResolvedRow per value (POST /api/resolve)."""

from typing import Literal

from pydantic import BaseModel, Field

from engine.resolve import address, cadastre, notes
from engine.resolve.classify import Classified, classify
from engine.resolve.context import Pilot, ResolveConfig, Versions
from engine.resolve.models import Note, ResolvedRow
from engine.resolve.places import Places

RowKind = Literal["auto", "cadastre", "address"]


class RowIn(BaseModel):
    value: str | int | float | None
    kind: RowKind = "auto"  # what the column holds; "auto" decides per value


class ResolveRequest(BaseModel):
    """`values` for a plain pasted list; `rows` when a column says what it holds.
    Both may be given; `values` come first."""

    values: list[str | int | float | None] = Field(default_factory=list)
    rows: list[RowIn] = Field(default_factory=list)

    def all_rows(self) -> list[RowIn]:
        return [RowIn(value=x) for x in self.values] + list(self.rows)


class ResolveResponse(BaseModel):
    rows: list[ResolvedRow]
    summary: dict[str, int]  # rows per status
    versions: dict[str, int]  # dataset versions read (provenance)


def _wrong_kind(c: Classified, kind: RowKind) -> str | None:
    if kind == "cadastre" and c.kind in ("address", "address_code"):
        return "kolonnā jābūt kadastra apzīmējumam vai īpašuma numuram"
    if kind == "address" and c.kind == "cadastre":
        return "kolonnā jābūt adresei"
    return None


def resolve(
    conn, v: Versions, places: Places, pilot: Pilot, cfg: ResolveConfig, rows: list[RowIn]
) -> ResolveResponse:
    classified = [classify(r.value) for r in rows]
    facts = cadastre.fetch(conn, v, [c.value for c in classified if c.kind == "cadastre"])
    out: list[ResolvedRow] = []
    resolved_addresses: dict[int, str] = {}  # row -> VARIS code whose objects to attach

    for i, (row, c) in enumerate(zip(rows, classified, strict=True)):
        r = ResolvedRow(
            index=i,
            input=c.input,
            kind=c.kind,
            normalized=c.value,
            status="empty" if c.kind == "empty" else "invalid",
            corrections=c.corrections,
            warnings=list(c.warnings),
            reason=c.reason,
        )
        out.append(r)
        if c.kind in ("empty", "invalid"):
            continue
        if wrong := _wrong_kind(c, row.kind):
            r.status, r.reason = "invalid", wrong
            continue

        if c.kind == "cadastre":
            d = cadastre.decide(c, facts, pilot)
            r.status, r.type, r.matches, r.reason = d.status, d.type, d.matches, d.reason
            r.warnings += d.warnings
            if d.status == "resolved":
                r.warnings += d.matches[0].warnings
            continue

        if c.kind == "address_code":
            d = address.by_code(conn, v, places, c.value)
        else:
            d, q = address.decide(conn, v, places, cfg.address, c.value)
            r.normalized = q.norm
        r.status, r.matches, r.reason = d.status, d.matches, d.reason
        r.warnings += d.warnings
        if d.status == "resolved":
            r.type = "address"
            resolved_addresses[i] = d.resolved_code

    _attach_objects(conn, v, out, resolved_addresses)
    _mark_duplicates(out)
    summary: dict[str, int] = {}
    for r in out:
        summary[r.status] = summary.get(r.status, 0) + 1
    return ResolveResponse(rows=out, summary=summary, versions=v.as_dict())


def _attach_objects(conn, v: Versions, out: list[ResolvedRow], codes: dict[int, str]) -> None:
    """Cadastre objects at each resolved address (buildings marked non-existing left out)."""
    if not codes:
        return
    found = cadastre.objects_at_addresses(conn, v, sorted(set(codes.values())), False)
    for i, code in codes.items():
        objects, excluded = found[code]
        match = next(m for m in out[i].matches if m.designation == code)
        match.objects = objects
        if not objects and not excluded:
            out[i].warnings.append(notes.no_objects_at_address())


def _mark_duplicates(out: list[ResolvedRow]) -> None:
    """Same resolved object, or (unresolved) the same normalised value, as an
    earlier row. Duplicates stay in the output, flagged."""
    first: dict[tuple[str, ...], int] = {}
    for r in out:
        if r.normalized is None or r.kind in ("empty", "invalid"):
            continue
        if r.status == "resolved":
            target = next(m for m in r.matches if m.type == r.type)
            key = ("resolved", target.type, target.designation)
        else:
            key = (r.kind, r.normalized)
        if key in first:
            r.duplicate_of = first[key]
            r.warnings.append(
                Note(
                    code="duplicate",
                    message=f"atkārtojas: tāda pati vērtība rindā {first[key] + 1}",
                )
            )
        else:
            first[key] = r.index
