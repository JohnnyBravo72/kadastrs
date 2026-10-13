"""One line of text per check-result item, shared by the Excel report and the map
popups so both word a finding the same way."""

import json
from typing import Any


def purposes(item: dict[str, Any]) -> str:
    names = [p.get("name") for p in item.get("land_purposes") or [] if isinstance(p, dict)]
    return ", ".join(n for n in names if n)


def describe(module: str, item: dict[str, Any]) -> str:
    """One item as a line of text."""
    if module == "cadastre_facts":
        parts = [f"{item.get('type') or ''} {item.get('designation') or ''}".strip()]
        if item.get("area_m2") is not None:
            parts.append(f"platība {item['area_m2']} m²")
        if item.get("name") or item.get("use_kind"):
            parts.append(" / ".join(x for x in (item.get("name"), item.get("use_kind")) if x))
        if uses := purposes(item):
            parts.append(f"lietošanas mērķis: {uses}")
        on_parcel = item.get("buildings_on_parcel") or []
        if on_parcel:
            parts.append(f"būves uz zemes vienības: {len(on_parcel)}")
        if item.get("property_numbers"):
            parts.append(f"īpašums {', '.join(item['property_numbers'])}")
        return "; ".join(p for p in parts if p)
    if module == "nature":
        name = item.get("name") or ""
        extra = ", ".join(x for x in (item.get("category"), item.get("zone_type")) if x)
        return f"{item.get('kind_lv') or item.get('kind')}: {name}" + (
            f" ({extra})" if extra else ""
        )
    if module == "flood_10y":
        return f"10 gadu plūdu zona ({item.get('layer_name') or item.get('layer')})"
    if module == "zoning":
        name = item.get("group_name") or item.get("zone_index") or item.get("zone_code") or ""
        bits = [name]
        if item.get("zone_index") and item.get("zone_index") != name:
            bits.append(item["zone_index"])
        if item.get("zone_code"):
            bits.append(str(item["zone_code"]))
        text = " / ".join(b for b in bits if b) or "funkcionālā zona"
        if item.get("share") is not None:
            text += f"; {item['share']:.1%}"
        return text
    if module == "bis":
        bits = [
            item.get("object_name"),
            item.get("stage"),
            item.get("construction_kind"),
            item.get("created_date"),
        ]
        return f"{item.get('case_number')}: " + ", ".join(str(b) for b in bits if b)
    if module == "encumbrances":
        text = f"{item.get('code')} {item.get('description') or ''}".strip()
        if item.get("area") is not None:
            text += f"; platība {item['area']} {item.get('measure') or ''}".rstrip()
        if item.get("establish_date"):
            text += f"; reģistrēts {item['establish_date']}"
        if item.get("frozen"):
            text += "; tikai 2025-01-31 sarakstā – pārbaudīt manuāli"
        return text
    if module == "applicant_company":
        name = item.get("name") or item.get("name_note") or ""
        text = f"{item.get('reg_no')} {name}".strip()
        text += f"; {item.get('form_text') or item.get('form')}; {item.get('status_lv')}"
        if item.get("registered"):
            text += f"; reģistrēts {item['registered']}"
        if item.get("terminated"):
            text += f"; darbību beidzis {item['terminated']}"
        for p in item.get("proceedings") or []:
            if p.get("open"):
                text += f"; atvērts {p.get('form_lv')} (no {p.get('started_on')})"
        return text
    if module == "companies_at_address":
        text = f"{item.get('address') or item.get('varis_code')}: {item.get('active_count')} aktīvi"
        if item.get("ended_count"):
            text += f", {item['ended_count']} likvidēti"
        if item.get("building_area_m2") is not None:
            kind = "dzīvojamā ēka" if item.get("residential") else "ēka"
            text += f"; {kind} {item['building_area_m2']:.0f} m²"
        return text + " (juridiskā adrese, nav darbības pierādījums)"
    if module == "sanctions":
        label = {
            "reg_no": "reģistrācijas numurs sarakstā",
            "linked_entity": "saistīta sankcionēta juridiskā persona",
            "name_only": "tikai nosaukums sakrīt – pārbaudīt manuāli",
        }.get(item.get("match"), item.get("match"))
        bits = [
            item.get("entity_name"),
            item.get("relationship"),
            item.get("list_text") or item.get("list"),
            item.get("program"),
            item.get("entry_date") or item.get("sanctions_from"),
            item.get("basis"),
        ]
        src = "FID iesaldētie aktīvi" if item.get("source") == "fid_sanctions" else "UR sankcijas"
        return f"{label} ({src}): " + ", ".join(str(b) for b in bits if b)
    return json.dumps(item, ensure_ascii=False, sort_keys=True)
