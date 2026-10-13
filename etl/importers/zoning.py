"""tapis_zoning: TAPIS functional zones + plan-territory coverage mask (D1 E4).

Layers from config/sources.yaml E4 `wfs_layers`:
  finding         tapis_apvienotie:funkcionalais_zonejums
  coverage_mask   tapis_apvienotie:speka_esosu_planojumu_teritorijas

Pilot: ATVK filter (etl.yaml pilot_atvk). Country (Phase 9): unfiltered WFS
pages. WFS GeoJSON in EPSG:3059 → lks92_to_lks2020() on load. Version date from
the data.gov.lv listing (package_show metadata_modified). Snapshot only; never
queried live.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime
from xml.etree import ElementTree as ET

import httpx

from etl.identity import FileRecord, iso
from etl.importers.common import FLAGS_AGG, create_stage
from etl.spatial import LKS92_SRID, normalise_into

RETRY_PAUSES = (1, 4, 9)


def _e4(ctx):
    e4 = next((e for e in ctx.registry.allowed_external_resources if e.id == "E4"), None)
    if e4 is None or e4.status != "allowed":
        raise LookupError("D1 E4 is not an allowed external resource in config/sources.yaml")
    extra = e4.model_extra or {}
    layers = extra.get("wfs_layers") or {}
    if set(layers) != {"finding", "coverage_mask"}:
        raise ValueError("E4 wfs_layers must define finding and coverage_mask")
    return e4.urls[0].rstrip("?"), layers, extra.get("processing") or []


class TapisZoning:
    source_id = "tapis_zoning"

    def _get(self, ctx, url: str, params: dict) -> httpx.Response:
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
                if pause:
                    time.sleep(pause)
                return resp
            except httpx.TransportError as exc:
                last = f"{type(exc).__name__}: {exc}"
        raise RuntimeError(f"{url}: failed after retries ({last})")

    def _hits(self, ctx, base: str, typename: str, atvk: str | None) -> int:
        params = {
            "SERVICE": "WFS",
            "VERSION": "2.0.0",
            "REQUEST": "GetFeature",
            "TYPENAMES": typename,
            "RESULTTYPE": "hits",
            "COUNT": "1",
        }
        if atvk is not None:
            params["FILTER"] = (
                '<Filter xmlns="http://www.opengis.net/fes/2.0">'
                "<PropertyIsEqualTo><ValueReference>atvk_kods</ValueReference>"
                f"<Literal>{atvk}</Literal></PropertyIsEqualTo></Filter>"
            )
        resp = self._get(ctx, base, params)
        root = ET.fromstring(resp.content)  # noqa: S314 WFS hits XML from the allowed E4 endpoint
        return int(root.attrib.get("numberMatched") or 0)

    def _page(
        self, ctx, base: str, typename: str, atvk: str | None, start: int, count: int
    ) -> dict:
        params = {
            "SERVICE": "WFS",
            "VERSION": "2.0.0",
            "REQUEST": "GetFeature",
            "TYPENAMES": typename,
            "OUTPUTFORMAT": "application/json",
            "COUNT": str(count),
            "STARTINDEX": str(start),
        }
        if atvk is not None:
            params["FILTER"] = (
                '<Filter xmlns="http://www.opengis.net/fes/2.0">'
                "<PropertyIsEqualTo><ValueReference>atvk_kods</ValueReference>"
                f"<Literal>{atvk}</Literal></PropertyIsEqualTo></Filter>"
            )
        return self._get(ctx, base, params).json()

    def _fetch_pages(self, ctx, base: str, typename: str, atvk: str | None, page_size: int):
        n = self._hits(ctx, base, typename, atvk)
        label = f"ATVK {atvk}" if atvk else "country"
        print(f"   {typename} {label}: {n} features", file=sys.stderr, flush=True)
        features = []
        start = 0
        while start < n:
            doc = self._page(ctx, base, typename, atvk, start, page_size)
            batch = doc.get("features") or []
            if not batch:
                break
            features.extend(batch)
            start += len(batch)
            if len(batch) < page_size:
                break
        return features

    def fetch(self, ctx):
        base, layers, _ = _e4(ctx)
        pkg = ctx.ckan.package(ctx.dataset)
        listed = pkg.get("metadata_modified")
        ctx.source_last_modified = datetime.fromisoformat(listed) if listed else None
        page_size = int(ctx.options.get("page_size", 500))
        ctx.workdir.mkdir(parents=True, exist_ok=True)
        atvk_list: list[str | None] = list(ctx.cfg.pilot_atvk) if ctx.cfg.is_pilot else [None]
        files = []
        for role, typename in layers.items():
            features = []
            for atvk in atvk_list:
                features.extend(self._fetch_pages(ctx, base, typename, atvk, page_size))
            out = {
                "type": "FeatureCollection",
                "role": role,
                "typename": typename,
                "features": features,
            }
            data = json.dumps(out, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            path = f"{role}.geojson"
            (ctx.workdir / path).write_text(data, encoding="utf-8")
            raw = data.encode("utf-8")
            files.append(
                FileRecord(
                    role=role,
                    resource_id="E4",
                    url=f"{base}?TYPENAMES={typename}",
                    last_modified=iso(ctx.source_last_modified),
                    size=len(raw),
                    sha256=hashlib.sha256(raw).hexdigest(),
                    path=path,
                )
            )
        if ctx.cfg.is_pilot:
            what = f"Features with atvk_kods in {list(ctx.cfg.pilot_atvk)}"
        else:
            what = "Unfiltered WFS pages (import_scope=country)"
        ctx.processing.append(
            {"id": "import_scope", "what": what, "import_scope": ctx.cfg.import_scope}
        )
        return files

    def version_date(self, ctx, files):
        if ctx.source_last_modified is None:
            raise ValueError(f"{ctx.dataset}: no metadata_modified; cannot date the version")
        return ctx.source_last_modified.date()

    def _row(self, role: str, feat: dict) -> tuple:
        props = feat.get("properties") or {}
        geom = feat.get("geometry")
        if geom is None:
            raise RuntimeError(f"TAPIS {role}: feature without geometry")
        if role == "finding":
            tid = props.get("tapis_id")
            if tid is None:
                raise RuntimeError("TAPIS finding: missing tapis_id")
            object_id = str(tid)
            group_code = (props.get("grupa_kods") or "").strip() or None
            group_name = (props.get("grupa_nos") or props.get("veids") or "").strip() or None
            zone_code = (props.get("kods") or "").strip() or None
            zone_index = (props.get("indekss") or "").strip() or None
            zone_name = (props.get("nosaukums") or "").strip() or None
            dok_id = str(props["dok_id"]) if props.get("dok_id") is not None else None
            dok_name = (props.get("dok_nos") or "").strip() or None
        else:
            dok = props.get("dok_id")
            atvk = (props.get("atvk_kods") or "").strip()
            if dok is None or not atvk:
                raise RuntimeError("TAPIS coverage: missing dok_id or atvk_kods")
            object_id = f"{dok}:{atvk}"
            group_code = group_name = zone_code = zone_index = zone_name = None
            dok_id = str(dok)
            dok_name = (props.get("dok_nosaukums") or "").strip() or None
        atvk = (props.get("atvk_kods") or "").strip() or None
        return (
            role,
            object_id,
            group_code,
            group_name,
            zone_code,
            zone_index,
            zone_name,
            atvk,
            dok_id,
            dok_name,
            None,  # flags
            json.dumps(geom, separators=(",", ":")),
        )

    def load(self, ctx, conn, version_id, files):
        _, _, processing = _e4(ctx)
        create_stage(
            conn,
            "stage_zoning",
            {
                "role": "text",
                "object_id": "text",
                "group_code": "text",
                "group_name": "text",
                "zone_code": "text",
                "zone_index": "text",
                "zone_name": "text",
                "atvk": "text",
                "dok_id": "text",
                "dok_name": "text",
                "flags": "text",
                "geojson": "text",
            },
        )
        per_role: dict[str, int] = {}
        with conn.cursor().copy(
            "COPY stage_zoning (role, object_id, group_code, group_name, zone_code,"
            " zone_index, zone_name, atvk, dok_id, dok_name, flags, geojson) FROM STDIN"
        ) as cp:
            for f in files:
                doc = json.loads((ctx.workdir / f.path).read_text(encoding="utf-8"))
                role = doc["role"]
                for feat in doc["features"]:
                    cp.write_row(self._row(role, feat))
                per_role[role] = len(doc["features"])
        counts = normalise_into(
            conn,
            stage="stage_zoning",
            target="ref.zoning_zone",
            version_id=version_id,
            keys=["role", "object_id"],
            aggregates={
                "group_code": "min(group_code)",
                "group_name": "min(group_name)",
                "zone_code": "min(zone_code)",
                "zone_index": "min(zone_index)",
                "zone_name": "min(zone_name)",
                "atvk": "min(atvk)",
                "dok_id": "min(dok_id)",
                "dok_name": "min(dok_name)",
                "flags": FLAGS_AGG,
            },
            source_srid=LKS92_SRID,
        )
        parts = conn.execute(
            "INSERT INTO ref.zoning_zone_part"
            " (dataset_version_id, role, object_id, part_no, geom)"
            " SELECT dataset_version_id, role, object_id,"
            " row_number() OVER (PARTITION BY role, object_id), g"
            " FROM (SELECT dataset_version_id, role, object_id, ST_Subdivide(geom, 256) AS g"
            "       FROM ref.zoning_zone WHERE dataset_version_id = %s) s",
            (version_id,),
        ).rowcount
        counts["subdivided_parts"] = parts
        counts["source_features_by_role"] = per_role
        if counts["loaded"] != counts["source_records"]:
            raise ValueError(
                f"zoning_zone: {counts['source_records']} features, {counts['loaded']} rows"
            )
        ctx.processing = [
            *ctx.processing,
            *[{**p, "applied": True} for p in processing],
            {
                "id": "repair_counts",
                "invalid_repaired": counts["invalid_repaired"],
                "outside_grid": counts["outside_grid"],
                "validated": counts["validated"],
                "features_by_role": per_role,
            },
        ]
        return {"zoning_zone": counts}
