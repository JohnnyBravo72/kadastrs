"""Module 6: registered encumbrances, apgrūtinājumi (PLAN.md §6.1).

A list per object from the cadastre text data: a parcel with its parcel parts,
a parcel part, or a building. No ATIS geometries are open, so there is no
spatial overlap. Frozen-only encumbrances (in the 2025-01-31 list, object still
in the cadastre, code not in the current list; ref.encumbrance_frozen_status)
are never items: each is a warning line "apgrūtinājums no 2025-01-31 saraksta,
pašreizējos datos nav – pārbaudīt manuāli", and an object whose only
encumbrances are frozen-only is `found` with that reason, never `clear`.
"""

from engine.checks.context import RunContext
from engine.checks.contract import CheckResult, Display, Warning_
from engine.checks.modules.base import ModuleSpec, make, not_found
from engine.checks.modules.cadastre_facts import NOT_IN_REGISTER
from engine.checks.units import Unit

FROZEN_ONLY = "apgrūtinājums no 2025-01-31 saraksta, pašreizējos datos nav – pārbaudīt manuāli"
ONLY_FROZEN_REASON = "tikai 2025-01-31 saraksta apgrūtinājumi – pārbaudīt manuāli"


def _num(x):
    return None if x is None else float(x)


def run(ctx: RunContext, units: list[Unit]) -> dict[str, CheckResult]:
    c = ctx.conn
    t, ev = ctx.v("cadastre_text"), ctx.v("cadastre_encumbrances")
    fv, av = ctx.v("encumbrances_frozen"), ctx.v("atis_classifier")
    found = [u for u in units if u.found and u.obj.in_register]
    parcels = sorted({u.code for u in found if u.type == "parcel"})
    parts_of: dict[str, list[str]] = {}
    for parcel, part in c.execute(
        "SELECT parcel_code, code FROM ref.parcel_part WHERE dataset_version_id = %s"
        " AND parcel_code = ANY(%s) ORDER BY code",
        (t, parcels),
    ):
        parts_of.setdefault(parcel, []).append(part)
    objects = {u.code: [u.code, *parts_of.get(u.code, [])] for u in found}
    every = sorted({o for objs in objects.values() for o in objs})

    current: dict[str, list[dict]] = {}
    for row in c.execute(
        """SELECT e.object_code, e.object_type, e.kind_id, coalesce(a.description, e.kind_name),
                  a.group_name, e.encumbrance_nr, e.establish_date, e.area, e.measure, e.row_no
           FROM ref.encumbrance e
           LEFT JOIN ref.atis_classifier a ON a.dataset_version_id = %s AND a.code = e.kind_id
           WHERE e.dataset_version_id = %s AND e.object_code = ANY(%s)
           ORDER BY e.object_code, e.kind_id, e.establish_date, e.encumbrance_nr, e.row_no""",
        (av, ev, every),
    ):
        obj, otype, code, desc, group, nr, date, area, measure, row_no = row
        current.setdefault(obj, []).append(
            {
                "object_code": obj,
                "object_type": otype,
                "code": code,
                "description": desc,
                "group": group,
                "encumbrance_nr": nr,
                "establish_date": date.isoformat() if date else None,
                "area": _num(area),
                "measure": measure,
                "row_no": row_no,
            }
        )
    frozen: dict[str, list[Warning_]] = {}
    for obj, code, desc, date, file_role, row_no in c.execute(
        """SELECT s.object_code, s.code, f.description, f.establish_date, s.file_role, s.row_no
           FROM ref.encumbrance_frozen_status(%s, %s, %s) s
           JOIN ref.encumbrance_frozen f ON f.dataset_version_id = %s
                                        AND f.file_role = s.file_role AND f.row_no = s.row_no
           WHERE s.object_code = ANY(%s) AND s.frozen_only
           ORDER BY s.object_code, s.code, s.file_role, s.row_no""",
        (fv, ev, t, fv, every),
    ):
        frozen.setdefault(obj, []).append(
            Warning_(
                code="frozen_only",
                message=FROZEN_ONLY,
                object_code=obj,
                encumbrance_code=code,
                description=desc,
                establish_date=date.isoformat() if date else None,
                evidence=f"{file_role}:{row_no}",
            )
        )

    out: dict[str, CheckResult] = {}
    for u in units:
        if not u.found:
            out[u.key] = not_found(SPEC, ctx, u)
            continue
        if not u.obj.in_register:
            out[u.key] = make(SPEC, ctx, u, "no_data", reason=NOT_IN_REGISTER)
            continue
        items = [i for o in objects[u.code] for i in current.get(o, [])]
        warns = [w for o in objects[u.code] for w in frozen.get(o, [])]
        if items:
            out[u.key] = make(SPEC, ctx, u, "found", items=items, warnings=warns)
        elif warns:
            out[u.key] = make(SPEC, ctx, u, "found", reason=ONLY_FROZEN_REASON, warnings=warns)
        else:
            out[u.key] = make(SPEC, ctx, u, "clear")
    return out


SPEC = ModuleSpec(
    id="encumbrances",
    no=6,
    version="1",
    name_lv="Apgrūtinājumi",
    selectors=("cadastre_encumbrances",),
    reads=("cadastre_encumbrances", "cadastre_text", "encumbrances_frozen", "atis_classifier"),
    optional=(),
    display=Display(
        kind="table",
        columns=["object_code", "code", "description", "area", "measure", "establish_date"],
    ),
    run=run,
)
