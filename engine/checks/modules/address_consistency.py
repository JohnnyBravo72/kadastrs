"""Module 2: address consistency, "Neatbilst" (PLAN.md §6.1).

Runs once per target. The given address (a VARIS code: the address the user
typed, or the address column next to a designation) is compared with the
addresses the cadastre links to the target's objects:
- own address of a parcel, building or (via its parcel) parcel part;
- the address of a building on the parcel, or of the parcel under the building.
For a property, every unit counts. A deleted (DEL) given address is also
compared through its current successors (VARIS KODS_HIS, both directions) and
gets the warning "vēsturiska adrese".
  clear  the given address is linked (match_type own_address | linked_object_address)
  found  it is not: "Neatbilst" (match_type mismatch)
  no_data "adrese nav norādīta" when no address was given (counted as not applicable)
"""

from engine.checks.context import RunContext
from engine.checks.contract import CheckResult, Display, Warning_
from engine.checks.modules.base import ModuleSpec, make, not_found
from engine.checks.units import Unit

NOT_GIVEN = "adrese nav norādīta"
UNKNOWN_ADDRESS = "norādītā adrese nav atrasta adrešu reģistrā"


def _linked(ctx: RunContext, members: list[Unit]) -> list[dict]:
    """(object, relation, VARIS code) for every address the cadastre links."""
    t = ctx.v("cadastre_text")
    parcels = sorted(
        {m.code for m in members if m.type == "parcel"}
        | {p for m in members if m.type == "parcel_part" for p in m.obj.parcel_codes}
    )
    buildings = sorted({m.code for m in members if m.type == "building"})
    rows = ctx.conn.execute(
        """SELECT p.code, 'parcel', 'own', p.varis_code FROM ref.parcel p
           WHERE p.dataset_version_id = %(t)s AND p.code = ANY(%(p)s) AND p.varis_code IS NOT NULL
           UNION
           SELECT b.code, 'building', 'own', b.varis_code FROM ref.building b
           WHERE b.dataset_version_id = %(t)s AND b.code = ANY(%(b)s) AND b.varis_code IS NOT NULL
           UNION
           SELECT b.code, 'building', 'on_parcel', b.varis_code
           FROM ref.building_parcel bp
           JOIN ref.building b ON b.dataset_version_id = bp.dataset_version_id
                              AND b.code = bp.building_code
           WHERE bp.dataset_version_id = %(t)s AND bp.parcel_code = ANY(%(p)s)
             AND NOT b.not_exist AND b.varis_code IS NOT NULL
           UNION
           SELECT p.code, 'parcel', 'under_building', p.varis_code
           FROM ref.building_parcel bp
           JOIN ref.parcel p ON p.dataset_version_id = bp.dataset_version_id
                            AND p.code = bp.parcel_code
           WHERE bp.dataset_version_id = %(t)s AND bp.building_code = ANY(%(b)s)
             AND p.varis_code IS NOT NULL
           ORDER BY 3 DESC, 1, 4""",
        {"t": t, "p": parcels, "b": buildings},
    ).fetchall()
    return [
        {"object": o, "object_type": ot, "relation": rel, "varis_code": vc}
        for o, ot, rel, vc in rows
    ]


def run(ctx: RunContext, units: list[Unit]) -> dict[str, CheckResult]:
    v = ctx.v("varis_addresses")
    c = ctx.conn
    out: dict[str, CheckResult] = {}
    for u in units:
        members = [m for m in (u.members or [u]) if m.found]
        if u.given_address is None:
            out[u.key] = make(SPEC, ctx, u, "no_data", reason=NOT_GIVEN)
            continue
        if not members:
            out[u.key] = not_found(SPEC, ctx, u)
            continue
        given = c.execute(
            "SELECT code, status, full_text FROM ref.address WHERE dataset_version_id = %s"
            " AND code = %s",
            (v, u.given_address),
        ).fetchone()
        if given is None:
            out[u.key] = make(SPEC, ctx, u, "no_data", reason=UNKNOWN_ADDRESS)
            continue
        code, status, text = given
        warns: list[Warning_] = []
        compare = {code}
        if status == "DEL":
            successors = sorted(
                r[0]
                for r in c.execute(
                    """SELECT code_his FROM ref.address_history
                       WHERE dataset_version_id = %(v)s AND code = %(c)s AND code_his IS NOT NULL
                       UNION
                       SELECT code FROM ref.address_history
                       WHERE dataset_version_id = %(v)s AND code_his = %(c)s""",
                    {"v": v, "c": code},
                )
            )
            compare |= set(successors)
            warns.append(
                Warning_(
                    code="historical_address", message="vēsturiska adrese", successors=successors
                )
            )
        linked = _linked(ctx, members)
        texts = dict(
            c.execute(
                "SELECT code, full_text FROM ref.address WHERE dataset_version_id = %s"
                " AND code = ANY(%s)",
                (v, sorted({row["varis_code"] for row in linked})),
            ).fetchall()
        )
        items = [
            row
            | {
                "address": texts.get(row["varis_code"]),
                "matches_given": row["varis_code"] in compare,
            }
            for row in linked
        ]
        hits = [i for i in items if i["matches_given"]]
        given_item = {"given_address": code, "given_text": text, "given_status": status}
        if any(h["relation"] == "own" for h in hits):
            out[u.key] = make(
                SPEC,
                ctx,
                u,
                "clear",
                items=[given_item, *items],
                match_type="own_address",
                warnings=warns,
            )
        elif hits:
            out[u.key] = make(
                SPEC,
                ctx,
                u,
                "clear",
                items=[given_item, *items],
                match_type="linked_object_address",
                warnings=warns,
            )
        else:
            if not items:
                warns.append(
                    Warning_(
                        code="no_registered_address",
                        message="objektam kadastrā nav piesaistītas adreses",
                    )
                )
            out[u.key] = make(
                SPEC,
                ctx,
                u,
                "found",
                reason="Neatbilst",
                items=[given_item, *items],
                match_type="mismatch",
                warnings=warns,
            )
    return out


SPEC = ModuleSpec(
    id="address_consistency",
    no=2,
    version="1",
    name_lv="Adreses atbilstība",
    selectors=("varis_addresses",),
    reads=("varis_addresses", "cadastre_text"),
    optional=(),
    display=Display(
        kind="table", columns=["object", "relation", "varis_code", "address", "matches_given"]
    ),
    run=run,
)
