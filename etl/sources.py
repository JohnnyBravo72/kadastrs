"""Source registry: validate config/sources.yaml and load it into the DB.

    python -m etl.sources validate [--config PATH]
    python -m etl.sources load [--config PATH] [--database-url URL]

The YAML is the source of truth. Loading upserts every entry; entries no longer
in the YAML are kept (dataset_version and import_log point to them) but set
active = false.
"""

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

import psycopg
import yaml
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

# ISO 8601 duration, e.g. P2D, P1M, P120D, PT12H.
_ISO_DURATION = re.compile(r"^P(?!$)(\d+Y)?(\d+M)?(\d+W)?(\d+D)?(T(?=\d)(\d+H)?(\d+M)?(\d+S)?)?$")

StrList = Annotated[list[str], Field(default_factory=list)]


def _as_list(value: str | list[str] | None) -> list[str]:
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value)


def default_config_path() -> Path:
    config_dir = os.environ.get("KADASTRS_CONFIG_DIR")
    base = Path(config_dir) if config_dir else Path(__file__).resolve().parents[1] / "config"
    return base / "sources.yaml"


class Names(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lv: str
    en: str


class Datagov(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset_id: str | list[str]
    resource_ids: StrList

    @property
    def dataset_ids(self) -> list[str]:
        return _as_list(self.dataset_id)


class Source(BaseModel):
    """One entry under `sources:` (PLAN.md §4, table `source`)."""

    model_config = ConfigDict(extra="forbid")

    id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
    names: Names
    owner: str
    group: str
    order: int
    # reference = core data (cadastre, addresses, boundaries): always used,
    # hidden from the sources checklist.
    type: Literal["layer", "check", "reference"]
    subject_kinds: Annotated[
        list[Literal["object", "applicant", "municipality"]], Field(min_length=1)
    ]
    default_selected: bool
    # Shown to evaluators (report sheet "Avoti"), so in Latvian; the English
    # wording is kept as a YAML comment for developers. Stored in source.coverage.
    coverage_lv: Annotated[str, Field(min_length=1)]
    # What the import changes or leaves out, in Latvian, for the "Avoti" sheet
    # (next to the processing notes of the source's D1 resources).
    processing_lv: StrList
    # Freshness (docs/decisions.md "Freshness"): warn when the publisher has
    # released nothing newer for this long. None = never (a frozen list).
    source_stale_after: str | None = None
    datagov: Datagov | None = None
    external_resources: StrList  # ids from allowed_external_resources (D1)
    licence: str | None = None

    @field_validator("source_stale_after")
    @classmethod
    def _iso_duration(cls, v: str | None) -> str | None:
        if v is not None and not _ISO_DURATION.match(v):
            raise ValueError(
                f"source_stale_after must be an ISO 8601 duration such as P30D or P2Y, got {v!r}"
            )
        return v

    @model_validator(mode="after")
    def _reference_always_selected(self) -> Self:
        if self.type == "reference" and not self.default_selected:
            raise ValueError(f"source {self.id!r}: a reference source must be default_selected")
        return self

    @model_validator(mode="after")
    def _has_origin(self) -> Self:
        if not (self.datagov and self.datagov.dataset_ids) and not self.external_resources:
            raise ValueError(
                f"source {self.id!r}: needs datagov.dataset_id or external_resources (D1)"
            )
        return self


class ExternalResource(BaseModel):
    """One entry under `allowed_external_resources:` (decision D1).

    Extra keys (layers, licence, access, processing, ...) are allowed and stored
    in the `config` column as loaded.
    """

    model_config = ConfigDict(extra="allow")

    id: Annotated[str, Field(pattern=r"^E[0-9]+$")]
    name: str
    url: str | list[str]
    host: str
    datagov_dataset: str | list[str] | None
    status: Literal["allowed", "withdrawn"]
    fallback: str | None = None

    @property
    def urls(self) -> list[str]:
        return _as_list(self.url)

    @property
    def datagov_datasets(self) -> list[str]:
        return _as_list(self.datagov_dataset)

    @model_validator(mode="after")
    def _urls_on_host(self) -> Self:
        for url in self.urls:
            parts = urlsplit(url)
            if parts.scheme != "https":
                raise ValueError(f"{self.id}: {url} is not https")
            if parts.hostname != self.host:
                raise ValueError(f"{self.id}: {url} is not on host {self.host}")
        return self


class SourcesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: list[Source] = Field(default_factory=list)
    allowed_external_resources: list[ExternalResource] = Field(default_factory=list)

    @model_validator(mode="after")
    def _cross_checks(self) -> Self:
        for label, ids in (
            ("source", [s.id for s in self.sources]),
            ("external resource", [e.id for e in self.allowed_external_resources]),
        ):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            if dupes:
                raise ValueError(f"duplicate {label} ids: {', '.join(dupes)}")

        external = {e.id: e for e in self.allowed_external_resources}
        for e in self.allowed_external_resources:
            if e.fallback and e.fallback not in external:
                raise ValueError(f"{e.id}: fallback {e.fallback} is not listed")
        for s in self.sources:
            for ref in s.external_resources:
                if ref not in external:
                    raise ValueError(f"source {s.id!r}: external resource {ref} is not listed")
                if external[ref].status != "allowed":
                    raise ValueError(
                        f"source {s.id!r}: external resource {ref} is {external[ref].status}"
                    )
        return self


def load_config(path: Path | None = None) -> SourcesConfig:
    path = path or default_config_path()
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return SourcesConfig.model_validate(data)


_UPSERT_EXTERNAL = """
INSERT INTO allowed_external_resource
    (id, name, urls, host, datagov_datasets, status, config, active, loaded_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, true, now())
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name, urls = EXCLUDED.urls, host = EXCLUDED.host,
    datagov_datasets = EXCLUDED.datagov_datasets, status = EXCLUDED.status,
    config = EXCLUDED.config, active = true, loaded_at = now()
"""

_UPSERT_SOURCE = """
INSERT INTO source
    (id, name_lv, name_en, owner, source_group, display_order, type, subject_kinds,
     default_selected, coverage, source_stale_after, datagov_dataset_ids, datagov_resource_ids,
     external_resource_ids, licence, config, active, loaded_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::interval, %s, %s, %s, %s, %s, true, now())
ON CONFLICT (id) DO UPDATE SET
    name_lv = EXCLUDED.name_lv, name_en = EXCLUDED.name_en, owner = EXCLUDED.owner,
    source_group = EXCLUDED.source_group, display_order = EXCLUDED.display_order,
    type = EXCLUDED.type, subject_kinds = EXCLUDED.subject_kinds,
    default_selected = EXCLUDED.default_selected, coverage = EXCLUDED.coverage,
    source_stale_after = EXCLUDED.source_stale_after,
    datagov_dataset_ids = EXCLUDED.datagov_dataset_ids,
    datagov_resource_ids = EXCLUDED.datagov_resource_ids,
    external_resource_ids = EXCLUDED.external_resource_ids, licence = EXCLUDED.licence,
    config = EXCLUDED.config, active = true, loaded_at = now()
"""


def sync_registry(conn: psycopg.Connection, cfg: SourcesConfig) -> dict[str, int]:
    """Upsert the config into the registry tables in one transaction."""
    with conn.transaction():
        for e in cfg.allowed_external_resources:
            conn.execute(
                _UPSERT_EXTERNAL,
                (
                    e.id,
                    e.name,
                    e.urls,
                    e.host,
                    e.datagov_datasets,
                    e.status,
                    Jsonb(e.model_dump(mode="json")),
                ),
            )
        ext_off = conn.execute(
            "UPDATE allowed_external_resource SET active = false"
            " WHERE active AND NOT (id = ANY(%s))",
            ([e.id for e in cfg.allowed_external_resources],),
        ).rowcount

        for s in cfg.sources:
            conn.execute(
                _UPSERT_SOURCE,
                (
                    s.id,
                    s.names.lv,
                    s.names.en,
                    s.owner,
                    s.group,
                    s.order,
                    s.type,
                    list(s.subject_kinds),
                    s.default_selected,
                    s.coverage_lv,
                    s.source_stale_after,
                    s.datagov.dataset_ids if s.datagov else [],
                    s.datagov.resource_ids if s.datagov else [],
                    s.external_resources,
                    s.licence,
                    Jsonb(s.model_dump(mode="json")),
                ),
            )
        src_off = conn.execute(
            "UPDATE source SET active = false WHERE active AND NOT (id = ANY(%s))",
            ([s.id for s in cfg.sources],),
        ).rowcount

    return {
        "sources": len(cfg.sources),
        "sources_deactivated": src_off,
        "external_resources": len(cfg.allowed_external_resources),
        "external_resources_deactivated": ext_off,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m etl.sources", description=__doc__.split("\n")[0]
    )
    parser.add_argument("command", choices=["validate", "load"])
    parser.add_argument("--config", type=Path, default=None, help="default: config/sources.yaml")
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL"),
        help="default: $DATABASE_URL",
    )
    args = parser.parse_args(argv)

    path = args.config or default_config_path()
    try:
        cfg = load_config(path)
    except ValidationError as exc:
        print(f"{path}: invalid\n{exc}", file=sys.stderr)
        return 1
    print(
        f"{path}: valid ({len(cfg.sources)} sources,"
        f" {len(cfg.allowed_external_resources)} external resources)"
    )
    if args.command == "validate":
        return 0

    if not args.database_url:
        print("no database URL: set DATABASE_URL or pass --database-url", file=sys.stderr)
        return 2
    with psycopg.connect(args.database_url) as conn:
        counts = sync_registry(conn, cfg)
    print("loaded: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
