# DB image

`Dockerfile` builds PostgreSQL 18 + PostGIS 3.6 with the LKS-92 → LKS-2020 grid (decision D9 in [`docs/decisions.md`](../../docs/decisions.md)).

## `lv_lgia_lks92to2020.tif`

| | |
|---|---|
| What | NTv2 horizontal grid (GeoTIFF) for the transformation **EPSG:10838 "LKS-92 to LKS-2020 (1)"** |
| Producer | Latvijas Ģeotelpiskās informācijas aģentūra (LĢIA) |
| Obtained from | `https://cdn.proj.org/lv_lgia_lks92to2020.tif` (PROJ-data), 2026-10-09 |
| Licence | CC-BY 4.0 |
| Size | 20,235 bytes |
| SHA-256 | `6be363d4796bb3038e751da00e2344593edbb149ed193fc31b9c200688b31498` |

**Attribution:** "LKS-92 → LKS-2020 transformation grid © Latvijas Ģeotelpiskās informācijas aģentūra, CC-BY 4.0, distributed via PROJ-data (cdn.proj.org)."

The file is committed so the image builds offline and reproducibly. The Dockerfile copies it to `/usr/share/proj/` and stops the build if the checksum differs.

**Why it matters:** without the grid, PROJ 9.8.1 does not error. It silently applies a null shift between LKS-92 and LKS-2020, which is about 9.5 cm off at the EPSG sample point Odukalns. With the grid, the error is about 1 mm. `tests/test_crs.py` checks both cases.

**Replacing the file:** download it again from cdn.proj.org, update the SHA-256 here and in `Dockerfile` (`LKS_GRID_SHA256`) and in `tests/test_crs.py`, rebuild (`docker compose build db`) and run the tests.
