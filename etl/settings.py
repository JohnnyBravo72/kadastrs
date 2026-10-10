"""ETL settings: config/etl.yaml, config/schemas.yaml, DB URL and raw-file directory."""

import os
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml


def config_dir() -> Path:
    env = os.environ.get("KADASTRS_CONFIG_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[1] / "config"


def raw_dir() -> Path:
    """Raw files of each live version are kept here (row-count tests recount them)."""
    return Path(os.environ.get("KADASTRS_RAW_DIR", "/data/raw"))


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return url


@dataclass(frozen=True)
class EtlConfig:
    ckan_api: str
    pilot_atvk: tuple[str, ...]
    pilot_cadastral_territory: dict[str, str]  # ATVK -> first 4 digits of designations
    files: dict[str, dict[str, str]]  # source id -> role -> CKAN resource id
    options: dict[str, dict]  # source id -> importer options


@cache
def etl_config(path: Path | None = None) -> EtlConfig:
    data = yaml.safe_load((path or config_dir() / "etl.yaml").read_text(encoding="utf-8"))
    atvk = data["pilot_atvk"]
    if not all(isinstance(a, str) and len(a) == 7 and a.isdigit() for a in atvk):
        raise ValueError("pilot_atvk must be 7-digit strings (codes are text)")
    files = {
        sid: {str(k): str(v) for k, v in s["files"].items()} for sid, s in data["sources"].items()
    }
    options = {sid: dict(s.get("options") or {}) for sid, s in data["sources"].items()}
    territory = {str(k): str(v) for k, v in data["pilot_cadastral_territory"].items()}
    if sorted(territory) != sorted(atvk) or not all(
        len(v) == 4 and v.isdigit() for v in territory.values()
    ):
        raise ValueError("pilot_cadastral_territory needs a 4-digit code (text) per pilot ATVK")
    return EtlConfig(
        ckan_api=data["ckan_api"],
        pilot_atvk=tuple(atvk),
        pilot_cadastral_territory=territory,
        files=files,
        options=options,
    )


@cache
def schemas(path: Path | None = None) -> dict:
    return yaml.safe_load((path or config_dir() / "schemas.yaml").read_text(encoding="utf-8"))
