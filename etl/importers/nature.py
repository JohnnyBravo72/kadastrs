"""DAP nature data (national SHP zips, EPSG:3059 by .prj name).

One importer class per data.gov.lv dataset; the key is GlobalID (unique in
every layer, docs/data-sources.md §6.2). Geometry: E5 with lks92_to_lks2020().
Repair counts (invalid, empty, rings pyshp could not assemble) go to import_log.
"""

import json
import zipfile
from datetime import date

from etl.importers.common import FLAGS_AGG, create_stage, fetch_whole, resource_date
from etl.settings import schemas
from etl.spatial import LKS92_SRID, as_text, normalise_into, open_layers

# Columns mapped to their own table columns (first one present wins).
NAME = ("NAME", "LOCALNAME", "NAME_LV")
CATEGORY = ("CATEGORY", "CODE_EC", "MR_TYPE")
ATIS_DESCRIPTION = ("ATIS_veids", "ATIS_DESCR")
DERIVED = {"Shape_Leng", "Shape_Area"}  # computed by the publisher's GIS, not data


def _first(rec: dict, names) -> str | None:
    for n in names:
        if n in rec:
            return as_text(rec[n])
    return None


def _json_value(v):
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return v


class NatureImporter:
    source_id: str
    filename: str
    layers: dict[str, str]  # SHP layer -> nature_area.kind

    def fetch(self, ctx):
        return [fetch_whole(ctx, "shp", self.filename)]

    def version_date(self, ctx, files):
        return resource_date(ctx, ["shp"])

    def load(self, ctx, conn, version_id, files):
        create_stage(
            conn,
            "stage_nature",
            {
                "global_id": "text",
                "kind": "text",
                "source_layer": "text",
                "dap_id": "text",
                "mrcode": "text",
                "name": "text",
                "category": "text",
                "atis_code": "text",
                "atis_description": "text",
                "attributes": "jsonb",
                "flags": "text",
                "geojson": "text",
            },
        )
        per_layer, rebuilt = {}, {}
        with (
            zipfile.ZipFile(ctx.workdir / self.filename) as z,
            conn.cursor().copy(
                "COPY stage_nature (global_id, kind, source_layer, dap_id, mrcode, name, category,"
                " atis_code, atis_description, attributes, flags, geojson) FROM STDIN"
            ) as cp,
        ):
            for layer_name, kind in self.layers.items():
                layers = open_layers(z, layer_name, schemas()["shp_dap"][layer_name])
                if len(layers) != 1:
                    raise ValueError(
                        f"{self.filename}: expected one {layer_name}, found {len(layers)}"
                    )
                layer = layers[0]
                if layer.srid != LKS92_SRID:
                    raise ValueError(f"{layer_name}: SRID {layer.srid}, expected {LKS92_SRID}")
                n = 0
                for rec, geo in layer.records():
                    gid = as_text(rec.get("GlobalID"))
                    if not gid:
                        raise ValueError(f"{layer_name}: record without GlobalID")
                    attrs = {k: _json_value(v) for k, v in rec.items() if k not in DERIVED}
                    flags = (
                        "rings_rebuilt"
                        if geo and geo.startswith('{"type":"MultiLineString"')
                        else None
                    )
                    cp.write_row(
                        (
                            gid,
                            kind,
                            layer_name,
                            as_text(rec.get("ID")),
                            as_text(rec.get("MRCODE")),
                            _first(rec, NAME),
                            _first(rec, CATEGORY),
                            as_text(rec.get("ATIS_CODE")),
                            _first(rec, ATIS_DESCRIPTION),
                            json.dumps(attrs, ensure_ascii=False),
                            flags,
                            geo,
                        )
                    )
                    n += 1
                per_layer[layer_name] = n
                rebuilt[layer_name] = layer.rings_rebuilt
        counts = normalise_into(
            conn,
            stage="stage_nature",
            target="ref.nature_area",
            version_id=version_id,
            keys=["global_id"],
            aggregates={
                c: f"min({c})"
                for c in (
                    "kind",
                    "source_layer",
                    "dap_id",
                    "mrcode",
                    "name",
                    "category",
                    "atis_code",
                    "atis_description",
                )
            }
            | {"attributes": "(array_agg(attributes))[1]", "flags": FLAGS_AGG},
            source_srid=LKS92_SRID,
        )
        if counts["distinct_keys"] != counts["source_records"]:
            raise ValueError(
                f"{self.source_id}: GlobalID not unique "
                f"({counts['source_records']} records, {counts['distinct_keys']} keys)"
            )
        counts["source_records_by_layer"] = per_layer
        counts["rings_rebuilt_by_layer"] = rebuilt
        ctx.processing = [
            {
                "id": "make_valid",
                "what": "Invalid geometries repaired with make_valid; polygon parts kept",
                "invalid_repaired": counts["invalid_repaired"],
                "without_geometry": counts["keys_without_geometry"],
                "rings_rebuilt": rebuilt,
            },
            {
                "id": "reproject",
                "what": "EPSG:3059 -> EPSG:10306 with the EPSG:10838 grid; vertices outside "
                "the grid "
                "(sea) get a zero shift and the object the flag outside_grid",
                "outside_grid": counts["outside_grid"],
            },
        ]
        return {"nature_area": counts}


class NatureProtectedAreas(NatureImporter):
    source_id = "nature_protected_areas"
    filename = "ipasi_aizsargajamas_dabas_teritorijas.zip"
    layers = {"IADT_pamatteritorijas": "protected_area", "IADT_zonejums": "protected_area_zone"}


class NatureMicroreserves(NatureImporter):
    source_id = "nature_microreserves"
    filename = "mikroliegumi.zip"
    layers = {"Mikroliegumi": "microreserve", "MikroliegumuBuferzonas": "microreserve_buffer"}


class NatureMonuments(NatureImporter):
    source_id = "nature_monuments"
    filename = "dabas_pieminekli.zip"
    layers = {"IADT_dabas_pieminekli": "nature_monument"}


class NatureHabitats(NatureImporter):
    source_id = "nature_habitats"
    filename = "biotopi.zip"
    layers = {"Biotopi": "habitat"}
