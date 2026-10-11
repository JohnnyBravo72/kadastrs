"""GeoJSON for the results view (PLAN.md §8.2), always from a run's PINNED dataset
versions (work.run_version), never from *_current views or agency services, so
the map shows exactly what the stored results and the Excel report are about.

- targets(): every checked unit's outline (the geometry the engine checked: its
  own, or its parcel's for a building without geometry) with its worst risk.
- attention(): the overlap areas behind the findings, built with the engine's
  own code: the run's check geometry is rebuilt as in runner.replay (pinned
  versions, build_geometry; rolled back) and intersected with the features the
  engine used (flood parts unioned per layer; nature by the item's global_id
  and version). Their areas equal the stored overlap_m2. Each carries the risk
  of the rule that fired for its item (RuleSet.explain, stored rule set).
- layer(): Kadastrs, Plūdi, Daba, BIS clipped to a view box, simplified to it.
Output in EPSG:4326 (CLAUDE.md CRS).
"""

from dataclasses import dataclass
from typing import Any

from engine.checks import rules as rules_mod
from engine.checks import runner, summary
from engine.checks.context import RunContext, load_pinned
from engine.checks.describe import describe
from engine.checks.modules import BY_ID
from engine.checks.modules.nature import KINDS
from engine.checks.modules.nature import SOURCES as NATURE_SOURCES
from engine.checks.units import build_geometry, expand

MAX_BOX_M = 6_000  # a view wider or higher than this is refused ("pietuviniet karti")
MAX_FEATURES = 4000
GEOJSON = "ST_AsGeoJSON(ST_Transform({g}, 4326), 7)::json"
RISK_LV = {
    "high": "augsts",
    "medium": "vidējs",
    "unknown": "nezināms",
    "low": "zems",
    "none": "nav",
}
SPATIAL_MODULES = ("flood_10y", "nature", "bis")


class BoxTooLarge(ValueError):
    pass


class NotFound(LookupError):
    pass


@dataclass
class RunState:
    ctx: RunContext
    rules: rules_mod.RuleSet
    targets: list  # units.Target


def _feature(geometry, props: dict[str, Any]) -> dict[str, Any]:
    return {"type": "Feature", "geometry": geometry, "properties": props}


def collection(features: list[dict], **extra) -> dict[str, Any]:
    return {"type": "FeatureCollection", "features": features, **extra}


def _run_context(conn, run_id: int) -> RunContext:
    row = conn.execute(
        "SELECT created_at, sources, rule_set FROM work.run WHERE id = %s", (run_id,)
    ).fetchone()
    if row is None:
        raise NotFound(f"pārbaude {run_id} nav atrasta")
    created_at, sources, rule_set = row
    return RunContext(conn, rules_mod.from_json(rule_set), created_at, load_pinned(conn, run_id),
                      set(sources))  # fmt: skip


def _rebuild(conn, run_id: int, target_nos: list[int] | None = None) -> RunState:
    """Inside a rolled-back transaction: the run's targets and chk_geom, as the
    engine built them."""
    ctx = _run_context(conn, run_id)
    targets_in = runner.load_targets(conn, run_id)
    conn.execute("DROP TABLE IF EXISTS pg_temp.chk_geom")
    targets = expand(ctx, targets_in)
    if target_nos is not None:
        targets = [t for t in targets if t.no in target_nos]
    units = {}
    for t in targets:
        for u in t.units:
            units.setdefault(u.key, u)
    if units:
        build_geometry(ctx, list(units.values()))
    return RunState(ctx, ctx.rules, targets)


def _risks(conn, run_id: int):
    """worst risk per target and per (target, unit), from the stored results;
    not-applicable results (module 2 without an address) do not count."""
    per_target: dict[int, list[str]] = {}
    per_unit: dict[tuple[int, str], list[str]] = {}
    for row in runner.stored(conn, run_id):
        r = row.result
        if summary.bucket(r.module, r.status, r.reason) == "not_applicable":
            continue
        if row.scope == "target":
            per_target.setdefault(row.target_no, []).append(r.risk)
            if row.unit_type != "property":
                per_unit.setdefault((row.target_no, row.unit_code), []).append(r.risk)
        else:
            per_unit.setdefault((row.target_no, row.unit_code), []).append(r.risk)
    return per_target, per_unit


# --- targets -------------------------------------------------------------------------------


def targets(conn, run_id: int) -> dict[str, Any]:
    """Each checked unit's outline with its worst risk; bounding box per target."""
    with conn.transaction(force_rollback=True):
        state = _rebuild(conn, run_id)
        rules = state.rules
        per_target, per_unit = _risks(conn, run_id)
        geoms = {
            code: (basis, basis_codes, gj, box)
            for code, basis, basis_codes, gj, box in conn.execute(
                f"""SELECT code, basis, basis_codes, {GEOJSON.format(g="geom")},
                           ST_AsGeoJSON(ST_Transform(ST_Envelope(geom), 4326), 7)::json
                    FROM chk_geom WHERE geom IS NOT NULL"""  # noqa: S608
            )
        } if state.targets else {}  # fmt: skip
    head = {t["target_no"]: t for t in summary.targets(conn, run_id)}
    features = []
    boxes: dict[int, list[float]] = {}
    for t in state.targets:
        tw = rules.worst(per_target.get(t.no, []))
        for u in t.units:
            g = geoms.get(u.code)
            if g is None:
                continue
            basis, basis_codes, gj, box = g
            uw = rules.worst(per_unit.get((t.no, u.code), [])) or tw
            features.append(
                _feature(
                    gj,
                    {
                        "target_no": t.no,
                        "unit": u.code,
                        "unit_type": u.type,
                        "basis": basis,
                        "basis_codes": basis_codes,
                        "risk": uw,
                        "risk_lv": RISK_LV.get(uw),
                        "target_risk": tw,
                        "designation": t.given.designation,
                        "project_no": head.get(t.no, {}).get("project_no"),
                    },
                )
            )
            ring = box["coordinates"][0]
            xs, ys = [p[0] for p in ring], [p[1] for p in ring]
            b = boxes.get(t.no)
            boxes[t.no] = [
                min(xs + ([b[0]] if b else [])),
                min(ys + ([b[1]] if b else [])),
                max(xs + ([b[2]] if b else [])),
                max(ys + ([b[3]] if b else [])),
            ]
    return collection(features, bbox_by_target={str(k): v for k, v in boxes.items()})


# --- attention ------------------------------------------------------------------------------


def _results_for(conn, run_id: int, target_no: int):
    """The results to show per unit: unit rows when the target has units, else its row."""
    rows = [r for r in runner.stored(conn, run_id) if r.target_no == target_no]
    with_units = {r.result.module for r in rows if r.scope == "unit"}
    return [
        r
        for r in rows
        if r.result.module in SPATIAL_MODULES
        and r.result.status == "found"
        and (r.scope == "unit" or r.result.module not in with_units)
    ]


def _explained(rules, result, **kw) -> tuple[list[str], list[str], str]:
    fired = rules.explain(result, **kw)
    ids = [f.id for f in fired] or list(result.rule_ids)
    texts = [f.text_lv for f in fired]
    risk = rules.worst([f.level for f in fired]) if fired else result.risk
    return ids, texts, risk


def attention(conn, run_id: int, target_no: int) -> dict[str, Any]:
    """Overlap areas and BIS objects behind one target's findings."""
    features: list[dict] = []
    with conn.transaction(force_rollback=True):
        state = _rebuild(conn, run_id, [target_no])
        if not state.targets:
            raise NotFound(f"objekts {target_no} nav šajā pārbaudē")
        ctx, rules = state.ctx, state.rules
        for row in _results_for(conn, run_id, target_no):
            r = row.result
            unit = row.unit_code
            base = {
                "module": r.module,
                "module_no": r.module_no,
                "module_name": BY_ID[r.module].name_lv,
                "unit": unit,
            }
            for item in r.items:
                ids, texts, risk = _explained(rules, r, item=item)
                props = base | {
                    "item": describe(r.module, item),
                    "rule_ids": ids,
                    "rule_texts": texts,
                    "risk": risk,
                    "risk_lv": RISK_LV.get(risk),
                    "overlap_m2": item.get("overlap_m2"),
                    "share": item.get("share"),
                }
                features += _item_geometry(ctx, unit, r.module, item, props)
    return collection(features)


def _nature_versions(ctx: RunContext) -> list[int]:
    """The run's pinned nature versions (items keep global_id and kind, not the version)."""
    return [ctx.v(s) for s in NATURE_SOURCES if ctx.v(s) is not None]


def _item_geometry(ctx: RunContext, unit: str, module: str, item: dict, props: dict) -> list:
    c = ctx.conn
    if module == "flood_10y":
        row = c.execute(
            f"""SELECT {GEOJSON.format(g="geom")}, ST_Area(geom) FROM (
                    SELECT ST_Multi(ST_CollectionExtract(
                               ST_Union(ST_Intersection(g.geom, p.geom)), 3)) AS geom
                    FROM chk_geom g
                    JOIN ref.flood_zone_part p ON p.dataset_version_id = %s
                         AND p.role = 'finding' AND p.layer = %s
                         AND ST_Intersects(g.inner_geom, p.geom)
                    WHERE g.code = %s) x WHERE geom IS NOT NULL""",  # noqa: S608
            (ctx.v("flood_10y"), item.get("layer"), unit),
        ).fetchone()
        return [_feature(row[0], props | {"area_m2": round(row[1], 2)})] if row else []
    if module == "nature":
        row = c.execute(
            f"""SELECT {GEOJSON.format(g="geom")}, ST_Area(geom) FROM (
                    SELECT ST_Multi(ST_CollectionExtract(ST_Intersection(g.geom, n.geom), 3))
                           AS geom
                    FROM chk_geom g
                    JOIN ref.nature_area n ON n.dataset_version_id = ANY(%s)
                         AND n.global_id = %s AND n.kind = %s
                    WHERE g.code = %s) x WHERE NOT ST_IsEmpty(geom)""",  # noqa: S608
            (_nature_versions(ctx), item.get("global_id"), item.get("kind"), unit),
        ).fetchone()
        return (
            [_feature(row[0], props | {"area_m2": round(row[1], 2), "kind": item.get("kind")})]
            if row
            else []
        )  # noqa: E501
    if module == "bis":
        out = []
        extra = {
            "case_number": item.get("case_number"),
            "match_type": item.get("match_type"),
            "match_label": item.get("match_label"),
            "stage": item.get("stage"),
        }
        for gj, row_no in c.execute(
            """SELECT ST_AsGeoJSON(ST_SetSRID(ST_MakePoint(lon, lat), 4326), 7)::json, row_no
               FROM ref.bis_object WHERE dataset_version_id = %s AND row_no = ANY(%s)
                    AND lon IS NOT NULL AND lat IS NOT NULL ORDER BY row_no""",
            (ctx.v("bis_cases"), item.get("row_nos") or []),
        ):
            out.append(_feature(gj, props | extra | {"row_no": row_no, "kind": "point"}))
        for gj, code in c.execute(
            f"""SELECT {GEOJSON.format(g="geom")}, code FROM ref.kk_building
                WHERE dataset_version_id = %s AND code = ANY(%s) ORDER BY code""",  # noqa: S608
            (ctx.v("cadastre_spatial"), item.get("objects") or []),
        ):
            out.append(_feature(gj, props | extra | {"building": code, "kind": "building"}))
        return out
    return []


# --- layers ---------------------------------------------------------------------------------

LAYERS = ("kadastrs", "pludi", "daba", "bis")


def _box(conn, bbox: tuple[float, float, float, float]):
    """The view box in EPSG:10306 and its size; refused when too large."""
    x0, y0, x1, y1, w, h = conn.execute(
        """SELECT ST_XMin(b), ST_YMin(b), ST_XMax(b), ST_YMax(b),
                  ST_XMax(b) - ST_XMin(b), ST_YMax(b) - ST_YMin(b)
           FROM (SELECT ST_Envelope(ST_Transform(ST_MakeEnvelope(%s, %s, %s, %s, 4326), 10306))
                 AS b) x""",
        bbox,
    ).fetchone()
    if w > MAX_BOX_M or h > MAX_BOX_M:
        raise BoxTooLarge("pietuviniet karti: skats ir pārāk liels")
    return (x0, y0, x1, y1), max(0.2, max(w, h) / 3000)


def _source(ctx_pinned, source_id: str) -> dict[str, Any] | None:
    p = ctx_pinned.get(source_id)
    if p is None:
        return None
    return {
        "id": source_id,
        "name": p.info.get("name"),
        "dataset_date": p.info.get("dataset_date"),
        "dataset_version_id": p.version_id,
        "datagov_url": p.info.get("datagov_url"),
    }


def layer(conn, run_id: int, name: str, bbox: tuple[float, float, float, float]) -> dict:
    if name not in LAYERS:
        raise NotFound(f"slānis {name} nav zināms")
    pinned = load_pinned(conn, run_id)
    if not pinned:
        raise NotFound(f"pārbaude {run_id} nav atrasta")
    box, tol = _box(conn, bbox)
    env = "ST_MakeEnvelope(%s, %s, %s, %s, 10306)"
    v = {s: p.version_id for s, p in pinned.items()}
    feats: list[dict] = []
    sources = []
    truncated = False

    def take(rows, props_of):
        nonlocal truncated
        for n, row in enumerate(rows):
            if n >= MAX_FEATURES:
                truncated = True
                break
            feats.append(_feature(row[0], props_of(row)))

    # display only (no union): the fast clip; unions below clip with ST_Intersection,
    # because ST_ClipByBox2D may return invalid polygons that ST_Union rejects
    clip = f"ST_SimplifyPreserveTopology(ST_ClipByBox2D(geom, {env}), %s)"
    if name == "kadastrs":
        sources = [_source(pinned, "cadastre_spatial")]
        for table, kind in (("kk_parcel", "parcel"), ("kk_building", "building")):
            take(
                conn.execute(
                    f"""SELECT {GEOJSON.format(g=clip)}, code FROM ref.{table}
                        WHERE dataset_version_id = %s AND geom && {env}
                        ORDER BY code LIMIT %s""",  # noqa: S608
                    (*box, tol, v.get("cadastre_spatial"), *box, MAX_FEATURES + 1),
                ),
                lambda row, kind=kind: {"kind": kind, "code": row[1]},
            )
    elif name == "pludi":
        sources = [_source(pinned, "flood_10y")]
        fv = v.get("flood_10y")
        take(
            conn.execute(
                f"""SELECT {GEOJSON.format(g="g")}, layer, layer_name FROM (
                        SELECT p.layer, max(z.layer_name) AS layer_name,
                               ST_SimplifyPreserveTopology(
                                   ST_Union(ST_Intersection(p.geom, {env})), %s) AS g
                        FROM ref.flood_zone_part p
                        LEFT JOIN ref.flood_zone z ON z.dataset_version_id = p.dataset_version_id
                             AND z.layer = p.layer AND z.object_id = p.object_id
                        WHERE p.dataset_version_id = %s AND p.role = 'finding'
                              AND p.geom && {env}
                        GROUP BY p.layer) x WHERE NOT ST_IsEmpty(g)""",  # noqa: S608
                (*box, tol, fv, *box),
            ),
            lambda row: {"kind": "flood_10y", "layer": row[1], "layer_name": row[2]},
        )
        take(
            conn.execute(
                f"""SELECT {GEOJSON.format(g="g")} FROM (
                        SELECT ST_SimplifyPreserveTopology(ST_Difference({env},
                                   coalesce(ST_Union(ST_Intersection(p.geom, {env})),
                                            'POLYGON EMPTY'::geometry)), %s) AS g
                        FROM ref.flood_zone_part p
                        WHERE p.dataset_version_id = %s AND p.role = 'coverage_mask'
                              AND p.geom && {env}) x
                    WHERE NOT ST_IsEmpty(g)""",  # noqa: S608
                (*box, *box, tol, fv, *box),
            ),
            lambda row: {"kind": "no_flood_map", "label": "nav plūdu kartes"},
        )
    elif name == "daba":
        names = [s for s in ("nature_protected_areas", "nature_microreserves",
                             "nature_monuments", "nature_habitats") if s in v]  # fmt: skip
        sources = [_source(pinned, s) for s in names]
        take(
            conn.execute(
                f"""SELECT {GEOJSON.format(g=clip)}, kind, name, category,
                           attributes->>'SITE_NAME'
                    FROM ref.nature_area
                    WHERE dataset_version_id = ANY(%s) AND geom && {env}
                    ORDER BY kind, global_id LIMIT %s""",  # noqa: S608
                (*box, tol, [v[s] for s in names], *box, MAX_FEATURES + 1),
            ),
            lambda row: {
                "kind": row[1],
                "kind_lv": KINDS.get(row[1], row[1]),
                "name": row[4] if row[1] == "protected_area_zone" else row[2],
                "zone_type": row[2] if row[1] == "protected_area_zone" else None,
                "category": row[3],
            },
        )
    else:  # bis
        sources = [_source(pinned, "bis_cases")]
        take(
            conn.execute(
                """SELECT ST_AsGeoJSON(ST_SetSRID(ST_MakePoint(o.lon, o.lat), 4326), 7)::json,
                          o.case_number, c.object_name, c.stage, c.construction_kind,
                          c.created_date::text, o.name
                   FROM ref.bis_object o
                   LEFT JOIN ref.bis_case c ON c.dataset_version_id = o.dataset_version_id
                        AND c.case_number = o.case_number
                   WHERE o.dataset_version_id = %s AND o.lon IS NOT NULL
                         AND ST_Transform(ST_SetSRID(ST_MakePoint(o.lon, o.lat), 4326), 10306)
                             && ST_MakeEnvelope(%s, %s, %s, %s, 10306)
                   ORDER BY o.case_number, o.row_no LIMIT %s""",
                (v.get("bis_cases"), *box, MAX_FEATURES + 1),
            ),
            lambda row: {
                "kind": "bis",
                "case_number": row[1],
                "object_name": row[2] or row[6],
                "stage": row[3],
                "construction_kind": row[4],
                "created_date": row[5],
            },
        )
    return collection(feats, sources=[s for s in sources if s], truncated=truncated)
