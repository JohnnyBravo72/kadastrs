# Kadastra pārbaude

A tool for CFLA project evaluators: takes a list of kadastra numuri, apzīmējumi or addresses and checks each object against open data.
Output: an Excel report per object (MVP), later an interactive map and dashboard. Full plan: [PLAN.md](PLAN.md).

## Stack
- **DB:** PostgreSQL 16 + PostGIS, `pg_trgm`, `unaccent`
- **ETL and check engine:** Python (geopandas / ogr2ogr / psycopg), CLI commands, scheduled imports
- **API:** FastAPI + Pydantic
- **Reports:** `openpyxl` (Excel); PDF later via Playwright
- **Frontend:** Vite + React + TypeScript + Leaflet
- **Dev:** Docker Compose (db, api, web)

## CRS
- Store and analyse in **LKS-92 / EPSG:3059** (areas and overlaps in metres).
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
1. **All data comes only from data.gov.lv** (PLAN.md §2.1). No scraping, no commercial services (e.g. Lursoft), no login-protected portals. A missing dataset means the module is not built and shows as *unavailable*; the only alternative is a named exception approved in writing and recorded in `docs/decisions.md`.
2. **Verify data endpoints before coding against them.** Never guess URLs, dataset ids, resource ids or field names. Confirm them via the data.gov.lv CKAN API or a downloaded sample, and record them in `docs/data-sources.md` first.
3. **Check results are never changed after they are stored.** `check_result` rows are never updated; re-checking creates a new run.
4. **Risk levels come only from `config/rules.yaml`.** No risk logic hard-coded elsewhere, and no AI/LLM decides risk.
5. **No personal data.** Never store or display names of owners or board members. Ownership is limited to owner type and is DPO-gated.
6. **Work phase by phase** following PLAN.md §9. Before starting each phase, propose a short plan and wait for approval.
