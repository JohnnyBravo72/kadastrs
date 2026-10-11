"""Module 5: construction cases, BIS (PLAN.md §6.1).

Links come from ref.bis_links(bis_version, cadastre_text_version), computed
once per run into a temp table. One item per distinct case, with its best
match type (strongest first):
  exact_building       the case object is this building
  building_on_parcel   the case building is on this parcel (cadastre link)
  probable_parcel      designation prefix = this parcel (building missing from the cadastre)
  same_address_code    the case object's VARIS code is this object's address
  same_property        linked (by one of the above) to another object of the same property
  nearby               a case object point within bis_nearby_m of the unit (coordinates)
Every match type of the case is listed, with the source rows (evidence).
"""

from engine.checks.context import RunContext
from engine.checks.contract import CheckResult, Display
from engine.checks.modules.base import ModuleSpec, make, not_found
from engine.checks.units import Unit, geometry_info, geometry_warnings

MATCH_ORDER = [
    "exact_building",
    "building_on_parcel",
    "probable_parcel",
    "same_address_code",
    "same_property",
    "nearby",
]
STRONG = ("exact_building", "building_on_parcel", "probable_parcel")
MATCH_LABEL = {
    "exact_building": "šī būve",
    "building_on_parcel": "būve uz šīs zemes vienības",
    "probable_parcel": "iespējami šī zemes vienība (pēc apzīmējuma)",
    "same_address_code": "tā pati adrese",
    "same_property": "cits tā paša īpašuma objekts",
    "nearby": "tuvumā (≤ {m:g} m), nav piesaistīts objektam",
}


def _links_table(ctx: RunContext) -> None:
    if ctx.once("chk_bis"):
        ctx.conn.execute(
            "CREATE TEMP TABLE chk_bis ON COMMIT DROP AS SELECT * FROM ref.bis_links(%s, %s)",
            (ctx.v("bis_cases"), ctx.v("cadastre_text")),
        )
        ctx.conn.execute("CREATE INDEX ON chk_bis (parcel_code)")
        ctx.conn.execute("CREATE INDEX ON chk_bis (building_code)")
        ctx.conn.execute("ANALYZE chk_bis")


def _direct(ctx: RunContext, codes: list[str]) -> list[tuple]:
    """(object code, case, match type, row_nos) for links that name the object."""
    return ctx.conn.execute(
        """SELECT parcel_code, case_number, match_type, row_nos FROM chk_bis
           WHERE parcel_code = ANY(%(c)s)
           UNION ALL
           SELECT building_code, case_number, match_type, row_nos FROM chk_bis
           WHERE building_code = ANY(%(c)s) AND parcel_code IS NULL
           UNION ALL
           SELECT building_code, case_number, match_type, row_nos FROM chk_bis
           WHERE building_code = ANY(%(c)s) AND match_type = 'probable_parcel'""",
        {"c": codes},
    ).fetchall()


def run(ctx: RunContext, units: list[Unit]) -> dict[str, CheckResult]:
    _links_table(ctx)
    c = ctx.conn
    t, bv = ctx.v("cadastre_text"), ctx.v("bis_cases")
    found = [u for u in units if u.found]
    # A parcel part is matched on its parcel.
    keys = {
        u.code: ([u.code] if u.type != "parcel_part" else list(u.obj.parcel_codes)) for u in found
    }

    # Other objects of the same property(ies), for same_property.
    siblings: dict[str, set[str]] = {}
    numbers = sorted({n for u in found for n in u.obj.property_numbers})
    members: dict[str, set[str]] = {}
    for number, obj in c.execute(
        "SELECT property_number, object_code FROM ref.property_object"
        " WHERE dataset_version_id = %s AND property_number = ANY(%s)",
        (t, numbers),
    ):
        members.setdefault(number, set()).add(obj)
    for u in found:
        sib = set().union(*(members.get(n, set()) for n in u.obj.property_numbers))
        siblings[u.code] = {s for s in sib if len(s) in (11, 14)} - set(keys[u.code])

    every = sorted({k for ks in keys.values() for k in ks} | set().union(*siblings.values()))
    direct: dict[str, list[tuple[str, str, list[int]]]] = {}
    for obj, case, mt, rows in _direct(ctx, every):
        direct.setdefault(obj, []).append((case, mt, list(rows)))

    geom = geometry_info(ctx)
    near: dict[str, list[tuple[str, int]]] = {}
    with_geom = sorted(code for code, g in geom.items() if g.basis != "none")
    for code, case, row_no in c.execute(
        """SELECT g.code, o.case_number, o.row_no
           FROM chk_geom g
           JOIN ref.bis_object o
             ON o.dataset_version_id = %s AND o.lon IS NOT NULL AND o.lat IS NOT NULL
            AND ST_DWithin(ST_Transform(ST_SetSRID(ST_MakePoint(o.lon, o.lat), 4326), 10306),
                           g.geom, %s)
           WHERE g.code = ANY(%s)""",
        (bv, ctx.thresholds.bis_nearby_m, with_geom),
    ):
        near.setdefault(code, []).append((case, row_no))

    per_unit: dict[str, dict[str, dict]] = {}
    for u in found:
        cases: dict[str, dict] = {}

        def add(case, mt, rows, obj, cases=cases):
            e = cases.setdefault(case, {"match_types": set(), "row_nos": set(), "objects": set()})
            e["match_types"].add(mt)
            e["row_nos"].update(rows)
            e["objects"].add(obj)

        for k in keys[u.code]:
            for case, mt, rows in direct.get(k, []):
                add(case, mt, rows, k)
        for s in sorted(siblings[u.code]):
            for case, mt, rows in direct.get(s, []):
                if mt in STRONG and case not in cases:
                    add(case, "same_property", rows, s)
        for case, row_no in near.get(u.code, []):
            if case not in cases or cases[case]["match_types"] == {"nearby"}:
                add(case, "nearby", [row_no], None)
        per_unit[u.code] = cases

    all_cases = sorted({case for cases in per_unit.values() for case in cases})
    details = {
        r[0]: r[1:]
        for r in c.execute(
            """SELECT case_number, authority, application_kind, object_name, stage,
                      construction_kind, created_date
               FROM ref.bis_case WHERE dataset_version_id = %s AND case_number = ANY(%s)""",
            (bv, all_cases),
        )
    }

    run_day = ctx.run_at.date()
    out: dict[str, CheckResult] = {}
    for u in units:
        if not u.found:
            out[u.key] = not_found(SPEC, ctx, u)
            continue
        items = []
        for case, e in per_unit[u.code].items():
            types = sorted(e["match_types"], key=MATCH_ORDER.index)
            authority, app_kind, obj_name, stage, kind, created = details.get(case, (None,) * 6)
            items.append(
                {
                    "case_number": case,
                    "match_type": types[0],
                    "match_label": MATCH_LABEL[types[0]].format(m=ctx.thresholds.bis_nearby_m),
                    "match_types": types,
                    "objects": sorted(o for o in e["objects"] if o),
                    "row_nos": sorted(e["row_nos"]),
                    "object_name": obj_name,
                    "stage": stage,
                    "application_kind": app_kind,
                    "construction_kind": kind,
                    "created_date": created.isoformat() if created else None,
                    # age at the run date (stored with the run, so a replay agrees)
                    "age_years": round((run_day - created).days / 365.25, 2) if created else None,
                    "authority": authority,
                }
            )
        items.sort(key=lambda i: (MATCH_ORDER.index(i["match_type"]), i["case_number"]))
        g = geom.get(u.code)
        warns = geometry_warnings(u, g) if g else []
        out[u.key] = make(
            SPEC,
            ctx,
            u,
            "found" if items else "clear",
            items=items,
            match_type=items[0]["match_type"] if items else None,
            warnings=warns,
        )
    return out


SPEC = ModuleSpec(
    id="bis",
    no=5,
    version="3",
    name_lv="Būvniecības lietas (BIS)",
    selectors=("bis_cases",),
    reads=("bis_cases", "cadastre_text", "cadastre_spatial"),
    optional=(),
    display=Display(
        kind="table",
        columns=[
            "case_number",
            "match_label",
            "object_name",
            "stage",
            "construction_kind",
            "created_date",
        ],
    ),
    run=run,
)
