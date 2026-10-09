# Runbook (Windows, local dev)

All commands are for **PowerShell**, run from the repo root (`C:\Users\PC\Downloads\Kadastrs`). The stack is local only (D3 interim): ports are bound to `127.0.0.1` and the credentials are dev-only defaults.

| Service | What | Address |
|---|---|---|
| `db` | PostgreSQL 18 + PostGIS 3.6 + LKS grid (`infra/db`) | `127.0.0.1:5432`, db/user `kadastrs`, password `kadastrs-dev` |
| `migrate` | dbmate, applies `infra/migrations`, then exits | — |
| `api` | FastAPI | `http://127.0.0.1:8000` (`/health`, `/docs`) |
| `tests` | pytest runner (profile `test`) | — |
| `db-nogrid` | same DB image **without** the grid, for negative CRS tests (profile `test`) | — |
| `migrate-test` | creates and migrates the `kadastrs_test` database used by the ETL tests (profile `test`) | — |
| `etl` | imports from data.gov.lv (profile `etl`); raw files of live versions in volume `kadastrs_etl_raw` | — |

## One-time setup

Install Docker Desktop, Git and **Python 3.14**. The Python version must match `.python-version`; a pre-commit hook checks it.

```powershell
py -3.14 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -c constraints.txt -e ".[dev]"
pre-commit install
```

The host venv is for the editor, ruff and pre-commit. **Tests run in a container** (see below). On this PC, Smart App Control blocks psycopg-binary's unsigned `pq` DLL, so psycopg cannot connect from the host Python. In the container it works, and CI uses the same container.

## Start

```powershell
docker compose up -d --build --wait
Invoke-RestMethod http://127.0.0.1:8000/health
```

`--wait` returns when `db` and `api` are healthy and `migrate` has finished. `/health` returns HTTP 200 with `"status": "ok"` and reports:
- the PostgreSQL, PostGIS and PROJ versions;
- `proj_ok` (PROJ ≥ 9.8);
- `srid_10306`;
- `lks_grid` (the EPSG:10838 grid transform works);
- the applied `migration`.

Any failed check gives HTTP 503 and the reason in `db.error`.

Status and logs:

```powershell
docker compose ps -a
docker compose logs -f api
docker compose logs migrate
```

## Stop

```powershell
docker compose --profile test --profile etl down
```

This keeps the data (volumes `kadastrs_dbdata` and `kadastrs_etl_raw`). `--profile test` also stops `db-nogrid`, which a plain `docker compose down` leaves running.

## Reset the DB (delete all data)

```powershell
docker compose --profile test --profile etl down -v
docker compose up -d --build --wait
```

`-v` deletes the `kadastrs_dbdata` and `kadastrs_etl_raw` volumes. On the next start, initdb enables the extensions and `migrate` recreates the schema from `infra/migrations`. Then import the data again (see "Import data").

## Load the source registry

`config/sources.yaml` is the source of truth; the loader copies it into the `source` and `allowed_external_resource` tables. The api container mounts `config/` read-only, so edits are picked up without rebuilding.

```powershell
docker compose exec api python -m etl.sources validate
docker compose exec api python -m etl.sources load
```

`load` is idempotent. An entry removed from the YAML is set `active = false`, never deleted, because dataset versions point to it.

## Import data (ETL)

All imports run in the `etl` container (CLAUDE.md rule 12), never with the host Python. Phase 2a sources, imported in this order by `all`:

| Source | What | Takes |
|---|---|---|
| `admin_boundaries` | VARIS `aw_shp.zip`: municipalities, cities, parishes (whole country) | ~30 s |
| `varis_addresses` | addresses of the pilot cities (`EKS` + `DEL`) and their earlier texts | ~1.5 min (340 MB download) |
| `cadastre_spatial` | cadastre map of the pilot cities: parcels, parts, buildings, engineering structures, servitudes | ~40 s |
| `cadastre_text` | cadastre text of the pilot cities: parcels, parts, buildings, building→parcel links, properties | ~3 min (pilot members only, by HTTP Range) |

```powershell
docker compose run --rm etl import all
docker compose run --rm etl import varis_addresses cadastre_text   # some sources only
docker compose run --rm etl status                                 # live version and last run per source
```

- The import also loads `config/sources.yaml` into the registry, so a separate `etl.sources load` is not needed.
- Each run writes one `import_log` row per source. New data creates a new `dataset_version`, which becomes `live` in the same transaction as its load; the previous version becomes `superseded`. If nothing changed, the run is `unchanged` and no version is created.
- **If a source changed its columns or XML elements, the import stops** (`failed`, with the reason in `import_log.message` and in the output), and the last good version stays live. Check the change, re-verify the source (`docs/data-sources.md`), update `config/schemas.yaml`, and import again.
- The exit code is 1 if any source failed.
- The ETL runs the checked-out code (mounted read-only), so code changes need no rebuild. Rebuild after dependency changes: `docker compose --profile etl build etl`.

Import history:

```powershell
docker compose exec db psql -U kadastrs -d kadastrs -c "SELECT id, source_id, status, started_at, message FROM import_log ORDER BY id DESC LIMIT 20"
```

## Run the tests

```powershell
docker compose --profile test run --rm tests
```

This builds the test image if needed, starts `db`, `migrate`, `api`, `db-nogrid` and `migrate-test`, and runs pytest with the repo mounted at `/src`. Code changes need no rebuild.

The ETL rule tests (`tests/etl`) import synthetic files through a fake data.gov.lv into the separate `kadastrs_test` database, so they never touch your data.

**The `pilot` tests check the real import in the dev database** (row counts against the source files, geometry, seed objects, and that a second run created no new versions). They **fail when nothing is imported**, so import twice first:

```powershell
docker compose run --rm etl import all
docker compose run --rm etl import all
docker compose --profile test run --rm tests
```

Without real data, run everything else:

```powershell
docker compose --profile test run --rm tests python -m pytest -p no:cacheprovider -m "not pilot"
``` A subset or extra pytest options:

```powershell
docker compose --profile test run --rm tests python -m pytest -p no:cacheprovider tests/test_crs.py -v
```

After changing **dependencies** (`pyproject.toml`, `constraints.txt`) or a **Dockerfile**, rebuild:

```powershell
docker compose --profile test --profile etl build
docker compose up -d --build --wait
```

Tests marked `stack` fail, and never skip, when the stack is down. A skipped CRS test would hide a missing grid.

Lint and format (also run on every commit by pre-commit):

```powershell
pre-commit run --all-files
```

CI (`.github/workflows/ci.yml`) runs pre-commit and the tests without `pilot` on every push and pull request. `.github/workflows/pilot-import.yml` does the real import twice and runs the full suite, every Monday and on demand (Actions → Pilot import → Run workflow).

## Migrations

Migrations are plain SQL files in `infra/migrations`, named `YYYYMMDDHHMMSS_description.sql`, each with `-- migrate:up` and `-- migrate:down` sections. Never edit a migration that has already been applied; add a new one.

```powershell
docker compose run --rm migrate status
docker compose run --rm migrate up
docker compose run --rm migrate rollback   # undoes the latest migration
```

## Database shell

```powershell
docker compose exec db psql -U kadastrs -d kadastrs
```

For a GUI client (QGIS, DBeaver), use `127.0.0.1:5432`, database and user `kadastrs`, password `kadastrs-dev`.

## Settings and overrides

Without a `.env`, the stack uses the dev-only defaults in `infra/docker-compose.yml`. To change a port or the password, copy `.env.example` to `.env` (git-ignored) and edit it, or set the variables in the shell (see Troubleshooting). The values in `.env.example` are for local development only.

## Troubleshooting

- **Port already in use:** choose other host ports for this shell, then start again:
  ```powershell
  $env:KADASTRS_DB_PORT = '5433'
  $env:KADASTRS_API_PORT = '8001'
  ```
  The tests talk to the services inside the compose network, so these ports do not affect them.
- **`/health` 503 with `lks_grid: false`:** the grid is missing from the DB image. Rebuild with `docker compose build --no-cache db`. The build itself fails if the grid checksum is wrong. See `infra/db/README.md`.
- **`/health` 503 with `migration: null`:** check `docker compose logs migrate`.
- **Replacing the grid file or updating the base image:** see `infra/db/README.md` and the comment at the top of `infra/db/Dockerfile`, then run the tests.
