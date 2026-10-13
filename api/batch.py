"""Batch runs and reports (PLAN.md §9 Phase 5 / Phase 10).

  POST /api/batch                  file (CSV / XLSX) or text (pasted list) -> new run;
                                   format=json (summary + report_url) or xlsx (the report)
  GET  /api/runs/{id}/report.xlsx  Excel report of a stored run
  GET  /api/runs/{id}/report.html  print-ready HTML (Phase 10; Print → PDF)
  GET  /api/runs/{id}/report.pdf   compact PDF summary (Phase 10)
  GET  /api/batch/template.xlsx    an empty input template
(The page at / is the results view, web/, served by api/web.py.)

The uploaded file is read in memory and never written by this code (PLAN.md §1);
Starlette may spool an upload over 1 MB to a temporary file that it deletes when
the request ends. Only the cleaned rows and the results are stored.
"""

import io
from html import escape
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from api.db import run_origin
from engine.batch import reader, template
from engine.batch.plan import preview, run_batch
from engine.checks import runner, summary
from engine.checks.contract import UnitRef
from engine.resolve.context import SourceUnavailable, resolve_config
from reports import excel
from reports import html as html_report
from reports import pdf as pdf_report

router = APIRouter(tags=["batch"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
MAX_UPLOAD = 5 * 1024 * 1024  # 1,000 rows are far below this


def _xlsx_response(data: bytes, name: str) -> Response:
    return Response(
        content=data,
        media_type=XLSX,
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )


def _error_page(status: int, message: str) -> HTMLResponse:
    body = (
        "<!doctype html><html lang='lv'><meta charset='utf-8'><title>Kļūda</title>"
        "<body style='font-family:system-ui,sans-serif;max-width:40rem;margin:2rem auto;"
        "padding:0 1rem'><h1>Pārbaudi nevarēja sākt</h1>"
        f"<p>{escape(message)}</p><p><a href='/'>Atpakaļ</a></p></body></html>"
    )
    return HTMLResponse(body, status_code=status)


class Entry(BaseModel):
    """One object chosen in the entry dialog (§8.1): the value as picked, its type
    (decides a property / parcel number), the given address, project, applicant
    and the ticked units or address objects (None = all)."""

    value: str = Field(min_length=1, max_length=300)
    kind: Literal["property", "parcel", "building"] | None = None
    project_no: str | None = Field(default=None, max_length=100)
    address: str | None = Field(default=None, max_length=300)
    applicant: str | None = Field(default=None, max_length=40)
    selected: list[UnitRef] | None = None


KIND_TEXT = {"property": "īpašums", "parcel": "zemes vienība", "building": "būve"}


def _entries(raw: str | None, first_row: int) -> list[reader.InputRow]:
    if not raw:
        return []
    try:
        entries = TypeAdapter(list[Entry]).validate_json(raw)
    except ValidationError as exc:
        raise reader.InputError(
            f"ievades loga dati nav derīgi: {exc.error_count()} kļūdas"
        ) from exc
    return [
        reader.InputRow(
            row_no=first_row + n,
            value=e.value.strip(),
            kind=KIND_TEXT[e.kind] if e.kind else None,
            project_no=(e.project_no or "").strip() or None,
            address=(e.address or "").strip() or None,
            applicant=(e.applicant or "").strip() or None,
            selected=None if e.selected is None else [u.model_dump() for u in e.selected],
        )
        for n, e in enumerate(entries)
    ]


def _skip(raw: str | None) -> set[int]:
    try:
        return {int(x) for x in (raw or "").split(",") if x.strip()}
    except ValueError as exc:
        raise reader.InputError("skip_rows: rindu numuri, atdalīti ar komatu") from exc


def _rows(
    file: UploadFile | None,
    text: str | None,
    entries: str | None = None,
    skip_rows: str | None = None,
) -> list[reader.InputRow]:
    """The file or pasted list (rows removed in the preview left out), then the
    objects chosen in the entry dialog."""
    limit = resolve_config().max_rows
    rows: list[reader.InputRow] = []
    has_file = file is not None and bool(file.filename)
    if has_file:
        data = file.file.read(MAX_UPLOAD + 1)
        if len(data) > MAX_UPLOAD:
            raise HTTPException(status_code=413, detail="fails ir pārāk liels (vairāk par 5 MB)")
        if data:
            rows = reader.read_upload(file.filename, data, limit)
    elif text and text.strip():
        rows = reader.read_text(text, limit)
    skip = _skip(skip_rows)
    rows = [r for r in rows if r.row_no not in skip]
    rows += _entries(entries, max((r.row_no for r in rows), default=0) + 1)
    if not rows:
        raise reader.InputError(
            "nav ievadīts saraksts: izvēlieties objektu, pievienojiet failu vai ielīmējiet vērtības"
        )
    if len(rows) > limit:
        raise reader.InputError(f"ne vairāk kā {limit} rindas vienā pārbaudē (ir {len(rows)})")
    return rows


@router.post("/api/batch", status_code=201, response_model=None)
def create_batch(
    request: Request,
    file: Annotated[UploadFile | None, File()] = None,
    text: Annotated[str | None, Form()] = None,
    sources: Annotated[str | None, Form()] = None,
    format: Annotated[Literal["json", "xlsx"], Form()] = "json",  # noqa: A002
    entries: Annotated[str | None, Form()] = None,
    skip_rows: Annotated[str | None, Form()] = None,
) -> Any:
    """A pasted list (`text`) or a CSV / XLSX file (`file`) with the columns
    vertiba, projekta_nr, pieteicejs_reg_nr, adrese, veids; at most 1,000 rows.
    `skip_rows`: row numbers removed in the import preview; `entries`: JSON list
    of objects chosen in the entry dialog (Entry), checked after the file's rows.
    Every row is resolved like POST /api/resolve; rows that are not checked are
    listed on the report's "Neatrasts" sheet."""
    selected = [s.strip() for s in sources.split(",") if s.strip()] if sources else None
    try:
        rows = _rows(file, text, entries, skip_rows)
        with request.app.state.pool.connection() as conn:
            run_id = run_batch(conn, rows, selected, origin=run_origin("batch"))
            if format == "xlsx":
                data = excel.to_bytes(excel.load(conn, run_id))
                return _xlsx_response(data, excel.filename(run_id))
            inputs = runner.stored_inputs(conn, run_id)
            return summary.summarize(conn, run_id) | {
                "inputs": {
                    "rows": len(inputs),
                    "checked": sum(1 for i in inputs if i["target_nos"]),
                    "not_checked": sum(1 for i in inputs if not i["target_nos"]),
                },
                "report_url": f"/api/runs/{run_id}/report.xlsx",
            }
    except (reader.InputError, runner.UnknownSources) as exc:
        status, message = 422, str(exc)
    except SourceUnavailable as exc:
        status, message = 503, str(exc)
    except HTTPException as exc:
        status, message = exc.status_code, str(exc.detail)
    if format == "xlsx":
        return _error_page(status, message)
    raise HTTPException(status_code=status, detail=message)


@router.post("/api/batch/preview")
def batch_preview(
    request: Request,
    file: Annotated[UploadFile | None, File()] = None,
    text: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    """The import preview (§8.1 step 6): the file is read like POST /api/batch and
    every row resolved, but nothing is stored. Run it by posting the same file to
    POST /api/batch with `skip_rows` for the rows removed in the preview."""
    try:
        rows = _rows(file, text)
        with request.app.state.pool.connection() as conn:
            return {"rows": preview(conn, rows), "limit": resolve_config().max_rows}
    except reader.InputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SourceUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _load_report(request: Request, run_id: int, grouping: int | None):
    with request.app.state.pool.connection() as conn:
        try:
            data = excel.load(conn, run_id, grouping_id=grouping)
        except runner.RunNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if data is None:
            raise HTTPException(status_code=404, detail=f"pārbaude {run_id} nav atrasta")
        return data


@router.get("/api/runs/{run_id}/report.xlsx")
def run_report(request: Request, run_id: int, grouping: int | None = None) -> Response:
    """The Excel report of a stored run, following its current project grouping
    (or the grouping row `grouping`); the Avoti sheet names the row used."""
    data = _load_report(request, run_id, grouping)
    return _xlsx_response(excel.to_bytes(data), excel.filename(run_id))


@router.get("/api/runs/{run_id}/report.html")
def run_report_html(request: Request, run_id: int, grouping: int | None = None) -> Response:
    """Print-ready HTML report (Phase 10). Use the browser's Print → Save as PDF
    for a full Latvian layout."""
    data = _load_report(request, run_id, grouping)
    return Response(
        content=html_report.to_bytes(data),
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{html_report.filename(run_id)}"'},
    )


@router.get("/api/runs/{run_id}/report.pdf")
def run_report_pdf(request: Request, run_id: int, grouping: int | None = None) -> Response:
    """Compact PDF summary (Phase 10). Diacritics are folded in the page text;
    prefer report.html + Print for a polished Latvian PDF."""
    data = _load_report(request, run_id, grouping)
    return Response(
        content=pdf_report.to_bytes(data),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{pdf_report.filename(run_id)}"'},
    )


@router.get("/api/batch/template.xlsx")
def input_template() -> Response:
    """The list template with readable Latvian headers (engine/batch/template.py)."""
    buf = io.BytesIO()
    template.input_template().save(buf)
    return _xlsx_response(buf.getvalue(), "saraksta_veidne.xlsx")
