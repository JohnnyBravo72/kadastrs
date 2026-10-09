# Decisions

Decisions from PLAN.md §10. When a decision is settled, fill in the outcome, the date and who decided.

| # | Decision | Needed by | Status | Outcome | Decided by / date |
|---|---|---|---|---|---|
| D1 | Agency-hosted resources listed on data.gov.lv count as data.gov.lv? | Phase 0 | **decided** | Yes, see [D1](#d1-agency-hosted-resources) | Janis, 2026-10-09 |
| D2 | Basemap: OSM or plain | Phase 6 | open | | |
| D3 | Hosting, sign-in, security review, retention, maintenance, legal status (PLAN.md §1) | **Phase 10** | open (**interim answers in force**) | Interim (2026-10-09): local Docker on Janis's PC for Phases 1–9; no sign-in, local only (sign-in required before any shared hosting); security review before shared hosting; keep all runs; maintenance Janis; footer "Informatīvs pārskats, balstīts uz atvērtajiem datiem; nav oficiāls reģistra izraksts". Revisit in Phase 10 | Janis, 2026-10-09 (interim) |
| D4 | Risk rules v1, agreed with the team leads | Phase 4 | open | | |
| D5 | Ownership module | Phase 8 | **decided** | Built, with owner **type** only (`PersonStatus`); no names. See [Policy](#policy-open-data-only) | Janis, 2026-10-09 |
| D6 | Sanctions module | Phase 8 | **decided** | Built for **legal entities by reg. no. only** (UR `sanctions`); natural-person fields never imported. See [Policy](#policy-open-data-only) | Janis, 2026-10-09 |
| D7 | Contents of Avoti and Žurnāls | Phase 6 | open | | |
| D8 | Project number format (free text for now) | Phase 7 | open | | |
| D9 | Storage and analysis CRS | Phase 1 | **decided** | EPSG:10306 (LKS-2020 / Latvia TM), see [D9](#d9-storage-and-analysis-crs) | Janis, 2026-10-09 |

## Policy: open data only

**Decided 2026-10-09 (Janis).** The project uses only open data and needs no external permissions or approvals. Instead of approval gates, these rules apply to every module:
- Modules use only fields published as open data.
- Ownership is the owner **type** only (natural / legal person, state, municipality, other).
- Sanctions cover **legal entities, matched by reg. no.** only.
- **No names of natural persons are stored** (nor personal codes or birth dates).
- Data that is not open (e.g. ATIS geometries, land book) is not used, and the affected check shows as *unavailable*.

## D1: agency-hosted resources

**Decision:** an official agency resource counts as an allowed source when it is referenced as a resource, or in the description, of a data.gov.lv dataset page. "Referenced" means a link or a service address on that page, or a service the referenced address itself points to. Each such resource is listed below **and** in `config/sources.yaml` (`allowed_external_resources`). Nothing that is missing from both lists may be used.

| # | Resource | Host | Referenced from (data.gov.lv dataset) | Used for | Status |
|---|---|---|---|---|---|
| E1 | De minimis export (CSV/XLSX) `https://deminimis.fm.gov.lv/public/mekletajs/export_csv` | deminimis.fm.gov.lv (FM) | `pieskirtais-de-minimis-atbalsts-latvija` (resource URL) | Module 11 | allowed |
| E2 | IUB notices/contracts JSON `https://open.iub.gov.lv/data/notice` | open.iub.gov.lv (IUB) | `ligumi`, `publisko-iepirkumu-pazinojumi` (resource URL) | Module 13 | allowed |
| E3 | DAP nature ArcGIS REST `https://ozols.gov.lv/arcgis/rest/services/OZOLS_DABASDATI_PUB_DATU_APMAINA/MapServer` and `/FeatureServer` | ozols.gov.lv (DAP) | `dabas-vertibu-geotelpiskie-dati` (resource); DAP nature datasets (description) | Module 3 (backup for the SHP files on data.gov.lv) | allowed |
| E4 | TAPIS WFS/WMS `https://geo-dpps.viss.gov.lv/api/DPPSPackage/client/Teritorija_454_4DUoZx/e4ab2161-88bf-4f35-85b8-f1ca8dd5ebb3` (WFS), `…/Teritorija_451_GKJOzb/96f059e4-9ed2-479c-976f-dcbed668972f` (WMS) | geo-dpps.viss.gov.lv → tapis.gov.lv (VARAM/VRAA) | `teritorijas-attstbas-plnoanas-informcijas-sistmas-tapis-eotelpiskie-dati` (resource URLs) | Module 8, zoning layer | allowed |
| E5 | Flood WMTS/WMS (spring 10-year WMTS `…/Pludu_risk_443_Dv50WI/…`; 3rd cycle WMS `…/3._cikla_L_556/557/558…`) | geo-dpps.viss.gov.lv → geodata.lvgmc.lv (LVĢMC) | `pldu-riska-karu-atvrtie-dati-un-servisi1`, `3-cikla-latvijas-pldu-postjumu-vietu-un-pldu-riska-kartes1` (resource URLs) | Plūdi map layer only (images) | allowed |
| E6 | geolatvija.lv flood products 309 and 361 (SHP) `https://geolatvija.lv/main?geoProductId=309`, `…=361` | geolatvija.lv (VRAA) | `pldu-riska-karu-atvrtie-dati-un-servisi`, `3-cikla-latvijas-pldu-postjumu-vietu-un-pldu-riska-kartes` (description) | Module 4 (if a stable file URL exists) | allowed; download URL **not verified** |
| E7 | LVĢMC ArcGIS MapServer `https://geodata.lvgmc.lv/server/rest/services/Atvertie_dati/Pavasara_pludu_kartes_3_cikls/MapServer`, layer 0 `Pavasara_palu_010_3_cikls` and layer 1 `Pavasara_pali_Salaca_010_3_cikls` | geodata.lvgmc.lv (LVĢMC) | Not named directly on a data.gov.lv page. The same server (`…/Atvertie_dati/Pavasara_pali_010/MapServer/WMTS`) is named in the capabilities of E5's WMTS, and the 3rd-cycle WMS (E5, resource 557) has the same 4 layers | Module 4 vectors (primary) | **allowed, decided**. Licence **CC0-1.0** (see below) |

### E7 (decided 2026-10-09, Janis)
- **Licence: CC0-1.0.**
  - **Source of that statement:** the data.gov.lv listing of the same data, [`3-cikla-latvijas-pldu-postjumu-vietu-un-pldu-riska-kartes1`](https://data.gov.lv/dati/lv/dataset/3-cikla-latvijas-pldu-postjumu-vietu-un-pldu-riska-kartes1) (`license_id: CC0-1.0`, harvested by ĢEOLatvija.lv, metadata modified 2026-08-19).
  - The service's own metadata has `copyrightText: "none"`.
- **Free data only:** the service description says depth-class data is paid; it is not used.
- **Snapshot only:** layers 0 and 1 are imported as a versioned dataset snapshot (`dataset_version`) by the ETL. The app and the check engine never query the service live.
- **E6 cross-check:** once E6 download links are verified, compare feature count and total area (EPSG:10306, m²) between E6 and E7 for the 10-year layers, and record the result here. E6 stays as the fallback source.

| Check | E7 | E6 | Result |
|---|---|---|---|
| Feature count, layer 0 (whole country) | 24,590 (2026-10-09, `returnCountOnly`) | not yet (E6 URL not verified) | pending |
| Feature count, layer 1 (Salaca) | 386 | not yet | pending |
| Total area | not yet computed | not yet | pending |

## D9: storage and analysis CRS

**Decision:** store and analyse in **EPSG:10306 (LKS-2020 / Latvia TM)**. Sources still in EPSG:3059 (LKS-92 / Latvia TM) are transformed to EPSG:10306 on import. GeoJSON is still served in EPSG:4326.

**Why:**
- LKS-2020 replaced LKS-92 as Latvia's official system on 2026-10-01 ([LĢIA: "2026. gada 1. oktobrī notiks pāreja uz LKS-2020"](https://www.lgia.gov.lv/lv/lks-2020); the EPSG remark on CRS 10305 reads "Replaces LKS-92 (CRS code 4661) from 2026-10-01").
- VZD has already switched its open data:
  - **VARIS:** change log in the VZD dataset description on data.gov.lv ([`varis-atvertie-dati`](https://data.gov.lv/dati/lv/dataset/varis-atvertie-dati)): "07.10.2026 – transformētas koordinātas no LKS-92 TM uz LKS -2020 TM".
  - **Cadastre map:** the VZD description of [`kadastra-informacijas-sistemas-atverti-telpiskie-dati`](https://data.gov.lv/dati/lv/dataset/kadastra-informacijas-sistemas-atverti-telpiskie-dati) says "Kadastra kartes taisnleņķa koordinātu tīkls atbilst … LKS–2020 TM". The `.prj` in `0007000_kk_shp.zip` (checked 2026-10-09) is `LKS_2020_Latvia_TM … AUTHORITY[EPSG,10306]`.
  - VZD's page [Pāreja uz LKS-2020](https://www.vzd.gov.lv/lv/pareja-uz-lks-2020) covers only municipal ADTI databases and gives no date for VARIS or the cadastre.
- Cadastre and addresses are the core tables, so keeping them untransformed avoids error in the most-used geometries.
- Still in LKS-92 / EPSG:3059: DAP nature data (per its descriptions), the TAPIS WFS and the LVĢMC flood service.

**PROJ check (2026-10-09; read from the published source, not run, because Docker is not installed on the dev machine):**

| Image | Base | PROJ | EPSG db | EPSG:10306 | LKS-92 → LKS-2020 transformation |
|---|---|---|---|---|---|
| `postgis/postgis:16-3.5` | Debian bullseye | 7.2.1 | v10.008 | **no** | **no** |
| (Debian bookworm) | | 9.1.1 | v10.076 | no | no |
| (Debian trixie, distro package) | | 9.6.0 | v12.004 | yes | **no** |
| `postgis/postgis:18-3.6` | `postgres:18-trixie` + apt.postgresql.org | **9.8.1** (`libproj25 9.8.1-1.pgdg13+1`) | v12.029 | **yes** | **yes: EPSG:10838 "LKS-92 to LKS-2020 (1)"**, NTv2 grid, ~1 cm |

Sources:
- the `Dockerfile`s in `github.com/postgis/docker-postgis`;
- Debian madison;
- the apt.postgresql.org `trixie-pgdg` package index;
- `data/sql/*.sql` at PROJ tags 7.2.1, 9.1.1, 9.6.0 and 9.8.1.

**Consequences:**
- **Use `postgis/postgis:18-3.6` (PostgreSQL 18), not 16-3.5.** PLAN.md said PostgreSQL 16, but the PG16 image's PROJ does not know EPSG:10306. Phase 1 must confirm inside the running container:
  - `SELECT postgis_full_version();` shows PROJ ≥ 9.8;
  - `SELECT proj4text FROM spatial_ref_sys WHERE srid = 10306;` returns a row. PostGIS's `spatial_ref_sys` may need the row added from PROJ.
- **EPSG:10838 needs the grid file `lv_lgia_lks92to2020.tif`** (20 KB, CC-BY 4.0, LĢIA, from `https://cdn.proj.org/lv_lgia_lks92to2020.tif`). Without it, PROJ falls back to a less accurate path without a clear error. The image must contain the file in the PROJ data directory (copied at build time, not downloaded at run time). Phase 1 test: transform the EPSG sample point Odukalns, 56.8283960°N 24.2727688°E (LKS-92) → 56.8283967°N 24.2727679°E (LKS-2020).
- Transformations happen in the ETL, once, on import. The check engine only sees EPSG:10306.
- **Local test (2026-10-09, pyproj 3.8.0 / PROJ 9.8.1, the same PROJ as the target image)** on the EPSG sample point:
  - **without** the grid, PROJ silently uses "LKS-92 to WGS 84 (1) + inverse LKS-2020 to WGS 84 (1)" and is off by **9.5 cm**;
  - **with** `lv_lgia_lks92to2020.tif`, it is off by **0.13 cm**.
  - Grid SHA-256: `6be363d4796bb3038e751da00e2344593edbb149ed193fc31b9c200688b31498` (20,235 bytes); pin it in the Dockerfile.

**Confirmed in Phase 1 (2026-10-09, in the running `kadastrs-db` container, `postgis/postgis:18-3.6` digest `sha256:60f6ad1d…`):**
- `postgis_full_version()`: PostGIS 3.6.4, **PROJ 9.8.1** at run time, EPSG db in `/usr/share/proj/proj.db`, `NETWORK_ENABLED=OFF`.
- `spatial_ref_sys` had **no rows for 10305 and 10306**. Migration `20261009120000_extensions_and_crs.sql` adds them, with auth `EPSG`; PROJ resolves both codes.
- Odukalns error with the grid: **0.13 cm** on both the geographic path (4661 → 10305) and the projected path (3059 → 10306). Without the grid (`db-nogrid` test service): **9.53 cm**, with no error raised.
- For imports, use the SQL function `lks92_to_lks2020(geom)` (explicit EPSG:10838 grid pipeline). It raises an error when the grid is missing, instead of silently falling back.
- Tests: `tests/test_crs.py`, run in CI.
