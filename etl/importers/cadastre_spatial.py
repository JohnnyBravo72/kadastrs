"""cadastre_spatial: cadastre map SHP zips of the pilot cities (EPSG:10306).

Layers: KKParcel, KKParcelPart, KKBuilding, KKEngineeringStructurePoly,
KKWayRestriction, one copy per cadastral-group folder. The map is imported as
delivered (the Daugavpils zip also holds groups 4460…, docs/data-sources.md §5.2).
"""

import zipfile

from etl import codes
from etl.importers.common import FLAGS_AGG, create_stage, fetch_whole, flags_text, resource_date
from etl.settings import schemas
from etl.spatial import as_text, normalise_into, open_layers

# Rule E6: OBJECTCODE first digit per layer. Anything else stops the import.
OBJECT_DIGIT = {
    "KKParcel": "7",
    "KKParcelPart": "7",
    "KKWayRestriction": "7",
    "KKBuilding": "5",
    "KKEngineeringStructurePoly": "6",
}
KIND_BY_DIGIT = {"5": "building", "6": "engineering_structure"}

STAGES = {
    # stage: (layers, target, keys, code length, extra stage columns)
    "stage_parcel": (["KKParcel"], "ref.kk_parcel", ["code"], codes.PARCEL, {"geom_date": "date"}),
    "stage_parcel_part": (
        ["KKParcelPart"],
        "ref.kk_parcel_part",
        ["code"],
        codes.PARCEL_PART,
        {"parcel_code": "text"},
    ),
    "stage_building": (
        ["KKBuilding", "KKEngineeringStructurePoly"],
        "ref.kk_building",
        ["code"],
        codes.BUILDING,
        {"parcel_code": "text", "object_kind": "text"},
    ),
    # servitude CODE length is not verified (C20 field), so no length check
    "stage_servitude": (
        ["KKWayRestriction"],
        "ref.kk_servitude",
        ["code", "parcel_code"],
        None,
        {"parcel_code": "text"},
    ),
}


def check_object_code(layer: str, object_code: str | None, where: str) -> str:
    """Rule E6: the first digit of OBJECTCODE decides the object kind."""
    if not object_code or not object_code.isdigit():
        raise ValueError(f"E6: {where}: OBJECTCODE {object_code!r} is not numeric")
    digit = object_code[0]
    if digit not in ("5", "6", "7"):
        raise ValueError(
            f"E6: {where}: OBJECTCODE {object_code} starts with {digit}, "
            "not 5 (building), 6 (engineering structure) or 7 (parcel/part/servitude)"
        )
    if digit != OBJECT_DIGIT[layer]:
        raise ValueError(f"E6: {where}: OBJECTCODE {object_code} (digit {digit}) in layer {layer}")
    return object_code


class CadastreSpatial:
    source_id = "cadastre_spatial"

    def fetch(self, ctx):
        return [
            fetch_whole(ctx, atvk, f"{atvk}_kk_shp.zip") for atvk in ctx.cfg.files[self.source_id]
        ]

    def version_date(self, ctx, files):
        return resource_date(ctx, ctx.cfg.files[self.source_id])

    def load(self, ctx, conn, version_id, files):
        spec = schemas()["shp"]
        for stage, (_, _, _, _, extra) in STAGES.items():
            create_stage(
                conn,
                stage,
                {
                    "code": "text",
                    "object_code": "text",
                    "group_code": "text",
                    "area_scale": "double precision",
                    "zip_atvk": "text",
                    "flags": "text",
                    "geojson": "text",
                    **extra,
                },
            )
        records: dict[str, dict[str, int]] = {}
        srids = set()
        for f in files:
            atvk = f.role
            with zipfile.ZipFile(ctx.workdir / f.path) as z:
                for stage, (layer_names, _, _, length, extra) in STAGES.items():
                    cols = [
                        "code",
                        "object_code",
                        "group_code",
                        "area_scale",
                        "zip_atvk",
                        "flags",
                        "geojson",
                        *extra,
                    ]
                    with conn.cursor().copy(f"COPY {stage} ({', '.join(cols)}) FROM STDIN") as cp:
                        for layer_name in layer_names:
                            n = 0
                            for layer in open_layers(z, layer_name, spec[layer_name]):
                                srids.add(layer.srid)
                                for rec, geo in layer.records():
                                    code, flags = codes.normalize_code(rec["CODE"], length)
                                    if code is None:
                                        raise ValueError(f"{layer.name}: record without CODE")
                                    oc = check_object_code(
                                        layer_name,
                                        as_text(rec["OBJECTCODE"]),
                                        f"{atvk}/{layer.name} {code}",
                                    )
                                    row = [
                                        code,
                                        oc,
                                        as_text(rec["GROUP_CODE"]),
                                        rec["AREA_SCALE"],
                                        atvk,
                                        None,
                                        geo,
                                    ]
                                    if "geom_date" in extra:
                                        d = rec["GEOM_ACT_D"]
                                        row.append(d if hasattr(d, "year") else None)
                                    if "parcel_code" in extra:
                                        pc, pflags = codes.normalize_code(
                                            rec["PARCELCODE"], codes.PARCEL
                                        )
                                        if pc is None and stage == "stage_servitude":
                                            raise ValueError(
                                                f"{layer.name}: servitude {code} without PARCELCODE"
                                            )
                                        flags += pflags
                                        row.append(pc)
                                    if "object_kind" in extra:
                                        row.append(KIND_BY_DIGIT[oc[0]])
                                    row[5] = flags_text(flags)
                                    cp.write_row(row)
                                    n += 1
                            records.setdefault(layer_name, {})[atvk] = n
        if len(srids) != 1:
            raise ValueError(f"cadastre layers in several CRSs: {srids}")
        srid = srids.pop()

        counts = {}
        for stage, (layer_names, target, keys, _, extra) in STAGES.items():
            aggregates = {
                "object_code": "min(object_code)",
                "group_code": "min(group_code)",
                "area_scale": "sum(area_scale)",
                "zip_atvk": "min(zip_atvk)",
                "flags": FLAGS_AGG,
            }
            for col in extra:
                if col not in keys:
                    aggregates[col] = f"min({col})"
            c = normalise_into(
                conn,
                stage=stage,
                target=target,
                version_id=version_id,
                keys=keys,
                aggregates=aggregates,
                source_srid=srid,
            )
            c["source_records_by_layer_and_city"] = {ln: records.get(ln, {}) for ln in layer_names}
            counts[target.split(".")[1]] = c
        return counts
