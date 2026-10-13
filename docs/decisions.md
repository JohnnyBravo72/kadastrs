# Decisions

Decisions from PLAN.md §10. When a decision is settled, fill in the outcome, the date and who decided.

| # | Decision | Needed by | Status | Outcome | Decided by / date |
|---|---|---|---|---|---|
| D1 | Agency-hosted resources listed on data.gov.lv count as data.gov.lv? | Phase 0 | **decided** | Yes, see [D1](#d1-agency-hosted-resources) | Janis, 2026-10-09 |
| D2 | Basemap: OSM or plain | Phase 6 | **decided** | OpenStreetMap tiles with attribution, see [D2](#d2-basemap-openstreetmap-tiles) | Janis, 2026-10-11 |
| D3 | Hosting, sign-in, security review, retention, maintenance, legal status (PLAN.md §1) | **Phase 10** | open (**interim answers in force**) | Interim (2026-10-09): local Docker on Janis's PC for Phases 1–9; no sign-in, local only (sign-in required before any shared hosting); security review before shared hosting; keep all runs; maintenance Janis; footer "Informatīvs pārskats, balstīts uz atvērtajiem datiem; nav oficiāls reģistra izraksts". Revisit in Phase 10 | Janis, 2026-10-09 (interim) |
| D4 | Risk rules, agreed with the team leads | Phase 4 | **decided** | v1 agreed by Janis Bardavskis 2026-10-11, to be revised after the test-set comparison. **v2 agreed 2026-10-12:** encumbrance codes 8317010100, 8317020100, 8317030100 (areas assessed for the cadastral value, about 54,000 pilot parcels) are `not_findings`: listed apart as "Tehniskie apgrūtinājumi", never a finding (an object with only these: clear, risk none instead of low). `config/rules.yaml` `version: "2"`, `status: agreed`; runs keep the rule set they were made with (v1 runs replay unchanged) **v3 agreed by Janis Bardavskis 2026-10-13:** rules for modules 9, 14 and 17 (Phase 8a); an open legal protection proceeding (court or out-of-court TAP) is high, "pārbaudīt atbilstību grūtībās nonākuša uzņēmuma kritērijiem"; sanctions_linked_entity kept (entity rows only); thresholds 183 days, 10 companies, 300 m² | Janis Bardavskis, 2026-10-11 / 2026-10-12 / 2026-10-13 |
| D5 | Ownership module | Phase 8 | **decided** | Built, with owner **type** only (`PersonStatus`); no names. See [Policy](#policy-open-data-only) | Janis, 2026-10-09 |
| D6 | Sanctions module | Phase 8 | **decided** | Built for **legal entities by reg. no. only** (UR `sanctions`); natural-person fields never imported. See [Policy](#policy-open-data-only) | Janis, 2026-10-09 |
| D7 | Contents of Avoti and Žurnāls | Phase 6 | **decided** | Avoti: every source with data date, freshness, coverage, licence and data.gov.lv links, plus the versions the open run read. Žurnāls: runs with date, objects, projects, overall risk, module count and origin; see [Phase 7](#phase-7-entry-dialog-reruns-and-projects-decided-2026-10-12-janis) | Janis, 2026-10-12 |
| D8 | Project number format (free text for now) | Phase 7 | **decided** | Free text, 1–100 characters, as typed (a code, never a number); group names unique per run ignoring case; "Bez projekta" reserved | Janis, 2026-10-12 |
| D9 | Storage and analysis CRS | Phase 1 | **decided** | EPSG:10306 (LKS-2020 / Latvia TM), see [D9](#d9-storage-and-analysis-crs) | Janis, 2026-10-09 |
| D10 | Applicant data from UR and FID: which files, rows and fields | Phase 8 | **decided** (option B pending) | Legal-entity rows and fields only; option A for sanctions; see [D10](#d10-applicant-data-ur-fid) | Janis, 2026-10-12 |
| D11 | Phase 8b data: VID rating, de minimis, EU projects, EIS procurement, FID frozen real estate | Phase 8 | **decided** (natural-person EU projects: DPO check before Phase 10) | Legal-entity rows and fields only; natural-person EU projects without any person field; see [D11](#d11-phase-8b-data-vid-de-minimis-eu-projects-eis-fid-real-estate) | Janis, 2026-10-13 |

## Policy: open data only

**Decided 2026-10-09 (Janis).** The project uses only open data and needs no external permissions or approvals. Instead of approval gates, these rules apply to every module:
- Modules use only fields published as open data.
- Ownership is the owner **type** only (natural / legal person, state, municipality, other).
- Sanctions cover **legal entities, matched by reg. no.** only.
- **No names of natural persons are stored** (nor personal codes or birth dates).
- Data that is not open (e.g. ATIS geometries, land book) is not used, and the affected check shows as *unavailable*.

## Source deep links, "Skatīt avotā" (decided 2026-10-12, Janis)

Each finding and object can be opened in the publisher's own public system, next to the data.gov.lv dataset link: kadastrs.lv (parcels, buildings, properties, VARIS addresses), BIS (cases), Ozols (nature), the LVĢMC flood map viewer (centred on the object). Shown in the results view (cards, header, map popups) and in the Excel sheet "Detaļas" (column "Avots sistēmā").
- **Links only open the source; no data is fetched** from those systems, and nothing they show is stored or used for checks. Rule 1 (data only from data.gov.lv) is unchanged.
- Only patterns verified with real requests on the seed objects, logged out, are used; each with its test date and limitation in `docs/data-sources.md` §8. Where no pattern opens the right object without login, the link goes to the system's public search page and the number is shown with a copy button.
- A link may break when a system is redesigned; links are re-checked when that happens, never guessed.

## D2: basemap, OpenStreetMap tiles (decided 2026-10-11, Janis)

The results view (Phase 6) uses **OpenStreetMap standard tiles** (`https://tile.openstreetmap.org/{z}/{x}/{y}.png`) as the background, with the attribution "© OpenStreetMap līdzautori" on the map and in the page footer.
- Tiles are not datasets (PLAN §2.1): nothing from them is stored, checked or reported. Every feature drawn over them comes from our API for the run's pinned versions (data.gov.lv imports).
- OSM's tile usage policy allows this low volume (a few pilot users, a normal browser, attribution shown). **Before shared hosting (Phase 10, D3)** use our own tiles or a tile provider with terms for that use.
- Tile requests tell the OSM servers which area a user looks at; acceptable for the local pilot, to be reviewed with D3.
- The tiles are shown slightly desaturated so the risk colours stand out. Automated tests never fetch them (the end-to-end test answers tile requests with a blank image).

## Freshness against the source (decided 2026-10-11, Janis)

**Problem:** a fixed `max_age` per source flagged data as stale when the publisher simply had not released anything newer (2026-10-11: VZD's cadastre files dated 2026-09-26, last modified on data.gov.lv 2026-09-28, dataset frequency WEEKLY). Raising `max_age` would have hidden real staleness, so the model changed instead.

**Decision:** fresh = we hold the newest release the publisher has made (`etl/freshness.py`).
- At the start of every check run and in `etl status`, read each source's latest release from data.gov.lv `package_show`: the newest `last_modified` of its resources, or the dataset `metadata_modified` for a source without CKAN files (flood, D1 E7). Same dates as the importer (E1, E7). This is catalogue metadata only; data is never read live (PLAN §2.2).
- Compare it with the release our live version came from: `import_log.source_last_modified` of the imports that produced or confirmed the live version (an `unchanged` import of a re-uploaded file counts).
- Outcomes and texts (Latvian, on the report's Avoti sheet and, if not current, as a `stale_data` warning on every result of that source):

| Case | Svaigums | Text | Warning |
|---|---|---|---|
| we hold the latest release | aktuāli | jaunākie pieejamie dati (avots atjaunots <date>) | no |
| a newer release is not imported | novecojuši | novecojuši – pieejama jaunāka versija (avots atjaunots <date>) | yes |
| no release for longer than `source_stale_after` | avots nav atjaunots | avots nav atjaunots kopš <date> | yes |
| data.gov.lv unreachable | (from the last good check) | … ; pēdējā pārbaude <date> | as that check |
| unreachable, never checked | nezināms | nav zināms, vai šī ir jaunākā versija … | yes |

- `source_stale_after` per source in `config/sources.yaml` (replaces `max_age`): cadastre text, cadastre map and encumbrances P60D; VARIS addresses and boundaries P14D; BIS P30D; flood, nature and the ATIS classifier P2Y; the frozen 2025-01-31 list none (never republished).
- Every look is recorded in `source_check` (origin `run`, `status` or `import`; an import is also a look). A run stores the verdict with its pinned versions (`work.run_version.source`), so its report always shows freshness as of the run and a replay gives the same report; a report downloaded later does not re-check. Runs made before this change keep their `max_age` verdict.
- Offline or tests: `KADASTRS_FRESHNESS_CHECK=off` skips the network and uses the last known checks.

## Phase 5: batch input rules (decided 2026-10-11, Janis)

How a batch list becomes checked objects (`engine/batch/plan.py`; runbook "Batch and Excel report"):

1. **Ambiguous values.** An 11-digit number that is a property and a parcel of another property is checked **both ways**: two report rows labelled "divdomīgs: nekustamais īpašums" / "divdomīgs: zemes vienība", with a warning, so nothing has to be re-entered. The optional input column **`veids`** (īpašums | zemes vienība | būve) removes the ambiguity (also in `test_set_template.xlsx` and `check compare`). Values whose Excel precision was lost and unclear addresses are **not checked**; they go to the "Neatrasts" sheet with suggestions.
2. **Addresses with several objects:** every linked cadastre object is checked, one row each. The 1,000-row limit counts input rows.
3. **Duplicate rows** are checked again and keep their "atkārtojas" warning.
4. **`adrese` column:** the given address for module 2. If it does not resolve, the object is still checked, the address is listed on "Neatrasts" and module 2 shows "adrese nav atrasta" (not "nav piemērojams"). Without `adrese`, an address in `vertiba` is the given address.
5. **`pieteicejs_reg_nr`:** stored only if it has the legal-entity pattern (11 digits, first digit 4, 5 or 9); anything else may be a personal code and is dropped with a note, its value not stored (Policy above, CLAUDE.md rule 5). A `vertiba` shaped like a personal code (`DDMMYY-NNNNN`) is not resolved or stored either.

Module 2 without any address is shown as **"nav piemērojams"** in the report (decided 2026-10-11 in Phase 4). The uploaded file is not stored; the cleaned rows are (`work.run_input`, insert-only like the other run tables), so the report is built from stored data only and a replayed run gives the same report.

## Phase 7: entry dialog, reruns and projects (decided 2026-10-12, Janis)

1. **Atjaunot** (filter bar) makes a **new** run with the same targets, unit selections and input rows and the new source set. It keeps the parent's **pinned dataset versions, rule set and evaluation time** (`run.checked_as_of`; BIS rates a case by its age on that day), so the modules still run give exactly the parent's results. The parent run is never changed (CLAUDE.md rule 3) and is linked by `run.parent_run_id`.
2. **Pārbaudīt ar jaunākajiem datiem** makes a new run on the **live** versions with the current rule set and lists the sources whose version changed. Also linked by `parent_run_id`.
3. **Only ticked units are checked.** A property with a partial selection carries "pārbaudītas N no M īpašuma vienībām (atzīmētās ievades logā)" on its results and in the Excel warnings column. All units ticked = the whole property (no selection stored).
4. **Project groups** are a view on a stored run: each change is a new row in the insert-only `work.run_grouping` (the newest is current; without a row, groups come from the input's project numbers). Check results are never touched. A deleted group's objects go to "Bez projekta". Runs made from a run start with its grouping.
5. **The Excel report follows the current grouping** (column "Projekta Nr." on Kopsavilkums) and names the grouping row it used, with its date, on Avoti ("Projektu grupējums"), so a report can be rebuilt for that row (`report.xlsx?grouping=<id>`). Runs without a grouping row show the input's project numbers, as before.
6. **Imports are read on the server** with the batch reader and not stored; the preview stores nothing. Removing a row re-sends the file with `skip_rows`, so no value is echoed back (a value shaped like a personal code is never shown).
7. **Žurnāls** lists every run on the server until sign-in exists (Phase 10, then per user), 50 per page, with search by project number and date range. Runs of test servers (origin `test` or `e2e`: the pilot tests, `api-e2e`, the screenshot server `api-screens`) are hidden unless "Rādīt testa pārbaudes" is ticked. Runs are never deleted (D3), so test runs made before 2026-10-12 through the normal server stay visible.
8. **Sources checklist:** a source that selects a check module can be unticked (its module is not run, its map layer hidden). Base data every module reads (cadastre map, boundaries, ATIS classifier, frozen encumbrance list) is always used and shown greyed. `partial_coverage: true` in `config/sources.yaml` (flood, habitats) adds the note "daļējs pārklājums".

## D1: agency-hosted resources

**Decision:** an official agency resource counts as an allowed source when it is referenced as a resource, or in the description, of a data.gov.lv dataset page. "Referenced" means a link or a service address on that page, or a service the referenced address itself points to. Each such resource is listed below **and** in `config/sources.yaml` (`allowed_external_resources`). Nothing that is missing from both lists may be used.

| # | Resource | Host | Referenced from (data.gov.lv dataset) | Used for | Status |
|---|---|---|---|---|---|
| E1 | De minimis export (CSV/XLSX) `https://deminimis.fm.gov.lv/public/mekletajs/export_csv` | deminimis.fm.gov.lv (FM) | `pieskirtais-de-minimis-atbalsts-latvija` (resource URL) | Module 11 (CSV only). The server omits its intermediate certificate: the ETL adds the pinned Sectigo intermediate to its CA bundle, verification stays on (D11, `docs/runbook.md` "TLS") | allowed |
| E2 | IUB notices/contracts JSON `https://open.iub.gov.lv/data/notice` | open.iub.gov.lv (IUB) | `ligumi`, `publisko-iepirkumu-pazinojumi` (resource URL) | Not used in Phase 8b (module 13 uses the EIS files on data.gov.lv; the URL answers with an HTML archive page, 2026-10-13) | allowed |
| E3 | DAP nature ArcGIS REST `https://ozols.gov.lv/arcgis/rest/services/OZOLS_DABASDATI_PUB_DATU_APMAINA/MapServer` and `/FeatureServer` | ozols.gov.lv (DAP) | `dabas-vertibu-geotelpiskie-dati` (resource); DAP nature datasets (description) | Module 3 (backup for the SHP files on data.gov.lv) | allowed |
| E4 | TAPIS WFS/WMS `https://geo-dpps.viss.gov.lv/api/DPPSPackage/client/Teritorija_454_4DUoZx/e4ab2161-88bf-4f35-85b8-f1ca8dd5ebb3` (WFS), `…/Teritorija_451_GKJOzb/96f059e4-9ed2-479c-976f-dcbed668972f` (WMS) | geo-dpps.viss.gov.lv → tapis.gov.lv (VARAM/VRAA) | `teritorijas-attstbas-plnoanas-informcijas-sistmas-tapis-eotelpiskie-dati` (resource URLs) | Module 8, zoning layer | allowed |
| E5 | Flood WMTS/WMS (spring 10-year WMTS `…/Pludu_risk_443_Dv50WI/…`; 3rd cycle WMS `…/3._cikla_L_556/557/558…`) | geo-dpps.viss.gov.lv → geodata.lvgmc.lv (LVĢMC) | `pldu-riska-karu-atvrtie-dati-un-servisi1`, `3-cikla-latvijas-pldu-postjumu-vietu-un-pldu-riska-kartes1` (resource URLs) | Plūdi map layer only (images) | allowed |
| E6 | geolatvija.lv flood products 309 and 361 (SHP) `https://geolatvija.lv/main?geoProductId=309`, `…=361` | geolatvija.lv (VRAA) | `pldu-riska-karu-atvrtie-dati-un-servisi`, `3-cikla-latvijas-pldu-postjumu-vietu-un-pldu-riska-kartes` (description) | None (was: module 4 fallback) | withdrawn |
| E7 | LVĢMC ArcGIS MapServer `https://geodata.lvgmc.lv/server/rest/services/Atvertie_dati/Pavasara_pludu_kartes_3_cikls/MapServer`, layer 0 `Pavasara_palu_010_3_cikls` and layer 1 `Pavasara_pali_Salaca_010_3_cikls` (findings); layer 3 `Pavasara_palu_200_3_cikls` (**coverage mask only, never a finding**, added 2026-10-09) | geodata.lvgmc.lv (LVĢMC) | Not named directly on a data.gov.lv page. The same server (`…/Atvertie_dati/Pavasara_pali_010/MapServer/WMTS`) is named in the capabilities of E5's WMTS, and the 3rd-cycle WMS (E5, resource 557) has the same 4 layers | Module 4 vectors (primary) | **allowed, decided**. Licence **CC0-1.0** (see below) |

### E7 (decided 2026-10-09, Janis)
- **Licence: CC0-1.0.**
  - **Source of that statement:** the data.gov.lv listing of the same data, [`3-cikla-latvijas-pldu-postjumu-vietu-un-pldu-riska-kartes1`](https://data.gov.lv/dati/lv/dataset/3-cikla-latvijas-pldu-postjumu-vietu-un-pldu-riska-kartes1) (`license_id: CC0-1.0`, harvested by ĢEOLatvija.lv, metadata modified 2026-08-19).
  - The service's own metadata has `copyrightText: "none"`.
- **Free data only:** the service description says depth-class data is paid; it is not used.
- **Snapshot only:** layers 0 and 1 are imported as a versioned dataset snapshot (`dataset_version`) by the ETL. The app and the check engine never query the service live.
- **Coverage mask: layer 3 (200-year extent), decided 2026-10-09 (Janis).**
  - Checked first: designated flood risk areas (APSFR, *nozīmīgas plūdu riska teritorijas*) are **not published as polygons on data.gov.lv**. The listing `…-kartes1` has three WMS proxies and geolatvija links; `pldu-riska-zonas(-wfs)` has only flood-management units; LVĢMC's `udens` dataset points to the LVĢMC website and EU reporting (`cdr.eionet.europa.eu`, 2019 cycle), neither listed in D1. The MapServer has no extent layer of the modelled areas.
  - So layer 3 of E7 is imported as a **coverage mask only, never a finding**. Module 4: a parcel outside the mask is `not_covered`, never `clear`, with the reason **"ārpus plūdu kartēs attēlotās teritorijas – plūdu karte šeit nav pieejama vai teritorija nav applūstoša pat 200 gadu scenārijā"**.
  - **Limitation:** open data cannot tell "not modelled" from "modelled and dry even at 0.5 %". Outside the mask both are reported as `not_covered`, the cautious reading; the reason text names both possibilities.
- **E6 cross-check:** not possible with open data (E6 withdrawn, below). E7 has no fallback source.

| Check | E7 | E6 | Result |
|---|---|---|---|
| Feature count, layer 0 (whole country) | 24,590 (2026-10-09, `returnCountOnly`) | — | not possible (E6 withdrawn) |
| Feature count, layer 1 (Salaca) | 386 | — | not possible (E6 withdrawn) |
| Total area | not computed | — | not possible (E6 withdrawn) |

### E6 (withdrawn 2026-10-10, Janis)
- **Reason:** geolatvija product files require login (HTTP 401), not open data under rule 1. Checked 2026-10-09: `geolatvija.lv/api/v1/geoproducts/309` and `…/361` answer **401 Unauthorised**; the app obtains files through orders (`/api/v1/geoproduct-orders`).
- Consequences: E7 has no fallback source, and the E6/E7 comparison above cannot be made.
- **Re-add** (status `allowed` here and in `config/sources.yaml`) if the files become openly downloadable; then run the comparison.

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
- **Outside the grid (2026-10-10):** DAP marine areas extend beyond the LĢIA grid, where EPSG:10838 is undefined. Imports use `lks92_to_lks2020_checked()`: strict grid where it has values, zero shift outside it, object flagged `outside_grid` (≤ ~10 cm, at sea only). The grid stays mandatory. Details: `docs/data-sources.md` §6.4.
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

## D10: applicant data (UR, FID)

**Decided 2026-10-12 (Janis).** Rule 5 in CLAUDE.md applied to the applicant modules (9, 14, 17):
1. **Imported:** UR `register.csv` (whole country: reg. no., form, register, status, registration and end dates, legal address and its VARIS code), UR insolvency proceedings of **legal entities**, the UR sanctions file and FID's "Sankciju subjekti" (rows below). Details: `docs/data-sources.md` §3.9, §3.9a, §3.17.
2. **Never imported:** UR officers (amatpersonas), members (dalībnieki), beneficial owners (patiesā labuma guvēji, PLG), procurations (prokūras), and any other file about natural persons.
3. **No names of individual merchants:** the names of `IK` (individuālais komersants) and `IND` (individuālais uzņēmums) are not stored; they are usually the owner's name. Their reg. no., form, status and address are. Farms (`ZEM`) keep their names. A database constraint enforces it.
4. **Legal-entity numbers only:** every stored registration number has the pattern `^[459][0-9]{10}$` (UR's 9-digit old numbers allowed in the company table); 11-digit numbers of any other shape could be personal codes and are dropped. Personal insolvency rows are dropped.
5. **Sanctions, option A (in force):** module 17 matches the applicant's reg. no. only against UR `LEGAL_ENTITY` / `FOREIGN_ENTITY` rows and FID rows with a Latvian legal-entity reg. no. **No data from `NATURAL_PERSON` rows is stored**, and FID's column 6 (the sanctioned person) never is. A name-only hit (a UR `FOREIGN_ENTITY` name equal to the applicant's name, no reg. no.) is flagged for manual review with no risk level of its own.
6. **Sanctions, option B (pending DPO assessment; CFLA's duties under the sanctions law are the likely legal basis):** from a `NATURAL_PERSON` row, store only the **linked company's** fields (reg. no., legal form, relationship `position_text_lv`, list, program, entry date), **never** a person field (name, birth date, personal code part, nationality). Module 17 would then report "uzņēmums saistīts ar sankciju sarakstā iekļautu personu (saistība: …)". Ready to build when decided: one extra table of company links (no person columns, same reg.-no. constraint), an importer branch for `NATURAL_PERSON` rows that copies only those fields, and one rule. Until this decision is updated, **no code path reads those rows** (a test checks it).
7. **Deep links:** "Skatīt UR" opens UR's public search with the reg. no. to copy; "Skatīt sankciju sarakstā" runs FID's public list search for the applicant (verified patterns, `docs/data-sources.md` §8). Nothing is fetched from those systems.

## D11: Phase 8b data (VID, de minimis, EU projects, EIS, FID real estate)

**Decided 2026-10-13 (Janis).** CLAUDE.md rule 5 applied to modules 10–13 and 18. Sources, counts and fields: `docs/data-sources.md` §3.10–3.13, §3.17.
1. **VID taxpayer rating (module 10):** reg. no. (legal-entity pattern only), rating, explanation and date. The name column is never stored (an IK is named after its owner); the name shown comes from UR.
2. **De minimis (module 11):** legal-entity rows only (rows with a personal-code shape, 9,716 of 76,021 on 2026-10-13, are dropped before any field is read). Never stored: `person_title` and `project_title`.
   - **Freshness "live export":** the CSV is generated on request and the data.gov.lv resource has no date, so the source is fresh while our last successful download is younger than its `source_stale_after` (P7D); the text names the download date. The version date is the newest `assign_date` in the file (the file's own date, rule E7).
   - **Period and ceilings:** aid in the 3 years before the run date (rolling), summed per regulation group; ceilings in `config/rules.yaml` (v4 draft). The module always carries the warning "Summa tikai šim reģ. Nr.; vienotā uzņēmuma saistītie uzņēmumi nav ņemti vērā – pārbaudīt manuāli" and shows the remaining headroom per regulation.
   - **TLS:** `deminimis.fm.gov.lv` does not send its intermediate certificate. The ETL verifies against the standard CA bundle plus the pinned intermediate "Sectigo Public Server Authentication CA DV R36" in `infra/certs/` (SHA-256 checked at start). Verification is never switched off (CLAUDE.md rule 9); `truststore` does not help inside the Linux container (OpenSSL does not fetch missing intermediates).
3. **EU co-financed projects (module 12):** the three CFLA datasets (2014–20, 2021–27, RRF): project list, locations, partners.
   - Legal-entity applicants (not IK): project fields, applicant reg. no. and name, location address. Partners: reg. no. only (legal-entity pattern), never names. Never: e-mail, web site.
   - **Natural-person and IK projects (`ProjektaIesniedzejaTips` "Fiziska persona…", "Individuālais komersants")** are imported with **only** project number, period, status, dates, amounts, measure, type and the cadastre numbers of their locations: no name, title, reg. no., address or e-mail (a DB constraint enforces it). **This is indirectly personal data:** a cadastre number identifies the owner through the land register. It is used for CFLA's double-funding control (another EU-funded project on the same object). **To be confirmed with the DPO before shared hosting (Phase 10, D3).**
   - Matching only by cadastre number (property, parcel, building; 17-digit premise groups cut to the building); the location address is often only a city and is not matched. Each result reports the location file's coverage (share of rows with a cadastre number per period).
4. **Procurement (module 13): EIS only** (`iepirkumu-rezultatu-datu-grupa`, yearly files 2018–2026), coverage note **"tikai EIS e-konkursu iepirkumi"**. The winner's name is never stored; a winner reg. no. only with the legal-entity pattern. IUB (D1 E2) is not used in Phase 8b.
5. **FID frozen real estate (module 18 "Iesaldēts nekustamais īpašums (FID)", an object check):** the FID "TA, VZD" file. Stored: cadastre number, asset type, link to the subject, register marks, basis, sanctions date, legal act, FID check and publication date, and the holder's reg. no. only with the legal-entity pattern. Never: the subject's name, birth date, nationality, address, the sanctioned person and their data (columns 1, 2 unless a legal-entity reg. no., 3, 7, 13, 14).

## Incident 2026-10-12: personal data printed during data discovery

While checking the FID file "Sankciju subjekti" for Phase 8a, an inspection script printed what it took for header rows; they were the first three data rows, with the names of sanctioned natural persons and one birth date from the **public** FID list. The values appeared only in the developer session's output: nothing was stored in the database, the repository or any report, and the downloaded samples were deleted the same day. Rule added to CLAUDE.md (rule 13): during data discovery, print only counts, column names and pattern checks, never values from columns that may hold personal data.
