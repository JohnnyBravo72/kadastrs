"""Place names: the pilot cities, and other cities and municipalities named in an
address input (VARIS admin areas, whole country, live admin_boundaries version)."""

from dataclasses import dataclass, field
from difflib import SequenceMatcher

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


# Street-type words (normalised). ref.addr_key() drops these and the two
# admin-level words below; tests/resolve/test_address.py keeps the lists equal.
STREET_WORDS = (
    "iela",
    "prospekts",
    "bulvaris",
    "laukums",
    "gatve",
    "cels",
    "soseja",
    "aleja",
    "krastmala",
    "dambis",
)
ADMIN_WORDS = ("novads", "pagasts")
KEY_DROP = STREET_WORDS + ADMIN_WORDS


@dataclass
class PlaceScan:
    """Place names found in a normalised address input."""

    tokens: list[str]  # the input without the place names
    pilot_city: Place | None = None
    outside: list[Place] = field(default_factory=list)
    city_typo: str | None = None  # typed word taken as the pilot city

    @property
    def outside_pilot(self) -> Place | None:
        """The non-pilot place that decides the input, if no pilot city is named."""
        return self.outside[0] if self.outside and self.pilot_city is None else None


def scan(norm: str, places: Places, city_fuzzy: float) -> PlaceScan:
    """Find city and municipality names in `norm` (output of ref.addr_norm).

    - "<x> novads" / "<x> pagasts" (whole phrase) is a municipality or parish;
      none is in the pilot (the pilot is three cities).
    - a word equal to a city name is that city, unless a street-type word
      follows it ("Ventspils iela" is a street in Daugavpils).
    - a word of 5+ letters close to a pilot city name is that city (typo).
    """
    tokens = norm.split()
    used = [False] * len(tokens)
    result = PlaceScan(tokens=[])

    def street_follows(i: int) -> bool:
        return i + 1 < len(tokens) and tokens[i + 1] in STREET_WORDS

    for p in places.places:
        if p.level == "pilseta":
            continue
        words = p.norm.split()
        n = len(words)
        for i in range(len(tokens) - n + 1):
            if tokens[i : i + n] == words and not any(used[i : i + n]):
                used[i : i + n] = [True] * n
                result.outside.append(p)
    cities = {p.norm: p for p in places.places if p.level == "pilseta"}
    for i, tok in enumerate(tokens):
        if used[i] or street_follows(i):
            continue
        city = cities.get(tok)
        if city is not None:
            used[i] = True
            if city.pilot:
                result.pilot_city = result.pilot_city or city
            else:
                result.outside.append(city)
    if result.pilot_city is None:
        for i, tok in enumerate(tokens):
            if used[i] or street_follows(i) or len(tok) < 5 or not tok.isalpha():
                continue
            best = max(
                places.pilot_cities,
                key=lambda c: SequenceMatcher(None, tok, c.norm).ratio(),
                default=None,
            )
            if best and SequenceMatcher(None, tok, best.norm).ratio() >= city_fuzzy:
                used[i] = True
                result.pilot_city = best
                result.city_typo = tok
                break
    result.tokens = [t for t, u in zip(tokens, used, strict=True) if not u]
    return result
