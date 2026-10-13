"""flood_10y: LVĢMC 3rd-cycle spring-flood maps (D1 E7), pilot extent + 1 km.

Layers and their roles come from the D1 E7 entry in config/sources.yaml:
0 and 1 (10-year) are findings, 3 (200-year extent) is the coverage mask only
(docs/decisions.md, E7). Fetch recipe (docs/data-sources.md §6.1): ids within
each pilot city's extent + 1 km, then objectIds in small batches with
outSR=3059 and maxAllowableOffset=0.01 (1 cm). Geometry: E5 with
lks92_to_lks2020(). The service has no date, so the version date comes from
the data.gov.lv listing of the same data (package_show).
"""

import hashlib
import json
import sys
import time
from datetime import datetime

import httpx

from etl.identity import FileRecord, iso
from etl.importers.common import FLAGS_AGG, create_stage
from etl.schema_check import SchemaMismatch
from etl.settings import schemas
from etl.spatial import LKS92_SRID, normalise_into

RETRY_PAUSES = (1, 4, 9)


def _e7(ctx):
    e7 = next((e for e in ctx.registry.allowed_external_resources if e.id == "E7"), None)
    if e7 is None or e7.status != "allowed":
        raise LookupError("D1 E7 is not an allowed external resource in config/sources.yaml")
    extra = e7.model_extra or {}
    roles = {int(k): v for k, v in (extra.get("layer_roles") or {}).items()}
    if sorted(roles) != sorted(int(x) for x in extra.get("layers", [])):
        raise ValueError("E7 layers and layer_roles disagree in config/sources.yaml")
    return e7.urls[0].rstrip("/"), roles, extra.get("processing") or []


class Flood10y:
    source_id = "flood_10y"

    # -- HTTP --------------------------------------------------------------------

    def _get(self, ctx, url: str, params: dict) -> dict:
        pause = float(ctx.options.get("request_pause_s", 0))
        last = None
        for wait in (0, *ctx.options.get("retry_pauses", RETRY_PAUSES)):
            if wait:
                time.sleep(wait)
            try:
                resp = ctx.client.get(url, params=params)
                if resp.status_code >= 500:
                    last = f"HTTP {resp.status_code}"
                    continue
                resp.raise_for_status()
                body = resp.json()
                if isinstance(body, dict) and "error" in body:
                    last = f"ArcGIS error {body['error']}"
                    continue
                if pause:
                    time.sleep(pause)
                return body
            except (httpx.TransportError, json.JSONDecodeError) as exc:
                last = f"{type(exc).__name__}: {exc}"
        raise RuntimeError(
            f"{url} {params.get('objectIds', '')[:60]}: failed after retries ({last})"
        )

    # -- fetch -------------------------------------------------------------------

    def _extents(self, ctx) -> dict[str, tuple[float, float, float, float]]:
        margin = float(ctx.options.get("margin_m", 1000))
        scope = ctx.cfg.scope_atvk()  # None = every city (country)
        with ctx.conn_factory() as c:
            admin = c.execute("SELECT ref.live_version('admin_boundaries')").fetchone()[0]
            if scope is None:
                rows = c.execute(
                    "SELECT atvk, ST_XMin(b), ST_YMin(b), ST_XMax(b), ST_YMax(b) FROM ("
                    " SELECT atvk, ST_Transform(ST_Expand(ST_Envelope(geom), %s), 3059) AS b"
                    " FROM ref.city_boundary) e",
                    (margin,),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT atvk, ST_XMin(b), ST_YMin(b), ST_XMax(b), ST_YMax(b) FROM ("
                    " SELECT atvk, ST_Transform(ST_Expand(ST_Envelope(geom), %s), 3059) AS b"
                    " FROM ref.city_boundary WHERE atvk = ANY(%s)) e",
                    (margin, list(scope)),
                ).fetchall()
        found = {r[0]: tuple(r[1:]) for r in rows}
        if ctx.cfg.is_pilot:
            missing = sorted(set(scope or ()) - set(found))
            if admin is None or missing:
                raise LookupError(
                    f"pilot city boundaries missing {missing}: import admin_boundaries first"
                )
            what = f"Features intersecting each pilot city's extent + {margin:g} m"
        else:
            if admin is None or not found:
                raise LookupError("city boundaries missing: import admin_boundaries first")
            what = f"Features intersecting every city extent + {margin:g} m (country)"
        ctx.processing.append(
            {
                "id": "import_extent",
                "what": what,
                "admin_boundaries_version": admin,
                "import_scope": ctx.cfg.import_scope,
            }
        )
        return found

    def _check_layer(self, ctx, base: str, layer: int) -> str:
        spec = schemas()["arcgis"][f"layer_{layer}"]
        info = self._get(ctx, f"{base}/{layer}", {"f": "json"})
        actual = {
            "name": info.get("name"),
            "geometry_type": info.get("geometryType"),
            "wkid": (info.get("extent") or {}).get("spatialReference", {}).get("wkid"),
            "fields": [[f["name"], f["type"]] for f in info.get("fields", [])],
        }
        expected = {k: spec[k] for k in ("name", "geometry_type", "wkid", "fields")}
        if actual != expected:
            diff = {k: (expected[k], actual[k]) for k in expected if expected[k] != actual[k]}
            raise SchemaMismatch(f"E7 layer {layer} differs from config/schemas.yaml: {diff}")
        return spec["name"]

    def fetch(self, ctx):
        base, roles, _ = _e7(ctx)
        pkg = ctx.ckan.package(ctx.dataset)
        listed = pkg.get("metadata_modified")
        ctx.source_last_modified = datetime.fromisoformat(listed) if listed else None
        extents = self._extents(ctx)
        batch = int(ctx.options.get("batch_size", 25))
        offset = ctx.options.get("max_allowable_offset", 0.01)
        ctx.workdir.mkdir(parents=True, exist_ok=True)
        files = []
        for layer in sorted(roles):
            name = self._check_layer(ctx, base, layer)
            ids: set[int] = set()
            for xmin, ymin, xmax, ymax in extents.values():
                body = self._get(
                    ctx,
                    f"{base}/{layer}/query",
                    {
                        "where": "1=1",
                        "geometry": f"{xmin},{ymin},{xmax},{ymax}",
                        "geometryType": "esriGeometryEnvelope",
                        "inSR": LKS92_SRID,
                        "spatialRel": "esriSpatialRelIntersects",
                        "returnIdsOnly": "true",
                        "f": "json",
                    },
                )
                ids.update(body.get("objectIds") or [])
            features = {}
            ordered = sorted(ids)
            started = time.monotonic()
            print(
                f"   layer {layer} ({roles[layer]}): {len(ordered)} features",
                file=sys.stderr,
                flush=True,
            )
            for i in range(0, len(ordered), batch):
                for fid, feat in self._features(
                    ctx, base, layer, ordered[i : i + batch], offset
                ).items():
                    features[fid] = feat
                done = min(i + batch, len(ordered))
                if done == len(ordered) or (i // batch) % 10 == 9:
                    print(
                        f"     {done}/{len(ordered)} ({time.monotonic() - started:.0f} s)",
                        file=sys.stderr,
                        flush=True,
                    )
            missing = sorted(set(ordered) - set(features))
            if missing:
                raise RuntimeError(f"E7 layer {layer}: objects {missing[:10]} not returned")
            doc = {
                "type": "FeatureCollection",
                "layer": layer,
                "layer_name": name,
                "role": roles[layer],
                "features": [features[i] for i in ordered],
            }
            data = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            path = f"layer_{layer}.geojson"
            (ctx.workdir / path).write_text(data, encoding="utf-8")
            raw = data.encode("utf-8")
            files.append(
                FileRecord(
                    role=f"layer_{layer}",
                    resource_id="E7",
                    url=f"{base}/{layer}",
                    last_modified=iso(ctx.source_last_modified),
                    size=len(raw),
                    sha256=hashlib.sha256(raw).hexdigest(),
                    path=path,
                )
            )
        return files

    def _features(self, ctx, base, layer, ids, offset) -> dict[int, dict]:
        params = {
            "objectIds": ",".join(map(str, ids)),
            "outFields": "*",
            "returnGeometry": "true",
            "outSR": LKS92_SRID,
            "maxAllowableOffset": offset,
            "f": "geojson",
        }
        try:
            body = self._get(ctx, f"{base}/{layer}/query", params)
        except RuntimeError as exc:
            if len(ids) == 1:
                raise
            print(
                f"     batch of {len(ids)} failed ({exc}); fetching one by one",
                file=sys.stderr,
                flush=True,
            )
            out = {}  # split the batch: one object at a time
            for one in ids:
                out.update(self._features(ctx, base, layer, [one], offset))
            return out
        out = {}
        for feat in body.get("features", []):
            props = feat.get("properties") or {}
            fid = props.get("objectid", feat.get("id"))
            if fid is None or feat.get("geometry") is None:
                raise RuntimeError(f"E7 layer {layer}: feature without objectid or geometry")
            out[int(fid)] = {
                "type": "Feature",
                "id": int(fid),
                "properties": props,
                "geometry": feat["geometry"],
            }
        return out

    def version_date(self, ctx, files):
        if ctx.source_last_modified is None:
            raise ValueError(f"{ctx.dataset}: no metadata_modified; cannot date the version")
        return ctx.source_last_modified.date()

    # -- load --------------------------------------------------------------------

    def load(self, ctx, conn, version_id, files):
        _, roles, processing = _e7(ctx)
        create_stage(
            conn,
            "stage_flood",
            {
                "layer": "integer",
                "object_id": "text",
                "role": "text",
                "layer_name": "text",
                "source_area": "double precision",
                "flags": "text",
                "geojson": "text",
            },
        )
        per_layer = {}
        with conn.cursor().copy(
            "COPY stage_flood (layer, object_id, role, layer_name, source_area, flags, geojson)"
            " FROM STDIN"
        ) as cp:
            for f in files:
                doc = json.loads((ctx.workdir / f.path).read_text(encoding="utf-8"))
                for feat in doc["features"]:
                    cp.write_row(
                        (
                            doc["layer"],
                            str(feat["id"]),
                            doc["role"],
                            doc["layer_name"],
                            feat["properties"].get("st_area(shape)"),
                            None,
                            json.dumps(feat["geometry"], separators=(",", ":")),
                        )
                    )
                per_layer[doc["layer"]] = len(doc["features"])
        counts = normalise_into(
            conn,
            stage="stage_flood",
            target="ref.flood_zone",
            version_id=version_id,
            keys=["layer", "object_id"],
            aggregates={
                "role": "min(role)",
                "layer_name": "min(layer_name)",
                "source_area": "min(source_area)",
                "flags": FLAGS_AGG,
            },
            source_srid=LKS92_SRID,
        )
        # Subdivided copy for fast spatial queries (migration 20261010090000).
        parts = conn.execute(
            "INSERT INTO ref.flood_zone_part"
            " (dataset_version_id, layer, role, object_id, part_no, geom)"
            " SELECT dataset_version_id, layer, role, object_id,"
            " row_number() OVER (PARTITION BY layer, object_id), g"
            " FROM (SELECT dataset_version_id, layer, role, object_id, ST_Subdivide(geom, 256) AS g"
            "       FROM ref.flood_zone WHERE dataset_version_id = %s) s",
            (version_id,),
        ).rowcount
        counts["subdivided_parts"] = parts
        counts["source_features_by_layer"] = per_layer
        if counts["loaded"] != counts["source_records"]:
            raise ValueError(
                f"flood_zone: {counts['source_records']} features, {counts['loaded']} rows"
            )
        ctx.processing = [
            *ctx.processing,
            *[{**p, "applied": True} for p in processing],
            {
                "id": "repair_counts",
                "invalid_repaired": counts["invalid_repaired"],
                "outside_grid": counts["outside_grid"],
                "validated": counts["validated"],
                "features_by_layer": per_layer,
                "layer_roles": {str(k): v for k, v in roles.items()},
            },
        ]
        return {"flood_zone": counts}
