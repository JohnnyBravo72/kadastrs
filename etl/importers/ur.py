"""Applicant sources (Phase 8a, docs/data-sources.md §3.9, §3.9a, §3.17; D10).

  ur_companies    UR register.csv, whole country: reg. no., form, status, dates,
                  legal address and its VARIS code
  ur_insolvency   UR insolvency and legal protection proceedings of legal entities
  ur_sanctions    UR sanctions file: LEGAL_ENTITY / FOREIGN_ENTITY rows only
  fid_sanctions   FID "Sankciju subjekti": rows with a Latvian legal-entity reg. no.

CLAUDE.md rule 5 and D10: no natural person's name, birth date or personal code
is ever read into a stored row. Natural-person rows are skipped before any of
their fields is touched; IK / IND names are dropped; registration numbers must
have the legal-entity pattern (the tables enforce the same, migration
20261012150000). The whole header is still schema-checked, so a renamed person
column cannot slip into a kept one.
"""

import re
from collections import Counter
from datetime import date, datetime

from openpyxl import load_workbook

from etl.importers.common import copy_rows, fetch_whole, resource_date
from etl.schema_check import SchemaMismatch, check_columns
from etl.settings import schemas
from etl.textio import clean_text, csv_header, iter_csv

LEGAL_REG_NO = re.compile(r"^[459][0-9]{10}$")
OLD_REG_NO = re.compile(r"^[0-9]{9}$")  # UR's old Uzņēmumu reģistra žurnāls numbers
NAMELESS_FORMS = {"IK", "IND"}  # individuālais komersants / uzņēmums: the owner's name (D10)
ENTITY_TYPES = {"LEGAL_ENTITY", "FOREIGN_ENTITY"}
_ISO = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}")


def iso_date(value: str | None, what: str) -> date | None:
    """`YYYY-MM-DD`, optionally followed by a time; empty -> None."""
    value = (value or "").strip()
    if not value:
        return None
    if not _ISO.match(value):
        raise ValueError(f"{what}: date {value!r} is not YYYY-MM-DD")
    return date.fromisoformat(value[:10])


def legal_reg_no(value) -> str | None:
    """A Latvian legal-entity reg. no. as text, else None (it may be a personal code)."""
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = re.sub(r"\s+", "", str(value))
    return text if LEGAL_REG_NO.match(text) else None


# --- UR companies ---------------------------------------------------------------------------

COMPANY_COLUMNS = [
    "dataset_version_id",
    "reg_no",
    "name",
    "form",
    "form_text",
    "register",
    "registered",
    "terminated",
    "closed",
    "address",
    "varis_code",
    "atvk",
]


class UrCompanies:
    source_id = "ur_companies"
    FILE = "register.csv"

    def check_schema(self, ctx):
        header = csv_header(ctx.workdir / self.FILE, delimiter=";")
        check_columns(self.FILE, header, schemas()["csv"]["ur_register"])

    def fetch(self, ctx):
        files = [fetch_whole(ctx, "register", self.FILE)]
        self.check_schema(ctx)
        return files

    def version_date(self, ctx, files):
        return resource_date(ctx, ["register"])

    def load(self, ctx, conn, version_id, files):
        self.check_schema(ctx)
        counts: Counter = Counter()

        def rows():
            for line, r in enumerate(iter_csv(ctx.workdir / self.FILE, delimiter=";"), start=2):
                counts["source_rows"] += 1
                reg = r["regcode"].strip()
                if not (LEGAL_REG_NO.match(reg) or OLD_REG_NO.match(reg)):
                    counts["skipped_reg_no_shape"] += 1  # could be a personal code (D10)
                    continue
                form = r["type"].strip()
                name = clean_text(r["name"])
                if form in NAMELESS_FORMS:
                    name = None
                    counts["name_not_stored"] += 1
                closed = r["closed"].strip() or None
                if closed not in (None, "L", "R"):
                    raise ValueError(
                        f"register.csv line {line}: closed {closed!r} is not L/R/blank"
                    )
                varis = r["addressid"].strip()
                if varis in ("", "0"):
                    varis = None
                elif not re.match(r"^[0-9]{9}$", varis):
                    counts["varis_code_invalid"] += 1
                    varis = None
                atvk = r["atvk"].strip() or None
                if atvk and not re.match(r"^[0-9]{7}$", atvk):
                    counts["atvk_invalid"] += 1
                    atvk = None
                counts["loaded"] += 1
                yield (
                    version_id,
                    reg,
                    name,
                    form,
                    clean_text(r["type_text"]),
                    clean_text(r["regtype_text"]),
                    iso_date(r["registered"], f"line {line} registered"),
                    iso_date(r["terminated"], f"line {line} terminated"),
                    closed,
                    clean_text(r["address"]),
                    varis,
                    atvk,
                )

        loaded = copy_rows(conn, "ref.ur_company", COMPANY_COLUMNS, rows())
        ctx.processing = [
            {
                "id": "personal_data",
                "what": "No names of individual merchants (IK, IND); registration numbers of "
                "another shape (possible personal codes) skipped (D10)",
                "name_not_stored": counts["name_not_stored"],
                "skipped_reg_no_shape": counts["skipped_reg_no_shape"],
            },
            {
                "id": "codes",
                "what": "addressid 0 = no VARIS code; invalid codes dropped",
                "varis_code_invalid": counts["varis_code_invalid"],
                "atvk_invalid": counts["atvk_invalid"],
            },
        ]
        return {"ur_company": {"source_rows": counts["source_rows"], "loaded": loaded}}


# --- UR insolvency --------------------------------------------------------------------------

INSOLVENCY_COLUMNS = [
    "dataset_version_id",
    "proceeding_id",
    "reg_no",
    "started_on",
    "ended_on",
    "form",
    "type",
    "subtype",
    "resolution_type",
    "resolution_name",
]


class UrInsolvency:
    source_id = "ur_insolvency"
    FILE = "insolvency.csv"

    def check_schema(self, ctx):
        header = csv_header(ctx.workdir / self.FILE, delimiter=";")
        check_columns(self.FILE, header, schemas()["csv"]["ur_insolvency"])

    def fetch(self, ctx):
        files = [fetch_whole(ctx, "proceedings", self.FILE)]
        self.check_schema(ctx)
        return files

    def version_date(self, ctx, files):
        return resource_date(ctx, ["proceedings"])

    def load(self, ctx, conn, version_id, files):
        self.check_schema(ctx)
        counts: Counter = Counter()

        def rows():
            for line, r in enumerate(iter_csv(ctx.workdir / self.FILE, delimiter=";"), start=2):
                counts["source_rows"] += 1
                reg = legal_reg_no(r["debtor_registration_number"])
                if reg is None:
                    counts["skipped_not_legal_entity"] += 1  # personal insolvency (D10)
                    continue
                pid = r["proceeding_id"].strip()
                if not pid:
                    raise ValueError(f"insolvency line {line}: no proceeding_id")
                counts["loaded"] += 1
                yield (
                    version_id,
                    pid,
                    reg,
                    iso_date(r["proceeding_started_on"], f"line {line} started"),
                    iso_date(r["proceeding_ended_on"], f"line {line} ended"),
                    clean_text(r["proceeding_form"]),
                    clean_text(r["proceeding_type"]),
                    clean_text(r["proceeding_subtype"]),
                    clean_text(r["proceeding_resolution_type"]),
                    clean_text(r["proceeding_resolution_name"]),
                )

        loaded = copy_rows(conn, "ref.ur_insolvency", INSOLVENCY_COLUMNS, rows())
        ctx.processing = [
            {
                "id": "personal_data",
                "what": "Only legal-entity debtors; debtor name and address not stored (D10)",
                "skipped_not_legal_entity": counts["skipped_not_legal_entity"],
            }
        ]
        return {"ur_insolvency": {"source_rows": counts["source_rows"], "loaded": loaded}}


# --- UR sanctions ---------------------------------------------------------------------------

SANCTION_COLUMNS = [
    "dataset_version_id",
    "entry_id",
    "entity_type",
    "registered_on",
    "legal_form_code",
    "reg_no",
    "foreign_reg_no",
    "entity_name",
    "entity_country",
    "position_text_lv",
    "subject_legal_form_code",
    "subject_reg_no",
    "subject_name",
    "list",
    "list_text",
    "program",
    "entry_date",
    "legal_base",
    "legal_base_url",
]


class UrSanctions:
    source_id = "ur_sanctions"
    FILE = "sanctions.csv"

    def check_schema(self, ctx):
        header = csv_header(ctx.workdir / self.FILE, delimiter=";")
        check_columns(self.FILE, header, schemas()["csv"]["ur_sanctions"])

    def fetch(self, ctx):
        files = [fetch_whole(ctx, "sanctions", self.FILE)]
        self.check_schema(ctx)
        return files

    def version_date(self, ctx, files):
        return resource_date(ctx, ["sanctions"])

    def load(self, ctx, conn, version_id, files):
        self.check_schema(ctx)
        counts: Counter = Counter()

        def rows():
            for line, r in enumerate(iter_csv(ctx.workdir / self.FILE, delimiter=";"), start=2):
                counts["source_rows"] += 1
                kind = r["entity_type"].strip()
                if kind not in ENTITY_TYPES:
                    # NATURAL_PERSON (or anything else): nothing of the row is stored,
                    # not even the linked company (D10 option A)
                    counts[f"skipped_{kind.lower() or 'empty'}"] += 1
                    continue
                raw_reg = r["legal_entity_registration_number"].strip()
                reg = legal_reg_no(raw_reg)
                counts["loaded"] += 1
                yield (
                    version_id,
                    r["id"].strip(),
                    kind,
                    iso_date(r["registered_on"], f"line {line} registered_on"),
                    clean_text(r["legal_form_code"]),
                    reg,
                    None if reg else (clean_text(raw_reg) if kind == "FOREIGN_ENTITY" else None),
                    clean_text(r["legal_entity_name"]),
                    clean_text(r["legal_entity_country"]),
                    clean_text(r["position_text_lv"]),
                    clean_text(r["sanctions_subject_legal_form_code"]),
                    legal_reg_no(r["sanctions_subject_registration_number"]),
                    clean_text(r["sanctions_subject_name"]),
                    clean_text(r["list"]),
                    clean_text(r["list_text"]),
                    clean_text(r["program"]),
                    iso_date(r["entry_date"], f"line {line} entry_date"),
                    clean_text(r["legal_base"]),
                    clean_text(r["legal_base_url"]),
                )

        loaded = copy_rows(conn, "ref.ur_sanction", SANCTION_COLUMNS, rows())
        ctx.processing = [
            {
                "id": "personal_data",
                "what": "Only LEGAL_ENTITY and FOREIGN_ENTITY rows; natural-person rows and the "
                "fields name, birth_date, latvian_identity_number_masked, nationality never "
                "stored (D10 option A)",
                **{k: v for k, v in sorted(counts.items()) if k.startswith("skipped_")},
            }
        ]
        return {"ur_sanction": {"source_rows": counts["source_rows"], "loaded": loaded}}


# --- FID sanctions subjects -----------------------------------------------------------------

FID_COLUMNS = [
    "dataset_version_id",
    "row_no",
    "reg_no",
    "entity_name",
    "country",
    "asset_kind",
    "basis",
    "sanctions_from",
    "legal_act",
    "first_published",
]


def _cell_text(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime | date):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    return clean_text(str(value))


class FidSanctions:
    source_id = "fid_sanctions"
    FILE = "fid_subjects.xlsx"

    def _sheet(self, ctx):
        spec = schemas()["xlsx"]["fid_subjects"]
        wb = load_workbook(ctx.workdir / self.FILE, read_only=True, data_only=True)
        if spec["sheet"] not in wb.sheetnames:
            wb.close()
            raise SchemaMismatch(f"{self.FILE}: no sheet {spec['sheet']!r} ({wb.sheetnames})")
        return wb, wb[spec["sheet"]], spec["columns"]

    def check_schema(self, ctx):
        wb, ws, expected = self._sheet(ctx)
        try:
            header = next(ws.iter_rows(min_row=1, max_row=1, values_only=True))
            titles = [str(c).strip() if c is not None else "" for c in header]
            while titles and titles[-1] == "":
                titles.pop()
            check_columns(self.FILE, titles, expected)
        finally:
            wb.close()

    def fetch(self, ctx):
        files = [fetch_whole(ctx, "subjects", self.FILE)]
        self.check_schema(ctx)
        return files

    def version_date(self, ctx, files):
        return resource_date(ctx, ["subjects"])

    def load(self, ctx, conn, version_id, files):
        self.check_schema(ctx)
        counts: Counter = Counter()
        wb, ws, _ = self._sheet(ctx)

        def rows():
            for row_no, cells in enumerate(ws.iter_rows(min_row=2, values_only=True), start=1):
                cells = list(cells) + [None] * 10
                if all(c is None or str(c).strip() == "" for c in cells[:10]):
                    continue
                counts["source_rows"] += 1
                reg = legal_reg_no(cells[1])
                if reg is None:
                    # a person (birth date), a foreign number or nothing: not stored (D10)
                    counts["skipped_no_lv_reg_no"] += 1
                    continue
                counts["loaded"] += 1
                # columns 1-5, 7, 8, 10; column 6 (the sanctioned person) never
                yield (
                    version_id,
                    row_no,
                    reg,
                    _cell_text(cells[0]),
                    _cell_text(cells[2]),
                    _cell_text(cells[3]),
                    _cell_text(cells[4]),
                    _cell_text(cells[6]),
                    _cell_text(cells[7]),
                    _cell_text(cells[9]),
                )

        try:
            loaded = copy_rows(conn, "ref.fid_sanction", FID_COLUMNS, rows())
        finally:
            wb.close()
        ctx.processing = [
            {
                "id": "personal_data",
                "what": "Only rows with a Latvian legal-entity reg. no.; column 6 (the sanctioned "
                "person) never stored (D10)",
                "skipped_no_lv_reg_no": counts["skipped_no_lv_reg_no"],
            }
        ]
        return {"fid_sanction": {"source_rows": counts["source_rows"], "loaded": loaded}}
