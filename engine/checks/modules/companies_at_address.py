"""Module 14 "Uzņēmumi adresē" (PLAN.md §6.1, Phase 8a): legal entities whose
legal address (UR `addressid`) is a VARIS address of the object.

Addresses of a unit: its own VARIS code; for a parcel also the codes of the
buildings on it (the cadastre's own building -> parcel link); for a building
without a code, or a parcel part, the codes of its parcel(s). A legal address is
not proof of activity: every result says so. Per address the item gives the
active and ended companies, and what stands there (residential building use
11xx, the largest building area), so the rules can tell a mass-registration
address in a small or residential building from an office centre (rules.yaml).
Individual merchants' names are not stored (D10): their entries show the form only.
"""

from engine.checks.context import RunContext
from engine.checks.contract import CheckResult, Display, Warning_
from engine.checks.modules.base import ModuleSpec, make, not_found
from engine.checks.units import Unit

MAX_LISTED = 50  # companies listed per address; the counts are always complete
LEGAL_ADDRESS_ONLY = Warning_(
    code="legal_address_only", message="juridiskā adrese, nav darbības pierādījums"
)
NO_ADDRESS = Warning_(
    code="no_address", message="objektam nav VARIS adreses: uzņēmumi pēc adreses nav meklēti"
)

_CODES_SQL = """
WITH u AS (SELECT unnest(%(codes)s::text[]) AS code)
SELECT u.code, p.varis_code, 'own' FROM u
  JOIN ref.parcel p ON p.dataset_version_id = %(t)s AND p.code = u.code
 WHERE p.varis_code IS NOT NULL
UNION
SELECT u.code, b.varis_code, 'own' FROM u
  JOIN ref.building b ON b.dataset_version_id = %(t)s AND b.code = u.code
 WHERE b.varis_code IS NOT NULL
UNION
-- buildings standing on a parcel
SELECT u.code, b.varis_code, 'building_on_parcel' FROM u
  JOIN ref.building_parcel bp ON bp.dataset_version_id = %(t)s AND bp.parcel_code = u.code
  JOIN ref.building b ON b.dataset_version_id = %(t)s AND b.code = bp.building_code
 WHERE b.varis_code IS NOT NULL AND NOT b.not_exist
UNION
-- a building without its own code: the parcel(s) it stands on
SELECT u.code, p.varis_code, 'parcel' FROM u
  JOIN ref.building b ON b.dataset_version_id = %(t)s AND b.code = u.code AND b.varis_code IS NULL
  JOIN ref.building_parcel bp ON bp.dataset_version_id = %(t)s AND bp.building_code = b.code
  JOIN ref.parcel p ON p.dataset_version_id = %(t)s AND p.code = bp.parcel_code
 WHERE p.varis_code IS NOT NULL
UNION
-- a parcel part: its parcel (the first 11 digits)
SELECT u.code, p.varis_code, 'parcel' FROM u
  JOIN ref.parcel p ON p.dataset_version_id = %(t)s AND p.code = left(u.code, 11)
 WHERE length(u.code) = 15 AND p.varis_code IS NOT NULL
"""


def run(ctx: RunContext, units: list[Unit]) -> dict[str, CheckResult]:
    t, cv = ctx.v("cadastre_text"), ctx.v("ur_companies")
    found = [u for u in units if u.found]
    codes_of: dict[str, set[str]] = {}
    for code, varis, _via in ctx.conn.execute(
        _CODES_SQL, {"codes": [u.code for u in found], "t": t}
    ):
        codes_of.setdefault(code, set()).add(varis)
    all_codes = sorted({c for cs in codes_of.values() for c in cs})

    companies: dict[str, list[tuple]] = {}
    for varis, reg, name, form, form_text, registered, closed, address in ctx.conn.execute(
        """SELECT varis_code, reg_no, name, form, form_text, registered, closed, address
           FROM ref.ur_company WHERE dataset_version_id = %s AND varis_code = ANY(%s)
           ORDER BY varis_code, registered DESC NULLS LAST, reg_no""",
        (cv, all_codes),
    ):
        companies.setdefault(varis, []).append(
            (reg, name, form, form_text, registered, closed, address)
        )
    buildings = {
        varis: (residential, area, uses)
        for varis, residential, area, uses in ctx.conn.execute(
            """SELECT varis_code, bool_or(use_kind_id LIKE '11%%'), max(area_m2),
                      array_agg(DISTINCT use_kind_name ORDER BY use_kind_name)
                        FILTER (WHERE use_kind_name IS NOT NULL)
               FROM ref.building WHERE dataset_version_id = %s AND varis_code = ANY(%s)
                AND NOT not_exist
               GROUP BY varis_code""",
            (t, all_codes),
        )
    }

    out: dict[str, CheckResult] = {}
    for u in units:
        if not u.found:
            out[u.key] = not_found(SPEC, ctx, u)
            continue
        codes = sorted(codes_of.get(u.code, ()))
        if not codes:
            out[u.key] = make(SPEC, ctx, u, "clear", warnings=[NO_ADDRESS])
            continue
        items = []
        for varis in codes:
            rows = companies.get(varis, [])
            active = [r for r in rows if r[5] is None]
            if not active:
                continue
            residential, area, uses = buildings.get(varis, (False, None, []))
            items.append(
                {
                    "varis_code": varis,
                    "address": next((r[6] for r in rows if r[6]), None),
                    "active_count": len(active),
                    "ended_count": len(rows) - len(active),
                    "residential": bool(residential),
                    "building_area_m2": float(area) if area is not None else None,
                    "building_uses": list(uses or []),
                    "companies": [
                        {
                            "reg_no": reg,
                            "name": name,
                            "form": form,
                            "form_text": form_text,
                            "registered": registered.isoformat() if registered else None,
                        }
                        for reg, name, form, form_text, registered, _c, _a in active[:MAX_LISTED]
                    ],
                    "not_listed": max(0, len(active) - MAX_LISTED),
                }
            )
        out[u.key] = make(
            SPEC,
            ctx,
            u,
            "found" if items else "clear",
            items=items,
            warnings=[LEGAL_ADDRESS_ONLY] if items else [],
        )
    return out


SPEC = ModuleSpec(
    id="companies_at_address",
    no=14,
    version="1",
    name_lv="Uzņēmumi adresē",
    selectors=("ur_companies",),
    reads=("ur_companies", "cadastre_text"),
    optional=(),
    display=Display(
        kind="table",
        columns=["address", "active_count", "ended_count", "residential", "building_area_m2"],
    ),
    run=run,
)
