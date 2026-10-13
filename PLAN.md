# Kadastra pārbaude: Build Plan

**Goal:** a tool for CFLA project evaluators. They give it a list of objects: **kadastra numuri**, **kadastra apzīmējumi** or **addresses**, optionally grouped by **project number** and linked to the **applicant's registration number**. The tool checks each object against open data and produces:
1. an **Excel report** with one row per object: findings, risk level, source, data date and evidence link (MVP), and
2. an **interactive map and dashboard** with layers (Plūdi, Zonējums, Daba, Kadastrs) and a results list (after the MVP).

**Data policy:** all data comes from **data.gov.lv** (section 2).

**Status (2026-10-13):** Phase 8b (modules 7, 10–13, 18: ownership, VID, de minimis, EU projects, EIS, FID frozen RE) is built; data policy D11; rule set v4 **agreed** 2026-10-13 (D4). Phase 8a (modules 9, 14, 17) is built and tested; rules v3 agreed 2026-10-13 (D4). Phase 7 is built and tested; Phase 6's zoning (module 8) is still open. Phases 1–3 are done; Phase 4 is built and tested (test-set comparison waits for filled files). Phase 5 is built and tested (colleague pilot timing open). Phase 0 steps 1 and 3 done; baseline and returned test set still open.

**Change log**
- 2026-10-13 (Phase 8b): modules 7, 10–13 and 18 (D11; sources in `docs/data-sources.md` §3.10–3.13, §3.16–3.17).
  - **7 Ownership:** pilot members of `ownership.zip`; `OwnershipStatus` + `PersonStatus` only (D5); risk none (informational).
  - **10 VID rating:** reg. no., rating, explanation, date; name never stored; A none / B low / C high / J·N medium / missing unknown.
  - **11 De minimis:** live CSV via D1 E1 with pinned Sectigo intermediate (`infra/certs/`); legal entities only; 3-year rolling sum vs ceilings in `rules.yaml`; linked-undertakings warning always.
  - **12 EU projects:** three CFLA periods; object match by cadastre; applicant module for the same reg. no.; natural-person/IK rows stripped (D11); location coverage warning.
  - **13 EIS procurement:** yearly files 2018–2026; winner name never stored; coverage "tikai EIS e-konkursu iepirkumi".
  - **18 FID frozen RE:** TA/VZD file; cadastre match; no person columns; risk high.
  - **Rule set v4 (agreed by Janis Bardavskis 2026-10-13, D4):** modules 7, 10–13 and 18; ownership informational; VID A/B/C/J/N; de minimis ceilings and 80%/100% shares; EU ongoing high / finished medium / applicant low; EIS low; FID frozen RE high.
- 2026-10-12 (Phase 8a, applicant): modules 9, 14 and 17 (D10 in `docs/decisions.md`; sources in `docs/data-sources.md` §3.9, §3.9a, §3.17).
  - **Sources** (whole country, legal entities only): UR `register.csv` (`ur_companies`), UR insolvency proceedings (`ur_insolvency`), UR sanctions file (`ur_sanctions`, `LEGAL_ENTITY` / `FOREIGN_ENTITY` rows only) and FID "Sankciju subjekti" (`fid_sanctions`, rows with a Latvian legal-entity reg. no.). Never imported: officers, members, beneficial owners, procurations, natural-person sanctions rows, FID's sanctioned-person column. No names of individual merchants (IK, IND). Database constraints enforce it.
  - **Applicant modules run once per applicant reg. no.** (results with scope `applicant`, stored on the first target that names it): 9 "Pieteicējs (UR)" (status aktīvs / likvidēts / reorganizēts, form, dates, legal address, open insolvency or legal protection) and 17 "Sankcijas" (reg. no. against UR entity rows and FID subjects, sanctioned entities linked to the applicant; a name-only hit is a manual-review flag, never a finding). Shown in their own section of the results page, on a new Excel sheet "Pieteicēji" and with their sources on Avoti.
  - **Module 14 "Uzņēmumi adresē"** (object module): active and ended companies whose legal address is one of the object's VARIS addresses, with the building's use and area, labelled "juridiskā adrese, nav darbības pierādījums".
  - **Links:** "Skatīt UR" (UR's public search, reg. no. to copy: no URL opens a company) and "Skatīt sankciju sarakstā" (FID's public list search; UR has no public sanctions search).
  - **Rule set v3 (agreed by Janis Bardavskis 2026-10-13, D4):** rules for 9, 14 and 17; an open legal protection proceeding is high; module 14 medium for 10+ active companies in a residential (11xx) or < 300 m² building, from the pilot data (36 of 4,428 addresses have 10+, 5 of them residential houses).
  - Sanctions option B (linked companies from natural-person rows, company fields only) is recorded in D10, **pending DPO assessment**; no code reads those rows.
  - Candidate for later: FID "TA, VZD" lists cadastre numbers of frozen real estate (an object check).
- 2026-10-12 (Phase 7): entry dialog, new runs from a stored run, project groups, header tabs (decisions in `docs/decisions.md` "Phase 7", D7, D8).
  - **Entry dialog** (§8.1), a modal on first open, reopened by "+ Jauna pārbaude":
    - kadastrs and address type-ahead with type badges; an ambiguous 11-digit number shows both meanings;
    - a property's units as a checklist (tri-state "Atzīmēt visu", "5 no 12", type filter), and "Rādīt visas īpašuma vienības" for a parcel; an address's objects with the same checkboxes;
    - a notice when the kadastrs and the address point to different objects (module 2 checks it);
    - "Projekta Nr." and "Pieteicēja reģ. Nr." (legal-entity pattern);
    - the sources checklist from `GET /api/sources` (grouped; modules' sources can be unticked, base data always used; partial-coverage note from the new `partial_coverage` flag);
    - CSV / XLSX import with a preview (`POST /api/batch/preview`, nothing stored; rows can be removed: the run re-sends the file with `skip_rows`);
    - footer "1 īpašums · 12 vienības · 9 avoti", or "N objekti (M vienības) · K avoti" for mixed lists.
  - **Only ticked units are checked:** `run_target.unit_selection`; the target warns "pārbaudītas 5 no 12 īpašuma vienībām", also in the Excel report.
  - **New runs from a stored run**, linked by `run.parent_run_id`; the stored run is never changed:
    - **Atjaunot** (filter bar: source chips with the banner "Filtru izmaiņas nav pielietotas") keeps the parent's pinned versions, rule set and evaluation time (`run.checked_as_of`), so only the source set changes;
    - **Pārbaudīt ar jaunākajiem datiem** pins the live versions and lists the sources whose version changed.
    - Layers of modules a run did not check are hidden.
  - **Projects:** groups per run in the insert-only `work.run_grouping` (create, rename, delete, move objects; default from the input's project numbers, "Bez projekta"), an overview table per group, and a click on a group zooms the map to it. The Excel report follows the current grouping and names the grouping row it used on Avoti (`report.xlsx?grouping=<id>` rebuilds an older one).
  - **Header tabs:** Atlase, Avoti (registry with data date, freshness, coverage, links, and the open run's versions) and **Žurnāls**:
    - lists all runs on the server; per user once sign-in exists (Phase 10);
    - 50 per page, search by project number and date range;
    - runs of test servers (origin `test` / `e2e`) are hidden unless "Rādīt testa pārbaudes" is ticked; `api-e2e` and the screenshot server `api-screens` store their runs as `e2e`.
  - Tests: unit selection, unticked source = module not run, both rerun kinds (old run replays unchanged), grouping insert-only and results unchanged, report per grouping row identical on rebuild, Žurnāls filters and paging, import preview; vitest for the checklist, footer and groups; Playwright: property → untick a unit → run → change sources → Atjaunot → Žurnāls, import preview, groups and map zoom.
- 2026-10-12: source deep links "Skatīt avotā" (kadastrs.lv, BIS, Ozols, LVĢMC; verified patterns in `docs/data-sources.md` §8, decision "Source deep links"; links only open the source) in the view and the Excel column "Avots sistēmā". Rule set v2 (D4, agreed 2026-10-12): encumbrance codes 8317* are "Tehniskie apgrūtinājumi", never findings. Review fixes: zoom with ~30 % padding, layers of modules with findings switched on automatically, clean cards one line, labels "atrasts / nav atrasts" and "risks: …".
- 2026-10-11 (Phase 6, results view): Vite + React + TypeScript + Leaflet frontend, built in the api image (no Node on the host) and served at `/`, replacing the plain form. Input: search (`/api/suggest`) plus paste/upload, all through `POST /api/batch`. Results per run (URL `?run=&target=&view=`): header with the kadastra numurs and address, status strip (chip per module; click = card + layer), map with the checked objects by worst risk, hatched attention areas (the engine's own overlaps, risk of the fired rule) and the layers Kadastrs, Plūdi (with "nav plūdu kartes"), Daba, BIS from the run's pinned versions (view box ≤ 6 km), module cards, target switcher, overview table, Excel download. Risk always colour + icon + word (Paul Tol vibrant). D2 decided: OSM tiles. Tests: map API, vitest, Playwright end-to-end in CI, pilot map checks. Not yet: zoning (module 8), the §8.2 header (Atlase / Avoti / Žurnāls) and filter bar, the full §8.3 list.
- 2026-10-11 (freshness): freshness is checked against the source (§2.2, `docs/decisions.md` "Freshness"): "aktuāli" when we hold the latest release on data.gov.lv, a warning when a newer release is not imported or the publisher has been silent longer than `source_stale_after` (replaces `max_age`). Runs read `package_show` at start (the only live call), record it in `source_check`, and store the verdict with the run. Avoti and the source notes are in Latvian (`coverage_lv`, `processing_lv`).
- 2026-10-11 (Phase 5): batch input and the Excel report (§7.1).
  - Input: pasted list, CSV or XLSX (`vertiba`, optional `projekta_nr`, `pieteicejs_reg_nr`, `adrese`, new optional `veids`), at most 1,000 rows; via `POST /api/batch`, `check batch` and a plain page at `/` (upload or paste → Excel). The upload is not stored; the cleaned rows are (`work.run_input`, insert-only).
  - Rows (decided 2026-10-11, Janis; `docs/decisions.md` "Phase 5"): property-or-parcel numbers checked both ways ("divdomīgs: …") unless `veids` decides; precision-lost values and unclear addresses not checked and listed on "Neatrasts"; an address checked on every linked object; duplicates checked with a warning; `adrese` = module 2's given address (unresolved: object still checked, "adrese nav atrasta"); applicant reg. no. only with the legal-entity pattern.
  - Report built only from the stored run, so a replay gives the same report (`check report <id> --replay`). Sheets Kopsavilkums, Detaļas (a property per unit, fired rule id and text from the run's rule set), Avoti (versions, freshness, coverage and processing notes stored with the run; rule set and thresholds), Neatrasts. `test_set_template.xlsx` gained the `veids` column.
  - Pilot: 1,000 rows → 1,227 objects → report in about 26 s (target < 5 min).
- 2026-10-11 (Phase 4): check engine v1 built (§6); modules 1–6 store their results in runs.
  - Runs pin the live version of every source; modules read only those versions, so `replay` rebuilds an old run after newer imports. `work.check_result` rows are guarded in the DB (no `UPDATE` / `DELETE`; results only for a running run and only with its pinned versions).
  - Risk rules v1 in `config/rules.yaml` (reason per rule): **agreed by Janis Bardavskis 2026-10-11** (`status: agreed`, D4), to be revised after the test-set comparison. Each run stores the whole rule set; the aggregate order is `high > medium > unknown > low > none`.
  - §6.3 reading: the 0.5 m inward-buffered overlap decides whether there is a finding (≥ 1 m² or ≥ 0.1 %); the m² and % reported are those of the whole unit (a parcel fully in the zone shows 100 %).
  - Module 2 runs once per target; without a given address it is `no_data` "adrese nav norādīta", **counted as "not applicable", not as a data gap**, in summaries and the Excel report (decided 2026-10-11, Janis).
  - Module 5 adds "nearby": a BIS object point (WGS84 coordinates as published) within 20 m of the unit (`bis_nearby_m`), labelled **"tuvumā (≤ 20 m), nav piesaistīts objektam"**, risk `none` (agreed 2026-10-11).
  - Module 6 (decided 2026-10-11, Janis): frozen-only encumbrances are always warning lines. Next to current encumbrances they add **no risk** (rule level `none`). Only an object whose encumbrances are **all** frozen-only gets risk `unknown`; it is `found` with reason "tikai 2025-01-31 saraksta apgrūtinājumi – pārbaudīt manuāli" and lists them as items flagged `frozen` (code, description, date), never `clear`. On 100 pilot parcels: 51 had frozen-only lines next to current ones, 1 had only frozen-only ones.
  - API `POST /api/runs`, `GET /api/runs/{id}`, `/targets`, `/targets/{no}`; CLI `docker compose run --rm check run|show|replay|compare`.
  - Rules v1 draft reviewed (2026-10-11, Janis; still `status: draft`): flood outside the maps and partial coverage rate `none` (status stays `not_covered`); flood tiers ≥ 10 % high, 1–10 % medium, < 1 % low; nature by DAP `CATEGORY` and zone type (`NAME`), a zoned area decided by the zone overlapping the unit (zones link by `SITE_NAME`), every value in the data mapped and an unmapped one `unknown`; BIS exact / building-on-parcel cases medium when active (stage not Ekspluatācija / Izbeigta) or under 5 years old, else low; encumbrances medium for water, flood-plain, groundwater-source, nature and cultural-heritage codes (listed in `rules.yaml`), else low; the Baltic limited-activity belt 7311010300 stays low (it covers most of Jūrmala). On 100 pilot parcels the worst risk per parcel is high 1, medium 41, low 55, none 3.
  - Comparison tool for the returned test-set templates (`check compare`). Phase 4's "done when" (findings match the colleagues' answers) waits for those files.
- 2026-10-10 (Phase 3): input resolution built (§5).
  - Endpoints `/api/suggest`, `/api/resolve`, `/api/property/{number}/units`, `/api/address/{varis_code}/objects`; nothing is stored.
  - Classification adds 15 digits (parcel part), 9 digits (VARIS code) and Excel `precision_lost` (scientific notation with dropped digits is never resolved without confirmation).
  - Pilot data: 158 numbers are a property **and** a parcel of another property (shown as ambiguous); the seed `05000041006` is a property only (its parcel is `05000040014`, itself one of the 158).
  - Address rules: current text before earlier texts (an address split into 86A–86D keeps "86" as their earlier text); a place outside the pilot named in the input gives `outside_pilot` ("<vieta> nav pilota teritorijā"); every auto-resolved fuzzy match carries "ievadīts: '…' → atrasts: '…'".
  - Deleted-address coordinates (`dzesto-adresu-koordinatas`) deferred; the applicant reg. no. waits for Phase 8.
- 2026-10-10 (Phase 2c): BIS cases and cadastre encumbrances imported for the pilot.
  - The frozen pre-2025 encumbrance list is imported (flag `frozen`): 19,694 pilot rows with current codes are missing from the current list.
  - BIS links and frozen-encumbrance status are SQL functions of dataset versions; check results store the version ids (§6.5).
  - Module 6: frozen-only encumbrances are a warning ("apgrūtinājums no 2025-01-31 saraksta, pašreizējos datos nav – pārbaudīt manuāli"), never a plain finding, never dropped.
  - Module 5: BIS links and counts are per distinct case; duplicate raw rows are kept as published.
  - DAP `ATIS_CODE` = cadastre encumbrance codes (one classifier).
- 2026-10-09 (policy): open data only, no external permissions or approvals.
  - DPO gates and the named-exception route are removed.
  - Rule: open-data fields only; ownership = owner type; sanctions = legal entities by reg. no.; no names of natural persons stored.
  - D5, D6 and E7 are decided (E7 licence CC0-1.0 per data.gov.lv).
- 2026-10-09 (later): updated with Phase 0 steps 1 and 3 results.
  - §2.3 now has the verified datasets.
  - D1 decided: listed agency-hosted resources are allowed.
  - D9: CRS changed to EPSG:10306 (LKS-2020); PostgreSQL 18 image.
  - Module 5 join keys; module 6 is a per-parcel list (no ATIS map layer or restriction geometries).
  - Module 10 freshness; sanctions module defined.
- 2026-10-09: rewritten after a critical review.
  - Check engine and Excel report now come before the map.
  - Added a subject model (object / applicant / municipality).
  - Added explicit risk rules, unchangeable result snapshots and an operating-context section.
  - Removed contradictions between sections.

---

## 1. Operating context

**Interim answers recorded 2026-10-09 (Janis). All rows marked *interim* are to be revisited in Phase 10** (D3 in `docs/decisions.md`).

| Question | Answer | Status |
|---|---|---|
| Users | Janis + 2–3 pilot colleagues | interim, revisit in Phase 10 |
| Hosting | Local Docker on Janis's PC for Phases 1–9; shared hosting decided in Phase 10 | interim, revisit in Phase 10 |
| Sign-in | None, local only. **Required before any shared hosting** | interim, revisit in Phase 10 |
| Security review | Before shared hosting (Phase 10) | interim, revisit in Phase 10 |
| Data protection | Open-data fields only; ownership = owner type only; sanctions = legal entities by reg. no. only; no names of natural persons stored (see `docs/decisions.md`, Policy) | decided 2026-10-09 |
| Storage of uploads | Uploaded files are not stored. Only the cleaned list and the results are kept | decided 2026-10-09 |
| Retention | Keep all runs; no deletion during the MVP | interim, revisit in Phase 10 |
| Maintenance | Janis | interim, revisit in Phase 10 |
| Legal status of output | Report footer: "Informatīvs pārskats, balstīts uz atvērtajiem datiem; nav oficiāls reģistra izraksts" | interim, revisit in Phase 10 |

---

## 2. Data policy and sources

### 2.1 Rule
- **Rule:** every dataset the platform uses must be listed on **data.gov.lv**. Nothing comes from scraping, commercial services (Lursoft) or login-protected portals.
- **Agency-hosted resources (D1, decided 2026-10-09):** an official agency resource referenced from a data.gov.lv dataset page (file, WFS, ArcGIS service) is allowed. It must be listed by name in `docs/decisions.md` (D1) and in `config/sources.yaml` (`allowed_external_resources`).
- **Open data only:** the project needs no external permissions or approvals. If a dataset is missing or not open, the module is not built and shows as *unavailable* in the source registry.
- **Basemap (D2, decided 2026-10-11):** background tiles are not datasets. OpenStreetMap tiles with attribution; own tiles or a provider before shared hosting (`docs/decisions.md` D2).

### 2.2 How data gets in
- **Find:** datasets are found through the data.gov.lv CKAN API (`package_search`, `package_show`).
- **Import, never call live:** resources are downloaded and imported into PostGIS on a schedule. The app never reads data from agency services at request time. The one live call is to the **data.gov.lv catalogue** (`package_show`) at the start of a check run, to read each source's latest release date for the freshness check below; if it fails, the run goes on with the last known check.
- **Track every import:** `import_log` records the dataset id, resource id, licence, last-modified date, row counts and a file checksum. Each import becomes a **dataset version**.
- **Schema check on every import:** expected columns, types and CRS. If a source changes, the import stops and alerts; the last good version stays live.
- **Freshness against the source (decided 2026-10-11, `docs/decisions.md` "Freshness"; replaces the fixed `max_age`):** fresh means *we hold the newest file the publisher has released*, not *our copy is younger than N days*. At the start of every check run, and in `etl status`, each source's latest release is read from `package_show` (newest resource `last_modified`, or the dataset's `metadata_modified` for a source without CKAN files, as the importer does, E1/E7) and compared with the release our live version was imported from (`import_log.source_last_modified`, also counting `unchanged` imports of a re-uploaded file). Each look is recorded in `source_check`; the run stores the verdict with its pinned versions, so its report shows freshness as of the run and a replay gives the same report.
  - **We hold the latest release:** "aktuāli", text "jaunākie pieejamie dati (avots atjaunots <date>)", no warning.
  - **A newer release exists that we have not imported:** "novecojuši – pieejama jaunāka versija", warning.
  - **The publisher has released nothing for longer than the source's `source_stale_after`:** "avots nav atjaunots kopš <date>", warning. Values: cadastre text, cadastre map and encumbrances P60D; VARIS addresses and boundaries P14D; BIS P30D; flood, nature and the ATIS classifier P2Y; the frozen 2025-01-31 list none.
  - **data.gov.lv cannot be reached:** the last good check is used and the text adds "pēdējā pārbaude <date>"; with no earlier check the status is "nezināms", with a warning.
  - Later sources set their own `source_stale_after` (e.g. the VID rating, released at least 4× a year: about 120 days).

### 2.3 Availability (single source of truth)

Phase 0 steps 1 and 3 were done on 2026-10-09 (metadata, fields, join keys). Details, counts and evidence are in `docs/data-sources.md`; every resource URL is in `docs/data-sources-resources.md`. "Verified" means the dataset and fields were confirmed from data.gov.lv. **Samples (step 2) were inspected on 2026-10-09 for the MVP sources** (samples taken for Jelgava; "Sample inspection" parts in `docs/data-sources.md`). ☑☑ = metadata and sample checked.

| Source | Owner | data.gov.lv dataset(s) | Notes | Verified |
|---|---|---|---|---|
| Address Register (VARIS) | VZD | `varis-atvertie-dati` (daily, CC-BY-4.0) | CSV + `aw_shp.zip`; address code `KODS`. **LKS-2020 since 2026-10-07.** The Miro slug `valsts-adresu-registra-informacijas-sistemas-atvertie-dati` is not public (403). Sample: CSV is UTF-8 with BOM; the SHP `.prj` has no EPSG code, so assign 10306 explicitly | ☑☑ |
| Cadastre (parcels, buildings, parts, property numbers) | VZD | Text: `kadastra-informacijas-sistemas-atvertie-dati` (XML, weekly). Spatial: `kadastra-informacijas-sistemas-atverti-telpiskie-dati` (SHP per municipality, weekly) | SHP is **EPSG:10306** (LKS-2020). Layers KKParcel, KKParcelPart, KKBuilding (with `PARCELCODE`), KKWayRestriction, … in one folder per cadastral group. XML per municipality, UTF-8. `building.xml` gives the building→parcel link | ☑☑ |
| Administrative boundaries | VZD / VARAM | VARIS `aw_shp.zip` (Novadi, Pagasti, Pilsetas); `atr` | Use the VARIS layers | ☑ |
| ATIS (apgrūtinājumi) | VZD | **Per-parcel encumbrances only:** cadastre text resource "Kadastra objektam reģistrētie apgrūtinājumi" (code, description, area); classifier `atis-datu-un-kadastra-objektu-apgrutinajumu-klasifikators` | **No ATIS geometries on data.gov.lv.** Module 6 is a list per parcel, not a map layer or overlap. A frozen pre-2025-02-01 list also exists (`apgrutinajumi-kas-kadastra-registreti-lidz-2025-gada-31-janvarim`); **it is imported too** (flag `frozen`), because part of it is not in the current list (`docs/data-sources.md` §7.3). Encumbrances are also registered on buildings. DAP `ATIS_CODE` uses the same codes (§7.4). Pilot: 45,297 objects, 278,798 encumbrances | ☑☑ |
| Flood maps | LVĢMC (harvested via ĢEOLatvija.lv) | Spring 10-year: `pldu-riska-karu-atvrtie-dati-un-servisi` (SHP, geolatvija link only), `…-servisi1` (WMTS); 3rd cycle: `3-cikla-latvijas-pldu-postjumu-vietu-un-pldu-riska-kartes` (SHP, geolatvija link only), `…-kartes1` (WMS) | **Vectors: not directly downloadable from data.gov.lv.** Images (WMTS/WMS) are fine for the map layer (D1 E5). Vector candidates: geolatvija products 309/361 (D1 E6, **withdrawn 2026-10-10**: files require login) and the LVĢMC ArcGIS MapServer `Pavasara_pludu_kartes_3_cikls`, layers 0 and 1, which supports feature queries with geometry (D1 E7, **decided 2026-10-09 as the primary source**: snapshot import only; licence CC0-1.0 per the data.gov.lv listing of the same data). The Miro slug `…-servisi5` is the sea wind-surge 200-year WMTS, the wrong layer. Covers designated risk areas only. E7 sample (Jelgava): 749 polygons, only `objectid`, 5% invalid (repairable). Very large polygons need `objectIds` paging with `maxAllowableOffset=0.01` | ☑☑ (E7); E6 ☐ |
| Protected areas, microreserves, nature monuments, habitats | DAP | `ipasi-aizsargajamas-dabas-teritorijas` (incl. zoning), `mikroliegumi` (incl. buffer zones), `dabas-pieminekli`, `aizsargajamas-dzivotnes-biotopi` (SHP/GDB, annual, CC0) | LKS-92 (`.prj` has no EPSG code, so assign 3059). ArcGIS REST on ozols.gov.lv as a backup (D1 E3). Sample: UTF-8; self-intersecting rings in every polygon layer except monuments (up to 6% in buffer zones); habitat `ID` not unique, so use `GlobalID`; layers carry `ATIS_CODE` | ☑☑ |
| Zoning (TAPIS) | VARAM | `teritorijas-attstbas-plnoanas-informcijas-sistmas-tapis-eotelpiskie-dati` (WFS, EPSG:3059, layer `funkcionalais_zonejums`; D1 E4); `fz-skelumi` (VZD, quarterly) | The ~55% coverage figure is not verified. Zone types still need a common legend | ☑ |
| Construction cases (BIS) | BVKB | `bis_jlyakg7hgslonjnwyrwc6w` (cases), `bis_tln9s3hrpjlnucmjip9r3g` (case objects), `bis_04lylzfvt9f25h4divvcfq` (new builds, geo); daily, CC0 | All case types (new build, reconstruction, demolition, …). Objects carry the **building** designation (14 digits, or 17 for premise groups) and the VARIS address code, **not** the parcel designation. Sample: the case-objects CSV has 425,185 rows (the DataStore copy has only 48,000); filenames are dated, so take URLs from `package_show`. The raw CSV writes ATVK without leading zeros (padded on import). Pilot (2026-10-10): 39,448 object rows, 23,388 distinct cases; per case 65.8 % join exactly, 1.6 % probably, 24.4 % only by address code, 8.1 % not at all (`docs/data-sources.md` §7.6) | ☑☑ |
| Companies (UR) | UR | `uz` (daily, CC0) | `addressid` = VARIS address code (99% filled). **No NACE** in `register.csv` (`area-of-activity` not yet inspected) | ☑ |
| VID taxpayer rating | VID | `nodoklu-maksataju-reitings` (CC0) | Ratings A/B/C/J/N. **Updated irregularly, at least 4× a year** (not daily) | ☑ |
| VID tax debts | VID | **Not found** | Searched "nodokļu parādi / parādnieki". Module 10 uses the rating only | ✗ |
| De minimis aid | FM | `pieskirtais-de-minimis-atbalsts-latvija` (export on deminimis.fm.gov.lv, D1 E1) | Current + 2 previous fiscal years; `person_reg_nr`. Contains natural persons' names and codes: import legal-entity rows only | ☑ |
| EU co-financed projects | CFLA | `eiropas-savienibas-fondu-21-27-perioda-lidzfinansetie-projekti`, `es-lidzfinansetie-projekti`, `eiropas-savienibas-atveselosanas-fonda-lidzfinansetie-projekti` (daily, CC0) | "Īstenošanas vietas" has `KadastraNumurs` (11 digits; 65–87% filled) and `Adrese`; applicant `IesniedzejaRegNo` | ☑ |
| Procurement (EIS / IUB) | VDAA / IUB | `iepirkumu-rezultatu-datu-grupa` (EIS CSV); `ligumi`, `publisko-iepirkumu-pazinojumi` (JSON on open.iub.gov.lv, D1 E2) | Winner and buyer reg. no. | ☑ |
| Cultural heritage | KISC | `valsts-aizsargajamo-nekustamo-piemineklu-saraksts` (CSV, CC0) | `Kadastra_apzimejums` in 84% of rows; no geometry | ☑ |
| Municipal liabilities | Valsts kase | `pasvaldibu-saistibu-apmers` (annual, CC0) | Per municipality (ATVK) | ☑ |
| Ownership (īpašumtiesības) | VZD | Cadastre text resource "Īpašumtiesību statusu raksturojošie dati" | Per XSD: ownership status + person type (natural / legal / state / municipality / other) only; no names. Land book excluded. Module 7 uses the owner type only | ☑ (XSD) |
| Pre-registered buildings (**secondary cross-check, not MVP**) | VZD | `pirmsregistretas-buves` (quarterly, CC-BY-4.0, CSV/XLSX) | Building → parcel link for pre-registered buildings; no geometry. **Not an MVP source** (decided 2026-10-09). In Jelgava it covers only 18 of the 2,072 pre-registered buildings without geometry, while all 2,072 already have the parcel link in the cadastre text (`building.xml`); where both exist the parcel agrees in 1,224 of 1,224. 6,996 rows nationally have lost a leading zero. Use only as a cross-check; re-check its value on whole-country data in Phase 9 | ☑☑ |
| Sanctions | UR / FID | `sanctions` (UR, daily), `sankciju-subjektu-lidzekli-un-saimnieciskie-resursi-kas-iesaldeti-latvija` (FID) | **Available on data.gov.lv** (contrary to the earlier assumption). Contains personal data: use legal entities by reg. no. only (§6.1). EU/UN consolidated lists themselves: not found | ☑ |

### 2.4 Phase 0 checklist
1. **Inventory:** for every row above, open the data.gov.lv dataset and record resources, formats, CRS, key fields, update frequency and licence.
2. **Samples:** download one sample per source and inspect it in QGIS: ID fields, geometry validity, encoding.
3. **Join keys:** answer the questions that decide feasibility:
   - Do BIS cases carry cadastre designations?
   - Does UR have an address code?
   - Do EU projects have location data?
   - What does the cadastre say about ownership?
4. **Baseline:** time the current manual check for 5 objects with 2 colleagues. This is the number the tool must beat.
5. **Test set:** collect **14–20 real projects** with the colleagues' manual answers and the date of each check. Seed examples: Daugavpils Tautas iela 11 / `05000041006`, `13000102702`, `09000360220`, UR `90000077325`.
6. **Write up:** record findings in `docs/data-sources.md`; update the "Verified" column and section 6.
7. **CSBLatvia repo:** read `CSBLatvia/postgresql-open-data-lv` as a structural reference. It has **no licence**, so do not copy its code unless the authors grant one.


### 2.5 ETL rules (Phase 2)

These come from the CSBLatvia reference (`docs/data-sources.md` §2b) and our own sample findings. Each rule has a test (T-E*n*) that must pass in CI before Phase 2 is done.

| # | Rule | Test |
|---|---|---|
| E1 | **Resource URLs are resolved from `package_show` on every run**, never hard-coded in `etl/` (filenames contain dates, e.g. BIS `…09.10.2026.csv`). `etl/discovery/` is exempt | **T-E1:** with a mocked `package_show` that returns a re-dated resource URL, the import fetches the new file; a static check finds no `/resource/…/download/` URLs in `etl/` outside `etl/discovery/` |
| E2 | **Codes are text; restore lost leading zeros.** Designations, VARIS codes, reg. numbers and ATVK are read as strings. A digits-only value one digit short of its expected length (11 / 14 / 15 / 17) gets a leading `0` and the flag `leading_zero_restored` (VZD's own `pirmsregistretas-buves` CSV has 6,996 such values) | **T-E2:** fixture rows `1000040006002` / `1000040006` import as `01000040006002` / `01000040006` with the flag; no code column is numeric in the DB schema |
| E3 | **CSV through a real CSV parser** with `"` quoting and `""` escaping; UTF-8 with BOM handled; **the file wins over the declared metadata encoding** (VZD metadata says ISO-8859-1, the files are UTF-8) | **T-E3:** VARIS fixture fields written in the file as `"""4"""` and `"""Elektriķi 2"""` import as the values `"4"` and `"Elektriķi 2"` (quotes kept) and round-trip byte-exactly; a UTF-8 BOM file whose metadata says ISO-8859-1 imports without replacement characters |
| E4 | **XML: namespace-agnostic parsing; text fields normalised.** CR, LF and tab become single spaces and values are trimmed; backslashes are kept as data and escaped only on export | **T-E4:** the same fixture with and without `xmlns` gives identical rows; a building name containing a carriage return, a line feed, a tab and a backslash is stored normalised and round-trips through the Excel export |
| E5 | **Geometry normalisation**, in this order: assign the source CRS explicitly (VARIS and DAP `.prj` files have no EPSG code) → `make_valid` (GEOS `method=structure`; the default `linework` did not finish on the largest flood polygon, `docs/data-sources.md` §6.3) → **keep polygon parts only** → **union per key** (`CODE`; servitudes `CODE` + `PARCELCODE`) → `MultiPolygon` → transform to EPSG:10306 (EPSG:10838 grid) → check validity | **T-E5:** a fixture with a self-intersecting ring, a bow-tie that `make_valid` turns into polygon + line, and two pieces with the same `CODE` gives one valid MultiPolygon per key with no non-polygon parts and area within 0.01 %; after the pilot import, every geometry is valid and of type `MULTIPOLYGON` (`POINT` for addresses), and `(CODE, PARCELCODE)` is unique for servitudes |
| E6 | **Object kind from `OBJECTCODE` first digit**: 5 = building, 6 = engineering structure, 7 = parcel / parcel part / servitude. Any other digit stops the import | **T-E6:** the Jelgava sample imports with all `KKBuilding` = 5, engineering structures = 6, parcels / parts / servitudes = 7; a fixture row with first digit 9 fails loudly |
| E7 | **Version dates come from the source** (`dataset_version.version_date` = CKAN resource `last_modified`, or the file's own date such as XML `PreparedDate` / CSV `Data`), **never the run date**. Same checksum = same version | **T-E7:** importing the same fixture on two simulated run dates gives one version with the source date; a changed file gives a new version |
| E8 | **Storage:** full `dataset_version` snapshots for the pilot area. Per-object history (as in CSBLatvia) is reconsidered in Phase 9 for whole-country scale | — (reviewed in Phase 9) |

---

## 3. Architecture

```
data.gov.lv ──(scheduled ETL + schema check)──► PostgreSQL/PostGIS (versioned datasets)
                                                     │
                                         Check engine (Python, rules)
                                                     │
                              ┌──────────────────────┼──────────────────────┐
                        Batch runner            FastAPI API            Report builder
                     (list → results)     (resolve, results, layers)   (Excel; PDF later)
                                                     │
                                         Web UI (React + Leaflet)
```

The **check engine is the core**. The UI and the reports only display its stored results, so the Excel report, the dashboard and the PDF always agree.

**Stack**
- **DB:** PostgreSQL 18 + PostGIS 3.6 (`postgis/postgis:18-3.6`, PROJ 9.8.1, which is needed for EPSG:10306; see D9), `pg_trgm`, `unaccent`.
- **ETL and engine:** Python (geopandas / ogr2ogr / psycopg), CLI commands, cron or a simple scheduler.
- **API:** FastAPI + Pydantic.
- **Reports:** `openpyxl` for Excel. PDF later via Playwright on the server, which also captures the map.
- **Frontend:** Vite + React + TypeScript + Leaflet.
  - Pilot: layers served as GeoJSON per bounding box from the API.
  - Whole country: vector tiles via Martin, with a switch to MapLibre if Leaflet struggles with them (decide in Phase 9).
- **Dev:** Docker Compose (db, api, web).

**CRS (decided, D9):** store and analyse in **LKS-2020 / Latvia TM, EPSG:10306**, because areas and overlaps are in metres and VZD cadastre and VARIS data have been in LKS-2020 since October 2026. Sources still in LKS-92 / EPSG:3059 (DAP, TAPIS, LVĢMC) are transformed on import with EPSG:10838 (NTv2 grid `lv_lgia_lks92to2020.tif`). Serve GeoJSON in EPSG:4326.

---

## 4. Data model

**Reference data** (one table set per dataset, each row tagged with `dataset_version_id`)
- `address`: varis_code, full_text, normalized_text, hierarchy, geom
- `parcel`, `building`, `parcel_part`: designation, property_number, area, land_use, geom
- `property`: property_number, type
- `encumbrance` (per parcel or parcel part, from cadastre text data: code, description, area; **no geometry**), `flood_zone`, `nature_area` (kind: protected area / microreserve / buffer zone / nature monument / habitat), `zoning_zone`, `bis_case`, `company`, and so on
- `admin_area`
- `dataset_version`: source_id, datagov ids, last_modified, imported_at, checksum, row_count, status

**Work data**
- `project`: project_no (free text), applicant_reg_no (optional), name
- `subject`: kind (object | applicant | municipality), identifier, resolved ids, project_id. An object subject points to a property, parcel or building; an applicant subject points to a reg. no.
- `run`: who, when, selected sources, rule set version, dataset versions used
- `check_result`: run_id, subject_id, module, module_version, status, risk, rule_ids, items (jsonb), match_type, warnings, dataset_version_id, computed_at. **Never updated:** re-checking creates a new run.
- `risk_rule`: id, module, condition, level, text, version
- `source` (registry, also in `sources.yaml`): id, names, owner, group, order, type (layer / check), subject kinds, default_selected, coverage (Latvian), source_stale_after, datagov ids, licence

**Indexes:** GIST on geometries, GIN trigram on `normalized_text`, btree on codes.

---

## 5. Input resolution

### 5.1 Classification
Inputs are normalised first: strip spaces and hyphens, `unaccent`, lowercase, expand abbreviations.

| Input | Rule | Resolves to |
|---|---|---|
| 11 digits | Property number **or** parcel designation; the same value is often both. Look up both tables and show both matches when ambiguous | property / parcel |
| 14 digits | Building designation | building |
| 17 digits | Room-group designation (out of scope for checks; resolve to the building) | building |
| 15 digits | Parcel-part designation (14 digits that are no building are also tried as a parcel part without its leading 0) | parcel part |
| 9 digits | VARIS address code | address |
| Registration number (11 digits) entered in the **applicant** field or column | UR reg. no. (never guessed from the main field) | applicant |
| Text | Address: trigram + prefix match against VARIS | address → linked parcel(s) / building(s) |

**Address status (VARIS `STATUSS`: EKS eksistējošs, DEL likvidēts, ERR kļūdains; `docs/data-sources.md` §3.1):**
1. Match `EKS` addresses first, on the current text and then on earlier texts of the same code from `aw_eka_his` (renamed streets, reforms). If the address matches **only** through an earlier text, the current address is returned with warning **"atrasts pēc agrākā nosaukuma; pašreizējā adrese: <current>"**, where `<current>` is the current full address (`STD`).
2. Only if no `EKS` address matches: match a `DEL` address and return it with warning **"vēsturiska adrese"**, plus the current `EKS` address(es) if VARIS links one through `aw_eka_his.KODS_HIS` (either direction; about 3% of `DEL` addresses; several = split, list all). With no link, the result says "pašreizējā adrese nav zināma" and the object is not resolved automatically.
3. **`ERR` addresses are never matched.**

**Also (Phase 3, 2026-10-10):**
- **Current text first:** an existing address matched by its current text wins over an earlier text of another address (VARIS keeps "Ganību iela 86" as the earlier text of 86A–86D after a split).
- **Fuzzy matches are visible:** an address resolved without an exact text match carries the warning **"ievadīts: '<input>' → atrasts: '<full address>'"**. Only a clear winner with the typed house number resolves automatically; thresholds are in `config/resolve.yaml` (matching settings, not risk rules).
- **Places outside the pilot:** if the input names a city, municipality ("… novads") or parish ("… pagasts") outside the pilot and no pilot city, the row is `outside_pilot` with the reason **"<vieta> nav pilota teritorijā"**. A city name followed by a street-type word is a street ("Ventspils iela" is in Daugavpils). Suggestions from other cities always show their city.
- A designation from a cadastral territory outside the pilot, or a map-only object flagged `outside_pilot`, is `outside_pilot` too.

**Phase 3 candidate: deleted-address coordinates (deferred 2026-10-10, not adopted in Phase 3).**
- VZD's open dataset [`dzesto-adresu-koordinatas`](https://data.gov.lv/dati/lv/dataset/dzesto-adresu-koordinatas) (annual, CC-BY-4.0) gives code, end date, X/Y and full text of deleted addresses.
- For a `DEL` match **without** a `KODS_HIS` link (about 97% of `DEL` addresses), the point could locate the parcel or building there now and suggest its current address. That suggestion would be match type **"probable"**, with warning "vēsturiska adrese; iespējamā pašreizējā adrese pēc atrašanās vietas: <current>", never resolved automatically.
- **Before adopting it in Phase 3:** check the CRS of X/Y (LKS-92 or LKS-2020), the coverage of the 32,453 `DEL` addresses, and hit rates against `KODS_HIS` links where both exist. Until then, step 2 applies unchanged.

**Excel leading zeros:** a value that is 1 digit short of 11, 14 or 17 gets a `0` added at the front and the flag "leading zero restored". The fix also handles scientific notation and a trailing `.0`. Scientific notation that keeps fewer digits than the number has (Excel keeps at most 15) is flagged `precision_lost` and needs confirmation.

### 5.2 Endpoints
- `GET /api/suggest?q=&kind=cadastre|address`: ranked suggestions with type labels
- `GET /api/property/{number}/units?include_non_existing=false`: linked parcels, buildings, parcel parts and premise groups, plus buildings on its parcels that belong to other properties (non-existing buildings only on request, §6.3)
- `GET /api/address/{varis_code}/objects`: cadastre objects for an address (a deleted address lists its current successors)
- `POST /api/resolve`: raw values in (max 1,000); per row: type, match status, matches, corrections, warnings, duplicates; plus the dataset versions read. Examples: `docs/runbook.md`
- `GET /api/sources`: the source registry

---

## 6. Check engine

### 6.1 Modules

| # | Module | Subject | Source | Phase | Notes |
|---|---|---|---|---|---|
| 1 | Cadastre facts | object | Cadastre | 4 | Units, areas, land use, buildings |
| 2 | Address consistency ("Neatbilst") | object + given address | VARIS + Cadastre | 4 | Flags when the given address is not linked to the given designation |
| 3 | Protected nature (OZOLS scheme) | object | DAP datasets | 4 | Separate lines: protected area, microreserve, buffer zone, nature monument, habitat |
| 4 | Flood (10-year) | object | LVĢMC | 4 | Intersect yes/no, share of area; outside coverage = `not_covered`. **Coverage = the 200-year extent (E7 layer 3), used only as a mask** (decided 2026-10-09; no APSFR polygons are open). Outside it: `not_covered`, never `clear`, reason "ārpus plūdu kartēs attēlotās teritorijas – plūdu karte šeit nav pieejama vai teritorija nav applūstoša pat 200 gadu scenārijā"; limitation: "not modelled" and "dry even at 0.5 %" look the same (`docs/decisions.md`, E7). Source: **LVĢMC MapServer `Pavasara_pludu_kartes_3_cikls`, layers 0 and 1 (Salaca), D1 E7**, imported as a versioned snapshot and never queried live; EPSG:3059 → 10306 on import. No fallback: geolatvija SHP (E6) withdrawn 2026-10-10 (files require login). Licence CC0-1.0 (per the data.gov.lv listing of the same data) |
| 5 | Construction cases (BIS) | object | BIS | 4 | BIS has no parcel designation. Join keys, in this order: (a) building designation (17-digit premise groups cut to 14) → **the cadastre's own building→parcel link** (`building.xml` `ObjectRelation` + `ParcelCadastreNrList`); (b) **building designation prefix** (first 11 digits = the parcel the building was created on), as a fallback only for buildings missing from the cadastre, with match type "probable"; (c) **VARIS address code** (`Buves_objekta_adreses_kods` / `Buves_adreses_kods`), matched against both the building's and the parcel's VARIS code. **Verified on Jelgava samples:** the prefix equals the cadastre parcel in 90.5% (case objects) and 93.4% (new builds) of buildings found. The other ~7–10% are re-formed parcels, so the prefix alone is not exact. The address code matches the building or parcel VARIS code in 84%. Match types: exact building / building on parcel (cadastre link) / probable parcel (prefix) / same address code / same property / nearby (coordinates, fuzzy). **Counted per distinct case:** the case-objects CSV repeats rows (34,040 exact duplicates nationally); raw rows are stored as published, but links (`ref.bis_links`, one row per case and target, with the source row numbers as evidence) and every number shown to users count distinct cases. The colleagues' example: 13 cases, only 3 exact |
| 6 | Registered encumbrances (apgrūtinājumi) | object | Cadastre text data (encumbrances resource, ATIS-coded) + frozen list until 2025-01-31 | 4 | **A list per parcel, parcel part or building:** code, description, area, registration date. No ATIS geometries are open, so there is no map layer and no spatial overlap. **Frozen-only encumbrances** (in the 2025-01-31 list, object still in the cadastre, code not in the current list; `ref.encumbrance_frozen_status`, column `frozen_only`) are **reported as a warning, never as a plain finding and never dropped**, with the text **"apgrūtinājums no 2025-01-31 saraksta, pašreizējos datos nav – pārbaudīt manuāli"**, one line per encumbrance with its code, description and date. An object whose only encumbrances are frozen-only gets the same warning and is never `clear`. The warning has no risk level of its own (risk comes only from `rules.yaml`) |
| 7 | Ownership status | object | Cadastre (owner type only) | 8 | Owner type only (`PersonStatus`: natural / legal person, state, municipality, other). Never names of natural persons |
| 8 | Zoning | object | TAPIS | 6 | Common legend mapping; partial coverage |
| 9 | Applicant registry | applicant | UR | 8 | Status, form, legal address, dates. **Built (8a):** UR register + insolvency proceedings of legal entities; IK/IND names not stored (D10) |
| 10 | Applicant tax (VID rating) | applicant | VID | 8 | Rating A/B/C/J/N with its date. Freshness: `source_stale_after` about 120 days (the source is updated irregularly, at least 4× a year). **No tax-debt data on data.gov.lv**, so the module does not claim to check debts |
| 11 | De minimis | applicant | FM | 8 | Aid in the relevant period. Legal-entity rows only |
| 12 | EU double funding | object + applicant | EU projects | 8 | Other EU-funded projects on the same object or for the same applicant |
| 13 | Procurement | applicant | IUB / EIS | 8 | |
| 14 | Companies at address | object | UR | 8 | Legal address only, labelled "not proof of activity". **Built (8a):** join on the VARIS code (UR `addressid`), with the building's use and area |
| 15 | Cultural heritage | object | KISC | later | Match on `Kadastra_apzimejums`; no geometry |
| 16 | Municipal liabilities | municipality | Valsts kase | later | Per ATVK |
| 17 | Sanctions (legal entities) | applicant | UR `sanctions`, FID frozen-asset subjects | 8 | Legal entities only. Match **only by reg. no.** (applicant reg. no. against `legal_entity_registration_number` / `sanctions_subject_registration_number`). A name-only hit is never a finding: it is flagged "manual review" with no risk level. Natural-person fields (name, birth date, personal code) are never imported. **Built (8a), D10 option A:** natural-person rows not stored at all; option B pending DPO assessment |

### 6.2 Module contract
```
check(subject, dataset_version) -> {
  module, module_version, subject: {kind, id},
  status: found | clear | not_covered | no_data | source_unavailable | error,
  reason: text | null,             # required for no_data, e.g. "nav ģeometrijas"
  risk: high | medium | low | none | unknown,
  rule_ids: [...],                 # risk rules that fired
  items: [...], match_type,
  warnings: [...],                 # e.g. stale data, partial coverage, leading zero restored, no_geometry
  source: {id, name, dataset_date, dataset_version_id, datagov_url},
  computed_at,
  display: {kind: kv|table|badges|text, columns: [...]}
}
```

**Status meanings:**
- `found`: the source covers the object and has relevant records.
- `clear`: the source covers the object and nothing relevant was found.
- `not_covered`: the source does not cover this area, e.g. outside the flood maps' 200-year extent (the module 4 coverage mask) or with no zoning vectors. This is never reported as "clear".
- `no_data`: the object itself was not found in the dataset, **or it has no geometry** (see §6.3). Always comes with a `reason`.
- `source_unavailable` / `error`: the import is missing or the check failed.

### 6.3 Spatial rules
- Intersections use the parcel geometry **buffered inward by 0.5 m** to avoid boundary slivers. A finding also needs an overlap of **≥ 1 m² or ≥ 0.1% of the parcel**. Both thresholds live in config and are listed in the report.
- Every overlap reports its area in m² and its % of the parcel.
- A property with several units: results are per unit, plus an aggregate (worst risk wins).
- **Objects without geometry:** some objects are in the register but have no geometry (e.g. pre-registered buildings, point and linear engineering structures; ~9% of buildings in the Jelgava sample, `docs/data-sources.md` §3.2). They always get the warning **`no_geometry`** and are **never** `clear` because of a missing geometry. Spatial modules (3, 4, 8 and the spatial matches in 5) then work as follows:
  1. **Building without geometry, parcel with geometry:** run on the geometry of the parcel(s) the cadastre links the building to (`building.xml`), with warning **"pārbaudīts pēc zemes vienības"**. Results are labelled as parcel-level.
  2. **Neither the building nor its parcel(s) has geometry** (or the object is a parcel without geometry): status **`no_data`** with reason **"nav ģeometrijas"**, risk `unknown`.

  Non-spatial modules (1, 2, 6, 7) still run on register data. A property whose units partly lack geometry is checked on the units that have it; the aggregate carries the warning.
- **Buildings marked non-existing** (`NotExist` "Būve apvidū nav konstatēta"; 272 in Jelgava, 264 of them still drawn on the map):
  - stay resolvable when entered directly, with warning **"reģistrā atzīmēta kā neeksistējoša"**;
  - are **excluded from "buildings on parcel" lists** (module 1, `/api/property/{number}/units`, the entry-dialog unit checklist) unless the user asks for them (`include_non_existing=true`).

### 6.4 Risk rules
- Risk levels come only from `risk_rule` entries, e.g.:
  - "microreserve overlap > threshold → high"
  - "BIS case on the exact parcel → medium"
  - "outside flood coverage → unknown"
- Rules are versioned and kept in `rules.yaml`, reviewed with the team leads, and the rule-set version is printed on every report.
- **No AI or LLM decides risk.** An LLM may later write a plain-language summary of stored results, clearly labelled.

### 6.5 Snapshots and evidence
- Each run stores its results and the dataset versions used. Old reports can be reproduced and are never silently changed by a data refresh.
- **Derived links are functions of versions, not stored tables.** Matches that combine sources are SQL functions of the dataset versions they read, deterministic for the same version ids: BIS links `ref.bis_links(bis_version, cadastre_text_version)` (module 5) and frozen-encumbrance status `ref.encumbrance_frozen_status(frozen_version, encumbrance_version, cadastre_text_version)` (module 6). The `_current` views call them with the live versions. **A check result stores every version id it used** (for module 5 both the BIS and the cadastre text version id; for module 6 the encumbrance, frozen-list and cadastre text version ids) in its `run` / `check_result` record, so an old report is rebuilt by calling the same functions with the stored ids. Superseded versions keep their rows (E8), so this works for any past run.
- Re-running creates a new run. The UI shows "results from <date>; newer data available" when relevant.

---

## 7. Outputs

### 7.1 Excel report (MVP)
- **Sheet "Kopsavilkums":** one row per object with:
  - project no., input value, resolved designation, address
  - one column per module with a status icon and risk
  - overall risk
  - warnings
- **Sheet "Detaļas":** one row per finding: object, module, item, overlap, match type, risk rule, source, dataset date, data.gov.lv link.
- **Sheet "Avoti":** each source with dataset version, date, freshness status and coverage note, plus the rule-set version and thresholds.
- **Sheet "Neatrasts":** inputs that could not be resolved, with a reason and suggestions (also an unresolved `adrese` and a dropped applicant number).
- Built only from the stored run (`reports/excel.py`); module 2 without an address shows "nav piemērojams". Input rules: `docs/decisions.md` "Phase 5".
- Footer text (§1): "Informatīvs pārskats, balstīts uz atvērtajiem datiem; nav oficiāls reģistra izraksts." The data dates are on the "Avoti" sheet.

### 7.2 PDF evidence report (after the MVP)
One object per report: map snapshot with active layers and legend (rendered on the server with Playwright), all module results, sources and dates. It replaces the manual screenshots.

---

## 8. User interface (after the MVP)

### 8.1 Entry dialog
A modal "Meklēt īpašumu" on first load; "Skip to map" closes it and "New search" reopens it.
1. **Kadastrs field:**
   - type-ahead from 3 digits; type badge (property number / parcel / building)
   - ambiguous 11-digit values show both matches
   - pasted lists are cleaned automatically
2. **Related apzīmējumi** (when a property number is picked):
   - checklist of units with a tri-state "Select all" (all ticked by default)
   - counter "5 of 12"; filter by type
   - entering a parcel offers "show all units of this property"
3. **Address field:** diacritic- and typo-tolerant type-ahead on VARIS (2–3 characters, ~200 ms debounce); resolves to linked objects with the same checkboxes. If the address and kadastrs point to different objects, show a notice and run the "Neatbilst" check.
4. **Projekta Nr.** and **Applicant reg. no.** (both optional). The applicant field enables modules 9–13.
5. **Sources checklist:**
   - built from the registry; all ticked by default; group headers
   - sources not valid for the given subjects are greyed out (e.g. applicant checks without a reg. no.)
   - partial-coverage sources carry a note
6. **Import CSV / Excel:**
   - template download; columns `vertiba`, optional `projekta_nr`, `pieteicejs_reg_nr`, `adrese`
   - auto-detects the delimiter (`;`/`,`) and the encoding (UTF-8 / Windows-1257)
   - preview with detected type, match status, corrections and duplicates
   - error list download; limit 1,000 rows for the MVP
   - files are read on the server with the batch reader and not stored (decided 2026-10-12, Phase 7); removing a row in the preview re-sends the file with the rows to skip
7. **Footer:** "N objects, M sources" + **Meklēt**.

### 8.2 Main screen
1. **Header:** *Atlase / Avoti / Žurnāls*. What Avoti and Žurnāls contain is still to be confirmed with the colleagues. Proposal:
   - **Avoti:** the source registry with dates and coverage
   - **Žurnāls:** the user's past runs
2. **Filter bar:**
   - source chips toggle on and off
   - **Atjaunot** marks pending changes and creates a new run
   - a banner shows when filters have changed but not been applied
3. **Target switcher:**
   - Project dropdown (incl. "Visi projekti") + searchable object combobox with ◀ ▶ and "3 / 12"; keyboard ← → and `/`
   - "Objekti" drawer: tree of projects → numuri → apzīmējumi, with status badges
   - groups can be created, renamed and moved
4. **Object header:**
   - the kadastra numurs (large) and address; buttons *Atlase*, *Excel*, *PDF*
   - several units of one property default to the property view with all units highlighted
5. **Map:**
   - zoomed to the object; marker and address chip
   - combinable layer toggles *Vieta, Plūdi, Zonējums, Daba, Kadastrs* with opacity
   - legend for the active layers only, with source and date
   - click to identify a feature; scale bar; attribution
   - layers come from the layer registry and are hidden when their source is unticked
6. **Results list:**
   - status strip (one chip per source; click scrolls to the card and shows its layer)
   - one card per source in registry order; findings open by default, clean cards collapsed
   - footer per card: source, dataset date, run date, data.gov.lv link; per-unit breakdown
   - lazy loading per card with Retry
   - generic renderer driven by `display`
7. **Group overview:** all objects of a project on the map + the summary table (same as the Excel "Kopsavilkums"); a row click opens that object.

**Plūdi layer:** shows only the 3rd-cycle spring-flood 10-year scenario. Other scenarios sit behind a config flag; a sea-surge (*Jūras vējuzplūdi*) switch appears only if the data exists for the area. Outside coverage: "Šajā teritorijā plūdu karte nav pieejama".

**Sessions and Žurnāls** are stored on the **server**. Until sign-in exists (Phase 10), Žurnāls lists every run on the server (runs of test servers hidden by default); with sign-in it becomes per user (decided 2026-10-12, Phase 7). The URL holds `?run=&target=&view=&tab=`.

### 8.3 UI acceptance criteria
- `05000041006` shows the correct badge; its units appear, and Select all works in one click.
- An ambiguous 11-digit value shows both matches.
- `riga tautas` and typo variants give suggestions in < 300 ms.
- An `.xlsx` file with lost leading zeros resolves correctly and reports the fix.
- Unticking a source and pressing Atjaunot removes its card and layer.
- A failing source shows an error card while the other cards display normally.
- Switching between any two objects takes ≤ 2 clicks or ← →; the shared URL restores the view.
- The legend always matches the active layers; Plūdi shows only the 10-year scenario.
- Keyboard-only use works; the UI is in Latvian by default, with English switchable.

---

## 9. Roadmap

**MVP = phases 0–5:** a list in, an Excel report out, for the pilot area (the cities of Jelgava, Jūrmala and Daugavpils), covering modules 1–6.

| Phase | Deliverable | Done when |
|---|---|---|
| 0. Discovery | `docs/data-sources.md`, completed availability table, manual-time baseline, 14–20 test projects, operating-context answers (section 1) | Every MVP source verified or explicitly dropped |
| 1. Foundation | Repo, Docker Compose, PostGIS, CI, `CLAUDE.md`, `sources.yaml`, `rules.yaml` skeleton. **Custom DB Dockerfile `FROM postgis/postgis:18-3.6`** that bundles `lv_lgia_lks92to2020.tif` (from cdn.proj.org, CC-BY 4.0, checksum pinned) into the PROJ data directory (D9) | `docker compose up` gives an empty DB + API health check. **CRS test (in CI)**: fails if the grid file is missing, if PROJ < 9.8 or SRID 10306 is unknown, or if the EPSG sample point Odukalns 56.8283960°N 24.2727688°E (LKS-92) does not transform to 56.8283967°N 24.2727679°E (LKS-2020) **within 1 cm** |
| 2. ETL | Pilot area (Jelgava, Jūrmala, Daugavpils): VARIS, cadastre, admin boundaries, flood (if a vector source is confirmed), nature, cadastre encumbrances, BIS; transform 3059 sources to 10306; dataset versions; schema checks | Row counts match the sources; re-runs are idempotent; a changed schema fails loudly; **ETL rule tests T-E1 to T-E7 (§2.5) pass in CI** |
| 3. Resolution | `/suggest`, `/resolve`, property units; leading-zero repair | Test-set inputs resolve correctly, including ambiguous ones |
| 4. Check engine v1 | Modules 1–6, spatial rules, risk rules v1, stored runs and results | The test set's findings match the colleagues' manual answers, with differences explained by data dates |
| 5. Batch + Excel | CLI and API: list (pasted or CSV/XLSX) → run → Excel report; a plain input page. **Built and tested 2026-10-11** | **Pilot with 2–3 colleagues; measured time per object vs the baseline** (open) |
| 6. Map + dashboard | Main screen (section 8.2), layers incl. zoning (module 8), results list. **Results view built 2026-10-11** (map, layers, attention areas, cards, overview); zoning, header tabs and filter bar open | UI criteria pass for the pilot area |
| 7. Entry dialog + projects | Full entry dialog, import UI, project grouping, server-side sessions (needs sign-in). **Built 2026-10-12** (entry dialog, import preview, unit selection, Atjaunot and latest-data reruns, project groups, Avoti and Žurnāls); per-user sessions wait for sign-in (Phase 10) | UI criteria pass |
| 8. Applicant & funding | Modules 7 and 9–14, and 17–18. **8a built 2026-10-12:** modules 9, 14, 17 (rules v3 agreed). **8b built 2026-10-13:** modules 7, 10–13, 18 (D11; rule set v4 agreed) | Each module verified on the test set; v4 agreed |
| 9. Whole country + performance | Full import, vector tiles, MapLibre decision, storage review (E8: snapshots vs per-object history), re-check value of `pirmsregistretas-buves` on whole-country data | Search < 300 ms; a 1,000-row batch finishes in < 5 min |
| 10. Hardening | Scheduled refresh, monitoring, alerts, runbook, PDF report, D3 final: shared hosting, sign-in (required before sharing), security review, retention, maintenance, legal wording; deployment behind sign-in | A refresh runs unattended; a failed import alerts the owner |

**Pilot area (decided 2026-10-09): the cities of Jelgava (ATVK 0003000), Jūrmala (0004000) and Daugavpils (0002000).** Together they cover all seed examples (§2.4) and have 10-year flood coverage of 15.9%, 10.2% and 8.0% of their area (`docs/data-sources.md` §2a). Samples were inspected for Jelgava; Jūrmala and Daugavpils use the same source formats. Final check against the test set (step 5) later.

---

## 10. Risks and open decisions

**Risks**
- **ATIS geometries are not open** (confirmed in Phase 0). Module 6 can only list encumbrances registered on the parcel; it cannot show restricted areas that are not yet registered. Reports must say so; non-open ATIS data is not used.
- **Flood vectors** are not directly downloadable from data.gov.lv. Module 4 uses D1 E7 (LVĢMC MapServer snapshot), with no fallback (E6 withdrawn 2026-10-10: files require login). The licence is still to be confirmed with LVĢMC (`docs/decisions.md`).
- **Missing join keys:** if BIS, UR or EU-project data has no cadastre or address codes, the matching is fuzzy and may be wrong. Show the match type and confidence; never present a fuzzy match as exact.
- **Over-trust:** evaluators may read "clear" as "no risk". The status wording (`clear` vs `not_covered` vs `no_data`) and the report footer must make the limits visible.
- **Freshness:** open data lags the live registries, especially for tax and company status. The stale-data warnings and the report date are mandatory.
- **Personal data:** modules use only open-data fields. No names of natural persons (owners, board members, aid recipients, sanctioned persons) are stored. Ownership = owner type only; sanctions = legal entities by reg. no. only.
- **Licences:** confirm reuse and attribution terms for each dataset and the basemap.
- **Bus factor:** one developer. The runbook, the tests and `CLAUDE.md` are deliverables, not extras.
- **Data volume:** whole-country parcels and buildings are large. The pilot area (three cities) comes first; tiles and indexes come before scaling.

**Open decisions**

| # | Decision | Needed by |
|---|---|---|
| D1 | Agency-hosted resources listed on data.gov.lv count as data.gov.lv? | Phase 0 |
| D2 | Basemap: **decided** OSM tiles with attribution (2026-10-11) | Phase 6 |
| D3 | Hosting, sign-in, security review, retention, maintenance, legal status (section 1; interim answers recorded) | Phase 10 |
| D4 | Risk rules v1, agreed with the team leads: **decided**, v1 agreed 2026-10-11 (revise after the test-set comparison) | Phase 4 |
| D5 | Ownership module: **decided**, owner type only | Phase 8 |
| D6 | Sanctions: **decided**, legal entities by reg. no. only (module 17) | Phase 8 |
| D7 | Contents of Avoti and Žurnāls: **decided** (2026-10-12, `docs/decisions.md`) | Phase 6 |
| D8 | Project number format: **decided**, free text (2026-10-12) | Phase 7 |
| D9 | Storage CRS: **decided** EPSG:10306 (LKS-2020); see `docs/decisions.md` | Phase 1 |

D1 is **decided** (2026-10-09): listed agency-hosted resources are allowed; see `docs/decisions.md`.

---

## 11. Working with Claude Code in VS Code

1. **Set up the repo:** add this file and a `CLAUDE.md` covering:
   - stack, folder layout, run and test commands
   - CRS = EPSG:10306 (LKS-2020; D9)
   - "verify data endpoints before coding against them"
   - "results are unchangeable; never compute risk outside `rules.yaml`"
2. **Work phase by phase:** ask Claude Code for a short plan per phase, implement with tests, and commit per phase.
3. **Repo layout:**
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
4. **First prompt:** *"Read PLAN.md. Execute Phase 0 steps 1–3: for every row in section 2.3, find the data.gov.lv dataset via the CKAN API, list its resources, formats, CRS, key fields, update frequency and licence, and answer the join-key questions. Write docs/data-sources.md. Do not write application code yet."*
