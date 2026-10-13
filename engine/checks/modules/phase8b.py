"""Phase 8b check modules (PLAN.md §6.1; docs/decisions.md D11; rule set v4).

  7  ownership              object: owner type only
  10 vid_rating             applicant: A/B/C/J/N
  11 deminimis              applicant: 3-year rolling sum vs ceilings
  12 eu_funding             object: other EU projects on the same cadastre number
  12 eu_funding_applicant   applicant: other EU projects for the same reg. no.
  13 procurement            applicant: EIS contracts as buyer or winner
  18 fid_frozen_property    object: FID TA/VZD frozen real estate
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from engine.checks.context import RunContext
from engine.checks.contract import CheckResult, Display, Warning_
from engine.checks.modules.base import ModuleSpec, make, not_found
from engine.checks.units import Unit

PERSON_LV = {
    "natural": "fiziska persona",
    "legal": "juridiska persona",
    "state": "valsts",
    "municipality": "pašvaldība",
    "other": "cits",
}
LINKED_WARNING = Warning_(
    code="deminimis_linked_undertakings",
    message="Summa tikai šim reģ. Nr.; vienotā uzņēmuma saistītie uzņēmumi nav ņemti vērā"
    " – pārbaudīt manuāli",
)
EIS_COVERAGE = Warning_(
    code="eis_partial_coverage",
    message="tikai EIS e-konkursu iepirkumi",
)


# --- 7 Ownership --------------------------------------------------------------


def run_ownership(ctx: RunContext, units: list[Unit]) -> dict[str, CheckResult]:
    v = ctx.v("cadastre_ownership")
    codes = [u.code for u in units]
    by: dict[str, list[dict]] = {}
    for cad, otype, status, person, kind in ctx.conn.execute(
        """SELECT object_cadastre_nr, object_type, ownership_status, person_status, person_kind
           FROM ref.ownership WHERE dataset_version_id = %s AND object_cadastre_nr = ANY(%s)
           ORDER BY object_cadastre_nr, ownership_status, person_status""",
        (v, codes),
    ):
        by.setdefault(cad, []).append(
            {
                "object_type": otype,
                "ownership_status": status,
                "person_status": person,
                "person_kind": kind,
                "person_kind_lv": PERSON_LV.get(kind, person),
            }
        )
    out: dict[str, CheckResult] = {}
    for u in units:
        if not u.found:
            out[u.key] = not_found(OWNERSHIP, ctx, u)
            continue
        items = by.get(u.code, [])
        out[u.key] = make(
            OWNERSHIP,
            ctx,
            u,
            "found" if items else "no_data",
            reason=None if items else "īpašumtiesību statuss nav datos",
            items=items,
        )
    return out


OWNERSHIP = ModuleSpec(
    id="ownership",
    no=7,
    version="1",
    name_lv="Īpašumtiesības",
    selectors=("cadastre_ownership",),
    reads=("cadastre_ownership",),
    optional=(),
    display=Display(kind="table", columns=["ownership_status", "person_kind_lv", "object_type"]),
    run=run_ownership,
)


# --- 10 VID -------------------------------------------------------------------


def run_vid(ctx: RunContext, units: list[Unit]) -> dict[str, CheckResult]:
    v = ctx.v("vid_rating")
    regs = [u.code for u in units]
    rows = {
        r[0]: r
        for r in ctx.conn.execute(
            "SELECT reg_no, rating, explanation, rated_on FROM ref.vid_rating"
            " WHERE dataset_version_id = %s AND reg_no = ANY(%s)",
            (v, regs),
        )
    }
    out: dict[str, CheckResult] = {}
    for u in units:
        row = rows.get(u.code)
        if row is None:
            out[u.key] = make(VID, ctx, u, "no_data", reason="nav VID reitingā")
            continue
        _, rating, expl, rated = row
        out[u.key] = make(
            VID,
            ctx,
            u,
            "found",
            items=[
                {
                    "reg_no": u.code,
                    "rating": rating,
                    "explanation": expl,
                    "rated_on": rated.isoformat() if rated else None,
                }
            ],
        )
    return out


VID = ModuleSpec(
    id="vid_rating",
    no=10,
    version="1",
    name_lv="Nodokļu reitings (VID)",
    selectors=("vid_rating",),
    reads=("vid_rating",),
    optional=(),
    display=Display(kind="kv", columns=["rating", "explanation", "rated_on"]),
    run=run_vid,
    subject="applicant",
)


# --- 11 De minimis ------------------------------------------------------------


def run_deminimis(ctx: RunContext, units: list[Unit]) -> dict[str, CheckResult]:
    v = ctx.v("deminimis")
    dm = ctx.rules.de_minimis
    window = dm.window_days
    ceil_map = dict(dm.ceilings)
    start = ctx.run_at.date() - timedelta(days=window)
    regs = [u.code for u in units]
    by_reg: dict[str, list] = {}
    for reg, assign_date, amount, regul, key, programme, instrument in ctx.conn.execute(
        """SELECT reg_no, assign_date, amount, regulation, regulation_key, programme, instrument
           FROM ref.deminimis_aid
           WHERE dataset_version_id = %s AND reg_no = ANY(%s) AND assign_date >= %s
           ORDER BY reg_no, assign_date DESC""",
        (v, regs, start),
    ):
        by_reg.setdefault(reg, []).append(
            (assign_date, amount, regul, key, programme, instrument)
        )
    out: dict[str, CheckResult] = {}
    for u in units:
        rows = by_reg.get(u.code, [])
        if not rows:
            out[u.key] = make(DEMINIMIS, ctx, u, "clear", warnings=[LINKED_WARNING])
            continue
        sums: dict[str, Decimal] = {}
        titles: dict[str, str] = {}
        detail = []
        for assign_date, amount, regul, key, programme, instrument in rows:
            sums[key] = sums.get(key, Decimal(0)) + Decimal(amount)
            titles[key] = regul
            detail.append(
                {
                    "assign_date": assign_date.isoformat(),
                    "amount": float(amount),
                    "regulation": regul,
                    "regulation_key": key,
                    "programme": programme,
                    "instrument": instrument,
                }
            )
        summary = []
        for key, total in sums.items():
            ceiling = Decimal(str(ceil_map[key])) if key in ceil_map else None
            share = float(total / ceiling) if ceiling else None
            headroom = float(ceiling - total) if ceiling is not None else None
            summary.append(
                {
                    "regulation_key": key,
                    "regulation": titles[key],
                    "sum": float(total),
                    "ceiling": float(ceiling) if ceiling is not None else None,
                    # None when the regulation key has no ceiling in rules.yaml
                    "share": share,
                    "headroom": headroom,
                }
            )
        out[u.key] = make(
            DEMINIMIS, ctx, u, "found", items=summary + detail, warnings=[LINKED_WARNING]
        )
    return out


DEMINIMIS = ModuleSpec(
    id="deminimis",
    no=11,
    version="1",
    name_lv="De minimis",
    selectors=("deminimis",),
    reads=("deminimis",),
    optional=(),
    display=Display(
        kind="table",
        columns=["regulation_key", "sum", "ceiling", "headroom", "share"],
    ),
    run=run_deminimis,
    subject="applicant",
)


# --- 12 EU funding ------------------------------------------------------------


def _coverage_warnings(ctx: RunContext) -> list[Warning_]:
    v = ctx.v("eu_projects")
    if v is None:
        return []
    (proc,) = ctx.conn.execute(
        "SELECT processing FROM dataset_version WHERE id = %s", (v,)
    ).fetchone()
    for block in proc or []:
        if not isinstance(block, dict) or block.get("id") != "location_coverage":
            continue
        parts = []
        for k, val in block.items():
            if (
                k.startswith("loc_coverage_")
                and isinstance(val, dict)
                and val.get("share") is not None
            ):
                period = k.removeprefix("loc_coverage_")
                parts.append(f"{period}: {val['share']:.0%}")
        if parts:
            return [
                Warning_(
                    code="eu_location_coverage",
                    message="kadastra numurs atrašanās vietās: " + "; ".join(parts),
                )
            ]
    return []


def _project_item(row, *, match: str) -> dict:
    (
        period,
        pno,
        title,
        status,
        atype,
        reg,
        name,
        started,
        ended,
        fund,
        measure_no,
        measure_name,
        total,
        eu,
    ) = row
    return {
        "match": match,
        "period": period,
        "project_no": pno,
        "title": title,
        "status": status,
        "ongoing": (status or "") == "Līgums",
        "applicant_type": atype,
        "applicant_reg_no": reg,
        "applicant_name": name,
        "started_on": started.isoformat() if started else None,
        "ended_on": ended.isoformat() if ended else None,
        "fund": fund,
        "measure_no": measure_no,
        "measure_name": measure_name,
        "total_cost": float(total) if total is not None else None,
        "eu_funding": float(eu) if eu is not None else None,
    }


def run_eu_object(ctx: RunContext, units: list[Unit]) -> dict[str, CheckResult]:
    v = ctx.v("eu_projects")
    codes = [u.code for u in units]
    loc_rows = ctx.conn.execute(
        """SELECT l.cadastre_nr, p.period, p.project_no, p.title, p.status, p.applicant_type,
                  p.applicant_reg_no, p.applicant_name, p.started_on, p.ended_on, p.fund,
                  p.measure_no, p.measure_name, p.total_cost, p.eu_funding
           FROM ref.eu_project_location l
           JOIN ref.eu_project p
             ON p.dataset_version_id = l.dataset_version_id
            AND p.period = l.period AND p.project_no = l.project_no
           WHERE l.dataset_version_id = %s AND l.cadastre_nr = ANY(%s)
           ORDER BY l.cadastre_nr, p.period, p.project_no""",
        (v, codes),
    ).fetchall()
    by: dict[str, list[dict]] = {}
    for row in loc_rows:
        by.setdefault(row[0], []).append(_project_item(row[1:], match="object"))
    warns = _coverage_warnings(ctx)
    out: dict[str, CheckResult] = {}
    for u in units:
        if not u.found:
            out[u.key] = not_found(EU_OBJECT, ctx, u)
            continue
        items = by.get(u.code, [])
        out[u.key] = make(
            EU_OBJECT,
            ctx,
            u,
            "found" if items else "clear",
            items=items,
            match_type="object" if items else None,
            warnings=warns,
        )
    return out


def run_eu_applicant(ctx: RunContext, units: list[Unit]) -> dict[str, CheckResult]:
    v = ctx.v("eu_projects")
    regs = [u.code for u in units]
    rows = ctx.conn.execute(
        """SELECT period, project_no, title, status, applicant_type, applicant_reg_no,
                  applicant_name, started_on, ended_on, fund, measure_no, measure_name,
                  total_cost, eu_funding
           FROM ref.eu_project
           WHERE dataset_version_id = %s AND applicant_reg_no = ANY(%s)
           ORDER BY period, project_no""",
        (v, regs),
    ).fetchall()
    by: dict[str, list[dict]] = {}
    for row in rows:
        by.setdefault(row[5], []).append(_project_item(row, match="applicant"))
    out: dict[str, CheckResult] = {}
    for u in units:
        items = by.get(u.code, [])
        out[u.key] = make(
            EU_APPLICANT,
            ctx,
            u,
            "found" if items else "clear",
            items=items,
            match_type="applicant" if items else None,
            warnings=_coverage_warnings(ctx),
        )
    return out


EU_OBJECT = ModuleSpec(
    id="eu_funding",
    no=12,
    version="1",
    name_lv="ES projekti (objekts)",
    selectors=("eu_projects",),
    reads=("eu_projects",),
    optional=(),
    display=Display(
        kind="table",
        columns=["match", "period", "project_no", "status", "title", "eu_funding"],
    ),
    run=run_eu_object,
)

EU_APPLICANT = ModuleSpec(
    id="eu_funding_applicant",
    no=12,
    version="1",
    name_lv="ES projekti",
    selectors=("eu_projects",),
    reads=("eu_projects",),
    optional=(),
    display=Display(
        kind="table",
        columns=["match", "period", "project_no", "status", "title", "eu_funding"],
    ),
    run=run_eu_applicant,
    subject="applicant",
)


# --- 13 Procurement -----------------------------------------------------------


def run_procurement(ctx: RunContext, units: list[Unit]) -> dict[str, CheckResult]:
    v = ctx.v("eis_procurement")
    regs = [u.code for u in units]
    hits: dict[str, list[dict]] = {r: [] for r in regs}
    for row in ctx.conn.execute(
        """SELECT year, procurement_no, title, buyer_reg_no, winner_reg_no, winner_country,
                  status, amount, currency, signed_on, ended_on, eis_url
           FROM ref.eis_contract
           WHERE dataset_version_id = %s
             AND (buyer_reg_no = ANY(%s) OR winner_reg_no = ANY(%s))
           ORDER BY signed_on DESC NULLS LAST, year DESC, procurement_no""",
        (v, regs, regs),
    ):
        (
            year,
            pno,
            title,
            buyer,
            winner,
            country,
            status,
            amount,
            currency,
            signed,
            ended,
            url,
        ) = row
        base = {
            "year": year,
            "procurement_no": pno,
            "title": title,
            "buyer_reg_no": buyer,
            "winner_reg_no": winner,
            "winner_country": country,
            "status": status,
            "amount": float(amount) if amount is not None else None,
            "currency": currency,
            "signed_on": signed.isoformat() if signed else None,
            "ended_on": ended.isoformat() if ended else None,
            "eis_url": url,
        }
        if buyer in hits:
            hits[buyer].append({**base, "role": "buyer"})
        if winner in hits and winner != buyer:
            hits[winner].append({**base, "role": "winner"})
        elif winner in hits and winner == buyer:
            hits[winner][-1]["role"] = "buyer_and_winner"
    out: dict[str, CheckResult] = {}
    for u in units:
        items = hits.get(u.code, [])
        out[u.key] = make(
            PROCUREMENT,
            ctx,
            u,
            "found" if items else "clear",
            items=items,
            warnings=[EIS_COVERAGE],
        )
    return out


PROCUREMENT = ModuleSpec(
    id="procurement",
    no=13,
    version="1",
    name_lv="Iepirkumi (EIS)",
    selectors=("eis_procurement",),
    reads=("eis_procurement",),
    optional=(),
    display=Display(
        kind="table",
        columns=["role", "year", "procurement_no", "amount", "signed_on", "status"],
    ),
    run=run_procurement,
    subject="applicant",
)


# --- 18 FID frozen property ---------------------------------------------------


def run_fid_frozen(ctx: RunContext, units: list[Unit]) -> dict[str, CheckResult]:
    v = ctx.v("fid_frozen_property")
    codes = [u.code for u in units]
    by: dict[str, list[dict]] = {}
    for row in ctx.conn.execute(
        """SELECT cadastre_nr, asset_type, subject_link, holder_reg_no, basis,
                  sanctions_from, legal_act, published_on
           FROM ref.fid_frozen_property
           WHERE dataset_version_id = %s AND cadastre_nr = ANY(%s)
           ORDER BY cadastre_nr""",
        (v, codes),
    ):
        cad, asset, link, holder, basis, since, act, pub = row
        by.setdefault(cad, []).append(
            {
                "cadastre_nr": cad,
                "asset_type": asset,
                "subject_link": link,
                "holder_reg_no": holder,
                "basis": basis,
                "sanctions_from": since,
                "legal_act": act,
                "published_on": pub.isoformat() if pub else None,
            }
        )
    out: dict[str, CheckResult] = {}
    for u in units:
        if not u.found:
            out[u.key] = not_found(FID_FROZEN, ctx, u)
            continue
        items = by.get(u.code, [])
        out[u.key] = make(FID_FROZEN, ctx, u, "found" if items else "clear", items=items)
    return out


FID_FROZEN = ModuleSpec(
    id="fid_frozen_property",
    no=18,
    version="1",
    name_lv="Iesaldēts nekustamais īpašums (FID)",
    selectors=("fid_frozen_property",),
    reads=("fid_frozen_property",),
    optional=(),
    display=Display(
        kind="table",
        columns=["asset_type", "basis", "holder_reg_no", "sanctions_from", "legal_act"],
    ),
    run=run_fid_frozen,
)
