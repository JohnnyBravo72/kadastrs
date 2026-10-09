"""SHP reading and geometry normalisation (rule E5).

SHP files are read with pyshp (pure Python) into a staging table as GeoJSON.
All geometry work happens in PostGIS, in this order:
  assign the source SRID explicitly -> ST_MakeValid -> polygon parts only ->
  union per key -> MultiPolygon -> lks92_to_lks2020() if the source is EPSG:3059
  -> validity check.
"""

import io
import json
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass

import psycopg
import shapefile
from psycopg import sql

from etl.schema_check import SchemaMismatch, check_columns, check_prj

STORAGE_SRID = 10306
LKS92_SRID = 3059


@dataclass
class Layer:
    name: str  # e.g. "ExportCadGroup_0900001/KKParcel"
    fields: list[list]
    srid: int
    reader: shapefile.Reader

    def records(self) -> Iterator[tuple[dict, str | None]]:
        """(attributes, GeoJSON or None for a null shape)."""
        for sr in self.reader.iterShapeRecords():
            shape = sr.shape
            geo = None
            if shape.shapeType != shapefile.NULL and shape.points:
                geo = json.dumps(shape.__geo_interface__, separators=(",", ":"))
            yield sr.record.as_dict(), geo


def open_layers(z: zipfile.ZipFile, layer: str, spec: dict) -> list[Layer]:
    """All copies of `layer` in the zip (one per cadastral-group folder), each
    checked against config/schemas.yaml (fields and .prj)."""
    bases = sorted(
        {
            n[:-4]
            for n in z.namelist()
            if n.lower().endswith(".shp") and n.rsplit("/", 1)[-1][:-4] == layer
        }
    )
    out = []
    for base in bases:
        names = set(z.namelist())
        for ext in (".dbf", ".shx", ".prj"):
            if base + ext not in names:
                raise SchemaMismatch(f"{base}: {ext} missing")
        cpg = base + ".cpg"
        if cpg in names and z.read(cpg).decode("ascii", "replace").strip().upper() not in (
            "UTF-8",
            "UTF8",
        ):
            raise SchemaMismatch(f"{base}: .cpg is not UTF-8")
        reader = shapefile.Reader(
            shp=io.BytesIO(z.read(base + ".shp")),
            dbf=io.BytesIO(z.read(base + ".dbf")),
            shx=io.BytesIO(z.read(base + ".shx")),
            encoding="utf-8",
            encodingErrors="strict",
        )
        fields = [[f[0], f[1], f[2]] for f in reader.fields[1:]]
        check_columns(base, fields, spec["fields"])
        srid = check_prj(base, z.read(base + ".prj").decode("utf-8", "replace"), spec)
        out.append(Layer(base, fields, srid, reader))
    return out


def as_text(value) -> str | None:
    """DBF value -> text. Character fields are already str; pyshp returns
    numeric fields as numbers, which is only acceptable for codes that cannot
    have leading zeros (VARIS codes, checked by the caller)."""
    if value is None:
        return None
    if isinstance(value, str):
        v = value.strip()
        return v or None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value)


def normalise_into(
    conn: psycopg.Connection,
    *,
    stage: str,
    target: str,
    version_id: int,
    keys: list[str],
    aggregates: dict[str, str],
    source_srid: int,
) -> dict[str, int]:
    """Normalise staged GeoJSON (column `geojson`) into `target` (rule E5).

    `aggregates` maps target columns to SQL aggregate expressions over the
    stage columns, e.g. {"object_code": "min(object_code)"}. Returns counts.
    """
    if source_srid not in (STORAGE_SRID, LKS92_SRID):
        raise SchemaMismatch(f"unsupported source SRID {source_srid}")
    transform = "lks92_to_lks2020(geom)" if source_srid == LKS92_SRID else "geom"
    key_list = sql.SQL(", ").join(sql.Identifier(k) for k in keys)
    agg_cols = sql.SQL(", ").join(sql.Identifier(c) for c in aggregates)
    agg_exprs = sql.SQL(", ").join(
        sql.SQL("{} AS {}").format(sql.SQL(e), sql.Identifier(c)) for c, e in aggregates.items()
    )
    stats = conn.execute(
        sql.SQL(
            "SELECT count(*), count(*) FILTER (WHERE geojson IS NULL),"
            " count(*) FILTER (WHERE geojson IS NOT NULL AND NOT ST_IsValid("
            "ST_SetSRID(ST_GeomFromGeoJSON(geojson), {srid}))) FROM {stage}"
        ).format(srid=sql.Literal(source_srid), stage=sql.Identifier(stage))
    ).fetchone()
    inserted = conn.execute(
        sql.SQL(
            """
            INSERT INTO {target} (dataset_version_id, {keys}, {agg_cols}, parts, geom)
            SELECT {version}, {keys}, {agg_cols}, parts,
                   ST_Multi(ST_CollectionExtract({transform}, 3))
            FROM (
                SELECT {keys}, {agg_exprs}, count(*) AS parts,
                       ST_CollectionExtract(ST_Union(g), 3) AS geom
                FROM (
                    SELECT *, ST_CollectionExtract(ST_MakeValid(
                               ST_SetSRID(ST_GeomFromGeoJSON(geojson), {srid})), 3) AS g
                    FROM {stage} WHERE geojson IS NOT NULL
                ) s
                WHERE NOT ST_IsEmpty(g)
                GROUP BY {keys}
            ) u
            WHERE NOT ST_IsEmpty(geom)
            """
        ).format(
            target=sql.SQL(target),
            keys=key_list,
            agg_cols=agg_cols,
            agg_exprs=agg_exprs,
            version=sql.Literal(version_id),
            transform=sql.SQL(transform),
            srid=sql.Literal(source_srid),
            stage=sql.Identifier(stage),
        )
    ).rowcount
    distinct_keys = conn.execute(
        sql.SQL("SELECT count(*) FROM (SELECT DISTINCT {keys} FROM {stage}) k").format(
            keys=key_list, stage=sql.Identifier(stage)
        )
    ).fetchone()[0]
    bad = conn.execute(
        sql.SQL(
            "SELECT count(*) FROM {target} WHERE dataset_version_id = {v}"
            " AND (NOT ST_IsValid(geom) OR GeometryType(geom) <> 'MULTIPOLYGON'"
            " OR ST_SRID(geom) <> {srid})"
        ).format(target=sql.SQL(target), v=sql.Literal(version_id), srid=sql.Literal(STORAGE_SRID))
    ).fetchone()[0]
    if bad:
        raise ValueError(
            f"{target}: {bad} geometries invalid or not MULTIPOLYGON after normalisation"
        )
    return {
        "source_records": stats[0],
        "null_shapes": stats[1],
        "invalid_repaired": stats[2],
        "distinct_keys": distinct_keys,
        "loaded": inserted,
        # keys whose records were all null shapes or empty after make_valid:
        # these objects have no geometry (warning no_geometry, PLAN §6.3)
        "keys_without_geometry": distinct_keys - inserted,
    }
