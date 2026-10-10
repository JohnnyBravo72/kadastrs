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

Install Docker Desktop, Git and **Python 3.14** (for the editor). `.python-version` names the Python minor of the api/tests images; a pre-commit hook checks that they match.

```powershell
py -3.14 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -c constraints.txt -e ".[dev]"
git config core.hooksPath scripts/git-hooks
```

**Pre-commit hooks run in Linux, in the `lint` container**, never on the host: Smart App Control blocks unsigned executables such as `pre-commit.exe` and `ruff.exe` (2026-10-10). `git config core.hooksPath scripts/git-hooks` makes every `git commit` run `scripts/git-hooks/pre-commit`, which starts `docker compose --profile lint run --rm lint pre-commit run`. **Docker Desktop must be running to commit**; otherwise the hook stops with "start Docker Desktop, then commit again". Never bypass it with `--no-verify`. The hook environments are cached in the `kadastrs_precommit_cache` volume, so only the first commit is slow.

The host venv is for the editor only. **Tests run in a container** (see below). On this PC, Smart App Control blocks psycopg-binary's unsigned `pq` DLL, so psycopg cannot connect from the host Python. In the container it works, and CI uses the same container.

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

All imports run in the `etl` container (CLAUDE.md rule 12), never with the host Python. Sources, imported in this order by `all`:

| Source | What | Takes |
|---|---|---|
| `admin_boundaries` | VARIS `aw_shp.zip`: municipalities, cities, parishes (whole country) | ~10–30 s |
| `varis_addresses` | addresses of the pilot cities (`EKS` + `DEL`) and their earlier texts | ~1.5 min (340 MB download) |
| `cadastre_spatial` | cadastre map of the pilot cities: parcels, parts, buildings, engineering structures, servitudes | ~40 s |
| `cadastre_text` | cadastre text of the pilot cities: parcels, parts, buildings, building→parcel links, properties | ~3 min (pilot members only, by HTTP Range) |
| `flood_10y` | LVĢMC 10-year spring flood (layers 0, 1) and the 200-year coverage mask (layer 3), pilot extent + 1 km; needs `admin_boundaries` | 20–40 min (fetch ~2 min; repairing the largest polygons takes the rest); an unchanged rerun ~2 min |
| `nature_protected_areas` | DAP protected areas and their zoning (whole country) | ~20 s |
| `nature_microreserves` | DAP microreserves and buffer zones (whole country) | ~15 s |
| `nature_monuments` | DAP nature monuments (whole country) | ~1.5 min |
| `nature_habitats` | DAP protected habitats, 175,000 polygons (whole country) | ~9 min |
| `atis_classifier` | ATIS and cadastre encumbrance classifier (432 codes) | ~2 s |
| `cadastre_encumbrances` | encumbrances registered on pilot parcels, parcel parts and buildings (code, text, area, date; no geometry) | ~1 min (pilot members only, by HTTP Range) |
| `encumbrances_frozen` | the frozen list of encumbrances registered until 2025-01-31, pilot rows, flagged `frozen` (`docs/data-sources.md` §7.3) | ~1 min (175 MB download; never changes) |
| `bis_cases` | BIS construction cases and case objects of the pilot cities (raw CSVs, never the DataStore) | ~1 min (145 MB download) |

```powershell
docker compose run --rm etl import all
docker compose run --rm etl import varis_addresses cadastre_text   # some sources only
docker compose run --rm etl status                                 # live version and last run per source
```

- The import also loads `config/sources.yaml` into the registry, so a separate `etl.sources load` is not needed.
- Each run writes one `import_log` row per source. New data creates a new `dataset_version`, which becomes `live` in the same transaction as its load; the previous version becomes `superseded`. If nothing changed, the run is `unchanged` and no version is created.
- **If a source changed its columns or XML elements, the import stops** (`failed`, with the reason in `import_log.message` and in the output), and the last good version stays live. Check the change, re-verify the source (`docs/data-sources.md`), update `config/schemas.yaml`, and import again.
- The exit code is 1 if any source failed.
- **Flood (`flood_10y`)** asks the LVĢMC MapServer (D1 E7) for the features in each pilot city's extent + 1 km, 25 at a time, with 1 cm simplification; it prints its progress. A batch that fails is retried and then fetched one object at a time. Layer 3 (200-year extent) is stored only as the coverage mask (`ref.flood_coverage_current`), never as a finding.
- Geometry repair uses PostGIS `ST_MakeValid(method=structure)`; the largest flood polygons (over a million vertices) take a few minutes each (`docs/data-sources.md` §6.3).
- **BIS (`bis_cases`)** downloads the national case list and case objects and keeps only the pilot: objects whose ATVK is a pilot city or whose designation starts with the city's cadastral territory code (`pilot_cadastral_territory` in `config/etl.yaml`), and their cases. A new version is created only when the pilot rows change. Links to the cadastre are not stored: `ref.bis_object_link_current` computes them from the live BIS and cadastre text versions (`ref.bis_links(bis_version, cadastre_text_version)` for any past pair). Report:
  ```powershell
  docker compose run --rm etl bis-links
  ```
  prints how many pilot case objects match exactly (building in the cadastre), probably (designation prefix = a parcel), only by address code, or not at all.
- **Encumbrances:** `ref.encumbrance_current` (current list joined with the classifier text) and `ref.encumbrance_frozen_current` (frozen list with `in_current`, `object_in_cadastre`, `frozen_only`). Frozen-only rows are never shown as current encumbrances.
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

The pilot tests take about 3 minutes. The BIS and encumbrance checks (`tests/pilot/test_pilot_bis_encumbrances.py`) recount rows from the raw files, compare every stored designation and ATVK with the raw file (no lost leading zero), check the BIS join counts and that the DAP `ATIS_CODE` values are classifier codes. The four giant flood polygons (over a million vertices) are not validated again there: the import validates every stored geometry and records the count in the version's processing notes, which the test checks (re-validating them takes over an hour).

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

Lint and format (the git hook runs the same on the staged files of every commit):

```powershell
docker compose --profile lint run --rm lint pre-commit run --all-files
```

After changing `.pre-commit-config.yaml` dependencies or the Dockerfile, rebuild with `docker compose --profile lint build lint`.

**CI runners are pinned to `ubuntu-24.04`** in both workflows (`ubuntu-latest` moves to Ubuntu 26 on 2026-10-19). Upgrade deliberately: change `runs-on` in both files on a branch, run CI and Actions → Pilot import → Run workflow on that branch, and merge only when both are green.

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
