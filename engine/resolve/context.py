"""What one resolution request reads: the live dataset versions, the pilot area
and the matching thresholds (config/resolve.yaml)."""

from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml

from etl.settings import config_dir, etl_config

SOURCES = ("cadastre_text", "cadastre_spatial", "varis_addresses", "admin_boundaries")


class SourceUnavailable(RuntimeError):
    """A source that resolution needs has no live version (not imported)."""


@dataclass(frozen=True)
class Versions:
    cadastre_text: int
    cadastre_spatial: int
    varis_addresses: int
    admin_boundaries: int

    def as_dict(self) -> dict[str, int]:
        return {s: getattr(self, s) for s in SOURCES}


def live_versions(conn) -> Versions:
    rows = dict(
        conn.execute(
            "SELECT source_id, id FROM dataset_version WHERE status = 'live'"
            " AND source_id = ANY(%s)",
            (list(SOURCES),),
        ).fetchall()
    )
    missing = [s for s in SOURCES if s not in rows]
    if missing:
        raise SourceUnavailable(f"no live version of {', '.join(missing)} (import it first)")
    return Versions(**{s: rows[s] for s in SOURCES})


@dataclass(frozen=True)
class AddressSettings:
    retrieval_threshold: float  # pg_trgm word_similarity per search word
    max_candidates: int  # rows ranked in Python per tier
    auto_resolve_score: float  # best score needed to resolve without asking
    auto_resolve_margin: float  # lead over the next different address
    word_match: float  # a typed word counts as matching a word of the address
    pilot_city_fuzzy: float  # a typed word is taken as a pilot city name
    suggest_limit: int


@dataclass(frozen=True)
class ResolveConfig:
    address: AddressSettings
    cadastre_suggest_limit: int
    max_rows: int


@cache
def resolve_config(path: Path | None = None) -> ResolveConfig:
    data = yaml.safe_load((path or config_dir() / "resolve.yaml").read_text(encoding="utf-8"))
    return ResolveConfig(
        address=AddressSettings(**data["address"]),
        cadastre_suggest_limit=int(data["cadastre"]["suggest_limit"]),
        max_rows=int(data["resolve"]["max_rows"]),
    )


@dataclass(frozen=True)
class Pilot:
    atvk: tuple[str, ...]
    territory_to_atvk: dict[str, str]  # first 4 digits of a designation -> city ATVK


def pilot() -> Pilot:
    cfg = etl_config()
    return Pilot(
        atvk=cfg.pilot_atvk,
        territory_to_atvk={t: a for a, t in cfg.pilot_cadastral_territory.items()},
    )
