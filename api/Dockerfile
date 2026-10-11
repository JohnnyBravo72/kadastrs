# API image (target `runtime`), ETL runner (`etl`), check CLI (`check`) and test runner (`test`).
# The results view (web/, Vite + React) is built in the `web` stage: Node runs only
# in this container, never on the host (CLAUDE.md rule 12).
# Build context is the repo root (see infra/docker-compose.yml).
# Python minor must match .python-version (host venv and CI); tests check it.
FROM node:22.11.0-bookworm-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
# --ignore-scripts: no install scripts from dependencies run in the build
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY web/ ./
RUN npm test && npm run build

FROM python:3.14-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml constraints.txt ./
COPY api/ api/
COPY etl/ etl/
COPY engine/ engine/
COPY reports/ reports/
RUN pip install -c constraints.txt . \
    && useradd --system --no-create-home app \
    && mkdir -p /data/raw && chown app /data/raw

# /data/raw: mount point of the etl_raw volume (owned by app, so the ETL can write).

# Test runner: dev dependencies; the repo is bind-mounted at /src and run from
# there (cwd comes first on sys.path, so the mounted code is what gets tested).
FROM base AS test
RUN pip install -c constraints.txt ".[dev]"
COPY --from=web /web/dist /app/web/dist
ENV KADASTRS_WEB_DIST=/app/web/dist
WORKDIR /src
CMD ["python", "-m", "pytest", "-p", "no:cacheprovider"]

# Lint runner: pre-commit hooks in Linux (git hook scripts/git-hooks/pre-commit).
FROM test AS lint
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && git config --system --add safe.directory /src
CMD ["pre-commit", "run", "--all-files"]

# ETL runner: runs the mounted checkout (/src, read-only), CLAUDE.md rule 12.
FROM base AS etl
WORKDIR /src
USER app
ENTRYPOINT ["python", "-m", "etl"]

# Check engine CLI: runs the mounted checkout (/src), CLAUDE.md rule 12.
FROM base AS check
WORKDIR /src
USER app
ENTRYPOINT ["python", "-m", "engine.checks"]

FROM base AS runtime
ENV KADASTRS_CONFIG_DIR=/app/config     KADASTRS_WEB_DIST=/app/web/dist
COPY --from=web /web/dist /app/web/dist
COPY config/ config/
USER app
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
