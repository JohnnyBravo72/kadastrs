"""Module 4: flood, 10-year spring flood (PLAN.md §6.1, docs/decisions.md E7).

Findings: layers 0 and 1 (role finding) of the pinned flood_10y version.
Coverage: layer 3, the 200-year extent, used only as a mask.
  found        overlap with the 10-year zone passes the §6.3 thresholds
  not_covered  the unit's overlap with the mask does not pass them (never clear)
  clear        inside the mask and no 10-year finding; if part of the unit lies
               outside the mask, warning partial_coverage
Overlaps use the subdivided parts (ref.flood_zone_part), unioned per layer so
overlapping polygons are not counted twice. The inward-buffered geometry decides
(§6.3); the reported m2 and share are the overlap of the whole unit.
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
    "ārpus plūdu kartēs attēlotās teritorijas – plūdu karte šeit nav pieejama vai teritorija "
    "nav applūstoša pat 200 gadu scenārijā"
)

_OVERLAP = """
SELECT g.code, p.layer, ST_Area(ST_Union(ST_Intersection(g.inner_geom, p.geom))),
       ST_Area(ST_Union(ST_Intersection(g.geom, p.geom)))
FROM chk_geom g
JOIN ref.flood_zone_part p ON p.dataset_version_id = %s AND p.role = %s
                          AND ST_Intersects(g.inner_geom, p.geom)
WHERE g.code = ANY(%s)
GROUP BY g.code, p.layer
"""


def run(ctx: RunContext, units: list[Unit]) -> dict[str, CheckResult]:
    fv = ctx.v("flood_10y")
    geom = geometry_info(ctx)
    codes = sorted(
        {u.code for u in units if u.found and u.code in geom and geom[u.code].basis != "none"}
    )
    c = ctx.conn
    names = dict(
        c.execute(
            "SELECT DISTINCT layer, layer_name FROM ref.flood_zone WHERE dataset_version_id = %s",
            (fv,),
        ).fetchall()
    )
    inner_area = dict(
        c.execute("SELECT code, ST_Area(inner_geom) FROM chk_geom WHERE code = ANY(%s)", (codes,))
    )
    findings: dict[str, list[tuple[int, float, float]]] = {}
    for code, layer, inner, ov in c.execute(_OVERLAP, (fv, "finding", codes)):
        findings.setdefault(code, []).append((layer, inner, ov))
    covered: dict[str, float] = {}  # inner geometry inside the mask
    for code, _layer, inner, _ov in c.execute(_OVERLAP, (fv, "coverage_mask", codes)):
        covered[code] = covered.get(code, 0.0) + inner

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
        area = g.area_m2 or 0.0
        items = []
        for layer, inner, ov in sorted(findings.get(u.code, [])):
            share = ov / area if area else 0.0
            if overlap_passes(ctx, inner, inner / area if area else 0.0):
                items.append(
                    {
                        "layer": layer,
                        "layer_name": names.get(layer),
                        "overlap_m2": r2(ov),
                        "share": r6(share),
                    }
                )
        if items:
            out[u.key] = make(SPEC, ctx, u, "found", items=items, warnings=warns)
            continue
        cov = covered.get(u.code, 0.0)
        if not overlap_passes(ctx, cov, cov / area if area else 0.0):
            out[u.key] = make(SPEC, ctx, u, "not_covered", reason=NOT_COVERED, warnings=warns)
            continue
        outside = max(inner_area.get(u.code, 0.0) - cov, 0.0)
        if overlap_passes(ctx, outside, outside / area if area else 0.0):
            cov_share = cov / inner_area[u.code] if inner_area.get(u.code) else 0.0
            warns.append(
                Warning_(
                    code="partial_coverage",
                    message=f"plūdu karte aptver {cov_share:.0%} objekta; pārējā daļa ārpus "
                    "plūdu kartēs attēlotās teritorijas",
                    covered_share=r6(cov_share),
                )
            )
        out[u.key] = make(SPEC, ctx, u, "clear", warnings=warns)
    return out


SPEC = ModuleSpec(
    id="flood_10y",
    no=4,
    version="1",
    name_lv="Plūdi (10 gadu)",
    selectors=("flood_10y",),
    reads=("flood_10y", "cadastre_spatial", "cadastre_text"),
    optional=(),
    display=Display(kind="table", columns=["layer_name", "overlap_m2", "share"]),
    run=run,
)
