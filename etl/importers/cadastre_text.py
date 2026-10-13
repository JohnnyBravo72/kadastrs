"""cadastre_text: scoped members of the national cadastre XML zips.

Pilot: only the pilot cities' members. Country (Phase 9): every ATVK member.
Fetched by HTTP Range (full download if the server ignores Range). Version
identity: docs/data-sources.md §5.4.
"""

import json
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date
from pathlib import Path

from etl import codes
from etl.identity import FileRecord, MemberRecord, fingerprints, iso
from etl.importers.common import copy_rows
from etl.remote import RemoteZip
from etl.run import RemoteUnchanged
from etl.schema_check import SchemaMismatch, check_xml_paths
from etl.settings import schemas
from etl.textio import child, children, element_paths, local, text

ROLES = ("parcel", "parcelpart", "building", "property")
ITEMS = {
    "parcel": "ParcelItemData",
    "parcelpart": "ParcelPartItemData",
    "building": "BuildingItemData",
    "property": "PropertyItemData",
    "encumbrance": "EncumbranceItemData",  # cadastre_encumbrances (etl/importers/encumbrances.py)
    "ownership": "OwnershipItemData",  # cadastre_ownership (etl/importers/ownership.py)
}
# Elements the importer reads; each must exist in the file (schema check).
REQUIRED = {
    "parcel": [
        "ParcelBasicData/ParcelCadastreNr",
        "ParcelBasicData/ATVKCode",
        "ParcelBasicData/ParcelArea",
    ],
    "parcelpart": [
        "ParcelPartBasicData/ParcelPartCadastreNr",
        "ObjectRelation/ObjectCadastreNr",
        "ObjectRelation/ObjectType",
    ],
    "building": [
        "BuildingBasicData/BuildingCadastreNr",
        "ObjectRelation/ObjectCadastreNr",
        "ObjectRelation/ObjectType",
    ],
    "property": ["CadastreObjectIdData/ProCadastreNr", "CadastreObjectIdData/PropertyKind"],
}
# <Kind>/<ATVK>_<YYYYMMDD>_<n>/<GUID>.xml
_MEMBER = re.compile(r"^[^/]+/(?P<atvk>[0-9]{7})_(?P<date>[0-9]{8})_[0-9]+/[^/]+\.xml$")
OBJECT_KIND_LENGTH = {
    "Zemes vienība": codes.PARCEL,
    "Būve": codes.BUILDING,
    "Būve(FSO)": codes.BUILDING,
    "Telpu grupa": codes.PREMISE_GROUP,
}


def pilot_members(members, pilot: set[str] | None):
    """Members whose path ATVK is in `pilot`, or every ATVK member when pilot is None."""
    out = []
    for m in members:
        hit = _MEMBER.match(m.name)
        if not hit:
            continue
        if pilot is None or hit["atvk"] in pilot:
            out.append((hit["atvk"], m))
    return out


def scan_header(path: Path) -> dict[str, str]:
    """Root-level scalar elements (PreparedDate, ATVK, FilePartCount, FilePartNr)."""
    header, depth = {}, 0
    for ev, el in ET.iterparse(path, events=("start", "end")):  # noqa: S314 stdlib parser: no external entities; expat limits amplification
        if ev == "start":
            depth += 1
            continue
        if depth == 2 and len(el) == 0:
            header[local(el.tag)] = (el.text or "").strip()
        if depth == 2 and local(el.tag).endswith("ItemList"):
            break
        depth -= 1
    return header


def iter_file_items(path: Path, role: str, seen_paths: set[str], root_children: set[str]):
    """Yield items (depth 3) of one member, collecting element paths for the schema check."""
    item_name = ITEMS[role]
    spec = schemas()["xml"][role]
    depth = 0
    for ev, el in ET.iterparse(path, events=("start", "end")):  # noqa: S314 stdlib parser: no external entities; expat limits amplification
        if ev == "start":
            depth += 1
            if depth == 1 and local(el.tag) != spec["root"]:
                raise SchemaMismatch(f"{path.name}: root {local(el.tag)}, expected {spec['root']}")
            continue
        if depth == 2:
            root_children.add(local(el.tag))
        elif depth == 3:
            if local(el.tag) != item_name:
                raise SchemaMismatch(f"{path.name}: unexpected item {local(el.tag)}")
            seen_paths |= element_paths(el)
            yield el
            el.clear()
        depth -= 1


def fetch_pilot_members(ctx, roles) -> list[FileRecord]:
    """Fetch scoped members of national cadastre text zips by HTTP Range (whole
    zip if Range is ignored). Raises RemoteUnchanged when the zips' remote
    fingerprints equal the live version's (docs/data-sources.md §5.4)."""
    # None = country (every ATVK member); set = pilot cities only.
    scope = set(ctx.cfg.scope_atvk()) if ctx.cfg.is_pilot else None
    zips, records = {}, []
    for role in roles:
        res = ctx.resources[role]
        rz = RemoteZip(ctx.client, res.url, ctx.workdir / "_full").open()
        if not rz.range_supported:
            ctx.notes.append(f"range_unsupported: {role} downloaded in full")
        zips[role] = rz
        records.append(
            FileRecord(
                role=role,
                resource_id=res.id,
                url=res.url,
                last_modified=iso(res.last_modified),
                size=rz.total_size,
                central_directory_sha256=rz.central_directory_sha256,
                range_supported=rz.range_supported,
            )
        )
    live = ctx.live_fingerprints()
    if live is not None and live == fingerprints(records):
        raise RemoteUnchanged()

    for rec in records:
        rz = zips[rec.role]
        found = pilot_members(rz.members, scope)
        if scope is not None:
            missing = scope - {a for a, _ in found}
            if missing:
                raise ValueError(f"{rec.role}.zip has no member for ATVK {sorted(missing)}")
        elif not found:
            raise ValueError(f"{rec.role}.zip has no ATVK members")
        for _atvk, m in sorted(found, key=lambda x: x[1].name):
            rel = f"{rec.role}/{Path(m.name).name}"
            sha = rz.extract(m, ctx.workdir / rel)
            rec.members.append(
                MemberRecord(name=m.name, crc32=m.crc32, size=m.usize, sha256=sha, path=rel)
            )
    for rz in zips.values():
        if rz.local_copy is not None:
            rz.local_copy.unlink(missing_ok=True)
    return records


def prepared_date(ctx, files) -> date:
    """The files' own PreparedDate (rule E7): the oldest across members."""
    dates = []
    for f in files:
        for m in f.members:
            d = scan_header(ctx.workdir / m.path).get("PreparedDate")
            if not d:
                raise SchemaMismatch(f"{m.name}: no PreparedDate")
            dates.append(date.fromisoformat(d))
    return min(dates)


def check_parts(workdir: Path, role: str, members) -> None:
    """A city may be split into several members: all parts 1..FilePartCount present."""
    parts = defaultdict(list)
    for m in members:
        h = scan_header(workdir / m.path)
        parts[h["ATVK"]].append(int(h.get("FilePartNr") or 0))
        if int(h.get("FilePartCount") or 0) < 1:
            raise SchemaMismatch(f"{m.name}: FilePartCount missing")
    for m in members:
        h = scan_header(workdir / m.path)
        expected = int(h["FilePartCount"])
        if sorted(parts[h["ATVK"]]) != list(range(1, expected + 1)):
            raise ValueError(
                f"{role} ATVK {h['ATVK']}: parts {sorted(parts[h['ATVK']])}, "
                f"FilePartCount {expected}"
            )


def _code(value, length, what):
    code, flags = codes.normalize_code(value, length)
    if code is None:
        raise ValueError(f"{what}: missing designation")
    return code, flags


def _land_purposes(item) -> str:
    out = []
    for lp in children(item, "LandPurposeList", "LandPurposeData"):
        out.append(
            {
                "id": text(lp, "LandPurposeKind", "LandPurposeKindId"),
                "name": text(lp, "LandPurposeKind", "LandPurposeKindName"),
                "area": text(lp, "LandPurposeArea"),
            }
        )
    return json.dumps(out, ensure_ascii=False)


def _int(value: str | None) -> str | None:
    if value is None:
        return None
    if not re.fullmatch(r"-?[0-9]+", value):
        raise ValueError(f"not an integer: {value!r}")
    return value


class CadastreText:
    source_id = "cadastre_text"

    def fetch(self, ctx):
        return fetch_pilot_members(ctx, ROLES)

    def version_date(self, ctx, files) -> date:
        return prepared_date(ctx, files)

    # -- load ------------------------------------------------------------------

    def load(self, ctx, conn, version_id, files):
        counts = {}
        for f in files:
            role = f.role
            spec = schemas()["xml"][role]
            seen, root_children = set(), set()
            check_parts(ctx.workdir, role, f.members)
            handler = getattr(self, f"_load_{role}")
            c = handler(conn, version_id, ctx.workdir, f.members, seen, root_children)
            check_xml_paths(role, seen, spec["paths"], REQUIRED[role])
            unknown_root = root_children - set(spec["root_children"])
            if unknown_root:
                raise SchemaMismatch(f"{role}: unknown root elements {sorted(unknown_root)}")
            for table_counts in c.values():
                table_counts["members"] = len(f.members)
            counts.update(c)
        return counts

    def _items(self, workdir, members, role, seen, root_children):
        for m in members:
            atvk = scan_header(workdir / m.path)["ATVK"]
            for item in iter_file_items(workdir / m.path, role, seen, root_children):
                yield atvk, item

    def _load_parcel(self, conn, vid, workdir, members, seen, root_children):
        n = 0

        def rows():
            nonlocal n
            for _, it in self._items(workdir, members, "parcel", seen, root_children):
                n += 1
                code, flags = _code(
                    text(it, "ParcelBasicData", "ParcelCadastreNr"), codes.PARCEL, "parcel"
                )
                yield (
                    vid,
                    code,
                    text(it, "ParcelBasicData", "ATVKCode"),
                    text(it, "ParcelBasicData", "ParcelArea"),
                    text(it, "ParcelBasicData", "ParcelVARISCode"),
                    text(it, "ParcelBasicData", "ParcelStatus", "ParcelStatusKindName"),
                    _land_purposes(it),
                    flags,
                )

        loaded = copy_rows(
            conn,
            "ref.parcel",
            [
                "dataset_version_id",
                "code",
                "atvk",
                "area_m2",
                "varis_code",
                "status_kind",
                "land_purposes",
                "flags",
            ],
            rows(),
        )
        return {"parcel": {"source_items": n, "loaded": loaded}}

    def _load_parcelpart(self, conn, vid, workdir, members, seen, root_children):
        n = 0

        def rows():
            nonlocal n
            for atvk, it in self._items(workdir, members, "parcelpart", seen, root_children):
                n += 1
                code, flags = _code(
                    text(it, "ParcelPartBasicData", "ParcelPartCadastreNr"),
                    codes.PARCEL_PART,
                    "parcel part",
                )
                if text(it, "ObjectRelation", "ObjectType") != "PARCEL":
                    raise ValueError(f"parcel part {code}: ObjectType is not PARCEL")
                parcel, pflags = _code(
                    text(it, "ObjectRelation", "ObjectCadastreNr"),
                    codes.PARCEL,
                    f"parcel part {code}",
                )
                yield (
                    vid,
                    code,
                    parcel,
                    text(it, "ParcelPartBasicData", "ParcelPartArea"),
                    _land_purposes(it),
                    atvk,
                    flags + pflags,
                )

        loaded = copy_rows(
            conn,
            "ref.parcel_part",
            [
                "dataset_version_id",
                "code",
                "parcel_code",
                "area_m2",
                "land_purposes",
                "file_atvk",
                "flags",
            ],
            rows(),
        )
        return {"parcel_part": {"source_items": n, "loaded": loaded}}

    def _load_building(self, conn, vid, workdir, members, seen, root_children):
        n, links = 0, []

        def rows():
            nonlocal n
            for atvk, it in self._items(workdir, members, "building", seen, root_children):
                n += 1
                b = child(it, "BuildingBasicData")
                code, flags = _code(text(b, "BuildingCadastreNr"), codes.BUILDING, "building")
                if text(it, "ObjectRelation", "ObjectType") != "PARCEL":
                    raise ValueError(f"building {code}: ObjectType is not PARCEL")
                primary, pflags = _code(
                    text(it, "ObjectRelation", "ObjectCadastreNr"), codes.PARCEL, f"building {code}"
                )
                linked = {primary: "object_relation"}
                for nr in children(b, "ParcelCadastreNrList", "ObjectCadastreNrData"):
                    pc, f2 = _code(text(nr), codes.PARCEL, f"building {code} parcel list")
                    linked.setdefault(pc, "parcel_list")
                    pflags += f2
                links.extend((vid, code, pc, rel) for pc, rel in linked.items())
                kind = next(iter(children(it, "BuildingTypeData", "BuildingKind")), None)
                yield (
                    vid,
                    code,
                    atvk,
                    text(b, "BuildingName"),
                    text(b, "BuildingUseKind", "BuildingUseKindId"),
                    text(b, "BuildingUseKind", "BuildingUseKindName"),
                    text(kind, "BuildingKindId") if kind is not None else None,
                    text(kind, "BuildingKindName") if kind is not None else None,
                    text(b, "BuildingArea"),
                    text(b, "BuildingConstrArea"),
                    _int(text(b, "BuildingGroundFloors")),
                    _int(text(b, "BuildingUndergroundFloors")),
                    _int(text(b, "BuildingExploitYear")),
                    text(b, "BuildingAcceptionYears"),
                    text(b, "VARISCode"),
                    child(b, "NotExist") is not None,
                    child(b, "Prereg") is not None,
                    text(b, "EngineeringStructureType"),
                    sorted(set(flags + pflags)),
                )

        loaded = copy_rows(
            conn,
            "ref.building",
            [
                "dataset_version_id",
                "code",
                "file_atvk",
                "name",
                "use_kind_id",
                "use_kind_name",
                "building_kind_id",
                "building_kind_name",
                "area_m2",
                "construction_area_m2",
                "ground_floors",
                "underground_floors",
                "exploit_year",
                "acception_years",
                "varis_code",
                "not_exist",
                "prereg",
                "engineering_structure_type",
                "flags",
            ],
            rows(),
        )
        link_rows = copy_rows(
            conn,
            "ref.building_parcel",
            ["dataset_version_id", "building_code", "parcel_code", "relation"],
            links,
        )
        return {
            "building": {"source_items": n, "loaded": loaded},
            "building_parcel": {"loaded": link_rows},
        }

    def _load_property(self, conn, vid, workdir, members, seen, root_children):
        n, n_objects, objects = 0, 0, []

        def rows():
            nonlocal n, n_objects
            for atvk, it in self._items(workdir, members, "property", seen, root_children):
                n += 1
                number, flags = _code(
                    text(it, "CadastreObjectIdData", "ProCadastreNr"), codes.PARCEL, "property"
                )
                for od in children(it, "PropertyContentData", "ObjectList", "ObjectData"):
                    n_objects += 1
                    kind = text(od, "ObjectKindData")
                    if kind not in OBJECT_KIND_LENGTH:
                        raise SchemaMismatch(f"property {number}: unknown ObjectKindData {kind!r}")
                    oc, oflags = _code(
                        text(od, "ObjectCadastreNrData"),
                        OBJECT_KIND_LENGTH[kind],
                        f"property {number} object",
                    )
                    objects.append((vid, number, oc, kind, oflags))
                yield (
                    vid,
                    number,
                    atvk,
                    text(it, "CadastreObjectIdData", "PropertyKind"),
                    text(it, "PropertyBasicData", "PropertyName"),
                    text(it, "PropertyBasicData", "PropertyParcelTotalArea"),
                    text(it, "PropertyBasicData", "PropertyPremiseGroupTotalArea"),
                    text(it, "CadastreObjectIdData", "ShareFlatProperty"),
                    flags,
                )

        loaded = copy_rows(
            conn,
            "ref.property",
            [
                "dataset_version_id",
                "number",
                "file_atvk",
                "kind",
                "name",
                "parcel_total_area_m2",
                "premise_group_total_area_m2",
                "share_flat_property",
                "flags",
            ],
            rows(),
        )
        obj_loaded = copy_rows(
            conn,
            "ref.property_object",
            ["dataset_version_id", "property_number", "object_code", "object_kind", "flags"],
            objects,
        )
        return {
            "property": {"source_items": n, "loaded": loaded},
            "property_object": {"source_items": n_objects, "loaded": obj_loaded},
        }
