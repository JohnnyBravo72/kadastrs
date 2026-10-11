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
| `check` | check engine CLI: `run`, `show`, `replay`, `compare` (profile `check`) | — |

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
  prints how many **distinct** pilot cases match exactly (building in the cadastre), probably (designation prefix = a parcel), only by address code, or not at all. Duplicate rows in the BIS file are stored as published but never counted twice: `ref.bis_links` has one row per case and target, with the source row numbers in `row_nos`.
- **Encumbrances:** `ref.encumbrance_current` (current list joined with the classifier text) and `ref.encumbrance_frozen_current` (frozen list with `in_current`, `object_in_cadastre`, `frozen_only`). Frozen-only rows are never shown as current encumbrances.
- The ETL runs the checked-out code (mounted read-only), so code changes need no rebuild. Rebuild after dependency changes: `docker compose --profile etl build etl`.

Import history:

```powershell
docker compose exec db psql -U kadastrs -d kadastrs -c "SELECT id, source_id, status, started_at, message FROM import_log ORDER BY id DESC LIMIT 20"
```

## Input resolution (API)

The API turns raw values (kadastra numuri, apzīmējumi, VARIS codes, addresses) into cadastre objects (PLAN.md §5). It reads the **live** versions of `cadastre_text`, `cadastre_spatial`, `varis_addresses` and `admin_boundaries`; if one is not imported, the endpoints answer **503**. Nothing is stored. Matching thresholds are in `config/resolve.yaml` (mounted, no rebuild needed); code changes need `docker compose up -d --build --wait`. Interactive docs: `http://127.0.0.1:8000/docs`.

Use `curl.exe`, not `curl` (in Windows PowerShell 5.1, `curl` is an alias of `Invoke-WebRequest`):

```powershell
# type-ahead: designations by prefix (from 3 digits; a prefix without its leading zero is also tried)
curl.exe -s "http://127.0.0.1:8000/api/suggest?kind=cadastre&q=0500004100"

# type-ahead: addresses (diacritic-, case- and typo-tolerant; every entry carries its city)
curl.exe -s -G "http://127.0.0.1:8000/api/suggest" --data-urlencode "kind=address" --data-urlencode "q=riga tautas"

# units of a property (buildings marked non-existing only on request)
curl.exe -s "http://127.0.0.1:8000/api/property/05000041006/units"
curl.exe -s "http://127.0.0.1:8000/api/property/09000360220/units?include_non_existing=true"

# cadastre objects at a VARIS address code
curl.exe -s "http://127.0.0.1:8000/api/address/101765287/objects"

# bulk: raw values in, one row per value out (max 1,000 rows)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)   # send ā, ē, ... as UTF-8
'{"values": ["5.000041006E9", "05000040014", "Prohorova iela 28A, Jelgava", "riga tautas"]}' |
  curl.exe -s -X POST "http://127.0.0.1:8000/api/resolve" -H "Content-Type: application/json" --data-binary "@-"

# the same with a column kind per row ("auto" | "cadastre" | "address")
'{"rows": [{"value": "Tautas iela 11, Daugavpils", "kind": "address"}, {"value": "5000041006", "kind": "cadastre"}]}' |
  curl.exe -s -X POST "http://127.0.0.1:8000/api/resolve" -H "Content-Type: application/json" --data-binary "@-"
```

How `/api/resolve` reads a value:

| Input | Read as |
|---|---|
| 11 digits | property number **or** parcel; both are looked up. If the parcel belongs to another property: `ambiguous`, both listed |
| 14 / 15 digits | building / parcel part (14 digits that are no building are also tried as a parcel part that lost its leading 0) |
| 17 digits | premise group → its building (first 14 digits), warning `premise_group_to_building` |
| 10 / 13 / 16 digits | a lost leading zero is restored (correction `leading_zero_restored`) |
| 9 digits | VARIS address code |
| `5.000041006E9`, `05000041006.0`, `0500 004 1006`, `'05000041006` | Excel damage undone, each step listed in `corrections`; scientific notation with dropped digits gives `precision_lost` and is never resolved without confirmation |
| text | address: current text → earlier text (`earlier_name`) → deleted address (`historical_address`, resolved only through a single `KODS_HIS` successor); a fuzzy auto-match carries `ievadīts: '…' → atrasts: '…'` |
| a city, municipality or parish outside the pilot named in the text | `outside_pilot`, reason "<vieta> nav pilota teritorijā" (a city name followed by "iela", "prospekts", … is a street) |

Row statuses: `resolved`, `ambiguous` (pick from `matches`), `not_found`, `unresolved` (deleted address without a known successor), `outside_pilot`, `invalid`, `empty`. Repeated objects get `duplicate_of`. The response lists the dataset `versions` it read.

## Checks (runs and results)

The check engine (`engine/checks`, PLAN.md §6) runs modules 1–6 on resolved objects and **stores** every result. A run pins the live version of every source at its start; modules read only those versions. Results are never changed: the database rejects `UPDATE` and `DELETE` on `work.check_result`, `work.run_target` and `work.run_version`, and a finished `work.run` (CLAUDE.md rule 3). Checking again creates a new run.

| Module | id | Status values used |
|---|---|---|
| 1 Kadastra dati | `cadastre_facts` | `found`, `no_data` (not in the register) |
| 2 Adreses atbilstība | `address_consistency` | `clear` (given address linked), `found` "Neatbilst", `no_data` "adrese nav norādīta" (**counted as `not_applicable`** in summaries) |
| 3 Aizsargājamā daba | `nature` | `found` (one line per feature and kind), `clear`, `no_data` "nav ģeometrijas" |
| 4 Plūdi (10 gadu) | `flood_10y` | `found`, `clear` (warning `partial_coverage` if part of the unit is outside the mask), `not_covered` (outside the 200-year mask), `no_data` |
| 5 Būvniecības lietas | `bis` | `found` (one item per distinct case, best match type first, with `match_label`, e.g. "tuvumā (≤ 20 m), nav piesaistīts objektam"), `clear` |
| 6 Apgrūtinājumi | `encumbrances` | `found` (current encumbrances; frozen-only ones next to them are warning lines, no risk increase), `found` with reason "tikai 2025-01-31 saraksta apgrūtinājumi – pārbaudīt manuāli" (all frozen-only: listed as items with `frozen: true`, risk `unknown`, never `clear`), `clear` |

Any module can also give `source_unavailable` (no live version) or `error` (reason holds the exception). **Risk comes only from `config/rules.yaml`** (mounted; edits apply to the next run). Rule set v1 is **agreed** (`status: agreed`, D4, 2026-10-11); a changed rule set gets a new version and is `draft` until agreed. Each run stores the whole rule set and its SHA-256, and summaries show version and status. Thresholds (§6.3) are in the same file: 0.5 m inward buffer, overlap ≥ 1 m² or ≥ 0.1 %, BIS "nearby" 20 m. The buffered overlap decides whether there is a finding; the m² and % reported are those of the whole unit.

A **property** is checked per unit (parcels and buildings; buildings marked non-existing left out) plus an aggregate with the worst risk (`risk_order` in `rules.yaml`). Module 2 runs once per target. A building without geometry is checked on its parcel (warning `parcel_level`, "pārbaudīts pēc zemes vienības").

API (resolve first, then send the chosen objects; `sources: null` = the registry defaults, max 1,000 targets):

```powershell
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
'{"targets": [{"type": "property", "designation": "05000041006", "given_address": "101808322"},
              {"type": "parcel", "designation": "09000050400"}],
  "sources": null}' |
  curl.exe -s -X POST "http://127.0.0.1:8000/api/runs" -H "Content-Type: application/json" --data-binary "@-"

curl.exe -s "http://127.0.0.1:8000/api/runs/1"             # summary: rule set, versions, counts per module
curl.exe -s "http://127.0.0.1:8000/api/runs/1/targets"     # one line per object: status and risk per module
curl.exe -s "http://127.0.0.1:8000/api/runs/1/targets/0"   # all results of one object (units of a property too)
```

CLI (`check` service, profile `check`; built from the api image like `etl`):

```powershell
docker compose run --rm check run 09000360220 "Tautas iela 11, Daugavpils"   # resolve + new run
docker compose run --rm check show 13 [--json]
docker compose run --rm check replay 13     # recompute from the pinned versions; exit 1 if anything differs
```

`replay` is the reproducibility check (§6.5): a run is recomputed from its stored versions and rule-set snapshot, also after newer imports. It reproduces runs made by the same engine code; a run from an older engine version prints a note, and differences then show what the code change altered.

### Comparing with the colleagues' answers

When a filled copy of `tests/data/test_set_template.xlsx` comes back, put it in the repo (e.g. `tests/data/returned/`, not committed if it holds anything beyond designations) and run:

```powershell
docker compose run --rm check compare tests/data/returned/kolegis1.xlsx
```

It resolves each `vertiba`, checks all objects in one new run (origin `compare`) and writes `<file>_salidzinajums.xlsx` next to the input: one row per object and module with the manual answer, the engine status, **sakrīt / atšķiras / nav atbildes / nav salīdzināms**, the engine's risk and finding, the data dates and the manual check date ("Dati jaunāki par pārbaudi" = a source is newer than the manual check, so the difference may be explained by data dates). Answers are read from their first words: «Ir…» = `found`, «Nav» = `clear`, «Nav datu» = `no_data`, «Nav pārklājuma» = `not_covered`; for module 2, «Ir» means a mismatch was found. The yellow example rows (`PIEMĒRS…`) are skipped. An ambiguous number is checked as its first match and an address with several objects as its parcel, both with a note.

## Run the tests

```powershell
docker compose --profile test run --rm tests
```

This builds the test image if needed, starts `db`, `migrate`, `api`, `db-nogrid` and `migrate-test`, and runs pytest with the repo mounted at `/src`. Code changes need no rebuild.

The ETL rule tests (`tests/etl`) import synthetic files through a fake data.gov.lv into the separate `kadastrs_test` database, so they never touch your data. The resolution tests (`tests/resolve`) load a small synthetic pilot (seed objects, ambiguous numbers, renamed and deleted addresses) into the same database and call the API in-process. The engine tests (`tests/checks`) add synthetic flood, nature, BIS and encumbrance rows to that pilot (layout in `tests/checks/conftest.py`): every status of modules 1–6, the §6.3 thresholds and geometry fallback, the property aggregate, the database guards, determinism, replay after a new import, the comparison tool and the run API.

**The `pilot` tests check the real import in the dev database** (row counts against the source files, geometry, seed objects, and that a second run created no new versions). They **fail when nothing is imported**, so import twice first:

```powershell
docker compose run --rm etl import all
docker compose run --rm etl import all
docker compose --profile test run --rm tests
```

The pilot tests take about 3 minutes. The resolution checks (`tests/pilot/test_pilot_resolve.py`) cover the seed objects, every real property-or-parcel ambiguity, all leading-zero lengths, Excel-mangled inputs, typos and diacritics, renamed and deleted addresses, 300 random existing addresses, and `/api/suggest` p95 under 300 ms (printed with `-s`). The engine checks (`tests/pilot/test_pilot_checks.py`) run the flood regression parcels (`tests/data/flood_regression.yaml`), the seed objects and 100 parcels (under 30 s, then replayed with identical results); their runs stay in the dev DB like any run. The BIS and encumbrance checks (`tests/pilot/test_pilot_bis_encumbrances.py`) recount rows from the raw files, compare every stored designation and ATVK with the raw file (no lost leading zero), check the BIS join counts and that the DAP `ATIS_CODE` values are classifier codes. The four giant flood polygons (over a million vertices) are not validated again there: the import validates every stored geometry and records the count in the version's processing notes, which the test checks (re-validating them takes over an hour).

Without real data, run everything else:

```powershell
docker compose --profile test run --rm tests python -m pytest -p no:cacheprovider -m "not pilot"
```

A subset or extra pytest options:

```powershell
docker compose --profile test run --rm tests python -m pytest -p no:cacheprovider tests/test_crs.py -v
```

After changing **dependencies** (`pyproject.toml`, `constraints.txt`) or a **Dockerfile**, rebuild:

```powershell
docker compose --profile test --profile etl --profile check build
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
