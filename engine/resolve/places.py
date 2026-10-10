"""Place names: the pilot cities, and other cities and municipalities named in an
address input (VARIS admin areas, whole country, live admin_boundaries version)."""

from dataclasses import dataclass

from engine.resolve.context import Pilot, Versions


@dataclass(frozen=True)
class Place:
    name: str  # as in VARIS, e.g. "Rīga", "Jelgavas nov."
    norm: str  # ref.addr_norm(name), e.g. "riga", "jelgavas novads"
    level: str  # pilseta | novads | pagasts
    atvk: str | None
    pilot: bool


@dataclass(frozen=True)
class Places:
    places: tuple[Place, ...]
    city_by_atvk: dict[str, str]  # pilot ATVK -> city name
    territory_to_atvk: dict[str, str]

    def city_of_territory(self, territory: str) -> str | None:
        atvk = self.territory_to_atvk.get(territory)
        return self.city_by_atvk.get(atvk) if atvk else None

    @property
    def pilot_cities(self) -> tuple[Place, ...]:
        return tuple(p for p in self.places if p.pilot)


_cache: dict[tuple, Places] = {}


def load_places(conn, v: Versions, pilot: Pilot) -> Places:
    """Admin areas of the live version (cached per database and version id)."""
    key = (conn.info.host, conn.info.port, conn.info.dbname, v.admin_boundaries)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    rows = conn.execute(
        "SELECT name, ref.addr_norm(name), level, atvk FROM ref.admin_area"
        " WHERE dataset_version_id = %s ORDER BY level, name",
        (v.admin_boundaries,),
    ).fetchall()
    places = tuple(
        Place(name=n, norm=norm, level=lvl, atvk=a, pilot=lvl == "pilseta" and a in pilot.atvk)
        for n, norm, lvl, a in rows
    )
    result = Places(
        places=places,
        city_by_atvk={p.atvk: p.name for p in places if p.pilot},
        territory_to_atvk=pilot.territory_to_atvk,
    )
    _cache.clear()
    _cache[key] = result
    return result
