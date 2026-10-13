"""Minimal PDF summary of one stored run (Phase 10).

Drawn with Helvetica (Latvian diacritics folded to ASCII for the page glyphs).
For a full Latvian layout use the HTML report (``reports.html``) and Print →
Save as PDF. Built only from stored ReportData.
"""

from __future__ import annotations

from datetime import datetime

from engine.checks import summary
from reports.excel import (
    FOOTER,
    RISK_LV,
    STATUS_LV,
    TYPE_LV,
    ReportData,
    _by_target,
    _modules,
)
from reports.excel import (
    filename as excel_filename,
)


def filename(run_id: int) -> str:
    return excel_filename(run_id).removesuffix(".xlsx") + ".pdf"


def _fold(text: str) -> str:
    table = str.maketrans(
        {
            "ā": "a",
            "Ā": "A",
            "č": "c",
            "Č": "C",
            "ē": "e",
            "Ē": "E",
            "ģ": "g",
            "Ģ": "G",
            "ī": "i",
            "Ī": "I",
            "ķ": "k",
            "Ķ": "K",
            "ļ": "l",
            "Ļ": "L",
            "ņ": "n",
            "Ņ": "N",
            "š": "s",
            "Š": "S",
            "ū": "u",
            "Ū": "U",
            "ž": "z",
            "Ž": "Z",
        }
    )
    return text.translate(table)


def _page_content(lines: list[str], *, font_size: int = 10) -> bytes:
    parts = [b"BT", f"/F1 {font_size} Tf".encode(), b"14 TL", b"50 800 Td"]
    for line in lines:
        lit = _fold(line).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        parts.append(f"({lit}) Tj T*".encode("latin-1", errors="replace"))
    parts.append(b"ET")
    return b"\n".join(parts)


def build(data: ReportData) -> bytes:
    head = data.head
    run_id = head["id"]
    checked = head.get("checked_as_of") or head.get("finished_at") or head.get("created_at") or ""
    if isinstance(checked, datetime):
        checked = checked.strftime("%Y-%m-%d %H:%M")
    modules = _modules(data)
    results = _by_target(data)
    lines = [
        f"Kadastra parbaude #{run_id}",
        f"Objekti: {len(data.targets)}  |  parbaudits: {checked}  |  "
        f"rule set {(head.get('rule_set') or {}).get('version')}",
        "",
        "Kopsavilkums",
        "-" * 72,
    ]
    for t in data.targets:
        res = results.get(t["target_no"], {})
        applicable = []
        for m in modules:
            r = res.get(m)
            if r is None:
                continue
            if summary.bucket(m, r.status, r.reason) == "not_applicable":
                continue
            applicable.append(r.risk)
        worst = data.rules.worst(applicable)
        typ = TYPE_LV.get(t["type"], t["type"])
        risk = RISK_LV.get(worst, "") if worst else ""
        lines.append(f"{t['designation']} ({typ}): risks {risk}")
        for m in modules:
            r = res.get(m)
            if r is None:
                continue
            b = summary.bucket(m, r.status, r.reason)
            if b == "not_applicable":
                continue
            lines.append(f"  - {m}: {STATUS_LV[b]}/{RISK_LV[r.risk]}")
    lines += ["", "Atradumi", "-" * 72]
    n_findings = 0
    for row in data.rows:
        if row.scope != "target":
            continue
        r = row.result
        for item in r.items or []:
            n_findings += 1
            title = item.get("title") or item.get("code") or item.get("kind") or ""
            lines.append(f"{row.unit_code} | {r.module} | {title} | {RISK_LV.get(r.risk, r.risk)}")
            detail = str(item.get("detail") or item.get("text") or "").replace("\n", " ")
            if detail:
                lines.append(f"    {detail[:200]}")
    if n_findings == 0:
        lines.append("(nav atradumu)")
    lines += ["", FOOTER]

    pages_lines = [lines[i : i + 60] for i in range(0, max(len(lines), 1), 60)]
    kids = " ".join(f"{3 + i * 2} 0 R" for i in range(len(pages_lines)))
    final: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {len(pages_lines)} >>".encode(),
    ]
    for i, page_lines in enumerate(pages_lines):
        content_id = 4 + i * 2
        stream = _page_content(page_lines)
        final.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                f"/Contents {content_id} 0 R "
                f"/Resources << /Font << /F1 << /Type /Font /Subtype /Type1 "
                f"/BaseFont /Helvetica >> >> >> >>"
            ).encode()
        )
        final.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(final, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(final) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        b"trailer\n<< /Size "
        + str(len(final) + 1).encode()
        + b" /Root 1 0 R >>\nstartxref\n"
        + str(xref_pos).encode()
        + b"\n%%EOF\n"
    )
    return bytes(out)


def to_bytes(data: ReportData) -> bytes:
    return build(data)
