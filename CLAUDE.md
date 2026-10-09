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
Not set up yet. Added in Phase 1 (`docker compose up` → empty DB + API health check).

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
