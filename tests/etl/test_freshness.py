"""Freshness against the source (etl/freshness.py; docs/decisions.md "Freshness"):
current, newer release available, publisher silent too long, offline (last good
check, or unknown), and the package_show look itself."""

from datetime import UTC, datetime

import httpx
import pytest

from etl import freshness
from etl.freshness import Remote
from etl.sources import load_config, sync_registry
from tests.etl.fakes import API

pytestmark = pytest.mark.stack

AT = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


def live(c, source: str, vid: int, imported_from: datetime, status: str = "succeeded") -> None:
    """A live version and the import that gave it, from a release dated `imported_from`."""
    c.execute(
        "INSERT INTO dataset_version (id, source_id, version_date, source_last_modified,"
        " checksum, status) OVERRIDING SYSTEM VALUE VALUES (%s, %s, %s, %s, %s, 'live')",
        (vid, source, imported_from.date(), imported_from, "sha256:" + f"{vid:064x}"),
    )
    log(c, source, vid, imported_from, status)


def log(c, source, vid, seen: datetime, status="unchanged") -> None:
    c.execute(
        "INSERT INTO import_log (source_id, dataset_version_id, status, finished_at,"
        " source_last_modified) VALUES (%s, %s, %s, now(), %s)",
        (source, vid, status, seen),
    )


@pytest.fixture
def db(etl_db):
    with etl_db() as c:
        sync_registry(c, load_config())
        live(c, "cadastre_text", 1, utc(2026, 9, 28, 18, 59))
        live(c, "bis_cases", 2, utc(2026, 10, 1, 6, 0))
        live(c, "encumbrances_frozen", 3, utc(2025, 2, 10))
        live(c, "flood_10y", 4, utc(2026, 8, 19, 6, 57))
        c.commit()
    return etl_db


def test_latest_release_held_is_current(db):
    with db() as c:
        f = freshness.assess(c, {"cadastre_text": Remote(True, utc(2026, 9, 28, 18, 59))}, AT)
    ct = f["cadastre_text"]
    assert (ct["status"], ct["label_lv"], ct["warn"]) == ("current", "aktuāli", False)
    assert ct["text_lv"] == "jaunākie pieejamie dati (avots atjaunots 2026-09-28)"
    assert ct["source_updated"] == "2026-09-28" and ct["source_stale_after"] == "60 days"


def test_newer_release_not_imported_is_stale(db):
    with db() as c:
        f = freshness.assess(c, {"bis_cases": Remote(True, utc(2026, 10, 10, 5, 0))}, AT)
    b = f["bis_cases"]
    assert (b["status"], b["label_lv"], b["warn"]) == ("newer_available", "novecojuši", True)
    assert b["text_lv"].startswith("novecojuši – pieejama jaunāka versija")


def test_unchanged_import_of_a_republished_file_counts_as_held(db):
    """VZD re-uploads the same content: the import says unchanged, and the newer
    CKAN date it saw is ours too."""
    with db() as c:
        log(c, "bis_cases", 2, utc(2026, 10, 10, 5, 0))
        f = freshness.assess(c, {"bis_cases": Remote(True, utc(2026, 10, 10, 5, 0))}, AT)
    assert f["bis_cases"]["status"] == "current"


def test_publisher_silent_longer_than_source_stale_after(db):
    with db() as c:
        f = freshness.assess(
            c, {"cadastre_text": Remote(True, utc(2026, 9, 28, 18, 59))}, utc(2026, 12, 1)
        )
    ct = f["cadastre_text"]
    assert (ct["status"], ct["label_lv"], ct["warn"]) == (
        "source_stale",
        "avots nav atjaunots",
        True,
    )
    assert ct["text_lv"] == "avots nav atjaunots kopš 2026-09-28"


def test_frozen_list_is_never_source_stale(db):
    with db() as c:
        f = freshness.assess(c, {"encumbrances_frozen": Remote(True, utc(2025, 2, 10))}, AT)
    assert f["encumbrances_frozen"]["status"] == "current"
    assert f["encumbrances_frozen"]["source_stale_after"] is None


def test_offline_uses_the_last_good_check(db):
    with db() as c:
        freshness.record(c, {"bis_cases": Remote(True, utc(2026, 10, 9))}, "status")
        c.execute("UPDATE source_check SET checked_at = %s", (utc(2026, 10, 9, 8, 0),))
        offline = {"bis_cases": Remote(False, error="data.gov.lv nav sasniedzams")}
        f = freshness.assess(c, offline, AT)
        freshness.record(c, offline, "run")
        rows = c.execute("SELECT origin, ok, error FROM source_check ORDER BY id").fetchall()
    b = f["bis_cases"]
    assert b["status"] == "newer_available" and b["checked_live"] is False
    assert b["text_lv"].endswith("; pēdējā pārbaude 2026-10-09")
    assert rows == [("status", True, None), ("run", False, "data.gov.lv nav sasniedzams")]


def test_offline_and_never_checked_is_unknown(db):
    with db() as c:
        f = freshness.assess(c, {}, AT)
    ct = f["cadastre_text"]
    assert (ct["status"], ct["label_lv"], ct["warn"]) == ("unknown", "nezināms", True)
    assert "nav sasniedzams" in ct["text_lv"]


def test_fetch_remote_reads_package_show(server):
    server.publish("cadastre_text", "parcel", "parcel.zip", b"x", "2026-09-28T18:58:57")
    server.publish("cadastre_text", "building", "building.zip", b"x", "2026-09-28T18:59:26")
    server.publish("cadastre_text", "parcelpart", "parcelpart.zip", b"x", "2026-09-28T18:59:10")
    server.publish("cadastre_text", "property", "property.zip", b"x", "2026-09-28T18:58:26")
    server.metadata_modified["3-cikla-latvijas-pldu-postjumu-vietu-un-pldu-riska-kartes1"] = (
        "2026-08-19T06:57:02"
    )
    with server.client() as client:
        remotes = freshness.fetch_remote(client, api=API)
    assert remotes["cadastre_text"] == Remote(True, utc(2026, 9, 28, 18, 59, 26))  # newest file
    assert remotes["flood_10y"] == Remote(True, utc(2026, 8, 19, 6, 57, 2))  # no CKAN files
    assert remotes["bis_cases"].ok is False  # not published on the fake: recorded, not raised


def test_fetch_remote_offline_and_switched_off(monkeypatch):
    def down(request):
        raise httpx.ConnectError("no route", request=request)

    with httpx.Client(transport=httpx.MockTransport(down)) as client:
        remotes = freshness.fetch_remote(client, api=API)
    assert all(not r.ok and "nav sasniedzams" in r.error for r in remotes.values())
    monkeypatch.setenv(freshness.ENV_SWITCH, "off")
    assert all(not r.ok for r in freshness.fetch_remote().values())


def test_import_is_recorded_as_a_look_at_the_source(run, server, q):
    """Every finished import (new or unchanged) records the release it saw, so
    an offline run still has a recent "last good check"."""
    from tests.etl import fakes

    server.publish(
        "admin_boundaries", "aw_shp", "aw_shp.zip", fakes.admin_zip(), "2026-10-10T05:00:00"
    )
    assert run("admin_boundaries").status == "succeeded"
    assert run("admin_boundaries").status == "unchanged"
    rows = q("SELECT origin, ok, remote_last_modified FROM source_check ORDER BY id")
    assert rows == [("import", True, utc(2026, 10, 10, 5, 0))] * 2
