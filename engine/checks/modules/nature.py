"""Module 3: protected nature, OZOLS scheme (PLAN.md §6.1, §6.3).

One line per protected-area feature that overlaps the unit: protected area,
its functional zone, microreserve, microreserve buffer zone, nature monument
and habitat, each kind on its own lines. Overlaps use the inward-buffered unit
geometry and need >= min_overlap_m2 or >= min_overlap_share of the unit.
Only the selected nature sources are read.
"""

from engine.checks.context import RunContext
from engine.checks.contract import CheckResult, Display
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

KINDS = {
    "protected_area": "Īpaši aizsargājama dabas teritorija",
    "protected_area_zone": "ĪADT funkcionālā zona",
    "microreserve": "Mikroliegums",
    "microreserve_buffer": "Mikrolieguma buferzona",
    "nature_monument": "Dabas piemineklis",
    "habitat": "Aizsargājams biotops",
}
SOURCES = ("nature_protected_areas", "nature_microreserves", "nature_monuments", "nature_habitats")


def run(ctx: RunContext, units: list[Unit]) -> dict[str, CheckResult]:
    used = [s for s in SOURCES if s in ctx.selected and s in ctx.pinned]
    versions = [ctx.v(s) for s in used]
    geom = geometry_info(ctx)
    codes = sorted(
        {
            u.code
            for u in units
            if u.found and geom.get(u.code, None) and geom[u.code].basis != "none"
        }
    )
    hits: dict[str, list[dict]] = {}
    for row in ctx.conn.execute(
        """SELECT g.code, g.area_m2, n.kind, n.global_id, n.dap_id, n.mrcode, n.name, n.category,
                  n.atis_code, n.atis_description, n.source_layer,
                  ST_Area(ST_Intersection(g.inner_geom, n.geom)),
                  ST_Area(ST_Intersection(g.geom, n.geom))
           FROM chk_geom g
           JOIN ref.nature_area n ON n.dataset_version_id = ANY(%s)
                                 AND ST_Intersects(g.inner_geom, n.geom)
           WHERE g.code = ANY(%s)""",
        (versions, codes),
    ):
        code, area, kind, gid, dap_id, mrcode, name, category, atis, atis_desc, layer, inner, ov = (
            row
        )
        if not overlap_passes(ctx, inner, inner / area if area else 0.0):
            continue
        share = ov / area if area else 0.0
        hits.setdefault(code, []).append(
            {
                "kind": kind,
                "kind_lv": KINDS[kind],
                "name": name,
                "category": category,
                "dap_id": dap_id,
                "mrcode": mrcode,
                "atis_code": atis,
                "atis_description": atis_desc,
                "source_layer": layer,
                "global_id": gid,
                "overlap_m2": r2(ov),
                "share": r6(share),
            }
        )
    order = list(KINDS)
    out: dict[str, CheckResult] = {}
    for u in units:
        if not u.found:
            out[u.key] = not_found(SPEC, ctx, u)
            continue
        g = geom.get(u.code)
        if g is None or g.basis == "none":
            out[u.key] = no_geometry(SPEC, ctx, u, g)
            continue
        items = sorted(
            hits.get(u.code, []),
            key=lambda i: (order.index(i["kind"]), i["name"] or "", i["global_id"]),
        )
        out[u.key] = make(
            SPEC,
            ctx,
            u,
            "found" if items else "clear",
            items=items,
            warnings=geometry_warnings(u, g),
        )
    return out


SPEC = ModuleSpec(
    id="nature",
    no=3,
    version="1",
    name_lv="Aizsargājamā daba (OZOLS)",
    selectors=SOURCES,
    reads=("cadastre_spatial", "cadastre_text"),
    optional=SOURCES,
    display=Display(kind="table", columns=["kind_lv", "name", "category", "overlap_m2", "share"]),
    run=run,
)
