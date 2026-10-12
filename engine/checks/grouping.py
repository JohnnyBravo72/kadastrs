"""Project groups of a run (PLAN.md §8.2, Phase 7).

A grouping is a view on a stored run: it never touches check results (CLAUDE.md
rule 3). Each change is a new insert-only work.run_grouping row holding the whole
grouping; the newest row is current. Without a row the groups come from the
input's project numbers (run_target.project_no), in input order, with the
objects without one in "Bez projekta" (always last, cannot be renamed or deleted).
The Excel report follows the current grouping and names the row it used.
"""

import json
from datetime import datetime
from typing import Any

from engine.checks.runner import RunNotFound

NONE_ID = "none"
NONE_NAME = "Bez projekta"
MAX_NAME = 100


class GroupingError(ValueError):
    pass


def _j(x) -> str:
    return json.dumps(x, ensure_ascii=False)


def _targets(conn, run_id: int) -> list[tuple[int, str | None]]:
    return conn.execute(
        "SELECT target_no, project_no FROM work.run_target WHERE run_id = %s ORDER BY target_no",
        (run_id,),
    ).fetchall()


def default(conn, run_id: int) -> dict[str, Any]:
    """Groups from the input's project numbers (no stored row)."""
    groups: list[dict[str, str]] = []
    assignment: dict[str, str] = {}
    seen: dict[str, str] = {}
    for tno, project in _targets(conn, run_id):
        name = (project or "").strip()
        if not name:
            assignment[str(tno)] = NONE_ID
            continue
        if name not in seen:
            seen[name] = f"p{len(seen) + 1}"
            groups.append({"id": seen[name], "name": name})
        assignment[str(tno)] = seen[name]
    groups.append({"id": NONE_ID, "name": NONE_NAME})
    return {
        "id": None,
        "created_at": None,
        "origin": "input",
        "groups": groups,
        "assignment": assignment,
    }


def _row(rec) -> dict[str, Any]:
    gid, created, groups, assignment, origin = rec
    return {
        "id": gid,
        "created_at": created,
        "origin": origin,
        "groups": groups,
        "assignment": assignment,
    }


def current(conn, run_id: int, grouping_id: int | None = None) -> dict[str, Any]:
    """The newest grouping row of the run (or row `grouping_id`), else the default."""
    if conn.execute("SELECT 1 FROM work.run WHERE id = %s", (run_id,)).fetchone() is None:
        raise RunNotFound(f"pārbaude {run_id} nav atrasta")
    if grouping_id is not None:
        rec = conn.execute(
            "SELECT id, created_at, groups, assignment, origin FROM work.run_grouping"
            " WHERE run_id = %s AND id = %s",
            (run_id, grouping_id),
        ).fetchone()
        if rec is None:
            raise RunNotFound(f"grupējums {grouping_id} nav pārbaudē {run_id}")
        return _row(rec)
    rec = conn.execute(
        "SELECT id, created_at, groups, assignment, origin FROM work.run_grouping"
        " WHERE run_id = %s ORDER BY id DESC LIMIT 1",
        (run_id,),
    ).fetchone()
    return _row(rec) if rec else default(conn, run_id)


def validate(conn, run_id: int, groups: list[dict], assignment: dict[str, str]) -> list[dict]:
    """Every target in exactly one existing group; names unique and not empty;
    "Bez projekta" kept (last)."""
    clean: list[dict[str, str]] = []
    ids: set[str] = set()
    names: set[str] = set()
    for g in groups:
        gid, name = str(g.get("id") or "").strip(), " ".join(str(g.get("name") or "").split())
        if gid == NONE_ID:
            continue
        if not gid or gid in ids:
            raise GroupingError(f"grupas id '{gid}' nav derīgs vai atkārtojas")
        if not name or len(name) > MAX_NAME:
            raise GroupingError(f"grupas nosaukumam jābūt 1–{MAX_NAME} rakstzīmēm")
        if name.casefold() in names or name.casefold() == NONE_NAME.casefold():
            raise GroupingError(f"grupa „{name}” jau ir")
        ids.add(gid)
        names.add(name.casefold())
        clean.append({"id": gid, "name": name})
    clean.append({"id": NONE_ID, "name": NONE_NAME})
    targets = {str(t) for t, _ in _targets(conn, run_id)}
    if set(assignment) != targets:
        raise GroupingError("katram objektam jābūt tieši vienā grupā")
    unknown = sorted({g for g in assignment.values() if g not in ids | {NONE_ID}})
    if unknown:
        raise GroupingError(f"nezināma grupa: {', '.join(unknown)}")
    return clean


def save(
    conn, run_id: int, groups: list[dict], assignment: dict[str, str], origin: str = "user"
) -> dict[str, Any]:
    """Store a new grouping row (the old rows stay). Commits."""
    current(conn, run_id)  # 404 for an unknown run
    clean = validate(conn, run_id, groups, assignment)
    with conn.transaction():
        rec = conn.execute(
            "INSERT INTO work.run_grouping (run_id, groups, assignment, origin)"
            " VALUES (%s, %s, %s, %s) RETURNING id, created_at, groups, assignment, origin",
            (
                run_id,
                _j(clean),
                _j({k: assignment[k] for k in sorted(assignment, key=int)}),
                origin,
            ),
        ).fetchone()
    return _row(rec)


def carry_over(conn, old_run: int, new_run: int) -> None:
    """A run made from another (same targets, same order) starts with its grouping."""
    g = current(conn, old_run)
    if g["id"] is not None:
        save(conn, new_run, g["groups"], g["assignment"], origin="rerun")


def group_names(g: dict[str, Any]) -> dict[int, str]:
    """target_no -> group name ("Bez projekta" for the default group)."""
    names = {x["id"]: x["name"] for x in g["groups"]}
    return {int(t): names[gid] for t, gid in g["assignment"].items()}


def label(g: dict[str, Any]) -> str:
    """How the report names the grouping it used (Avoti sheet)."""
    if g["id"] is None:
        return "pēc ievadītajiem projekta numuriem (grupas nav mainītas)"
    created = g["created_at"]
    when = created.strftime("%Y-%m-%d %H:%M:%S %Z") if isinstance(created, datetime) else created
    return f"grupējums nr. {g['id']}, saglabāts {when}"
