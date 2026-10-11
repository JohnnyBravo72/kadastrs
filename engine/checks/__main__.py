"""Check engine CLI (runs in the `check` container, CLAUDE.md rule 12):

    docker compose run --rm check run 09000360220 "Tautas iela 11, Daugavpils"
    docker compose run --rm check show 12
    docker compose run --rm check replay 12
    docker compose run --rm check compare tests/data/filled.xlsx [--out report.xlsx]

`run` resolves the values like POST /api/resolve (an ambiguous value is checked
as its first match, with a note) and stores a new run. `replay` recomputes a
stored run from its pinned versions and exits 1 if anything differs. `compare`
checks a filled test-set template against the engine (engine/checks/compare.py).
"""

import argparse
import json
import sys
from pathlib import Path

import psycopg

from api.db import database_url
from engine.checks import ENGINE_VERSION, compare, runner, summary


def _connect():
    return psycopg.connect(database_url(), autocommit=True)


def _sources(text: str | None) -> list[str] | None:
    return [s.strip() for s in text.split(",") if s.strip()] if text else None


def cmd_run(args) -> int:
    with _connect() as conn:
        rows = [
            compare.ManualRow(i, None, v, None, {}, None, None) for i, v in enumerate(args.values)
        ]
        resolved = compare.resolve_rows(conn, rows)
        for r in resolved:
            if r.target is None or r.note:
                print(f"{r.row.value}: {r.note}", file=sys.stderr)
        targets = [r.target for r in resolved if r.target is not None]
        if not targets:
            print("nothing to check", file=sys.stderr)
            return 1
        run_id = runner.start_run(conn, targets, _sources(args.sources), origin="cli")
        _print_summary(conn, run_id)
    return 0


def _print_summary(conn, run_id: int) -> None:
    s = summary.summarize(conn, run_id)
    rs = s["rule_set"]
    print(f"run {run_id}: {s['targets']} objects, rule set {rs['version']} ({rs['status']})")
    for t in summary.targets(conn, run_id):
        cells = ", ".join(f"{m}={v['summary_status']}/{v['risk']}" for m, v in t["modules"].items())
        print(f"  {t['designation']} ({t['type']}): {cells}")


def cmd_show(args) -> int:
    with _connect() as conn:
        if args.json:
            print(
                json.dumps(
                    summary.summarize(conn, args.run_id), default=str, ensure_ascii=False, indent=2
                )
            )
        else:
            _print_summary(conn, args.run_id)
    return 0


def cmd_replay(args) -> int:
    with _connect() as conn:
        version = conn.execute(
            "SELECT engine_version FROM work.run WHERE id = %s", (args.run_id,)
        ).fetchone()
        if version is None:
            print(f"run {args.run_id} not found", file=sys.stderr)
            return 1
        if version[0] != ENGINE_VERSION:
            print(f"note: run made by engine {version[0]}, replayed with {ENGINE_VERSION}")
        stored = [r.comparable() for r in runner.stored(conn, args.run_id)]
        replayed = [r.comparable() for r in runner.replay(conn, args.run_id)]
    if stored == replayed:
        print(f"run {args.run_id}: {len(stored)} results reproduced")
        return 0
    diff = sum(1 for a, b in zip(stored, replayed, strict=False) if a != b)
    print(f"run {args.run_id}: {diff} results differ ({len(stored)} stored, {len(replayed)} now)")
    return 1


def cmd_compare(args) -> int:
    path = Path(args.file)
    out = Path(args.out) if args.out else path.with_name(path.stem + "_salidzinajums.xlsx")
    with _connect() as conn:
        report = compare.compare(conn, path, _sources(args.sources))
    compare.write_xlsx(report, out)
    compare.print_report(report)
    print(f"report: {out}")
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m engine.checks")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="resolve values and check them in a new run")
    r.add_argument("values", nargs="+")
    r.add_argument("--sources", help="comma-separated source ids (default: registry defaults)")
    r.set_defaults(func=cmd_run)
    s = sub.add_parser("show", help="summary of a stored run")
    s.add_argument("run_id", type=int)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_show)
    rp = sub.add_parser("replay", help="recompute a run from its pinned versions and compare")
    rp.add_argument("run_id", type=int)
    rp.set_defaults(func=cmd_replay)
    c = sub.add_parser("compare", help="compare a filled test-set template with the engine")
    c.add_argument("file")
    c.add_argument("--out")
    c.add_argument("--sources")
    c.set_defaults(func=cmd_compare)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
