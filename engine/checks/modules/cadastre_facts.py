"""Module 1: cadastre facts (PLAN.md §6.1). Register data of each unit: area,
land use, address, property numbers and, for a parcel, the buildings on it
(buildings marked non-existing left out and counted, §6.3)."""

from engine.checks.context import RunContext
from engine.checks.contract import CheckResult, Display, Warning_
from engine.checks.modules.base import ModuleSpec, make, not_found, r2
from engine.checks.units import Unit
from engine.resolve.cadastre import object_warnings

NOT_IN_REGISTER = "nav kadastra teksta datos (tikai kadastra kartē)"


def _num(x):
    return None if x is None else float(x)


def run(ctx: RunContext, units: list[Unit]) -> dict[str, CheckResult]:
    t, v = ctx.v("cadastre_text"), ctx.v("varis_addresses")
    found = [u for u in units if u.found]
    parcels = [u.code for u in found if u.type == "parcel"]
    parts = [u.code for u in found if u.type == "parcel_part"]
    buildings = [u.code for u in found if u.type == "building"]
    c = ctx.conn

    addr = {
        code: text
        for code, text in c.execute(
            "SELECT code, full_text FROM ref.address WHERE dataset_version_id = %s"
            " AND code = ANY(%s)",
            (v, sorted({u.obj.varis_code for u in found if u.obj.varis_code})),
        )
    }
    pfacts = {
        r[0]: r[1:]
        for r in c.execute(
            "SELECT code, area_m2, land_purposes, status_kind FROM ref.parcel"
            " WHERE dataset_version_id = %s AND code = ANY(%s)",
            (t, parcels),
        )
    }
    partfacts = {
        r[0]: r[1:]
        for r in c.execute(
            "SELECT code, area_m2, land_purposes FROM ref.parcel_part"
            " WHERE dataset_version_id = %s AND code = ANY(%s)",
            (t, parts),
        )
    }
    bfacts = {
        r[0]: r[1:]
        for r in c.execute(
            """SELECT code, name, use_kind_name, building_kind_name, engineering_structure_type,
                      area_m2, construction_area_m2, ground_floors, underground_floors,
                      exploit_year, acception_years
               FROM ref.building WHERE dataset_version_id = %s AND code = ANY(%s)""",
            (t, buildings),
        )
    }
    on_parcel: dict[str, list[dict]] = {}
    excluded: dict[str, int] = {}
    for parcel, code, name, use, nx in c.execute(
        """SELECT bp.parcel_code, b.code, b.name, b.use_kind_name, b.not_exist
           FROM ref.building_parcel bp
           JOIN ref.building b ON b.dataset_version_id = bp.dataset_version_id
                              AND b.code = bp.building_code
           WHERE bp.dataset_version_id = %s AND bp.parcel_code = ANY(%s)
           ORDER BY bp.parcel_code, b.code""",
        (t, parcels),
    ):
        if nx:
            excluded[parcel] = excluded.get(parcel, 0) + 1
        else:
            on_parcel.setdefault(parcel, []).append({"code": code, "name": name or use})

    out: dict[str, CheckResult] = {}
    for u in units:
        if not u.found:
            out[u.key] = not_found(SPEC, ctx, u)
            continue
        warns = [Warning_(**n.model_dump()) for n in object_warnings(u.obj)]
        if not u.obj.in_register:
            out[u.key] = make(SPEC, ctx, u, "no_data", reason=NOT_IN_REGISTER, warnings=warns)
            continue
        item = {
            "designation": u.code,
            "type": u.obj.label,
            "address": addr.get(u.obj.varis_code),
            "varis_code": u.obj.varis_code,
            "property_numbers": u.obj.property_numbers,
            "has_geometry": u.obj.has_geometry,
        }
        if u.type == "parcel":
            area, purposes, status_kind = pfacts.get(u.code, (None, [], None))
            item |= {
                "area_m2": r2(_num(area)),
                "land_purposes": purposes,
                "status_kind": status_kind,
                "buildings_on_parcel": on_parcel.get(u.code, []),
                "non_existing_excluded": excluded.get(u.code, 0),
            }
        elif u.type == "parcel_part":
            area, purposes = partfacts.get(u.code, (None, []))
            item |= {
                "area_m2": r2(_num(area)),
                "land_purposes": purposes,
                "parcel_codes": u.obj.parcel_codes,
            }
        elif u.type == "building":
            (name, use, kind, eng, area, built_area, floors, under, year, accepted) = bfacts.get(
                u.code, (None,) * 10
            )
            item |= {
                "name": name,
                "use_kind": use,
                "building_kind": kind or eng,
                "area_m2": r2(_num(area)),
                "construction_area_m2": r2(_num(built_area)),
                "ground_floors": floors,
                "underground_floors": under,
                "exploit_year": year,
                "acception_years": accepted,
                "parcel_codes": u.obj.parcel_codes,
                "not_exist": u.obj.not_exist,
                "prereg": u.obj.prereg,
            }
        out[u.key] = make(SPEC, ctx, u, "found", items=[item], warnings=warns)
    return out


SPEC = ModuleSpec(
    id="cadastre_facts",
    no=1,
    version="1",
    name_lv="Kadastra dati",
    selectors=("cadastre_text",),
    reads=("cadastre_text", "cadastre_spatial", "varis_addresses"),
    optional=(),
    display=Display(
        kind="kv",
        columns=[
            "designation",
            "type",
            "address",
            "area_m2",
            "land_purposes",
            "name",
            "use_kind",
            "buildings_on_parcel",
            "property_numbers",
        ],
    ),
    run=run,
)
