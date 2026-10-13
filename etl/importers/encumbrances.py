"""Registered encumbrances (PLAN §6.1 module 6; docs/data-sources.md §7.2-7.3).

- cadastre_encumbrances: scoped members of the cadastre text encumbrance.zip
  (HTTP Range, same identity rules as cadastre_text; pilot or country).
- atis_classifier: the ATIS and cadastre encumbrance classifier CSV.
- encumbrances_frozen: the list frozen on 2025-01-31. Pilot: rows of the regional
  files that hold the pilot cities, cut by cadastral territory. Country: every
  row of those same configured regional files (Latgale, Rīga, Zemgale — other
  regions need verified resource ids before they are added). Imported with the
  flag `frozen` and its as-of date.
"""

import re
from datetime import date

from etl import codes
from etl.importers.cadastre_text import (
    check_parts,
    fetch_pilot_members,
    iter_file_items,
    prepared_date,
    scan_header,
)
from etl.importers.common import copy_rows, fetch_whole, resource_date
from etl.schema_check import SchemaMismatch, check_columns, check_xml_paths
from etl.settings import schemas
from etl.textio import child, children, clean_text, csv_header, iter_csv, text

ATIS_CODE = 10
OBJECT_TYPE_LENGTH = {
    "PARCEL": codes.PARCEL,
    "PARCEL PART": codes.PARCEL_PART,
    "BUILDING": codes.BUILDING,
}
REQUIRED = [
    "ObjectRelation/ObjectCadastreNr",
    "ObjectRelation/ObjectType",
    "EncumbranceList/EncumbranceRowData/EncumbranceKind/EncumbranceKindId",
]
FROZEN = "frozen"

_NUM = re.compile(r"^[0-9]+(\.[0-9]+)?$")
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_FILE_DATE = re.compile(r"_(?P<d>[0-9]{8})\.csv$")


def _number(value: str | None, what: str) -> str | None:
    if value is None or not value.strip():
        return None
    if not _NUM.match(value.strip()):
        raise ValueError(f"{what}: not a number: {value!r}")
    return value.strip()


def _date(value: str | None, what: str) -> date | None:
    if value is None or not value.strip():
        return None
    if not _DATE.match(value.strip()):
        raise ValueError(f"{what}: date {value!r} is not YYYY-MM-DD")
    return date.fromisoformat(value.strip())


def _atis_code(value: str | None, what: str) -> tuple[str, list[str]]:
    code, flags = codes.normalize_code(value, ATIS_CODE)
    if code is None or not code.isdigit() or codes.UNEXPECTED_LENGTH in flags:
        raise ValueError(f"{what}: ATIS code {value!r} is not {ATIS_CODE} digits")
    return code, flags


class CadastreEncumbrances:
    source_id = "cadastre_encumbrances"
    role = "encumbrance"

    def fetch(self, ctx):
        return fetch_pilot_members(ctx, (self.role,))

    def version_date(self, ctx, files):
        return prepared_date(ctx, files)

    def load(self, ctx, conn, version_id, files):
        (f,) = files
        check_parts(ctx.workdir, self.role, f.members)
        spec = schemas()["xml"][self.role]
        seen, root_children = set(), set()
        items = rows_seen = 0
        by_type: dict[str, int] = {}

        def rows():
            nonlocal items, rows_seen
            row_no = 0
            for m in f.members:
                path = ctx.workdir / m.path
                atvk = scan_header(path)["ATVK"]
                for it in iter_file_items(path, self.role, seen, root_children):
                    items += 1
                    otype = text(it, "ObjectRelation", "ObjectType")
                    if otype not in OBJECT_TYPE_LENGTH:
                        raise SchemaMismatch(f"encumbrance: unknown ObjectType {otype!r}")
                    by_type[otype] = by_type.get(otype, 0) + 1
                    obj, oflags = codes.normalize_code(
                        text(it, "ObjectRelation", "ObjectCadastreNr"), OBJECT_TYPE_LENGTH[otype]
                    )
                    if obj is None:
                        raise ValueError("encumbrance: item without ObjectCadastreNr")
                    for r in children(it, "EncumbranceList", "EncumbranceRowData"):
                        rows_seen += 1
                        row_no += 1
                        kind, kflags = _atis_code(
                            text(r, "EncumbranceKind", "EncumbranceKindId"), f"encumbrance {obj}"
                        )
                        yield (
                            version_id,
                            row_no,
                            obj,
                            otype,
                            atvk,
                            kind,
                            text(r, "EncumbranceKind", "EncumbranceKindName"),
                            text(r, "EncumbranceNr"),
                            _date(text(r, "EncumbranceEstablishDate"), f"encumbrance {obj}"),
                            _number(text(r, "EncumbranceArea"), f"encumbrance {obj}"),
                            text(r, "EncumbranceMeasure"),
                            sorted(set(oflags + kflags)),
                        )
                    if child(it, "EncumbranceList") is None:
                        raise SchemaMismatch(f"encumbrance {obj}: no EncumbranceList")

        loaded = copy_rows(
            conn,
            "ref.encumbrance",
            [
                "dataset_version_id",
                "row_no",
                "object_code",
                "object_type",
                "file_atvk",
                "kind_id",
                "kind_name",
                "encumbrance_nr",
                "establish_date",
                "area",
                "measure",
                "flags",
            ],
            rows(),
        )
        check_xml_paths(self.role, seen, spec["paths"], REQUIRED)
        unknown_root = root_children - set(spec["root_children"])
        if unknown_root:
            raise SchemaMismatch(f"encumbrance: unknown root elements {sorted(unknown_root)}")
        if loaded != rows_seen:
            raise ValueError(f"encumbrance: {rows_seen} rows in the files but {loaded} loaded")
        return {
            "encumbrance": {
                "source_items": items,
                "source_rows": rows_seen,
                "loaded": loaded,
                "items_by_object_type": by_type,
                "members": len(f.members),
            }
        }


class AtisClassifier:
    source_id = "atis_classifier"
    role = "classifier"
    filename = "classifier.csv"

    def fetch(self, ctx):
        return [fetch_whole(ctx, self.role, self.filename)]

    def version_date(self, ctx, files):
        return resource_date(ctx, [self.role])

    def load(self, ctx, conn, version_id, files):
        path = ctx.workdir / self.filename
        check_columns(self.filename, csv_header(path), schemas()["csv"]["atis_classifier"])
        n = 0

        def rows():
            nonlocal n
            for r in iter_csv(path):
                n += 1
                code, _ = _atis_code(r["Kods"], f"classifier row {n}")
                yield (
                    version_id,
                    code,
                    clean_text(r["Dati"]),
                    clean_text(r["Grupa"]),
                    clean_text(r["Veids"]),
                    clean_text(r["Apraksts"]),
                    clean_text(r["Elements"]),
                    clean_text(r["DatiKadastra"]),
                    clean_text(r["Visparpieejami_dati"]),
                    clean_text(r["Ierobezoti_dati"]),
                )

        loaded = copy_rows(
            conn,
            "ref.atis_classifier",
            [
                "dataset_version_id",
                "code",
                "data_kind",
                "group_name",
                "kind",
                "description",
                "elements",
                "in_cadastre",
                "public_data",
                "restricted_data",
            ],
            rows(),
        )
        return {"atis_classifier": {"source_rows": n, "loaded": loaded}}


class EncumbrancesFrozen:
    source_id = "encumbrances_frozen"

    def _roles(self, ctx):
        return list(ctx.cfg.files[self.source_id])

    def fetch(self, ctx):
        return [fetch_whole(ctx, role, f"{role}.csv") for role in self._roles(ctx)]

    def frozen_as_of(self, ctx, role: str) -> date:
        """The file's own date (rule E7): `…_20250131.csv` in the resource URL."""
        hit = _FILE_DATE.search(ctx.resources[role].url)
        if not hit:
            raise SchemaMismatch(f"{role}: no YYYYMMDD date in {ctx.resources[role].url}")
        return date(int(hit["d"][:4]), int(hit["d"][4:6]), int(hit["d"][6:]))

    def version_date(self, ctx, files):
        dates = {self.frozen_as_of(ctx, role) for role in self._roles(ctx)}
        if len(dates) != 1:
            raise ValueError(f"frozen list files have different dates: {sorted(dates)}")
        return dates.pop()

    def load(self, ctx, conn, version_id, files):
        territories = ctx.cfg.scope_territories()  # None = country (no prefix cut)
        counts = {}
        for role in self._roles(ctx):
            path = ctx.workdir / f"{role}.csv"
            check_columns(path.name, csv_header(path), schemas()["csv"]["encumbrances_frozen"])
            kind = "parcel_part" if role.endswith("_part") else "parcel"
            length = codes.PARCEL_PART if kind == "parcel_part" else codes.PARCEL
            as_of = self.frozen_as_of(ctx, role)
            n = 0

            def rows(path=path, role=role, kind=kind, length=length, as_of=as_of):
                nonlocal n
                for row_no, r in enumerate(iter_csv(path), start=1):
                    n += 1
                    obj, flags = codes.normalize_code(r["CAD_NR"], length)
                    if obj is None:
                        continue
                    if territories is not None and obj[:4] not in territories:
                        continue
                    code = (r["ENCD_ID"] or "").strip()
                    if not code.isdigit():
                        raise ValueError(f"{role} row {row_no}: ENCD_ID {code!r} is not digits")
                    yield (
                        version_id,
                        role,
                        row_no,
                        obj,
                        kind,
                        clean_text(r["ADMRKIND"]),
                        clean_text(r["ADMTKIND"]),
                        code,  # as published: 6- and 8-digit codes of the earlier classifier
                        clean_text(r["DESCRIPTION"]),
                        clean_text(r["NR"]),
                        _date(r["ENC_DATE"], f"{role} row {row_no}"),
                        _number(r["ENC_SIZE"], f"{role} row {row_no}"),
                        clean_text(r["MEASURE"]),
                        as_of,
                        sorted({FROZEN, *flags}),
                    )

            loaded = copy_rows(
                conn,
                "ref.encumbrance_frozen",
                [
                    "dataset_version_id",
                    "file_role",
                    "row_no",
                    "object_code",
                    "object_kind",
                    "region_kind",
                    "territory",
                    "code",
                    "description",
                    "encumbrance_nr",
                    "establish_date",
                    "area",
                    "measure",
                    "frozen_as_of",
                    "flags",
                ],
                rows(),
            )
            counts[role] = {"source_rows": n, "loaded": loaded}
        ctx.processing = [
            {
                "id": "frozen",
                "what": "Encumbrances registered until 2025-01-31 (frozen list, never updated); "
                "rows not in the current list are shown separately, never as current",
                "frozen_as_of": str(self.version_date(ctx, files)),
            }
        ]
        return {f"encumbrance_frozen.{role}": c for role, c in counts.items()}
