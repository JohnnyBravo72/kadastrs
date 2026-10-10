# API image (target `runtime`), ETL runner (target `etl`) and test runner (target `test`).
# Build context is the repo root (see infra/docker-compose.yml).
# Python minor must match .python-version (host venv and CI); tests check it.
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
RUN pip install -c constraints.txt . \
    && useradd --system --no-create-home app \
    && mkdir -p /data/raw && chown app /data/raw

# /data/raw: mount point of the etl_raw volume (owned by app, so the ETL can write).

# Test runner: dev dependencies; the repo is bind-mounted at /src and run from
# there (cwd comes first on sys.path, so the mounted code is what gets tested).
FROM base AS test
RUN pip install -c constraints.txt ".[dev]"
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

FROM base AS runtime
ENV KADASTRS_CONFIG_DIR=/app/config
COPY config/ config/
USER app
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
