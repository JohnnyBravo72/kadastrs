"""Freshness against the source (decided 2026-10-11, docs/decisions.md "Freshness").

A source is fresh when we hold the newest file the publisher has released, not
when our copy is younger than a fixed age. At the start of a check run (and in
`etl status`) the source's latest release is read from data.gov.lv package_show,
the same dates the importer uses (rule E1): the newest `last_modified` of the
source's resources, or the dataset's `metadata_modified` for a source without
CKAN files (flood, D1 E7). It is compared with the release our live version was
imported from (import_log.source_last_modified of the imports that gave or
confirmed it):

  current          we hold the latest release      "aktuāli", no warning
  newer_available  a newer release is not imported  "novecojuši – pieejama jaunāka versija"
  source_stale     the publisher has released nothing for longer than the
                   source's `source_stale_after`    "avots nav atjaunots kopš <date>"
  unknown          offline and never checked before

If data.gov.lv cannot be reached, the last good check (table source_check) is
used and the text says "pēdējā pārbaude <date>". Every look is recorded in
source_check. A run stores the outcome with its pinned versions, so its report
(built from stored data only) always shows the freshness as of the run.
"""

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import httpx

from etl.ckan import Ckan, http_client
from etl.settings import etl_config
from etl.sources import load_config

ENV_SWITCH = "KADASTRS_FRESHNESS_CHECK"  # "off": no network, last known checks only
TIMEOUT = httpx.Timeout(10.0, connect=5.0)
LABEL_LV = {
    "current": "aktuāli",
    "newer_available": "novecojuši",
    "source_stale": "avots nav atjaunots",
    "unknown": "nezināms",
}


@dataclass(frozen=True)
class Remote:
    """One look at a source's latest release."""

    ok: bool
    last_modified: datetime | None = None
    error: str | None = None


def _utc(dt: datetime | None) -> datetime | None:
    """CKAN dates are UTC without an offset."""
    if dt is None:
        return None
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def _prefetch(ckan: Ckan, dataset: str) -> Exception | None:
    try:
        ckan.package(dataset)
    except Exception as exc:  # noqa: BLE001  (reported per source by the caller)
        return exc
    return None


def fetch_remote(client: httpx.Client | None = None, api: str | None = None) -> dict[str, Remote]:
    """The latest release of every registered source, from package_show. Never
    raises: a failure is recorded per source. No database access (a run calls
    this before it opens its transaction)."""
    sources = load_config().sources
    if os.environ.get(ENV_SWITCH, "on").lower() == "off":
        return {s.id: Remote(False, error=f"pārbaude izslēgta ({ENV_SWITCH}=off)") for s in sources}
    cfg = etl_config()
    own = client is None
    client = client or http_client(timeout=TIMEOUT)
    out: dict[str, Remote] = {}
    offline: str | None = None
    try:
        ckan = Ckan(client, api or cfg.ckan_api)
        # one package_show per distinct dataset, in parallel (cached in ckan);
        # failures surface again, per source, in the loop below
        datasets_all = sorted({d for s in sources if s.datagov for d in s.datagov.dataset_ids})
        with ThreadPoolExecutor(max_workers=8) as pool:
            for exc in pool.map(lambda d: _prefetch(ckan, d), datasets_all):
                if isinstance(exc, httpx.ConnectError | httpx.TimeoutException):
                    offline = f"data.gov.lv nav sasniedzams: {type(exc).__name__}"
                    break
        for s in sources:
            if offline:
                out[s.id] = Remote(False, error=offline)
                continue
            datasets = s.datagov.dataset_ids if s.datagov else []
            if not datasets:
                out[s.id] = Remote(False, error="avotam nav data.gov.lv datu kopas")
                continue
            try:
                rids = list(cfg.files.get(s.id, {}).values())
                if rids:
                    dates = [ckan.find_resource(datasets, rid).last_modified for rid in rids]
                    known = [d for d in dates if d is not None]
                    latest = max(known) if known else None
                else:
                    listed = ckan.package(datasets[0]).get("metadata_modified")
                    latest = datetime.fromisoformat(listed) if listed else None
                out[s.id] = Remote(True, _utc(latest))
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                offline = f"data.gov.lv nav sasniedzams: {type(exc).__name__}"
                out[s.id] = Remote(False, error=offline)
            except Exception as exc:  # noqa: BLE001  (recorded, never stops a run)
                out[s.id] = Remote(False, error=f"{type(exc).__name__}: {exc}"[:300])
    finally:
        if own:
            client.close()
    return out


def record(conn, remotes: dict[str, Remote], origin: str) -> None:
    known = {r[0] for r in conn.execute("SELECT id FROM source")}
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO source_check (source_id, origin, ok, remote_last_modified, error)"
            " VALUES (%s, %s, %s, %s, %s)",
            [
                (sid, origin, r.ok, r.last_modified, None if r.ok else r.error or "nav zināms")
                for sid, r in remotes.items()
                if sid in known
            ],
        )


_STATE_SQL = """
SELECT s.id, s.source_stale_after, s.source_stale_after::text,
       coalesce((SELECT max(l.source_last_modified) FROM import_log l
                 WHERE l.source_id = s.id AND l.dataset_version_id = v.id
                       AND l.status IN ('succeeded', 'unchanged')),
                v.source_last_modified),
       c.checked_at, c.remote_last_modified
FROM source s
JOIN dataset_version v ON v.source_id = s.id AND v.status = 'live'
LEFT JOIN LATERAL (SELECT checked_at, remote_last_modified FROM source_check
                   WHERE source_id = s.id AND ok
                   ORDER BY checked_at DESC, id DESC LIMIT 1) c ON true
"""


def _day(dt: datetime | None) -> str | None:
    return dt.date().isoformat() if dt else None


def assess(conn, remotes: dict[str, Remote], at: datetime) -> dict[str, dict]:
    """Freshness of every live version, from this look (or the last good one).
    Read before `record` so "the last good check" is an earlier one."""
    cfg = etl_config()
    out = {}
    for sid, stale_after, stale_text, ours, last_at, last_remote in conn.execute(_STATE_SQL):
        r = remotes.get(sid)
        live = r is not None and r.ok
        if live:
            latest, checked_at = r.last_modified, at
        elif last_at is not None:
            latest, checked_at = last_remote, last_at
        else:
            latest = checked_at = None
        ours = _utc(ours)
        latest = _utc(latest)
        live_export = bool(cfg.options.get(sid, {}).get("live_export"))

        if live_export:
            # D11: CSV is generated on request; fresh while our last download is
            # younger than source_stale_after. The text names the download date.
            checked_at = at if live else last_at
            if checked_at is None and ours is None:
                status, text = "unknown", "nav zināms: live eksports vēl nav lejupielādēts"
            elif (
                stale_after is not None
                and ours is not None
                and at - ours > _as_timedelta(stale_after)
            ):
                status = "source_stale"
                text = (
                    f"live eksports – atkārtoti lejupielādēt "
                    f"(pēdējā lejupielāde {_day(ours)})"
                )
            else:
                status = "current"
                text = f"live eksports (lejupielādēts {_day(ours)})" if ours else "live eksports"
            if checked_at is not None and not live:
                text += f"; pēdējā pārbaude {_day(checked_at)}"
            out[sid] = {
                "status": status,
                "label_lv": LABEL_LV[status],
                "text_lv": text,
                "warn": status != "current",
                "source_updated": _day(ours),
                "checked_at": checked_at.isoformat() if checked_at else None,
                "checked_live": live,
                "source_stale_after": stale_text,
            }
            continue

        if checked_at is None:
            status = "unknown"
            text = "nav zināms, vai šī ir jaunākā versija: avots nav sasniedzams, iepriekšējas"
            text += " pārbaudes nav"
        elif latest is not None and ours is not None and latest > ours:
            status = "newer_available"
            text = f"novecojuši – pieejama jaunāka versija (avots atjaunots {_day(latest)})"
        elif (
            stale_after is not None
            and latest is not None
            and at - latest > _as_timedelta(stale_after)
        ):
            status = "source_stale"
            text = f"avots nav atjaunots kopš {_day(latest)}"
        else:
            status = "current"
            text = "jaunākie pieejamie dati" + (
                f" (avots atjaunots {_day(latest)})" if latest else ""
            )
        if checked_at is not None and not live:
            text += f"; pēdējā pārbaude {_day(checked_at)}"
        out[sid] = {
            "status": status,
            "label_lv": LABEL_LV[status],
            "text_lv": text,
            "warn": status != "current",
            "source_updated": _day(latest),
            "checked_at": checked_at.isoformat() if checked_at else None,
            "checked_live": live,
            "source_stale_after": stale_text,
        }
    return out


def _as_timedelta(value) -> timedelta:
    return value if isinstance(value, timedelta) else timedelta(days=float(value))


def check(conn, at: datetime, origin: str, remotes: dict[str, Remote] | None = None):
    """Assess and record in one go (the caller commits)."""
    remotes = remotes if remotes is not None else fetch_remote()
    result = assess(conn, remotes, at)
    record(conn, remotes, origin)
    return result
