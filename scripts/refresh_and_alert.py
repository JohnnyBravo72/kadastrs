#!/usr/bin/env python3
"""Thin wrapper: prefer ``docker compose run --rm etl refresh`` (Phase 10)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from etl.__main__ import cmd_refresh  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(cmd_refresh(sys.argv[1:] or ["all"]))
