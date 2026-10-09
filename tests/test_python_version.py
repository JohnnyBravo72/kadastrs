"""Host venv, api image and CI use one Python minor, set in .python-version.

The host venv itself is checked by the `host-python-version` pre-commit hook,
because the suite runs in the tests container (docs/runbook.md).
"""

import platform
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _pinned() -> str:
    return (ROOT / ".python-version").read_text(encoding="utf-8").strip()


def test_runner_python_matches_python_version_file():
    runner = ".".join(platform.python_version_tuple()[:2])
    assert runner == _pinned(), f"tests run on Python {runner}, .python-version says {_pinned()}"


def test_api_image_uses_pinned_python():
    dockerfile = (ROOT / "api" / "Dockerfile").read_text(encoding="utf-8")
    m = re.search(r"^FROM python:(\d+\.\d+)[-.@\w]*", dockerfile, re.MULTILINE)
    assert m, "api/Dockerfile must start FROM python:<major.minor>-..."
    assert m.group(1) == _pinned()
