"""ETL command line. Runs in the `etl` compose service (CLAUDE.md rule 12):

docker compose run --rm etl import all
docker compose run --rm etl import cadastre_text varis_addresses
docker compose run --rm etl status
docker compose run --rm etl bis-links      # distinct BIS cases by best cadastre match
"""

import argparse
import json
import sys
from functools import partial

import psycopg

from etl import freshness
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
        # freshness against the source, same check as a run (etl/freshness.py), recorded
        at = c.execute("SELECT now()").fetchone()[0]
        fresh = freshness.check(c, at, "status")
        c.commit()
    stale_sources = []
    for sid, vid, vdate, n, imported, lstatus, lstarted, msg in rows:
        f = fresh.get(sid)
        state = f"{f['label_lv']}: {f['text_lv']}" if f else ""
        if f and f["warn"]:
            stale_sources.append(sid)
        live = (
            f"live v{vid} data {vdate} rows {n} imported {imported:%Y-%m-%d %H:%M} | {state}"
            if vid
            else "no live version"
        )
        last = f"last run {lstatus} {lstarted:%Y-%m-%d %H:%M}" if lstatus else "never run"
        print(f"{sid:18} {live} | {last}" + (f" | {msg}" if msg else ""))
    if stale_sources:
        print(f"check freshness: {', '.join(stale_sources)} (see the texts above)")
    return 0


# Distinct cases, never raw rows: the case-objects CSV has exact duplicate rows
# (docs/data-sources.md §7.1). DEL addresses are counted against live VARIS (report only).
BIS_LINKS_SQL = """
WITH best AS (
    SELECT * FROM ref.bis_case_best_match(%(bis)s, %(cad)s)
), del AS (
    SELECT DISTINCT o.case_number FROM ref.bis_object o
    JOIN ref.address_current a ON a.code = o.address_code AND a.status = 'DEL'
    WHERE o.dataset_version_id = %(bis)s
)
SELECT best_match, count(*) AS cases,
       count(*) FILTER (WHERE NOT has_designation) AS without_designation,
       count(*) FILTER (WHERE case_number IN (SELECT case_number FROM del)) AS del_address
FROM best GROUP BY best_match
ORDER BY array_position(ARRAY['exact', 'probable', 'address_only', 'none'], best_match)
"""


def cmd_bis_links() -> int:
    """Distinct pilot BIS cases by best match against the live cadastre text."""
    with psycopg.connect(database_url()) as c:
        bis, cad = c.execute(
            "SELECT ref.live_version('bis_cases'), ref.live_version('cadastre_text')"
        ).fetchone()
        if bis is None or cad is None:
            print("bis_cases and cadastre_text need live versions", file=sys.stderr)
            return 1
        rows = c.execute(BIS_LINKS_SQL, {"bis": bis, "cad": cad}).fetchall()
    total = sum(r[1] for r in rows)
    print(f"BIS v{bis} x cadastre_text v{cad}: {total} distinct pilot cases")
    head = ("best match", "cases", "share", "no desig.", "DEL addr")
    print("{:14} {:>8} {:>7} {:>9} {:>8}".format(*head))
    for best, n, nodes, dels in rows:
        print(f"{best:14} {n:8} {n / total:7.1%} {nodes:9} {dels:8}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m etl")
    sub = p.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("import", help="import sources (or all)")
    imp.add_argument("sources", nargs="+")
    sub.add_parser("status", help="live versions and last import per source")
    sub.add_parser("bis-links", help="distinct BIS cases by best cadastre match (live versions)")
    args = p.parse_args(argv)
    if args.cmd == "import":
        return cmd_import(args.sources)
    return cmd_bis_links() if args.cmd == "bis-links" else cmd_status()


if __name__ == "__main__":
    sys.exit(main())
