"""admin_boundaries: VARIS aw_shp.zip layers Novadi, Pilsetas, Pagasti (whole country)."""

import re
import zipfile

from etl.importers.common import FLAGS_AGG, create_stage, fetch_whole, resource_date
from etl.settings import schemas
from etl.spatial import as_text, normalise_into, open_layers

LEVELS = {"Novadi": "novads", "Pilsetas": "pilseta", "Pagasti": "pagasts"}
_VARIS_CODE = re.compile(r"^[0-9]{9}$")


class AdminBoundaries:
    source_id = "admin_boundaries"

    def fetch(self, ctx):
        return [fetch_whole(ctx, "aw_shp", "aw_shp.zip")]

    def version_date(self, ctx, files):
        return resource_date(ctx, ["aw_shp"])

    def load(self, ctx, conn, version_id, files):
        create_stage(
            conn,
            "stage_admin",
            {
                "varis_code": "text",
                "level": "text",
                "name": "text",
                "atvk": "text",
                "parent_code": "text",
                "status": "text",
                "flags": "text",
                "geojson": "text",
            },
        )
        per_layer = {}
        with (
            zipfile.ZipFile(ctx.workdir / "aw_shp.zip") as z,
            conn.cursor().copy(
                "COPY stage_admin (varis_code, level, name, atvk, parent_code, status, flags,"
                " geojson) FROM STDIN"
            ) as cp,
        ):
            for layer_name, level in LEVELS.items():
                layers = open_layers(z, layer_name, schemas()["shp"][layer_name])
                if len(layers) != 1:
                    raise ValueError(
                        f"aw_shp.zip: expected one {layer_name} layer, found {len(layers)}"
                    )
                layer = layers[0]
                srid = layer.srid
                n = 0
                for rec, geo in layer.records():
                    code = as_text(rec["KODS"])
                    if not code or not _VARIS_CODE.match(code):
                        raise ValueError(
                            f"{layer_name}: VARIS code {rec['KODS']!r} is not 9 digits"
                        )
                    cp.write_row(
                        (
                            code,
                            level,
                            as_text(rec["NOSAUKUMS"]),
                            as_text(rec["ATRIB"]),
                            as_text(rec["VKUR_CD"]),
                            as_text(rec["STATUSS"]),
                            None,
                            geo,
                        )
                    )
                    n += 1
                per_layer[layer_name] = n
        counts = normalise_into(
            conn,
            stage="stage_admin",
            target="ref.admin_area",
            version_id=version_id,
            keys=["varis_code"],
            aggregates={
                "level": "min(level)",
                "name": "min(name)",
                "atvk": "min(atvk)",
                "parent_code": "min(parent_code)",
                "status": "min(status)",
                "flags": FLAGS_AGG,
            },
            source_srid=srid,
        )
        counts["source_records_by_layer"] = per_layer
        if counts["loaded"] != counts["source_records"]:
            raise ValueError(
                f"admin_area: {counts['source_records']} records but "
                f"{counts['loaded']} rows (duplicate codes or empty geometries)"
            )
        return {"admin_area": counts}
