"""Pilot test fixtures (real data in the dev DB)."""

import pytest

from tests.pilot.support import live_versions


@pytest.fixture
def live(db_conn):
    """Live version id per pilot source; fails (never skips) when one is missing."""
    return live_versions(db_conn)
