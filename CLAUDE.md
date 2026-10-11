# Kadastra pārbaude

A tool for CFLA project evaluators: takes a list of kadastra numuri, apzīmējumi or addresses and checks each object against open data.
Output: an Excel report per object (MVP), later an interactive map and dashboard. Full plan: [PLAN.md](PLAN.md).

## Stack
- **DB:** PostgreSQL 18 + PostGIS 3.6 (`postgis/postgis:18-3.6`, PROJ ≥ 9.8, which is needed for EPSG:10306; see D9), `pg_trgm`, `unaccent`
- **ETL and check engine:** Python (geopandas / ogr2ogr / psycopg), CLI commands, scheduled imports
- **API:** FastAPI + Pydantic
- **Reports:** `openpyxl` (Excel); PDF later via Playwright
- **Frontend:** Vite + React + TypeScript + Leaflet
- **Dev:** Docker Compose (db, api, web)

## CRS
- Store and analyse in **LKS-2020 / Latvia TM, EPSG:10306** (decision D9 in `docs/decisions.md`). VZD cadastre and VARIS data are already in it.
- Sources still in LKS-92 / EPSG:3059 (DAP nature, TAPIS, LVĢMC flood) are transformed to EPSG:10306 **on import** with EPSG:10838 (NTv2 grid `lv_lgia_lks92to2020.tif`, which must be present in the PROJ data directory). Never mix the two CRSs in one table, and never call 3059 and 10306 "the same".
- Serve GeoJSON to the frontend in EPSG:4326.

## Folder layout
```
/docs        data-sources.md, decisions.md, runbook.md
/etl         download, schema checks, import
/engine      check modules, spatial rules, risk rules, batch runner
/reports     Excel (later PDF) builders
/api         FastAPI app + tests
/web         Vite React TS app
/config      sources.yaml, rules.yaml, layers.yaml
/infra       docker-compose.yml, SQL migrations
/tests/data  the 14–20 test projects with expected results
```

## Run and test
Full details in [docs/runbook.md](docs/runbook.md). From the repo root (PowerShell):
- **Start:** `docker compose up -d --build --wait`, then check `http://127.0.0.1:8000/health`.
- **Stop:** `docker compose --profile test --profile etl down`. **Reset the DB:** add `-v`.
- **Import data:** `docker compose run --rm etl import all` (or source ids), `docker compose run --rm etl status`.
- **Checks:** `POST /api/runs` or `docker compose run --rm check run|show|replay|compare …` (engine in `engine/checks`). A run pins dataset versions; `replay <run_id>` must reproduce it. Compare returned test-set files with `check compare <file.xlsx>`.
- **Batch + Excel:** `POST /api/batch`, `check batch <file|->`, or the page at `http://127.0.0.1:8000/`; report of a stored run: `GET /api/runs/{id}/report.xlsx` or `check report <id> [--replay]` (`reports/excel.py`, built only from stored results).
- **Tests:** `docker compose --profile test run --rm tests`. Tests run in a container because Smart App Control blocks psycopg's DLL on the host; CI does the same. The `pilot` tests need a real import (twice) in the dev DB; without it use `-m "not pilot"`.
- **Lint:** `docker compose --profile lint run --rm lint pre-commit run --all-files` (the git hook runs the same container on every commit).
- **Load the source registry:** `docker compose exec api python -m etl.sources load`.
- **Migrations:** plain SQL in `infra/migrations` (dbmate), applied by the `migrate` service on start.
- **LKS-92 → LKS-2020 in imports:** use the SQL function `lks92_to_lks2020(geom)`, not a bare `ST_Transform`. The function forces the EPSG:10838 grid and errors if the grid is missing, while `ST_Transform` silently falls back about 9.5 cm off.
- **One Python minor** (`.python-version`, 3.14) for the host venv, the api image and CI.

## Rules
1. **All data comes only from data.gov.lv** (PLAN.md §2.1). No scraping, no commercial services (e.g. Lursoft), no login-protected portals. Under D1, an official agency resource referenced from a data.gov.lv dataset page is allowed only if it is listed by name in `docs/decisions.md` (D1) **and** in `config/sources.yaml` (`allowed_external_resources`, `status: allowed`). We work **only on open data and need no external permissions or approvals**. A missing or non-open dataset means the module is not built and shows as *unavailable*.
2. **Verify data endpoints before coding against them.** Never guess URLs, dataset ids, resource ids or field names. Confirm them via the data.gov.lv CKAN API or a downloaded sample, and record them in `docs/data-sources.md` first.
3. **Check results are never changed after they are stored.** `check_result` rows are never updated; re-checking creates a new run.
4. **Risk levels come only from `config/rules.yaml`.** No risk logic hard-coded elsewhere, and no AI/LLM decides risk.
5. **Open-data fields only, no personal data** (policy in `docs/decisions.md`):
   - modules use only fields published as open data;
   - ownership = owner **type** only;
   - sanctions = **legal entities by reg. no.** only;
   - **no names of natural persons are stored** (nor personal codes or birth dates), including owners and board members.
6. **Work phase by phase** following PLAN.md §9. Before starting each phase, propose a short plan and wait for approval.
7. **Import from the raw resource files** (CSV, XML, SHP, service responses), **never from CKAN DataStore tables** (`datastore_search`). DataStore copies retype columns (leading zeros lost) and can be truncated. DataStore queries are fine for discovery only.
8. **Designations and codes are always text:** kadastra numuri and apzīmējumi, VARIS codes, reg. numbers, ATVK codes, project numbers. Never parse them as numbers in pandas, SQL or Excel; read them with an explicit string dtype.
9. **Never disable TLS verification** (`verify=False`, `CURL_SSL_NO_VERIFY`, unverified contexts). Fix certificate errors with `truststore` (OS certificate store) or a proper CA bundle that includes the missing intermediate certificate.
10. **Objects without geometry are never "clear" because of it** (PLAN.md §6.3). An object found in the register but without geometry gets the warning `no_geometry`. If it is a building whose parcel has geometry, spatial modules run on the parcel geometry with warning "pārbaudīts pēc zemes vienības". Only if the parcel has no geometry either do they return status `no_data` with reason "nav ģeometrijas".
11. **Address status** (PLAN.md §5.1): match VARIS `EKS` first; a `DEL`-only match is returned with warning "vēsturiska adrese" and the linked current address if `KODS_HIS` gives one. **Never match `ERR`.** Buildings marked non-existing stay resolvable with warning "reģistrā atzīmēta kā neeksistējoša", but are left out of "buildings on parcel" lists unless asked.
12. **Python that imports native libraries runs in containers, never on the Windows host.** This covers psycopg, GDAL, shapely, pyogrio, geopandas and anything else that loads compiled extensions. Smart App Control on the dev PC blocks unsigned DLLs, and it is not to be turned off. ETL and engine commands each get a compose service, built from the api image like the `tests` service, and run with `docker compose run --rm <service> …`. **The pre-commit hooks also run in a container** (`lint` service): the git hook `scripts/git-hooks/pre-commit` (activate with `git config core.hooksPath scripts/git-hooks`) starts it, because Smart App Control also blocks unsigned executables such as `pre-commit.exe` and `ruff.exe` (2026-10-10). Docker must be running to commit; if it is not, the hook fails with "start Docker Desktop" and is never skipped (no `--no-verify`). The host venv is only for the editor.
