"""10-year spring-flood coverage per municipality, to choose the pilot (PLAN.md §9).

Counts and area sums only (ArcGIS returnCountOnly / outStatistics); no flood geometry is downloaded.
Needs the 2026 boundaries from `atr` in data/samples/admin/ and the project venv (shapely).

    .venv/Scripts/python -I etl/discovery/pilot_flood.py data/samples/admin/administrativas_teritorijas_2026.geojson
"""

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from shapely.geometry import mapping, shape

SERVICE = ("https://geodata.lvgmc.lv/server/rest/services/Atvertie_dati/"
           "Pavasara_pludu_kartes_3_cikls/MapServer")
LAYERS = {0: "Pavasara_palu_010_3_cikls", 1: "Pavasara_pali_Salaca_010_3_cikls"}
OUT = Path(__file__).resolve().parent / "out" / "pilot_flood.json"


def query(layer, geom, **extra):
    data = urllib.parse.urlencode({
        "geometry": json.dumps(geom), "geometryType": "esriGeometryPolygon", "inSR": 3059,
        "spatialRel": "esriSpatialRelIntersects", "f": "json", **extra}).encode()
    req = urllib.request.Request(f"{SERVICE}/{layer}/query", data=data,
                                 headers={"User-Agent": "kadastrs-discovery/0.1"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.load(resp)


def esri_polygon(geom):
    """Shapely (Multi)Polygon -> Esri JSON rings (simplified to 25 m to keep requests small)."""
    g = geom.simplify(25)
    polys = g.geoms if g.geom_type == "MultiPolygon" else [g]
    rings = []
    for p in polys:
        rings.append([list(c) for c in mapping(p)["coordinates"][0]])
        rings += [[list(c) for c in r] for r in mapping(p)["coordinates"][1:]]
    return {"rings": rings, "spatialReference": {"wkid": 3059}}


def main(path):
    sys.stdout.reconfigure(encoding="utf-8")
    fc = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = []
    for f in fc["features"]:
        geom = shape(f["geometry"])
        esri = esri_polygon(geom)
        row = {"name": f["properties"]["nosaukums"], "atvk": f["properties"]["atrib"],
               "area_km2": round(geom.area / 1e6, 1)}
        for layer in LAYERS:
            row[f"l{layer}_count"] = query(layer, esri, where="1=1", returnCountOnly="true")["count"]
            stats = query(layer, esri, where="1=1", outStatistics=json.dumps([{
                "statisticType": "sum", "onStatisticField": "st_area(shape)", "outStatisticFieldName": "a"}]))
            feats = stats.get("features") or [{}]
            a = (feats[0].get("attributes") or {}).get("a")
            # Sum of whole polygons that touch the municipality (not clipped): an upper bound.
            row[f"l{layer}_area_km2_touching"] = round(a / 1e6, 2) if a else 0.0
        rows.append(row)
        print(row)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1])
