"""bis_cases: BIS construction cases (docs/data-sources.md §7.1).

Raw CSVs only, never the CKAN DataStore (truncated at 48,000 rows, designations
typed as numbers). Pilot scope: a case object whose ATVK (zero-padded to 7) is a
pilot city or whose designation starts with the city's cadastral territory code;
the cases are those of the pilot objects. Country (Phase 9): every case object.
Version identity: SHA-256 of the canonical scoped rows (FileRecord.pilot_sha256),
so in pilot mode a change elsewhere in Latvia creates no version. Links to the
cadastre: ref.bis_links (migration 20261010120000).
"""

import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date

from etl import codes
from etl.importers.common import copy_rows, fetch_whole, resource_date
from etl.schema_check import check_columns
from etl.settings import schemas
from etl.textio import clean_text, csv_header, iter_csv

FILES = {"cases": "cases.csv", "objects": "objects.csv"}

ATVK_ZERO_PADDED = "atvk_zero_padded"
ROOM_GROUP_CUT = "room_group_cut"
INVALID_DESIGNATION = "invalid_designation"

_NUM = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")

CASE_COLUMNS = [
    "dataset_version_id",
    "case_number",
    "authority",
    "application_kind",
    "object_name",
    "stage",
    "construction_kind",
    "created_date",
]
OBJECT_COLUMNS = [
    "dataset_version_id",
    "row_no",
    "case_number",
    "designation",
    "building_code",
    "engineering_id",
    "melioration_number",
    "lon",
    "lat",
    "name",
    "address_text",
    "address_code",
    "construction_kind",
    "atvk",
    "atvk_name",
    "in_scope_by",
    "flags",
]


def pad_atvk(value: str) -> tuple[str | None, list[str]]:
    """BIS writes ATVK codes without leading zeros (`4000` = `0004000`)."""
    value = value.strip()
    if not value:
        return None, []
    if not value.isdigit() or len(value) > 7:
        raise ValueError(f"ATVK {value!r} is not up to 7 digits")
    if len(value) < 7:
        return value.zfill(7), [ATVK_ZERO_PADDED]
    return value, []


def designation(value: str) -> tuple[str | None, str | None, list[str]]:
    """(designation, 14-digit building code, flags). Rule E2 restores one lost
    leading zero; a 17-digit room-group designation is cut to its building."""
    raw = value.strip()
    if not raw:
        return None, None, []
    if not raw.isdigit():
        return raw, None, [INVALID_DESIGNATION]
    length = codes.PREMISE_GROUP if len(raw) in (16, 17) else codes.BUILDING
    code, flags = codes.normalize_code(raw, length)
    if codes.UNEXPECTED_LENGTH in flags:
        return code, None, flags
    if len(code) == codes.PREMISE_GROUP:
        return code, code[: codes.BUILDING], [*flags, ROOM_GROUP_CUT]
    return code, code, flags


@dataclass(slots=True)
class PilotObject:
    """One case-object row cut to the pilot, with its normalised codes."""

    row_no: int
    row: dict[str, str]
    atvk: str | None
    designation: str | None
    building_code: str | None
    in_scope_by: list[str]
    flags: list[str]


def pilot_objects(path, pilot_atvk: set[str] | None, territories: set[str] | None):
    """Yield PilotObject for every in-scope row of the case-objects CSV (row_no from 1).

    When pilot_atvk/territories are None (country scope), every row is kept.
    """
    for row_no, row in enumerate(iter_csv(path), start=1):
        atvk, aflags = pad_atvk(row["Administrativas_teritorijas_kods"])
        des, building_code, dflags = designation(row["Buves_kadastra_apzimejums"])
        if pilot_atvk is None and territories is None:
            yield PilotObject(row_no, row, atvk, des, building_code, ["country"], aflags + dflags)
            continue
        scope = []
        if atvk in (pilot_atvk or ()):
            scope.append("atvk")
        if (
            des
            and territories is not None
            and des[:4] in territories
            and INVALID_DESIGNATION not in dflags
        ):
            scope.append("designation_prefix")
        if scope:
            yield PilotObject(row_no, row, atvk, des, building_code, scope, aflags + dflags)


def _digest(header: list[str], rows) -> str:
    """SHA-256 of the header and the raw (row_no, values) of the pilot rows."""
    h = hashlib.sha256(json.dumps(header, ensure_ascii=False).encode())
    for row_no, values in rows:
        h.update(b"\n" + json.dumps([row_no, *values], ensure_ascii=False).encode())
    return h.hexdigest()


def _number(value: str, what: str) -> float | None:
    value = value.strip()
    if not value:
        return None
    if not _NUM.match(value):
        raise ValueError(f"{what}: not a number: {value!r}")
    return float(value)


def _address_code(value: str, row_no: int) -> str | None:
    value = value.strip()
    if not value:
        return None
    if not (value.isdigit() and len(value) == 9):
        raise ValueError(f"case object row {row_no}: VARIS code {value!r} is not 9 digits")
    return value


def _date(value: str, case: str) -> date | None:
    value = value.strip()
    if not value:
        return None
    if not _DATE.match(value):
        raise ValueError(f"case {case}: date {value!r} is not YYYY-MM-DD")
    return date.fromisoformat(value)


class BisCases:
    source_id = "bis_cases"

    def _scope(self, ctx):
        if ctx.cfg.is_pilot:
            return set(ctx.cfg.pilot_atvk), set(ctx.cfg.pilot_cadastral_territory.values())
        return None, None

    def check_schema(self, ctx):
        for role, name in FILES.items():
            check_columns(name, csv_header(ctx.workdir / name), schemas()["csv"][f"bis_{role}"])

    def fetch(self, ctx):
        files = {role: fetch_whole(ctx, role, name) for role, name in FILES.items()}
        self.check_schema(ctx)
        objects = list(pilot_objects(ctx.workdir / FILES["objects"], *self._scope(ctx)))
        cases = {o.row["Buvniecibas_lietas_numurs"].strip() for o in objects}
        files["objects"].pilot_sha256 = _digest(
            csv_header(ctx.workdir / FILES["objects"]),
            ((o.row_no, list(o.row.values())) for o in objects),
        )
        files["cases"].pilot_sha256 = _digest(
            csv_header(ctx.workdir / FILES["cases"]),
            (
                (n, list(r.values()))
                for n, r in enumerate(iter_csv(ctx.workdir / FILES["cases"]), start=1)
                if r["Buvniecibas_lietas_numurs"].strip() in cases
            ),
        )
        return list(files.values())

    def version_date(self, ctx, files):
        return resource_date(ctx, FILES)

    def load(self, ctx, conn, version_id, files):
        self.check_schema(ctx)
        w = ctx.workdir
        flag_counts: Counter = Counter()
        seen_rows: Counter = Counter()
        cases: set[str] = set()
        n_objects = 0

        def object_rows():
            nonlocal n_objects
            for o in pilot_objects(w / FILES["objects"], *self._scope(ctx)):
                n_objects += 1
                r = o.row
                case = r["Buvniecibas_lietas_numurs"].strip()
                if not case:
                    raise ValueError(f"case object row {o.row_no}: no case number")
                cases.add(case)
                seen_rows[tuple(r.values())] += 1
                flag_counts.update(o.flags)
                yield (
                    version_id,
                    o.row_no,
                    case,
                    o.designation,
                    o.building_code,
                    clean_text(r["Objekta_identifikators_inzenierbuvem"]),
                    clean_text(r["Melioracijas_kadastra_numurs"]),
                    _number(r["Buves_atrasanas_vieta_geografiskais_garums"], f"row {o.row_no}"),
                    _number(r["Buves_atrasanas_vieta_geografiskais_platums"], f"row {o.row_no}"),
                    clean_text(r["Buves_nosaukums"]),
                    clean_text(r["Buves_objekta_adreses_teksts"]),
                    _address_code(r["Buves_objekta_adreses_kods"], o.row_no),
                    clean_text(r["Buvniecibas_veids"]),
                    o.atvk,
                    clean_text(r["Administrativas_teritorijas_nosaukums"]),
                    o.in_scope_by,
                    sorted(set(o.flags)),
                )

        loaded_objects = copy_rows(conn, "ref.bis_object", OBJECT_COLUMNS, object_rows())
        if loaded_objects != n_objects:
            raise ValueError(f"bis_object: {n_objects} pilot rows but {loaded_objects} loaded")

        source_cases = 0

        def case_rows():
            nonlocal source_cases
            for r in iter_csv(w / FILES["cases"]):
                source_cases += 1
                case = r["Buvniecibas_lietas_numurs"].strip()
                if case not in cases:
                    continue
                yield (
                    version_id,
                    case,
                    clean_text(r["Atbildigas_iestades_nosaukums"]),
                    clean_text(r["Buvniecibas_iesnieguma_veids"]),
                    clean_text(r["Objekta_nosaukums"]),
                    clean_text(r["Aktuala_stadija"]),
                    clean_text(r["Buvniecibas_veids"]),
                    _date(r["Lietas_izveidosanas_datums"], case),
                )

        loaded_cases = copy_rows(conn, "ref.bis_case", CASE_COLUMNS, case_rows())
        missing = len(cases) - loaded_cases
        duplicates = sum(n - 1 for n in seen_rows.values() if n > 1)
        ctx.processing = [
            {
                "id": "import_scope",
                "what": (
                    "Case objects whose ATVK is a pilot city or whose designation starts with "
                    "the city's cadastral territory code; the cases of those objects"
                    if ctx.cfg.is_pilot
                    else "Every case object in the national BIS files (import_scope=country)"
                ),
                "import_scope": ctx.cfg.import_scope,
                "scoped_objects": loaded_objects,
                "scoped_cases": len(cases),
                "cases_missing_from_case_list": missing,
            },
            {
                "id": "codes",
                "what": "ATVK zero-padded to 7 digits; room groups cut to the 14-digit building; "
                "rule E2 leading zeros",
                **{k: v for k, v in sorted(flag_counts.items())},
            },
            {
                "id": "duplicate_rows",
                "what": "Exact duplicate case-object rows kept as published (key = CSV row number)",
                "duplicate_rows": duplicates,
            },
        ]
        if missing:
            ctx.notes.append(f"{missing} scoped cases are not in the case list")
        return {
            "bis_object": {"loaded": loaded_objects, "flags": dict(flag_counts)},
            "bis_case": {
                "source_rows": source_cases,
                "scoped_cases": len(cases),
                "loaded": loaded_cases,
            },
        }
