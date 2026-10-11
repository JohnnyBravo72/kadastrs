"""Freshness in a run and its report: a newer release on data.gov.lv gives a
stale_data warning and "novecojuši" on Avoti; the run keeps that verdict, so its
report and its replay's report stay equal."""

from datetime import UTC, datetime

import pytest

from engine.batch.plan import run_batch
from engine.batch.reader import read_text
from engine.checks import runner
from etl import freshness
from reports import excel
from tests.batch.test_report import open_report, values
from tests.checks.conftest import V, all_current

pytestmark = pytest.mark.stack

OURS = datetime(2026, 9, 28, 18, 59, tzinfo=UTC)


@pytest.fixture(scope="module")
def run(batch_db):
    with batch_db() as c:
        c.execute(
            "UPDATE dataset_version SET source_last_modified = %s WHERE id = %s",
            (OURS, V["cadastre_text"]),
        )
    mp = pytest.MonkeyPatch()
    remotes = all_current() | {
        "cadastre_text": freshness.Remote(True, datetime(2026, 10, 9, tzinfo=UTC))
    }
    mp.setattr(freshness, "fetch_remote", lambda *a, **k: remotes)
    with batch_db() as c:
        rid = run_batch(c, read_text("09000050400", 1000))
    mp.undo()
    return rid


def test_newer_release_warns_and_shows_on_avoti(batch_db, run):
    with batch_db() as c:
        info = dict(
            c.execute(
                "SELECT source_id, source FROM work.run_version WHERE run_id = %s", (run,)
            ).fetchall()
        )
        rows = runner.stored(c, run)
        wb = open_report(excel.load(c, run))
    assert info["cadastre_text"]["freshness"]["status"] == "newer_available"
    assert info["bis_cases"]["freshness"]["status"] == "current"
    facts = next(r.result for r in rows if r.result.module == "cadastre_facts")
    stale = [w.message for w in facts.warnings if w.code == "stale_data"]
    assert stale == [
        "Kadastra teksta dati: novecojuši – pieejama jaunāka versija (avots atjaunots 2026-10-09)"
    ]
    ws = wb["Avoti"]
    by_id = {ws.cell(r, 2).value: [c.value for c in ws[r]] for r in range(2, ws.max_row + 1)}
    assert by_id["cadastre_text"][4:8] == [
        "novecojuši",
        "novecojuši – pieejama jaunāka versija (avots atjaunots 2026-10-09)",
        "2026-10-09",
        "60 d.",
    ]
    assert by_id["bis_cases"][4] == "aktuāli"
    assert by_id["encumbrances_frozen"][7] == "netiek pārbaudīts"


def test_report_keeps_the_runs_verdict_after_the_source_changes(batch_db, run):
    """A later look (now current) changes nothing in the stored run's report."""
    with batch_db() as c:
        before = values(open_report(excel.load(c, run)))
        freshness.record(c, all_current(), "status")
        replayed = values(open_report(excel.load(c, run, rows=runner.replay(c, run))))
    assert before == replayed
