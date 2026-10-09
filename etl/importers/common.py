"""Helpers shared by the importers."""

from collections.abc import Iterable, Sequence
from datetime import date, datetime

import psycopg
from psycopg import sql

from etl.identity import FileRecord, iso
from etl.remote import download
from etl.run import Context

# Aggregate the comma-joined `flags` of staged rows into a distinct text[] (rule E2 flags).
FLAGS_AGG = (
    "ARRAY(SELECT DISTINCT x FROM unnest(string_to_array(string_agg(flags, ','), ',')) x"
    " WHERE x <> '')"
)


def fetch_whole(ctx: Context, role: str, filename: str) -> FileRecord:
    res = ctx.resources[role]
    info = download(ctx.client, res.url, ctx.workdir / filename)
    return FileRecord(
        role=role,
        resource_id=res.id,
        url=res.url,
        last_modified=iso(res.last_modified),
        size=info.size,
        sha256=info.sha256,
        path=filename,
    )


def resource_date(ctx: Context, roles: Iterable[str]) -> date:
    """Version date from the source (rule E7): the oldest CKAN last_modified of
    the resources, i.e. the date all of the data is at least as new as."""
    dates = [ctx.resources[r].last_modified for r in roles]
    if any(d is None for d in dates):
        raise ValueError("a resource has no last_modified in CKAN; cannot date the version")
    return min(d for d in dates if d is not None).date()


def create_stage(conn: psycopg.Connection, name: str, columns: dict[str, str]) -> None:
    cols = sql.SQL(", ").join(
        sql.SQL("{} {}").format(sql.Identifier(c), sql.SQL(t)) for c, t in columns.items()
    )
    conn.execute(
        sql.SQL("CREATE TEMP TABLE {} ({}) ON COMMIT DROP").format(sql.Identifier(name), cols)
    )


def copy_rows(
    conn: psycopg.Connection, table: str, columns: Sequence[str], rows: Iterable[Sequence]
) -> int:
    """COPY rows into `table` (schema-qualified name allowed); returns the count."""
    n = 0
    target = sql.SQL(".").join(sql.Identifier(p) for p in table.split("."))
    stmt = sql.SQL("COPY {} ({}) FROM STDIN").format(
        target, sql.SQL(", ").join(sql.Identifier(c) for c in columns)
    )
    with conn.cursor().copy(stmt) as cp:
        for row in rows:
            cp.write_row(row)
            n += 1
    return n


def parse_varis_date(value: str | None) -> date | None:
    """VARIS CSV dates are always YYYY.MM.DD (docs/data-sources.md §5.1)."""
    if not value:
        return None
    return datetime.strptime(value, "%Y.%m.%d").date()


def flags_text(flags: list[str]) -> str | None:
    return ",".join(flags) if flags else None
