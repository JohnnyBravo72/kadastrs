"""ETL command line. Runs in the `etl` compose service (CLAUDE.md rule 12):

docker compose run --rm etl import all
docker compose run --rm etl import cadastre_text varis_addresses
docker compose run --rm etl status
"""

import argparse
import json
import sys
from functools import partial

import psycopg

from etl.ckan import http_client
from etl.importers import IMPORTERS
from etl.run import run_import
from etl.settings import database_url, etl_config, raw_dir
from etl.sources import load_config


def cmd_import(names: list[str]) -> int:
    if names == ["all"]:
        names = list(IMPORTERS)
    unknown = [n for n in names if n not in IMPORTERS]
    if unknown:
        print(f"unknown source(s) {unknown}; known: {', '.join(IMPORTERS)} or all", file=sys.stderr)
        return 2
    cfg, registry = etl_config(), load_config()
    conn_factory = partial(psycopg.connect, database_url())
    failed = 0
    with http_client() as client:
        for name in names:
            print(f"== {name}", flush=True)
            out = run_import(
                IMPORTERS[name](),
                conn_factory=conn_factory,
                client=client,
                cfg=cfg,
                registry=registry,
                raw_root=raw_dir(),
            )
            print(f"   {out.status}  version={out.version_id}  {out.message}")
            if out.row_counts:
                print("   " + json.dumps(out.row_counts, ensure_ascii=False, default=str))
            failed += out.status == "failed"
    return 1 if failed else 0


def cmd_status() -> int:
    with psycopg.connect(database_url()) as c:
        rows = c.execute(
            """
            SELECT s.id, v.id, v.version_date, v.row_count, v.imported_at,
                   l.status, l.started_at, l.message
            FROM source s
            LEFT JOIN dataset_version v ON v.source_id = s.id AND v.status = 'live'
            LEFT JOIN LATERAL (SELECT * FROM import_log WHERE source_id = s.id
                               ORDER BY started_at DESC LIMIT 1) l ON true
            WHERE s.active AND (s.type = 'reference' OR s.id = ANY(%s))
            ORDER BY s.display_order
            """,
            (list(IMPORTERS),),
        ).fetchall()
    for sid, vid, vdate, n, imported, lstatus, lstarted, msg in rows:
        live = (
            f"live v{vid} data {vdate} rows {n} imported {imported:%Y-%m-%d %H:%M}"
            if vid
            else "no live version"
        )
        last = f"last run {lstatus} {lstarted:%Y-%m-%d %H:%M}" if lstatus else "never run"
        print(f"{sid:18} {live} | {last}" + (f" | {msg}" if msg else ""))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m etl")
    sub = p.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("import", help="import sources (or all)")
    imp.add_argument("sources", nargs="+")
    sub.add_parser("status", help="live versions and last import per source")
    args = p.parse_args(argv)
    return cmd_import(args.sources) if args.cmd == "import" else cmd_status()


if __name__ == "__main__":
    sys.exit(main())
