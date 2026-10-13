"""cadastre_ownership: pilot members of ownership.zip (Phase 8b module 7, D5).

Owner type only (`OwnershipStatus` + `PersonStatus`); the XSD has no name or
person-code fields. Same Range-fetch identity as cadastre_text.
"""

from etl.importers.cadastre_text import (
    check_parts,
    fetch_pilot_members,
    iter_file_items,
    prepared_date,
    scan_header,
)
from etl.importers.common import copy_rows
from etl.schema_check import SchemaMismatch, check_xml_paths
from etl.settings import schemas
from etl.textio import children, text

PERSON_KIND = {
    "fiziska persona": "natural",
    "juridiska persona": "legal",
    "valsts": "state",
    "pašvaldība": "municipality",
    "cits": "other",
}
REQUIRED = [
    "ObjectRelation/ObjectCadastreNr",
    "ObjectRelation/ObjectType",
    "OwnershipStatusKindList/OwnershipStatusKind/OwnershipStatus",
    "OwnershipStatusKindList/OwnershipStatusKind/PersonStatus",
]
COLUMNS = [
    "dataset_version_id",
    "object_cadastre_nr",
    "object_type",
    "ownership_status",
    "person_status",
    "person_kind",
]


class CadastreOwnership:
    source_id = "cadastre_ownership"
    role = "ownership"

    def fetch(self, ctx):
        return fetch_pilot_members(ctx, (self.role,))

    def version_date(self, ctx, files):
        return prepared_date(ctx, files)

    def load(self, ctx, conn, version_id, files):
        (f,) = files
        check_parts(ctx.workdir, self.role, f.members)
        spec = schemas()["xml"][self.role]
        seen, root_children = set(), set()
        counts = {"items": 0, "rows": 0}

        def rows():
            for m in f.members:
                scan_header(ctx.workdir / m.path)
                for item in iter_file_items(ctx.workdir / m.path, self.role, seen, root_children):
                    counts["items"] += 1
                    cad = text(item, "ObjectRelation", "ObjectCadastreNr")
                    otype = text(item, "ObjectRelation", "ObjectType")
                    if not cad or not otype:
                        raise ValueError(f"{m.path}: ownership item without ObjectRelation")
                    for kind in children(item, "OwnershipStatusKindList", "OwnershipStatusKind"):
                        status = text(kind, "OwnershipStatus")
                        person = text(kind, "PersonStatus")
                        if not status or not person:
                            raise ValueError(f"{m.path}: empty OwnershipStatus/PersonStatus")
                        pk = PERSON_KIND.get(person)
                        if pk is None:
                            raise ValueError(f"{m.path}: unknown PersonStatus {person!r}")
                        counts["rows"] += 1
                        yield (version_id, cad, otype, status, person, pk)

        loaded = copy_rows(conn, "ref.ownership", COLUMNS, rows())
        check_xml_paths(self.role, seen, spec["paths"], REQUIRED)
        unknown_root = root_children - set(spec["root_children"])
        if unknown_root:
            raise SchemaMismatch(f"{self.role}: unknown root elements {sorted(unknown_root)}")
        ctx.processing = [
            {
                "id": "ownership_type_only",
                "what": "Owner type only (PersonStatus); no names in the source (D5)",
                "items": counts["items"],
                "rows": loaded,
            }
        ]
        return {
            "ownership": {
                "members": len(f.members),
                "items": counts["items"],
                "loaded": loaded,
            }
        }
