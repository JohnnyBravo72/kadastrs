"""The source registry for the entry dialog's sources checklist and the Avoti tab
(PLAN.md §5.2 `GET /api/sources`, §8.1 step 5, §8.2).

A source can be unticked when it selects a check module; the base data every
module reads (cadastre map, boundaries, classifiers) is always used. Freshness
is the last known look at data.gov.lv (etl/freshness.py); nothing is fetched
or recorded here.
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request

from engine.checks.context import DATASET_URL
from engine.checks.modules import MODULES
from etl import freshness

router = APIRouter(prefix="/api", tags=["sources"])


def registry(conn) -> list[dict[str, Any]]:
    selects: dict[str, list[dict[str, Any]]] = {}
    reads: dict[str, list[str]] = {}
    for m in MODULES:
        for s in m.selectors:
            selects.setdefault(s, []).append({"id": m.id, "no": m.no, "name": m.name_lv})
        for s in (*m.reads, *m.optional):
            reads.setdefault(s, [])
            if m.name_lv not in reads[s]:
                reads[s].append(m.name_lv)
    fresh = freshness.assess(conn, {}, datetime.now(UTC))
    out = []
    for (
        sid,
        name,
        owner,
        group,
        order,
        typ,
        default,
        coverage,
        partial,
        datasets,
        licence,
        vid,
        vdate,
    ) in conn.execute(
        """SELECT s.id, s.name_lv, s.owner, s.source_group, s.display_order, s.type,
                  s.default_selected, s.coverage,
                  coalesce((s.config->>'partial_coverage')::boolean, false),
                  s.datagov_dataset_ids, s.licence, v.id, v.version_date
           FROM source s
           LEFT JOIN dataset_version v ON v.source_id = s.id AND v.status = 'live'
           WHERE s.active ORDER BY s.display_order, s.id"""
    ):
        modules = selects.get(sid, [])
        out.append(
            {
                "id": sid,
                "name": name,
                "owner": owner,
                "group": group,
                "order": order,
                "type": typ,
                "default_selected": default,
                # unticking it leaves these modules out of the run
                "modules": modules,
                "selectable": bool(modules),
                # read by these modules whatever is ticked
                "used_by": [] if modules else reads.get(sid, []),
                "coverage": coverage,
                "partial_coverage": partial,
                "licence": licence,
                "live_version": None
                if vid is None
                else {"dataset_version_id": vid, "dataset_date": vdate.isoformat()},
                "freshness": fresh.get(sid),
                "datagov_urls": [DATASET_URL.format(d) for d in datasets],
            }
        )
    return out


@router.get("/sources")
def sources(request: Request) -> list[dict[str, Any]]:
    """The registry in display order with each source's group, the modules it
    selects, coverage (and whether it is partial), live data date, freshness and
    data.gov.lv links."""
    with request.app.state.pool.connection() as conn:
        return registry(conn)
