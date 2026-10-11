"""What one run reads: the pinned dataset versions, the rule set and the run time.

Versions are pinned once, at the start of a run (PLAN.md §6.5). Modules read
only by these version ids, never through the *_current views, so replaying a
run with its stored versions gives the same results after newer imports.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from engine.checks.contract import SourceRef, Warning_
from engine.checks.rules import RuleSet
from engine.resolve.context import SourceUnavailable, Versions
from etl import freshness

DATASET_URL = "https://data.gov.lv/dati/lv/dataset/{}"
REFERENCE = ("cadastre_text", "cadastre_spatial", "varis_addresses", "admin_boundaries")


@dataclass(frozen=True)
class Pinned:
    """One pinned source version, as stored in work.run_version."""

    source_id: str
    version_id: int
    # {id, name, dataset_date, datagov_url, freshness, coverage, processing}
    # (runs before the freshness change hold max_age and stale instead of freshness)
    info: dict[str, Any]

    def ref(self) -> SourceRef:
        return SourceRef(
            id=self.source_id,
            name=self.info["name"],
            dataset_date=self.info["dataset_date"],
            dataset_version_id=self.version_id,
            datagov_url=self.info.get("datagov_url"),
        )


def pin_live(conn, run_at: datetime, remotes: dict | None = None) -> dict[str, Pinned]:
    """The live version of every source, with what the report shows about it:
    its freshness against the source (etl/freshness.py; `remotes` = this run's
    look at data.gov.lv, None = use the last known checks), coverage and notes."""
    fresh = freshness.check(conn, run_at, "run", remotes if remotes is not None else {})
    rows = conn.execute(
        """SELECT v.source_id, v.id, v.version_date, s.name_lv, s.datagov_dataset_ids,
                  s.coverage,
                  -- Latvian processing notes (sources.yaml): the source's own
                  -- processing_lv, then those of its D1 resources
                  ARRAY(SELECT jsonb_array_elements_text(
                                   coalesce(s.config->'processing_lv', '[]')))
                  || ARRAY(SELECT p->>'report_lv'
                           FROM allowed_external_resource e,
                                jsonb_array_elements(coalesce(e.config->'processing', '[]')) p
                           WHERE e.id = ANY(s.external_resource_ids) AND e.status = 'allowed'
                                 AND p->>'report_lv' IS NOT NULL
                           ORDER BY e.id)
           FROM dataset_version v JOIN source s ON s.id = v.source_id
           WHERE v.status = 'live' ORDER BY v.source_id"""
    ).fetchall()
    out = {}
    for source_id, vid, vdate, name, datasets, coverage, processing in rows:
        out[source_id] = Pinned(
            source_id,
            vid,
            {
                "id": source_id,
                "name": name,
                "dataset_date": vdate.isoformat(),
                "datagov_url": DATASET_URL.format(datasets[0]) if datasets else None,
                # freshness against the source as of the run (warning if not current)
                "freshness": fresh.get(source_id),
                # shown on the report's "Avoti" sheet; stored with the run
                "coverage": coverage,
                "processing": list(processing),
            },
        )
    missing = [s for s in REFERENCE if s not in out]
    if missing:
        raise SourceUnavailable(f"no live version of {', '.join(missing)} (import it first)")
    return out


def load_pinned(conn, run_id: int) -> dict[str, Pinned]:
    return {
        s: Pinned(s, vid, info)
        for s, vid, info in conn.execute(
            "SELECT source_id, dataset_version_id, source FROM work.run_version"
            " WHERE run_id = %s ORDER BY source_id",
            (run_id,),
        )
    }


@dataclass
class RunContext:
    conn: Any
    rules: RuleSet
    run_at: datetime
    pinned: dict[str, Pinned]
    selected: set[str]
    _temp: set[str] = field(default_factory=set)  # temp tables built for this run

    @property
    def thresholds(self):
        return self.rules.thresholds

    def v(self, source_id: str) -> int | None:
        p = self.pinned.get(source_id)
        return p.version_id if p else None

    @property
    def cadastre(self) -> Versions:
        return Versions(**{s: self.pinned[s].version_id for s in REFERENCE})

    def refs(self, source_ids: list[str]) -> list[SourceRef]:
        return [self.pinned[s].ref() for s in source_ids if s in self.pinned]

    def stale_warnings(self, source_ids: list[str]) -> list[Warning_]:
        out = []
        for s in source_ids:
            p = self.pinned.get(s)
            f = p.info.get("freshness") if p else None
            if f is not None:  # runs since 2026-10-11: against the source
                if f["warn"]:
                    out.append(
                        Warning_(
                            code="stale_data", message=f"{p.info['name']}: {f['text_lv']}", source=s
                        )
                    )
            elif p and p.info.get("stale"):  # older runs (max_age), kept for replay
                out.append(
                    Warning_(
                        code="stale_data",
                        message=f"{p.info['name']}: dati no {p.info['dataset_date']}, "
                        f"vecāki par pieļaujamo ({p.info['max_age']})",
                        source=s,
                    )
                )
        return out

    def once(self, name: str) -> bool:
        """True the first time `name` is asked for in this run (build a temp table)."""
        if name in self._temp:
            return False
        self._temp.add(name)
        return True
