"""Batch input rows -> targets and stored input records (PLAN.md §9 Phase 5).

Values are resolved like POST /api/resolve (§5). Decided with Janis 2026-10-11:
- resolved: checked. An address is checked on every cadastre object linked to
  it, one target each (a building marked non-existing is left out, §6.3).
- an 11-digit number that is a property and a parcel of another property:
  checked both ways, two targets labelled "divdomīgs: nekustamais īpašums" /
  "divdomīgs: zemes vienība", with a warning. The `veids` column removes the
  ambiguity.
- anything else not resolved (precision_lost, unclear addresses, not found,
  outside the pilot, invalid, empty) is not checked and goes to "Neatrasts" with
  its reason and suggestions; nothing is dropped.
- a duplicate row is checked again and keeps its "atkārtojas" warning.
- `adrese` is the given address for module 2. If it does not resolve, the object
  is still checked; the address goes to "Neatrasts" and the target carries the
  warning `given_address_unresolved`. Without `adrese`, an address in `vertiba`
  is the given address.
- `pieteicejs_reg_nr` is stored only as a legal-entity number (11 digits,
  starting with 4, 5 or 9); anything else may be a personal code and is dropped
  with a note (CLAUDE.md rule 5).
"""

import re
from dataclasses import dataclass, field
from typing import Any

from engine.batch.headers import fold
from engine.batch.reader import InputRow
from engine.checks import runner
from engine.checks.contract import TargetIn, Warning_
from engine.resolve import cadastre, service
from engine.resolve.classify import PRECISION_LOST
from engine.resolve.context import live_versions, pilot, resolve_config
from engine.resolve.models import Match, ResolvedRow
from engine.resolve.places import load_places

KINDS = {
    "ipasums": "property",
    "nekustamais_ipasums": "property",
    "zemes_vieniba": "parcel",
    "buve": "building",
}
KIND_LV = {"property": "īpašums", "parcel": "zemes vienība", "building": "būve"}
# what each veids accepts (a parcel part is part of a parcel; a premise group
# resolves to its building)
ACCEPTS = {
    "property": {"property"},
    "parcel": {"parcel", "parcel_part"},
    "building": {"building", "premise_group"},
}
AMBIGUOUS_LABEL = {
    "property": "divdomīgs: nekustamais īpašums",
    "parcel": "divdomīgs: zemes vienība",
}
CADASTRE_TYPES = {"property", "parcel", "building", "parcel_part", "premise_group"}
LEGAL_REG_NO = re.compile(r"^[459][0-9]{10}$")
PERSONAL_CODE = re.compile(r"^[0-9]{6}-[0-9]{5}$")
MAX_SUGGESTIONS = 10


@dataclass
class Prepared:
    targets: list[TargetIn] = field(default_factory=list)
    inputs: list[dict[str, Any]] = field(default_factory=list)
    resolved: list[ResolvedRow] = field(default_factory=list)  # per input row (preview)


def _problem(column: str, status: str, reason: str | None, matches: list[Match] = ()) -> dict:
    suggestions = []
    for m in list(matches)[:MAX_SUGGESTIONS]:
        desc = m.description or (m.address.full_text if m.address else None)
        suggestions.append({"designation": m.designation, "label": m.label, "description": desc})
    return {"column": column, "status": status, "reason": reason, "suggestions": suggestions}


def _notes(rr: ResolvedRow, prefix: str = "", code: str | None = None) -> list[Warning_]:
    out = [
        Warning_(code=code or w.code, message=prefix + w.message)
        for w in rr.warnings
        if not (code and w.code == "duplicate")
    ]
    out += [Warning_(code=code or c.code, message=prefix + c.message) for c in rr.corrections]
    return out


def _kind(row: InputRow) -> tuple[str | None, dict | None]:
    if not row.kind:
        return None, None
    kind = KINDS.get(fold(row.kind))
    if kind is None:
        return None, _problem(
            "veids",
            "invalid",
            f"nezināms veids '{row.kind}'; derīgi: īpašums, zemes vienība, būve (neņemts vērā)",
        )
    return kind, None


def _applicant(row: InputRow) -> tuple[str | None, dict | None]:
    if not row.applicant:
        return None, None
    digits = re.sub(r"\s+", "", row.applicant)
    if LEGAL_REG_NO.match(digits):
        return digits, None
    # the value itself is not kept: it may be a personal code
    return None, _problem(
        "pieteicejs_reg_nr",
        "not_stored",
        "nav juridiskas personas reģistrācijas numurs (11 cipari, sākas ar 4, 5 vai 9);"
        " vērtība nav saglabāta",
    )


def given_address(rr: ResolvedRow | None) -> tuple[str | None, list[Warning_], dict | None]:
    """(VARIS code, target warnings, problem) for the `adrese` column (also used by
    `check compare`, engine/checks/compare.py)."""
    if rr is None:
        return None, [], None
    if rr.status == "resolved" and rr.type == "address":
        m = next(m for m in rr.matches if m.type == "address")
        return m.designation, _notes(rr, "norādītā adrese: ", "given_address_note"), None
    reason = rr.reason or {"ambiguous": "adrese nav viennozīmīga"}.get(rr.status, rr.status)
    warn = Warning_(
        code="given_address_unresolved",
        message=f"norādītā adrese nav atrasta ({reason}); adreses atbilstība nav pārbaudīta",
    )
    return None, [warn], _problem("adrese", rr.status, reason, rr.matches)


def _pick(matches: list[Match], kind: str) -> Match | None:
    return next((m for m in matches if m.type in ACCEPTS[kind]), None)


def _mismatch(kind: str, m: Match) -> dict:
    return _problem(
        "vertiba",
        "kind_mismatch",
        f"veids '{KIND_LV[kind]}' neatbilst: atrasts {m.label.lower()} {m.designation}",
        [m],
    )


def _objects(rr: ResolvedRow, kind: str | None):
    """Targets (type, designation, label, address code) from the value, or a problem."""
    if rr.status == "resolved" and rr.type == "address":
        m = next(m for m in rr.matches if m.type == "address")
        objects = [o for o in m.objects if kind is None or o.type in ACCEPTS[kind]]
        if not objects:
            why = (
                f"adresei nav kadastra objektu ar veidu '{KIND_LV[kind]}'"
                if kind and m.objects
                else "adresei kadastra datos nav piesaistītu objektu"
            )
            return [], _problem("vertiba", "no_objects", why, [m])
        objects.sort(key=lambda o: (o.type != "parcel", o.designation))
        many = len(objects) > 1
        return [
            (
                o.type,
                o.designation,
                f"adresei {len(objects)} objekti" if many else None,
                m.designation,
            )
            for o in objects
        ], None

    if rr.status == "resolved":
        m = next(m for m in rr.matches if m.type == rr.type)
        if kind and m.type not in ACCEPTS[kind]:
            alt = _pick(rr.matches, kind)
            if alt is None:
                return [], _mismatch(kind, m)
            m = alt
        return [(m.type, m.designation, None, None)], None

    if rr.status == "ambiguous":
        types = {m.type for m in rr.matches}
        precision_lost = any(w.code == PRECISION_LOST for w in rr.warnings)
        if rr.kind == "cadastre" and types == {"property", "parcel"} and not precision_lost:
            if kind:
                m = _pick(rr.matches, kind)
                if m is None:
                    return [], _mismatch(kind, rr.matches[0])
                return [(m.type, m.designation, None, None)], None
            order = sorted(rr.matches, key=lambda m: m.type != "property")
            return [(m.type, m.designation, AMBIGUOUS_LABEL[m.type], None) for m in order], None

    reason = rr.reason or {"ambiguous": "vērtība nav viennozīmīga"}.get(rr.status, rr.status)
    return [], _problem("vertiba", rr.status, reason, rr.matches)


def _select(rr: ResolvedRow, objects: list, selected: list[dict] | None):
    """Entry dialog: only the ticked objects of an address are checked (a
    property's ticked units are passed on to the engine as its unit selection)."""
    if selected is None or not objects or not (rr.status == "resolved" and rr.type == "address"):
        return objects, None
    wanted = {(s["type"], s["designation"]) for s in selected}
    kept = [o for o in objects if (o[0], o[1]) in wanted]
    if kept:
        many = len(kept) > 1
        return [
            (t, d, f"adresei {len(kept)} objekti" if many else None, a) for t, d, _, a in kept
        ], None
    return [], _problem("vertiba", "no_objects", "neviens adreses objekts nav atzīmēts")


def prepare(conn, rows: list[InputRow]) -> Prepared:
    """Resolve the rows (nothing is stored here)."""
    v = live_versions(conn)
    p = pilot()
    places = load_places(conn, v, p)
    cfg = resolve_config()

    values = []
    personal = set()
    for i, row in enumerate(rows):
        text = row.value if isinstance(row.value, str) else None
        if text and PERSONAL_CODE.match(text.strip()):
            personal.add(i)  # never resolved, never stored (CLAUDE.md rule 5)
            values.append(service.RowIn(value=None))
        else:
            values.append(service.RowIn(value=row.value))
    main = service.resolve(conn, v, places, p, cfg, values).rows

    with_address = [i for i, r in enumerate(rows) if r.address]
    addr_rows: dict[int, ResolvedRow] = {}
    if with_address:
        res = service.resolve(
            conn,
            v,
            places,
            p,
            cfg,
            [service.RowIn(value=rows[i].address, kind="address") for i in with_address],
        )
        addr_rows = dict(zip(with_address, res.rows, strict=True))

    out = Prepared()
    for i, (row, rr) in enumerate(zip(rows, main, strict=True)):
        problems: list[dict] = []
        kind, p_kind = _kind(row)
        reg, p_reg = _applicant(row)
        if i in personal:
            objects, p_value = (
                [],
                _problem(
                    "vertiba",
                    "not_stored",
                    "izskatās pēc personas koda; vērtība nav saglabāta un nav pārbaudīta",
                ),
            )
        else:
            objects, p_value = _objects(rr, kind)
            objects, p_sel = _select(rr, objects, row.selected)
            p_value = p_value or p_sel
        given, given_notes, p_addr = given_address(addr_rows.get(i))
        problems += [x for x in (p_value, p_kind, p_addr, p_reg) if x]
        target_nos = []
        if objects:
            notes = _notes(rr) + given_notes
            if any(label and label.startswith("divdomīgs") for _, _, label, _ in objects):
                notes.append(
                    Warning_(
                        code="ambiguous_checked_both",
                        message="vērtība divdomīga: pārbaudīta gan kā nekustamais īpašums,"
                        " gan kā zemes vienība",
                    )
                )
            for typ, designation, label, value_address in objects:
                target_nos.append(len(out.targets))
                out.targets.append(
                    TargetIn(
                        type=typ,
                        designation=designation,
                        input=rr.input,
                        given_address=given or (None if row.address else value_address),
                        project_no=row.project_no,
                        warnings=notes,
                        input_no=i,
                        label=label,
                        applicant_reg_no=reg,
                        unit_selection=row.selected if typ == "property" else None,
                    )
                )
        out.resolved.append(rr)
        out.inputs.append(
            {
                "input_no": i,
                "row_no": row.row_no,
                "value": None if i in personal else (rr.input or None),
                "kind": kind,
                "project_no": row.project_no,
                "address": row.address,
                "applicant_reg_no": reg,
                "status": "not_stored" if i in personal else rr.status,
                "problems": problems,
                "target_nos": target_nos,
            }
        )
    return out


def run_batch(
    conn, rows: list[InputRow], sources: list[str] | None = None, origin: str = "batch"
) -> int:
    """Resolve, check and store; returns the run id. Also a run with no checkable
    row is stored, so its report lists every row on "Neatrasts"."""
    prepared = prepare(conn, rows)
    return runner.start_run(conn, prepared.targets, sources, origin=origin, inputs=prepared.inputs)


def preview(conn, rows: list[InputRow]) -> list[dict[str, Any]]:
    """The import preview (entry dialog, §8.1 step 6): per row the detected type,
    match status, corrections, warnings, duplicates and the objects it would
    check. Nothing is stored. A value that looks like a personal code is not
    shown (CLAUDE.md rule 5)."""
    p = prepare(conn, rows)
    v = live_versions(conn)
    unit_counts: dict[str, int] = {}
    for t in p.targets:  # a property is checked on its units (engine/checks/units.py)
        if t.type == "property" and t.designation not in unit_counts:
            pu = cadastre.property_units(conn, v, t.designation, include_non_existing=False)
            unit_counts[t.designation] = len(pu.units) if pu else 0
    out = []
    for inp, rr in zip(p.inputs, p.resolved, strict=True):
        hidden = inp["status"] == "not_stored"
        dup = rr.duplicate_of
        out.append(
            {
                "row_no": inp["row_no"],
                "value": inp["value"],
                "kind": None if hidden else rr.kind,
                "type": None if hidden else rr.type,
                "status": inp["status"],
                "checked": bool(inp["target_nos"]),
                "project_no": inp["project_no"],
                "address": inp["address"],
                "applicant_reg_no": inp["applicant_reg_no"],
                "corrections": [] if hidden else [c.message for c in rr.corrections],
                "warnings": [] if hidden else [w.message for w in rr.warnings],
                "duplicate_of": None if dup is None else p.inputs[dup]["row_no"],
                "problems": inp["problems"],
                "targets": [
                    {
                        "type": p.targets[n].type,
                        "designation": p.targets[n].designation,
                        "label": p.targets[n].label,
                        "units": unit_counts.get(p.targets[n].designation, 0)
                        if p.targets[n].type == "property"
                        else 1,
                    }
                    for n in inp["target_nos"]
                ],
            }
        )
    return out
