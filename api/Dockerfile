# API image (target `runtime`) and test runner (target `test`).
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
    && useradd --system --no-create-home app

# Test runner: dev dependencies; the repo is bind-mounted at /src and run from
# there (cwd comes first on sys.path, so the mounted code is what gets tested).
FROM base AS test
RUN pip install -c constraints.txt ".[dev]"
WORKDIR /src
CMD ["python", "-m", "pytest", "-p", "no:cacheprovider"]

FROM base AS runtime
ENV KADASTRS_CONFIG_DIR=/app/config
COPY config/ config/
USER app
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
