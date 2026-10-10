"""pre-commit hook: .python-version matches the Python of the api/tests images.

Runs inside the `lint` container, which is built from the same api/Dockerfile
base stage (python:<minor>-slim) as the api and tests images, so its Python is
theirs. Also checks that api/Dockerfile names that minor.
"""

import re
import sys
from pathlib import Path

pinned = Path(".python-version").read_text(encoding="utf-8").strip()
running = f"{sys.version_info.major}.{sys.version_info.minor}"
dockerfile = Path("api/Dockerfile").read_text(encoding="utf-8")
match = re.search(r"^FROM python:(\d+\.\d+)", dockerfile, re.MULTILINE)
base = match.group(1) if match else "?"

errors = []
if running != pinned:
    errors.append(f"image Python {running} != .python-version {pinned}")
if base != pinned:
    errors.append(f"api/Dockerfile base python:{base} != .python-version {pinned}")
sys.exit("; ".join(errors) if errors else 0)
