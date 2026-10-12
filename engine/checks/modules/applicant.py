"""Applicant modules (PLAN.md §6.1, Phase 8a; docs/decisions.md D10). Subject
kind "applicant": each runs once per applicant reg. no. in the run.

  9  Pieteicējs (UR)  status (aktīvs / likvidēts / reorganizēts), form, legal
                      address, registration and end dates, and open insolvency
                      or legal protection proceedings
  17 Sankcijas        the applicant's reg. no. against the legal-entity entries of
                      the UR sanctions file and FID's frozen-asset subjects; a
                      name-only hit is flagged for manual review, never a finding

Only legal-entity data is stored (D10): no names of natural persons; IK / IND
names are not stored at all, so their items carry name None.
"""

import re

from engine.checks.context import RunContext
from engine.checks.contract import CheckResult, Display, Warning_
from engine.checks.modules.base import ModuleSpec, make
from engine.checks.units import Unit

NOT_IN_UR = "nav atrasts Uzņēmumu reģistrā"
STATUS_LV = {
    "active": "aktīvs",
    "liquidated": "likvidēts / izslēgts",
    "reorganized": "reorganizēts",
}
PROCEEDING_LV = {
    "INSOLVENCY": "maksātnespējas process",
    "LEGAL_PROTECTION": "tiesiskās aizsardzības process",
    "OUT_OF_COURT_LEGAL_PROTECTION": "ārpustiesas tiesiskās aizsardzības process",
}
NAME_NOT_STORED = "nosaukums nav saglabāts (individuālais komersants vai uzņēmums)"


# --- 9 Pieteicējs (UR) ----------------------------------------------------------------------


def run_company(ctx: RunContext, units: list[Unit]) -> dict[str, CheckResult]:
    cv, iv = ctx.v("ur_companies"), ctx.v("ur_insolvency")
    regs = [u.code for u in units]
    companies = {
        r[0]: r[1:]
        for r in ctx.conn.execute(
            """SELECT reg_no, name, form, form_text, register, registered, terminated, closed,
                      address, varis_code
               FROM ref.ur_company WHERE dataset_version_id = %s AND reg_no = ANY(%s)""",
            (cv, regs),
        )
    }
    proceedings: dict[str, list[dict]] = {}
    for reg, pid, started, ended, form, typ, res_name in ctx.conn.execute(
        """SELECT reg_no, proceeding_id, started_on, ended_on, form, type, resolution_name
           FROM ref.ur_insolvency WHERE dataset_version_id = %s AND reg_no = ANY(%s)
           ORDER BY reg_no, started_on DESC NULLS LAST, proceeding_id""",
        (iv, regs),
    ):
        proceedings.setdefault(reg, []).append(
            {
                "proceeding_id": pid,
                "form": form,
                "form_lv": PROCEEDING_LV.get(form, form),
                "type": typ,
                "started_on": started.isoformat() if started else None,
                "ended_on": ended.isoformat() if ended else None,
                "open": ended is None,
                "resolution": res_name,
            }
        )
    run_day = ctx.run_at.date()
    out: dict[str, CheckResult] = {}
    for u in units:
        c = companies.get(u.code)
        if c is None:
            out[u.key] = make(COMPANY, ctx, u, "no_data", reason=NOT_IN_UR)
            continue
        name, form, form_text, register, registered, terminated, closed, address, varis = c
        status = {"L": "liquidated", "R": "reorganized"}.get(closed or "", "active")
        procs = proceedings.get(u.code, [])
        open_forms = sorted({p["form"] for p in procs if p["open"]})
        item = {
            "reg_no": u.code,
            "name": name,
            "name_note": None if name else NAME_NOT_STORED,
            "form": form,
            "form_text": form_text,
            "register": register,
            "status": status,
            "status_lv": STATUS_LV[status],
            "registered": registered.isoformat() if registered else None,
            "terminated": terminated.isoformat() if terminated else None,
            # age at the run date (stored with the run, so a replay agrees)
            "age_days": (run_day - registered).days if registered else None,
            "address": address,
            "varis_code": varis,
            "open_proceedings": open_forms,
            "open_proceeding": open_forms[0] if open_forms else None,
            "proceedings": procs,
        }
        out[u.key] = make(COMPANY, ctx, u, "found", items=[item])
    return out


COMPANY = ModuleSpec(
    id="applicant_company",
    no=9,
    version="1",
    name_lv="Pieteicējs (UR)",
    selectors=("ur_companies",),
    reads=("ur_companies", "ur_insolvency"),
    optional=(),
    display=Display(
        kind="kv",
        columns=["reg_no", "name", "form_text", "status_lv", "registered", "terminated", "address"],
    ),
    run=run_company,
    subject="applicant",
)


# --- 17 Sankcijas ---------------------------------------------------------------------------

SOURCES = ("ur_sanctions", "fid_sanctions")
NAME_ONLY = Warning_(
    code="sanctions_name_only",
    message="nosaukums sakrīt ar sankciju saraksta ierakstu bez reģistrācijas numura:"
    " pārbaudīt manuāli",
)


def normalise_name(name: str | None) -> str:
    """Compare names without case, quotes, punctuation and spacing."""
    return re.sub(r"[^0-9a-zāčēģīķļņšūž]+", "", (name or "").casefold())


def run_sanctions(ctx: RunContext, units: list[Unit]) -> dict[str, CheckResult]:
    used = [s for s in SOURCES if s in ctx.selected and s in ctx.pinned]
    regs = [u.code for u in units]
    hits: dict[str, list[dict]] = {}
    if "ur_sanctions" in used:
        for row in ctx.conn.execute(
            """SELECT entry_id, entity_type, reg_no, subject_reg_no, entity_name, entity_country,
                      position_text_lv, list, list_text, program, entry_date, legal_base,
                      legal_base_url
               FROM ref.ur_sanction WHERE dataset_version_id = %s
                 AND (reg_no = ANY(%s) OR subject_reg_no = ANY(%s))
               ORDER BY entry_id""",
            (ctx.v("ur_sanctions"), regs, regs),
        ):
            (eid, etype, reg, subj, ename, country, pos, lst, lst_text, prog, entry, base, url) = (
                row
            )
            common = {
                "source": "ur_sanctions",
                "entry_id": eid,
                "entity_type": etype,
                "entity_name": ename,
                "entity_country": country,
                "list": lst,
                "list_text": lst_text,
                "program": prog,
                "entry_date": entry.isoformat() if entry else None,
                "legal_base": base,
                "legal_base_url": url,
            }
            if reg in regs:
                hits.setdefault(reg, []).append(common | {"match": "reg_no"})
            if subj in regs:
                # a sanctioned entity linked to the applicant (entity rows only, D10)
                hits.setdefault(subj, []).append(
                    common | {"match": "linked_entity", "relationship": pos}
                )
    if "fid_sanctions" in used:
        for row_no, reg, ename, country, asset, basis, since, act in ctx.conn.execute(
            """SELECT row_no, reg_no, entity_name, country, asset_kind, basis, sanctions_from,
                      legal_act
               FROM ref.fid_sanction WHERE dataset_version_id = %s AND reg_no = ANY(%s)
               ORDER BY row_no""",
            (ctx.v("fid_sanctions"), regs),
        ):
            hits.setdefault(reg, []).append(
                {
                    "source": "fid_sanctions",
                    "match": "reg_no",
                    "row_no": row_no,
                    "entity_name": ename,
                    "country": country,
                    "asset_kind": asset,
                    "basis": basis,
                    "sanctions_from": since,
                    "legal_act": act,
                }
            )
    # name-only: the applicant's UR name equals an entity entry without a Latvian
    # reg. no. (foreign entities); a manual-review flag, never a finding
    names = {
        reg: name
        for reg, name in ctx.conn.execute(
            "SELECT reg_no, name FROM ref.ur_company WHERE dataset_version_id = %s"
            " AND reg_no = ANY(%s) AND name IS NOT NULL",
            (ctx.v("ur_companies"), regs),
        )
    }
    by_name: dict[str, list[tuple]] = {}
    if "ur_sanctions" in used and names:
        for eid, ename, country, lst, prog in ctx.conn.execute(
            """SELECT entry_id, entity_name, entity_country, list, program FROM ref.ur_sanction
               WHERE dataset_version_id = %s AND reg_no IS NULL AND entity_name IS NOT NULL
               ORDER BY entry_id""",
            (ctx.v("ur_sanctions"),),
        ):
            by_name.setdefault(normalise_name(ename), []).append((eid, ename, country, lst, prog))
    out: dict[str, CheckResult] = {}
    for u in units:
        items = hits.get(u.code, [])
        review = [
            {
                "source": "ur_sanctions",
                "match": "name_only",
                "review": True,
                "entry_id": eid,
                "entity_name": ename,
                "entity_country": country,
                "list": lst,
                "program": prog,
            }
            for eid, ename, country, lst, prog in by_name.get(normalise_name(names.get(u.code)), [])
            if normalise_name(names.get(u.code))
        ]
        out[u.key] = make(
            SANCTIONS,
            ctx,
            u,
            "found" if items else "clear",
            items=items + review,
            match_type=items[0]["match"] if items else None,
            warnings=[NAME_ONLY] if review else [],
        )
    return out


SANCTIONS = ModuleSpec(
    id="sanctions",
    no=17,
    version="1",
    name_lv="Sankcijas",
    selectors=SOURCES,
    reads=("ur_companies",),
    optional=SOURCES,
    display=Display(
        kind="table",
        columns=["match", "entity_name", "list", "program", "entry_date", "basis"],
    ),
    run=run_sanctions,
    subject="applicant",
)
