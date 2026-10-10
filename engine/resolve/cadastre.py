"""Cadastre designations: bulk lookup, per-row decision, type-ahead and the
units of a property (PLAN.md §5, §6.3).

Lookups read the base tables of the live versions directly (fast for many
codes); only map-only objects are checked against the `outside_pilot` flag of
the ref.*_current_all views (migration 20261009190000).
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

from engine.resolve import notes
from engine.resolve.classify import Classified
from engine.resolve.context import Pilot, Versions
from engine.resolve.models import CadastreObject, Match, Note, PropertyUnits, Suggestion

TYPE_LABEL = {
    "property": "Nekustamais īpašums",
    "parcel": "Zemes vienība",
    "building": "Būve",
    "parcel_part": "Zemes vienības daļa",
    "premise_group": "Telpu grupa",
}
TYPE_ORDER = list(TYPE_LABEL)
# property_object.object_kind (cadastre text, ObjectKindData)
KIND_PARCEL = "Zemes vienība"
KIND_PREMISE_GROUP = "Telpu grupa"


@dataclass
class Facts:
    """Rows of the live versions for a set of designations."""

    properties: dict[str, CadastreObject] = field(default_factory=dict)
    parcels: dict[str, CadastreObject] = field(default_factory=dict)
    buildings: dict[str, CadastreObject] = field(default_factory=dict)
    parts: dict[str, CadastreObject] = field(default_factory=dict)
    owners: dict[str, list[str]] = field(default_factory=dict)  # object -> property numbers
    outside: set[str] = field(default_factory=set)  # map-only objects outside the pilot


def object_warnings(obj: CadastreObject) -> list[Note]:
    out = []
    if not obj.in_register:
        out.append(notes.not_in_register())
    if obj.has_geometry is False:
        out.append(notes.no_geometry())
    if obj.not_exist:
        out.append(notes.not_exist())
    if obj.prereg:
        out.append(notes.prereg())
    return out


def _desc(*parts) -> str | None:
    return " · ".join(p for p in parts if p) or None


def fetch(conn, v: Versions, codes: Iterable[str]) -> Facts:
    """All rows needed to decide on `codes` (any length), in five queries."""
    codes = set(codes)
    c11 = sorted(c for c in codes if len(c) == 11)
    c14 = sorted({c for c in codes if len(c) == 14} | {c[:14] for c in codes if len(c) == 17})
    c15 = sorted({c for c in codes if len(c) == 15} | {"0" + c for c in codes if len(c) == 14})
    p = {"t": v.cadastre_text, "s": v.cadastre_spatial, "v": v.varis_addresses}
    f = Facts()

    for number, kind, name in conn.execute(
        "SELECT number, kind, name FROM ref.property"
        " WHERE dataset_version_id = %(t)s AND number = ANY(%(c)s)",
        p | {"c": c11},
    ):
        f.properties[number] = CadastreObject(
            type="property",
            designation=number,
            label=TYPE_LABEL["property"],
            description=_desc(name, kind),
        )

    for code, in_reg, has_geom, varis, address in conn.execute(
        """SELECT c.code, p.code IS NOT NULL, k.code IS NOT NULL, p.varis_code, a.full_text
           FROM unnest(%(c)s::text[]) AS c(code)
           LEFT JOIN ref.parcel p ON p.dataset_version_id = %(t)s AND p.code = c.code
           LEFT JOIN ref.kk_parcel k ON k.dataset_version_id = %(s)s AND k.code = c.code
           LEFT JOIN ref.address a ON a.dataset_version_id = %(v)s AND a.code = p.varis_code
           WHERE p.code IS NOT NULL OR k.code IS NOT NULL""",
        p | {"c": c11},
    ):
        f.parcels[code] = CadastreObject(
            type="parcel",
            designation=code,
            label=TYPE_LABEL["parcel"],
            description=address,
            varis_code=varis,
            in_register=in_reg,
            has_geometry=has_geom,
        )

    for row in conn.execute(
        """SELECT c.code, b.code IS NOT NULL, k.code IS NOT NULL, b.name, b.use_kind_name,
                  b.engineering_structure_type, b.varis_code, a.full_text,
                  coalesce(b.not_exist, false), coalesce(b.prereg, false), k.parcel_code,
                  (SELECT array_agg(bp.parcel_code
                                    ORDER BY bp.relation <> 'object_relation', bp.parcel_code)
                   FROM ref.building_parcel bp
                   WHERE bp.dataset_version_id = %(t)s AND bp.building_code = c.code)
           FROM unnest(%(c)s::text[]) AS c(code)
           LEFT JOIN ref.building b ON b.dataset_version_id = %(t)s AND b.code = c.code
           LEFT JOIN ref.kk_building k ON k.dataset_version_id = %(s)s AND k.code = c.code
           LEFT JOIN ref.address a ON a.dataset_version_id = %(v)s AND a.code = b.varis_code
           WHERE b.code IS NOT NULL OR k.code IS NOT NULL""",
        p | {"c": c14},
    ):
        (code, in_reg, has_geom, name, use, eng, varis, address, nx, prereg, map_parcel,
         parcels) = row  # fmt: skip
        f.buildings[code] = CadastreObject(
            type="building",
            designation=code,
            label=TYPE_LABEL["building"],
            description=_desc(name or use or eng, address),
            parcel_codes=parcels or ([map_parcel] if map_parcel else []),
            varis_code=varis,
            in_register=in_reg,
            has_geometry=has_geom,
            not_exist=nx,
            prereg=prereg,
        )

    for code, in_reg, has_geom, parcel in conn.execute(
        """SELECT c.code, p.code IS NOT NULL, k.code IS NOT NULL,
                  coalesce(p.parcel_code, k.parcel_code)
           FROM unnest(%(c)s::text[]) AS c(code)
           LEFT JOIN ref.parcel_part p ON p.dataset_version_id = %(t)s AND p.code = c.code
           LEFT JOIN ref.kk_parcel_part k ON k.dataset_version_id = %(s)s AND k.code = c.code
           WHERE p.code IS NOT NULL OR k.code IS NOT NULL""",
        p | {"c": c15},
    ):
        f.parts[code] = CadastreObject(
            type="parcel_part",
            designation=code,
            label=TYPE_LABEL["parcel_part"],
            parcel_codes=[parcel] if parcel else [],
            in_register=in_reg,
            has_geometry=has_geom,
        )

    every = sorted(set(c11) | set(c14) | set(c15) | {c for c in codes if len(c) == 17})
    for code, numbers in conn.execute(
        "SELECT object_code, array_agg(property_number ORDER BY property_number)"
        " FROM ref.property_object WHERE dataset_version_id = %(t)s"
        " AND object_code = ANY(%(c)s) GROUP BY object_code",
        p | {"c": every},
    ):
        f.owners[code] = numbers

    map_only = {
        "parcel_current_all": [c for c, o in f.parcels.items() if not o.in_register],
        "building_current_all": [c for c, o in f.buildings.items() if not o.in_register],
        "parcel_part_current_all": [c for c, o in f.parts.items() if not o.in_register],
    }
    for view, view_codes in map_only.items():
        if view_codes:
            f.outside |= {
                r[0]
                for r in conn.execute(
                    f"SELECT code FROM ref.{view} WHERE code = ANY(%s) AND outside_pilot",  # noqa: S608
                    (view_codes,),
                )
            }

    for objects in (f.parcels, f.buildings, f.parts):
        for code, obj in objects.items():
            obj.property_numbers = f.owners.get(code, [])
            obj.warnings = object_warnings(obj)
    return f


@dataclass
class Decision:
    status: str
    type: str | None = None
    matches: list[Match] = field(default_factory=list)
    warnings: list[Note] = field(default_factory=list)
    reason: str | None = None


def _match(obj: CadastreObject, match_type: str) -> Match:
    return Match(
        type=obj.type,
        designation=obj.designation,
        label=obj.label,
        description=obj.description,
        match_type=match_type,
        object=obj,
        warnings=list(obj.warnings),
    )


def _missing(code: str, f: Facts, pilot: Pilot) -> Decision:
    if code in f.outside:
        return Decision(
            status="outside_pilot",
            reason="objekts kadastra kartē ir ārpus pilota pilsētu robežām",
        )
    territory = code[:4]
    if territory not in pilot.territory_to_atvk:
        return Decision(
            status="outside_pilot", reason=notes.outside_pilot(f"kadastra teritorija {territory}")
        )
    return Decision(status="not_found", reason="kadastra datos nav atrasts")


def _present(objects: dict[str, CadastreObject], code: str, f: Facts):
    obj = objects.get(code)
    return obj if obj is not None and code not in f.outside else None


def decide(c: Classified, f: Facts, pilot: Pilot) -> Decision:
    """Decision for one classified designation (c.kind == 'cadastre')."""
    code = c.value
    mt = "corrected" if c.corrections else "exact"
    d = _decide(code, c.designation, mt, f, pilot)
    if c.precision_lost and d.status == "resolved":
        d.status = "ambiguous"
        d.reason = "pārbaudiet numuru: eksponentpierakstā var būt zaudēti cipari"
    return d


def _decide(code: str, designation: str, mt: str, f: Facts, pilot: Pilot) -> Decision:
    if designation == "property_or_parcel":
        prop = f.properties.get(code)
        parcel = _present(f.parcels, code, f)
        if prop and parcel:
            if code in parcel.property_numbers:
                return Decision(
                    status="resolved",
                    type="property",
                    matches=[_match(prop, mt), _match(parcel, mt)],
                    warnings=[notes.property_is_own_parcel(code)],
                )
            return Decision(
                status="ambiguous",
                matches=[_match(prop, mt), _match(parcel, mt)],
                warnings=[notes.property_or_parcel(code, parcel.property_numbers)],
                reason="īpašuma numurs vai zemes vienības apzīmējums",
            )
        if prop or parcel:
            obj = prop or parcel
            return Decision(status="resolved", type=obj.type, matches=[_match(obj, mt)])
        return _missing(code, f, pilot)

    if designation == "building":
        if building := _present(f.buildings, code, f):
            return Decision(status="resolved", type="building", matches=[_match(building, mt)])
        if part := _present(f.parts, "0" + code, f):
            # a 15-digit parcel part that lost its leading zero
            return Decision(
                status="resolved",
                type="parcel_part",
                matches=[_match(part, "corrected")],
                warnings=[
                    Note(
                        code="leading_zero_restored",
                        message=f"nav būves {code}; atrasta zemes vienības daļa 0{code}",
                    )
                ],
            )
        return _missing(code, f, pilot)

    if designation == "parcel_part":
        if part := _present(f.parts, code, f):
            return Decision(status="resolved", type="parcel_part", matches=[_match(part, mt)])
        return _missing(code, f, pilot)

    # premise group: checked as its building (first 14 digits)
    building_code = code[:14]
    building = _present(f.buildings, building_code, f)
    if building is None:
        return _missing(building_code, f, pilot)
    warnings = [notes.premise_group_to_building(code, building_code)]
    if code not in f.owners:
        warnings.append(notes.premise_group_unknown(code))
    return Decision(
        status="resolved", type="building", matches=[_match(building, mt)], warnings=warnings
    )


# --- type-ahead ---------------------------------------------------------------------

_PREFIX_SQL = """
(SELECT 'property' AS t, number AS code FROM ref.property
 WHERE dataset_version_id = %(t)s AND number LIKE %(p)s ORDER BY number USING ~<~ LIMIT %(n)s)
UNION ALL
(SELECT 'parcel', code FROM ref.parcel
 WHERE dataset_version_id = %(t)s AND code LIKE %(p)s ORDER BY code USING ~<~ LIMIT %(n)s)
UNION ALL
(SELECT 'building', code FROM ref.building
 WHERE dataset_version_id = %(t)s AND code LIKE %(p)s ORDER BY code USING ~<~ LIMIT %(n)s)
UNION ALL
(SELECT 'parcel_part', code FROM ref.parcel_part
 WHERE dataset_version_id = %(t)s AND code LIKE %(p)s ORDER BY code USING ~<~ LIMIT %(n)s)
UNION ALL
(SELECT 'premise_group', object_code FROM ref.property_object
 WHERE dataset_version_id = %(t)s AND object_code LIKE %(p)s AND object_kind = %(pg)s
 ORDER BY object_code USING ~<~ LIMIT %(n)s)
"""


def digits_prefix(q: str) -> str | None:
    compact = "".join(ch for ch in q if ch not in "  -'\"")
    return compact if compact.isdigit() else None


def suggest(conn, v: Versions, q: str, limit: int, city_of_territory) -> list[Suggestion]:
    """Designations starting with the typed digits (from 3 digits). A prefix
    without its leading zero is also tried, and those entries are marked
    'corrected'."""
    prefix = digits_prefix(q)
    if prefix is None or len(prefix) < 3 or len(prefix) > 17:
        return []
    variants = [(prefix, "exact")]
    if len(prefix) < 17:
        variants.append(("0" + prefix, "corrected"))
    seen: dict[tuple[str, str], str] = {}
    for p, mt in variants:
        for t, code in conn.execute(
            _PREFIX_SQL,
            {"t": v.cadastre_text, "p": p + "%", "n": limit, "pg": KIND_PREMISE_GROUP},
        ):
            seen.setdefault((t, code), mt)
    ranked = sorted(
        seen.items(),
        key=lambda kv: (kv[1] != "exact", len(kv[0][1]), TYPE_ORDER.index(kv[0][0]), kv[0][1]),
    )[:limit]
    f = fetch(conn, v, [code for (_, code), _ in ranked])
    out = []
    for (t, code), mt in ranked:
        if t == "premise_group":
            building = f.buildings.get(code[:14])
            description = building.description if building else None
        else:
            obj = {
                "property": f.properties,
                "parcel": f.parcels,
                "building": f.buildings,
                "parcel_part": f.parts,
            }[t].get(code)
            description = obj.description if obj else None
        out.append(
            Suggestion(
                type=t,
                designation=code,
                label=TYPE_LABEL[t],
                description=description,
                city=city_of_territory(code[:4]),
                match_type=mt,
            )
        )
    return out


# --- units of a property ------------------------------------------------------------


def property_units(
    conn, v: Versions, number: str, include_non_existing: bool
) -> PropertyUnits | None:
    row = conn.execute(
        "SELECT kind, name FROM ref.property WHERE dataset_version_id = %s AND number = %s",
        (v.cadastre_text, number),
    ).fetchone()
    if row is None:
        return None
    kind, name = row
    objects = conn.execute(
        "SELECT object_code, object_kind FROM ref.property_object"
        " WHERE dataset_version_id = %s AND property_number = %s ORDER BY object_code",
        (v.cadastre_text, number),
    ).fetchall()
    parcels = [c for c, k in objects if k == KIND_PARCEL]
    groups = [c for c, k in objects if k == KIND_PREMISE_GROUP]
    buildings = [c for c, k in objects if len(c) == 14]
    parts = [
        r[0]
        for r in conn.execute(
            """SELECT code FROM ref.parcel_part
               WHERE dataset_version_id = %(t)s AND parcel_code = ANY(%(p)s)
               UNION
               SELECT code FROM ref.kk_parcel_part
               WHERE dataset_version_id = %(s)s AND parcel_code = ANY(%(p)s)
               ORDER BY 1""",
            {"t": v.cadastre_text, "s": v.cadastre_spatial, "p": parcels},
        )
    ]
    others = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT building_code FROM ref.building_parcel"
            " WHERE dataset_version_id = %s AND parcel_code = ANY(%s)"
            " AND NOT building_code = ANY(%s) ORDER BY 1",
            (v.cadastre_text, parcels, buildings),
        )
    ]
    f = fetch(conn, v, parcels + buildings + parts + groups + others)

    units: list[CadastreObject] = [f.parcels[c] for c in parcels if c in f.parcels]
    units += [f.parts[c] for c in parts if c in f.parts]
    excluded = 0

    def keep(code: str) -> CadastreObject | None:
        nonlocal excluded
        b = f.buildings.get(code)
        if b is not None and b.not_exist and not include_non_existing:
            excluded += 1
            return None
        return b

    units += [b for c in buildings if (b := keep(c))]
    on_parcels = [b for c in others if (b := keep(c))]
    for g in groups:
        building = f.buildings.get(g[:14])
        units.append(
            CadastreObject(
                type="premise_group",
                designation=g,
                label=TYPE_LABEL["premise_group"],
                description=building.description if building else None,
                property_numbers=f.owners.get(g, [number]),
                building_code=g[:14],
            )
        )
    counts = {t: sum(1 for u in units if u.type == t) for t in TYPE_ORDER if t != "property"}
    return PropertyUnits(
        number=number,
        kind=kind,
        name=name,
        units=units,
        buildings_on_parcels=on_parcels,
        counts=counts,
        non_existing_excluded=excluded,
    )


# --- objects at an address ------------------------------------------------------------


def objects_at_addresses(
    conn, v: Versions, varis_codes: list[str], include_non_existing: bool
) -> dict[str, tuple[list[CadastreObject], int]]:
    """Parcels and buildings whose cadastre text carries each VARIS code, and
    how many buildings marked non-existing were left out."""
    pairs = conn.execute(
        """SELECT varis_code, code FROM ref.parcel
           WHERE dataset_version_id = %(t)s AND varis_code = ANY(%(c)s)
           UNION ALL
           SELECT varis_code, code FROM ref.building
           WHERE dataset_version_id = %(t)s AND varis_code = ANY(%(c)s)
           ORDER BY 1, 2""",
        {"t": v.cadastre_text, "c": varis_codes},
    ).fetchall()
    f = fetch(conn, v, [code for _, code in pairs])
    out: dict[str, tuple[list[CadastreObject], int]] = {c: ([], 0) for c in varis_codes}
    for varis, code in pairs:
        objects, excluded = out[varis]
        obj = f.parcels.get(code) if len(code) == 11 else f.buildings.get(code)
        if obj is None:
            continue
        if obj.not_exist and not include_non_existing:
            out[varis] = (objects, excluded + 1)
            continue
        objects.append(obj)
    return out
