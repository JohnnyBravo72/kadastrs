"""Print-ready HTML report of one stored run (Phase 10).

Built from the same ReportData as the Excel report (stored results only).
Browsers can File → Print → Save as PDF; diacritics are preserved. The legal
footer is the D3 wording.
"""

from __future__ import annotations

import html
from datetime import datetime

from engine.checks import summary
from engine.checks.modules import BY_ID
from reports.excel import (
    FOOTER,
    RISK_LV,
    STATUS_LV,
    TYPE_LV,
    ReportData,
    _by_target,
    _modules,
    _projects,
)
from reports.excel import (
    filename as excel_filename,
)


def filename(run_id: int) -> str:
    return excel_filename(run_id).removesuffix(".xlsx") + ".html"


def _esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def build(data: ReportData) -> str:
    """Full HTML document for one run."""
    head = data.head
    run_id = head["id"]
    checked = head.get("checked_as_of") or head.get("finished_at") or head.get("created_at") or ""
    if isinstance(checked, datetime):
        checked = checked.strftime("%Y-%m-%d %H:%M")
    modules = _modules(data)
    results = _by_target(data)
    project = _projects(data)
    rows_html = []
    for t in data.targets:
        res = results.get(t["target_no"], {})
        applicable = []
        mod_bits = []
        for m in modules:
            r = res.get(m)
            if r is None:
                continue
            b = summary.bucket(m, r.status, r.reason)
            if b == "not_applicable":
                continue
            applicable.append(r.risk)
            label = f"{BY_ID[m].no}. {_esc(BY_ID[m].name_lv)}"
            mod_bits.append(f"{label}: {_esc(STATUS_LV[b])}/{_esc(RISK_LV[r.risk])}")
        worst = data.rules.worst(applicable)
        rows_html.append(
            "<tr>"
            f"<td>{_esc(t['target_no'] + 1)}</td>"
            f"<td>{_esc(project.get(t['target_no']))}</td>"
            f"<td>{_esc(t['input'])}</td>"
            f"<td>{_esc(t['designation'])}</td>"
            f"<td>{_esc(TYPE_LV.get(t['type'], t['type']))}</td>"
            f"<td>{_esc(RISK_LV.get(worst) if worst else '')}</td>"
            f"<td>{'<br/>'.join(mod_bits)}</td>"
            "</tr>"
        )
    findings = []
    for row in data.rows:
        if row.scope != "target":
            continue
        r = row.result
        for item in r.items or []:
            findings.append(
                "<tr>"
                f"<td>{_esc(row.unit_code)}</td>"
                f"<td>{_esc(BY_ID[r.module].name_lv if r.module in BY_ID else r.module)}</td>"
                f"<td>{_esc(item.get('title') or item.get('code') or item.get('kind'))}</td>"
                f"<td>{_esc(RISK_LV.get(r.risk, r.risk))}</td>"
                f"<td>{_esc(item.get('detail') or item.get('text') or '')}</td>"
                "</tr>"
            )
    return f"""<!DOCTYPE html>
<html lang="lv">
<head>
<meta charset="utf-8"/>
<title>Pārbaude {_esc(run_id)}</title>
<style>
  body {{ font-family: Georgia, "Times New Roman", serif; margin: 2rem; color: #1a1a1a;
         background: linear-gradient(#f7f5f0, #ebe6dc); min-height: 100vh; }}
  h1 {{ font-size: 1.6rem; margin-bottom: 0.25rem; }}
  .meta {{ color: #444; margin-bottom: 1.5rem; }}
  table {{ border-collapse: collapse; width: 100%; background: #fff; margin-bottom: 1.5rem; }}
  th, td {{ border: 1px solid #ccc; padding: 0.4rem 0.55rem; text-align: left;
            vertical-align: top; font-size: 0.9rem; }}
  th {{ background: #e8e2d6; }}
  footer {{ margin-top: 2rem; font-size: 0.85rem; color: #555; border-top: 1px solid #bbb;
            padding-top: 0.75rem; }}
  @media print {{
    body {{ background: #fff; margin: 1rem; }}
    footer {{ position: fixed; bottom: 0; left: 1rem; right: 1rem; }}
  }}
</style>
</head>
<body>
<h1>Kadastra pārbaude #{_esc(run_id)}</h1>
<p class="meta">Objektu: {_esc(len(data.targets))} · pārbaudīts: {_esc(checked)} ·
rule set {_esc((head.get("rule_set") or {}).get("version"))}</p>
<h2>Kopsavilkums</h2>
<table>
<thead><tr><th>Nr.</th><th>Projekts</th><th>Ievade</th><th>Apzīmējums</th>
<th>Veids</th><th>Risks</th><th>Moduļi</th></tr></thead>
<tbody>
{"".join(rows_html) or "<tr><td colspan='7'>Nav objektu</td></tr>"}
</tbody>
</table>
<h2>Atradumi</h2>
<table>
<thead><tr><th>Objekts</th><th>Modulis</th><th>Nosaukums</th><th>Risks</th><th>Detaļas</th></tr></thead>
<tbody>
{"".join(findings) or "<tr><td colspan='5'>Nav atradumu</td></tr>"}
</tbody>
</table>
<footer>{_esc(FOOTER)}</footer>
</body>
</html>
"""


def to_bytes(data: ReportData) -> bytes:
    return build(data).encode("utf-8")
