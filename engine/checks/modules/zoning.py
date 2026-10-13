"""Module 8: functional zoning (TAPIS) (PLAN.md §6.1, docs/data-sources.md §3.7).

Findings: pinned tapis_zoning role=finding (funkcionalais_zonejums).
Coverage: role=coverage_mask (speka_esosu_planojumu_teritorijas).
  found        overlap with a zone passes the §6.3 thresholds
  not_covered  outside the plan-territory mask (never clear)
  clear        inside the mask and no zone overlap; partial_coverage if the
               unit only partly lies in the mask
Items carry group_code (grupa_kods) for rules.yaml v5.
"""

from engine.checks.context import RunContext
from engine.checks.contract import CheckResult, Display, Warning_
from engine.checks.modules.base import (
    ModuleSpec,
    make,
    no_geometry,
    not_found,
    overlap_passes,
    r2,
    r6,
)
from engine.checks.units import Unit, geometry_info, geometry_warnings

NOT_COVERED = (
    "ārpus TAPIS spēkā esošo plānojumu teritorijām – zonējuma vektordati šeit nav pieejami"
)

_FINDINGS = """
SELECT g.code, p.object_id, z.group_code, z.group_name, z.zone_code, z.zone_index,
       z.zone_name, z.atvk, z.dok_id, z.dok_name,
       ST_Area(ST_Union(ST_Intersection(g.inner_geom, p.geom))),
       ST_Area(ST_Union(ST_Intersection(g.geom, p.geom)))
FROM chk_geom g
JOIN ref.zoning_zone_part p ON p.dataset_version_id = %s AND p.role = 'finding'
                           AND ST_Intersects(g.inner_geom, p.geom)
JOIN ref.zoning_zone z ON z.dataset_version_id = p.dataset_version_id
                      AND z.role = p.role AND z.object_id = p.object_id
WHERE g.code = ANY(%s)
GROUP BY g.code, p.object_id, z.group_code, z.group_name, z.zone_code, z.zone_index,
         z.zone_name, z.atvk, z.dok_id, z.dok_name
"""

_COVERED = """
SELECT g.code, ST_Area(ST_Union(ST_Intersection(g.inner_geom, p.geom)))
FROM chk_geom g
JOIN ref.zoning_zone_part p ON p.dataset_version_id = %s AND p.role = 'coverage_mask'
                           AND ST_Intersects(g.inner_geom, p.geom)
WHERE g.code = ANY(%s)
GROUP BY g.code
"""


def run(ctx: RunContext, units: list[Unit]) -> dict[str, CheckResult]:
    zv = ctx.v("tapis_zoning")
    geom = geometry_info(ctx)
    codes = sorted(
        {u.code for u in units if u.found and u.code in geom and geom[u.code].basis != "none"}
    )
    c = ctx.conn
    inner_area = dict(
        c.execute("SELECT code, ST_Area(inner_geom) FROM chk_geom WHERE code = ANY(%s)", (codes,))
    )
    findings: dict[str, list[dict]] = {}
    for row in c.execute(_FINDINGS, (zv, codes)):
        (
            code,
            oid,
            gcode,
            gname,
            zcode,
            zindex,
            zname,
            atvk,
            dok_id,
            dok_name,
            inner,
            ov,
        ) = row
        area = geom[code].area_m2 or 0.0
        if not overlap_passes(ctx, inner, inner / area if area else 0.0):
            continue
        findings.setdefault(code, []).append(
            {
                "object_id": oid,
                "group_code": gcode or "",
                "group_name": gname,
                "zone_code": zcode,
                "zone_index": zindex,
                "zone_name": zname,
                "atvk": atvk,
                "dok_id": dok_id,
                "dok_name": dok_name,
                "overlap_m2": r2(ov),
                "share": r6(ov / area if area else 0.0),
            }
        )
    covered = dict(c.execute(_COVERED, (zv, codes)))

    out: dict[str, CheckResult] = {}
    for u in units:
        if not u.found:
            out[u.key] = not_found(SPEC, ctx, u)
            continue
        g = geom.get(u.code)
        if g is None or g.basis == "none":
            out[u.key] = no_geometry(SPEC, ctx, u, g)
            continue
        warns = geometry_warnings(u, g)
        items = findings.get(u.code, [])
        if items:
            out[u.key] = make(SPEC, ctx, u, "found", items=items, warnings=warns)
            continue
        cov = covered.get(u.code, 0.0)
        area = g.area_m2 or 0.0
        if not overlap_passes(ctx, cov, cov / area if area else 0.0):
            out[u.key] = make(SPEC, ctx, u, "not_covered", reason=NOT_COVERED, warnings=warns)
            continue
        outside = max(inner_area.get(u.code, 0.0) - cov, 0.0)
        if overlap_passes(ctx, outside, outside / area if area else 0.0):
            cov_share = cov / inner_area[u.code] if inner_area.get(u.code) else 0.0
            warns.append(
                Warning_(
                    code="partial_coverage",
                    message=f"zonējuma plānojums aptver {cov_share:.0%} objekta",
                )
            )
        out[u.key] = make(SPEC, ctx, u, "clear", warnings=warns)
    return out


SPEC = ModuleSpec(
    id="zoning",
    no=8,
    version="1",
    name_lv="Zonējums (TAPIS)",
    selectors=("tapis_zoning",),
    reads=("tapis_zoning", "cadastre_spatial", "cadastre_text"),
    optional=(),
    display=Display(
        kind="table",
        columns=["group_name", "zone_index", "zone_code", "share", "overlap_m2"],
    ),
    run=run,
)
