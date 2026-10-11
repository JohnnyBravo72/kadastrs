"""Shared parts of the check modules: the spec, result building and the
common no_data cases (object not found, no geometry)."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from engine.checks.context import RunContext
from engine.checks.contract import CheckResult, Display, Subject, Warning_
from engine.checks.units import NO_GEOMETRY, NOT_FOUND, GeomInfo, Unit, geometry_warnings

Runner = Callable[[RunContext, list[Unit]], dict[str, CheckResult]]


@dataclass(frozen=True)
class ModuleSpec:
    id: str
    no: int
    version: str
    name_lv: str
    selectors: tuple[str, ...]  # the module runs when any of these sources is selected
    reads: tuple[str, ...]  # sources it needs (all pinned, else source_unavailable)
    optional: tuple[str, ...]  # sources it reads only when selected (nature layers)
    display: Display
    run: Runner

    def used_sources(self, ctx: RunContext) -> list[str]:
        opt = [s for s in self.optional if s in ctx.selected and s in ctx.pinned]
        return [*self.reads, *opt]


def make(
    spec: ModuleSpec,
    ctx: RunContext,
    unit: Unit,
    status: str,
    *,
    reason: str | None = None,
    items: list[dict[str, Any]] | None = None,
    match_type: str | None = None,
    warnings: list[Warning_] | None = None,
    sources: list[str] | None = None,
) -> CheckResult:
    used = sources if sources is not None else spec.used_sources(ctx)
    refs = ctx.refs(used)
    primary = next((r for r in refs if r.id in spec.selectors), refs[0] if refs else None)
    return CheckResult(
        module=spec.id,
        module_no=spec.no,
        module_version=spec.version,
        subject=Subject(type=unit.type, id=unit.code),
        status=status,
        reason=reason,
        items=items or [],
        match_type=match_type,
        warnings=[*unit.warnings, *(warnings or []), *ctx.stale_warnings(used)],
        source=primary,
        sources=refs,
        dataset_version_ids=sorted({r.dataset_version_id for r in refs}),
        computed_at=datetime.now(UTC),
        display=spec.display,
    )


def not_found(spec: ModuleSpec, ctx: RunContext, unit: Unit) -> CheckResult:
    return make(spec, ctx, unit, "no_data", reason=NOT_FOUND)


def no_geometry(spec: ModuleSpec, ctx: RunContext, unit: Unit, g: GeomInfo | None) -> CheckResult:
    """§6.3: neither the object nor its parcel(s) has geometry."""
    warns = geometry_warnings(unit, g)
    if not any(w.code == "no_geometry" for w in warns):
        warns.insert(0, Warning_(code="no_geometry", message="nav ģeometrijas kadastra kartē"))
    return make(spec, ctx, unit, "no_data", reason=NO_GEOMETRY, warnings=warns)


def overlap_passes(ctx: RunContext, overlap_m2: float, share: float) -> bool:
    """§6.3: a finding needs >= min_overlap_m2 or >= min_overlap_share of the parcel."""
    t = ctx.thresholds
    return overlap_m2 >= t.min_overlap_m2 or share >= t.min_overlap_share


def r2(x: float | None) -> float | None:
    return None if x is None else round(float(x), 2)


def r6(x: float | None) -> float | None:
    return None if x is None else round(float(x), 6)
