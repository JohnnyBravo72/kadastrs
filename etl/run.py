"""Import runner: one import = one import_log row; new data = one dataset_version.

Flow (PLAN.md §2.2, rules E1, E7, E8):
 1. import_log row `running` (committed at once, so failures are visible).
 2. Resolve resource URLs from CKAN package_show (E1).
 3. Fetch files into a work dir (Range-fetched zips may short-cut to
    `unchanged` by fingerprint); compute the version checksum.
 4. Same checksum as the live version -> `unchanged`; as an older version ->
    that version becomes live again. Otherwise load the new version.
 5. Load, validate and promote in ONE transaction: a failure leaves nothing
    behind and the last good version stays live.
 6. Keep the raw files of the live version only (row-count tests use them).
"""

import shutil
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

import httpx
import psycopg
from psycopg.types.json import Jsonb

from etl.ckan import Ckan, Resource
from etl.identity import FileRecord, fingerprints, version_checksum
from etl.settings import EtlConfig
from etl.sources import SourcesConfig, sync_registry


class RemoteUnchanged(Exception):
    """Raised by an importer when remote fingerprints equal the live version's."""


@dataclass
class Context:
    source_id: str
    dataset: str
    resources: dict[str, Resource]  # role -> resource (URLs from package_show)
    client: httpx.Client
    cfg: EtlConfig
    workdir: Path
    live_files: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    ckan: Ckan | None = None
    registry: SourcesConfig | None = None
    conn_factory: Callable[[], psycopg.Connection] | None = None
    options: dict = field(default_factory=dict)  # config/etl.yaml `options`
    processing: list[dict] = field(default_factory=list)  # recorded with the version
    source_last_modified: datetime | None = None  # set by importers without CKAN files

    def live_fingerprints(self) -> list[dict] | None:
        if not self.live_files:
            return None
        return fingerprints([_file_from_json(f) for f in self.live_files])


class Importer(Protocol):
    source_id: str

    def fetch(self, ctx: Context) -> list[FileRecord]: ...

    def version_date(self, ctx: Context, files: list[FileRecord]) -> date: ...

    def load(
        self, ctx: Context, conn: psycopg.Connection, version_id: int, files: list[FileRecord]
    ) -> dict: ...


@dataclass
class Outcome:
    source_id: str
    status: str  # succeeded | unchanged | failed
    version_id: int | None
    message: str = ""
    row_counts: dict = field(default_factory=dict)


def _file_from_json(d: dict) -> FileRecord:
    from etl.identity import MemberRecord

    d = dict(d)
    d["members"] = [MemberRecord(**m) for m in d.get("members", [])]
    return FileRecord(**d)


def _log(conn_factory: Callable[[], psycopg.Connection], sql: str, params) -> list:
    with conn_factory() as c:
        c.autocommit = True
        cur = c.execute(sql, params)
        return cur.fetchone() if cur.description else None


def run_import(
    importer: Importer,
    *,
    conn_factory: Callable[[], psycopg.Connection],
    client: httpx.Client,
    cfg: EtlConfig,
    registry: SourcesConfig,
    raw_root: Path,
) -> Outcome:
    sid = importer.source_id
    source = next((s for s in registry.sources if s.id == sid), None)
    if source is None or source.datagov is None:
        raise LookupError(f"{sid} is not a data.gov.lv source in config/sources.yaml")
    roles = cfg.files[sid]
    unlisted = set(roles.values()) - set(source.datagov.resource_ids)
    if unlisted:
        raise LookupError(f"{sid}: resources {unlisted} are not listed in config/sources.yaml")

    with conn_factory() as c:
        sync_registry(c, registry)  # FK target and current metadata
    log_id = _log(
        conn_factory,
        "INSERT INTO import_log (source_id, datagov_dataset_ids, datagov_resource_ids)"
        " VALUES (%s, %s, %s) RETURNING id",
        (sid, source.datagov.dataset_ids, list(roles.values())),
    )[0]
    workdir = raw_root / sid / f".incoming-{log_id}"
    ctx: Context | None = None
    try:
        ckan = Ckan(client, cfg.ckan_api)
        datasets = source.datagov.dataset_ids
        dataset = datasets[0]
        resources = {role: ckan.find_resource(datasets, rid) for role, rid in roles.items()}
        with conn_factory() as c:
            live = c.execute(
                "SELECT id, files FROM dataset_version WHERE source_id = %s AND status = 'live'",
                (sid,),
            ).fetchone()
        ctx = Context(
            sid,
            dataset,
            resources,
            client,
            cfg,
            workdir,
            live_files=live[1] if live else [],
            ckan=ckan,
            registry=registry,
            conn_factory=conn_factory,
            options=cfg.options.get(sid, {}),
        )
        urls = [r.url for r in resources.values()]
        licence = ckan.package(dataset).get("license_id")
        for ds in datasets:
            lic = ckan.package(ds).get("license_id")
            if source.licence and lic and lic != source.licence:
                ctx.notes.append(f"licence of {ds} is {lic}, registry says {source.licence}")
        _log(
            conn_factory,
            "UPDATE import_log SET resource_urls = %s, licence = %s,"
            " source_last_modified = %s WHERE id = %s",
            (
                urls,
                licence,
                max((r.last_modified for r in resources.values() if r.last_modified), default=None),
                log_id,
            ),
        )

        try:
            files = importer.fetch(ctx)
        except RemoteUnchanged:
            shutil.rmtree(workdir, ignore_errors=True)  # may hold full-zip downloads
            return _finish(
                conn_factory,
                log_id,
                sid,
                "unchanged",
                live[0],
                ctx,
                "remote fingerprints equal the live version; nothing fetched",
            )

        checksum = version_checksum(files)
        files_json = [f.to_json() for f in files]
        urls = urls or [f.url for f in files]
        last_modified = ctx.source_last_modified or max(
            (r.last_modified for r in resources.values() if r.last_modified), default=None
        )
        with conn_factory() as c:
            same = c.execute(
                "SELECT id, status FROM dataset_version WHERE source_id = %s AND checksum = %s",
                (sid, checksum),
            ).fetchone()
        if same and same[1] == "live":
            shutil.rmtree(workdir, ignore_errors=True)
            return _finish(
                conn_factory,
                log_id,
                sid,
                "unchanged",
                same[0],
                ctx,
                "same checksum as the live version",
                checksum=checksum,
                files=files_json,
            )

        vdate = importer.version_date(ctx, files)
        with conn_factory() as conn, conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (sid,))
            if same:  # an older version has exactly this data: make it live again
                vid = same[0]
                counts = {"reactivated_version": vid}
                ctx.notes.append(f"data equal to version {vid}; it is live again")
            else:
                vid = conn.execute(
                    "INSERT INTO dataset_version (source_id, datagov_dataset_ids,"
                    " datagov_resource_ids, resource_urls, licence, version_date,"
                    " source_last_modified, checksum, files)"
                    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (
                        sid,
                        source.datagov.dataset_ids,
                        list(roles.values()),
                        urls,
                        licence,
                        vdate,
                        last_modified,
                        checksum,
                        Jsonb(files_json),
                    ),
                ).fetchone()[0]
                counts = importer.load(ctx, conn, vid, files)
                total = sum(v.get("loaded", 0) for v in counts.values() if isinstance(v, dict))
                conn.execute(
                    "UPDATE dataset_version SET row_count = %s, processing = %s WHERE id = %s",
                    (total, Jsonb(ctx.processing), vid),
                )
            conn.execute(
                "UPDATE dataset_version SET status = 'superseded'"
                " WHERE source_id = %s AND status = 'live' AND id <> %s",
                (sid, vid),
            )
            conn.execute("UPDATE dataset_version SET status = 'live' WHERE id = %s", (vid,))

        _keep_raw(raw_root / sid, workdir, vid)
        return _finish(
            conn_factory,
            log_id,
            sid,
            "succeeded",
            vid,
            ctx,
            "",
            checksum=checksum,
            files=files_json,
            row_counts=counts,
        )
    except Exception as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        msg = f"{type(exc).__name__}: {exc}"
        detail = "".join(traceback.format_exception_only(exc)).strip()
        _finish(conn_factory, log_id, sid, "failed", None, ctx, detail)
        return Outcome(sid, "failed", None, msg)


def _finish(
    conn_factory,
    log_id,
    sid,
    status,
    version_id,
    ctx,
    message,
    *,
    checksum=None,
    files=None,
    row_counts=None,
) -> Outcome:
    notes = list(ctx.notes) if ctx else []
    if message:
        notes.insert(0, message)
    text = "; ".join(notes) or None
    _log(
        conn_factory,
        "UPDATE import_log SET status = %s, finished_at = now(), dataset_version_id = %s,"
        " checksum = coalesce(%s, checksum), files = coalesce(%s, files),"
        " row_counts = coalesce(%s, row_counts), message = %s WHERE id = %s",
        (
            status,
            version_id,
            checksum,
            Jsonb(files) if files is not None else None,
            Jsonb(row_counts) if row_counts is not None else None,
            text,
            log_id,
        ),
    )
    return Outcome(sid, status, version_id, text or "", row_counts or {})


def _keep_raw(source_dir: Path, workdir: Path, version_id: int) -> None:
    """Keep only the live version's raw files: <raw>/<source>/<version_id>/."""
    target = source_dir / str(version_id)
    if target.exists():
        shutil.rmtree(target)
    workdir.rename(target)
    for other in source_dir.iterdir():
        if other != target:
            shutil.rmtree(other, ignore_errors=True)
