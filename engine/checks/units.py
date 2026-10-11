"""Targets and the units they are checked on (PLAN.md §6.3).

- A property is checked per unit: its parcels and buildings (buildings marked
  non-existing left out, as in /api/property/{number}/units), plus parcel parts
  whose parcel is not itself a unit. Premise groups are checked on their building.
- A premise group target is checked on its building.
- Geometry per unit (temp table chk_geom, built once per run):
  own geometry; else, for a building or parcel part, the geometry of the
  parcel(s) the cadastre links it to ("pārbaudīts pēc zemes vienības");
  else none, and spatial modules return no_data "nav ģeometrijas".
"""

from dataclasses import dataclass, field

from engine.checks.context import RunContext
from engine.checks.contract import TargetIn, Warning_
from engine.resolve import cadastre
from engine.resolve.models import CadastreObject

NOT_FOUND = "objekts nav atrasts kadastrā"
NO_GEOMETRY = "nav ģeometrijas"
PARCEL_LEVEL = "pārbaudīts pēc zemes vienības"


@dataclass
class Unit:
    type: str
    code: str
    obj: CadastreObject | None  # None: not in the pinned cadastre versions
    warnings: list[Warning_] = field(default_factory=list)  # from the target, e.g. premise group
    # Target-level modules (module 2) get one Unit per target: the given address
    # and the units it is compared with.
    given_address: str | None = None
    members: list[Unit] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return self.obj is not None

    @property
    def key(self) -> str:
        """A property and a parcel may share a number, so results are keyed by both."""
        return f"{self.type}:{self.code}"


@dataclass
class Target:
    no: int
    given: TargetIn
    units: list[Unit]
    property_units: bool  # True: a property checked per unit plus an aggregate
    target_obj: CadastreObject | None = None  # the property itself


def _w(note) -> Warning_:
    return Warning_(**note.model_dump())


def expand(ctx: RunContext, targets: list[TargetIn]) -> list[Target]:
    v = ctx.cadastre
    out: list[Target] = []
    plans: list[tuple[TargetIn, list[tuple[str, str, list[Warning_]]], bool]] = []
    for t in targets:
        if t.type == "property":
            pu = cadastre.property_units(ctx.conn, v, t.designation, include_non_existing=False)
            if pu is None:
                plans.append((t, [("property", t.designation, [])], False))
                continue
            plan: list[tuple[str, str, list[Warning_]]] = []
            seen: set[str] = set()
            parcels = {u.designation for u in pu.units if u.type == "parcel"}
            for u in pu.units:
                code, utype, warns = u.designation, u.type, []
                if u.type == "premise_group":
                    code, utype = u.building_code or u.designation[:14], "building"
                    warns = [
                        Warning_(
                            code="premise_group_to_building",
                            message=f"telpu grupa {u.designation}: pārbauda būvi {code}",
                        )
                    ]
                if u.type == "parcel_part" and set(u.parcel_codes) & parcels:
                    continue  # its parcel is checked
                if code in seen:
                    continue
                seen.add(code)
                plan.append((utype, code, warns))
            plans.append((t, plan, True))
        elif t.type == "premise_group":
            b = t.designation[:14]
            note = Warning_(
                code="premise_group_to_building",
                message=f"telpu grupa {t.designation}: pārbauda būvi {b}",
            )
            plans.append((t, [("building", b, [note])], False))
        else:
            plans.append((t, [(t.type, t.designation, [])], False))

    codes = {code for _, plan, _ in plans for _, code, _ in plan}
    facts = cadastre.fetch(ctx.conn, v, codes)
    by_type = {
        "parcel": facts.parcels,
        "building": facts.buildings,
        "parcel_part": facts.parts,
        "property": facts.properties,
    }
    for no, (t, plan, per_unit) in enumerate(plans):
        units = [Unit(utype, code, by_type[utype].get(code), warns) for utype, code, warns in plan]
        out.append(Target(no, t, units, per_unit, facts.properties.get(t.designation)))
    return out


def build_geometry(ctx: RunContext, units: list[Unit]) -> None:
    """chk_geom(code, basis, basis_codes, geom, inner_geom, area_m2, buffer_empty)."""
    if not ctx.once("chk_geom"):
        return
    t, s = ctx.v("cadastre_text"), ctx.v("cadastre_spatial")
    c = ctx.conn
    c.execute(
        """CREATE TEMP TABLE chk_geom (
               code text PRIMARY KEY, basis text NOT NULL, basis_codes text[] NOT NULL,
               geom geometry(MultiPolygon, 10306), inner_geom geometry, area_m2 float8,
               buffer_empty boolean) ON COMMIT DROP"""
    )
    rows = [(u.code, u.type, u.obj.parcel_codes if u.obj else []) for u in units if u.found]
    rows = sorted(set((code, typ, tuple(p)) for code, typ, p in rows))
    for code, typ, parcels in rows:
        table = {"parcel": "kk_parcel", "building": "kk_building", "parcel_part": "kk_parcel_part"}
        own = (
            c.execute(
                f"SELECT geom FROM ref.{table[typ]} WHERE dataset_version_id = %s AND code = %s",  # noqa: S608
                (s, code),
            ).fetchone()
            if typ in table
            else None
        )
        if own is not None:
            c.execute(
                "INSERT INTO chk_geom (code, basis, basis_codes, geom) VALUES (%s, 'own', %s, %s)",
                (code, [code], own[0]),
            )
            continue
        if typ == "building" and not parcels:
            parcels = tuple(
                r[0]
                for r in c.execute(
                    "SELECT parcel_code FROM ref.building_parcel WHERE dataset_version_id = %s"
                    " AND building_code = %s ORDER BY parcel_code",
                    (t, code),
                )
            )
        c.execute(
            """INSERT INTO chk_geom (code, basis, basis_codes, geom)
               SELECT %s, CASE WHEN count(*) > 0 THEN 'parcel' ELSE 'none' END,
                      coalesce(array_agg(code ORDER BY code), '{}'),
                      ST_Multi(ST_Union(geom))
               FROM ref.kk_parcel WHERE dataset_version_id = %s AND code = ANY(%s)""",
            (code, s, list(parcels)),
        )
    c.execute(
        """UPDATE chk_geom SET area_m2 = ST_Area(geom),
               inner_geom = ST_Buffer(geom, -%s),
               buffer_empty = ST_IsEmpty(ST_Buffer(geom, -%s))
           WHERE geom IS NOT NULL""",
        (ctx.thresholds.inward_buffer_m, ctx.thresholds.inward_buffer_m),
    )
    # A unit narrower than twice the buffer keeps its own outline (flagged).
    c.execute("UPDATE chk_geom SET inner_geom = geom WHERE buffer_empty")
    c.execute("ANALYZE chk_geom")


@dataclass
class GeomInfo:
    basis: str  # own | parcel | none
    basis_codes: list[str]
    area_m2: float | None
    buffer_empty: bool


def geometry_info(ctx: RunContext) -> dict[str, GeomInfo]:
    return {
        code: GeomInfo(basis, list(codes), area, bool(empty))
        for code, basis, codes, area, empty in ctx.conn.execute(
            "SELECT code, basis, basis_codes, area_m2, buffer_empty FROM chk_geom ORDER BY code"
        )
    }


def geometry_warnings(unit: Unit, g: GeomInfo | None) -> list[Warning_]:
    """§6.3: no_geometry always; the parcel-level note when the fallback is used."""
    out = []
    if unit.obj is not None and unit.obj.has_geometry is False:
        out.append(Warning_(code="no_geometry", message="nav ģeometrijas kadastra kartē"))
    if g and g.basis == "parcel":
        out.append(Warning_(code="parcel_level", message=PARCEL_LEVEL, parcels=g.basis_codes))
    if g and g.buffer_empty:
        out.append(
            Warning_(
                code="inward_buffer_empty",
                message="objekts šaurāks par iekšējo buferi; pārbaudīts pēc tā kontūras",
            )
        )
    return out
