"""Phase 0 step 2: inspect the samples in data/samples/ (CRS, fields, ID fields, encoding, invalid geometries).

Run with the project venv (pyshp, shapely):
    .venv/Scripts/python -I etl/discovery/inspect_samples.py shp       # shapefile sources
    .venv/Scripts/python -I etl/discovery/inspect_samples.py xml       # cadastre text XML
    .venv/Scripts/python -I etl/discovery/inspect_samples.py csv       # VARIS / BIS CSV
    .venv/Scripts/python -I etl/discovery/inspect_samples.py flood     # E7 GeoJSON
    .venv/Scripts/python -I etl/discovery/inspect_samples.py bisrule   # BIS building-designation prefix rule
    .venv/Scripts/python -I etl/discovery/inspect_samples.py gaps      # VARIS CSV/SHP and building text/map count gaps
Results are written to etl/discovery/out/inspect_<part>.json.
"""

import collections
import csv
import io
import json
import sys
import zipfile
from pathlib import Path

import shapefile
from shapely.geometry import shape
from shapely.validation import explain_validity

ROOT = Path(__file__).resolve().parents[2] / "data" / "samples"
OUT = Path(__file__).resolve().parent / "out"
PILOT = "0003000"


def shp_layers(zip_path):
    """Yield (layer path, Reader, prj text, cpg text) for every .shp in a zip, read in memory."""
    z = zipfile.ZipFile(zip_path)
    names = z.namelist()
    for n in sorted(x for x in names if x.lower().endswith(".shp")):
        stem = n[:-4]
        part = lambda ext: z.read(stem + ext) if stem + ext in names else None
        cpg = (part(".cpg") or b"").decode("ascii", "replace").strip()
        prj = (part(".prj") or b"").decode("ascii", "replace")
        enc = {"UTF-8": "utf-8", "65001": "utf-8", "1257": "cp1257"}.get(cpg.upper(), cpg or "utf-8")
        r = shapefile.Reader(shp=io.BytesIO(part(".shp")), shx=io.BytesIO(part(".shx")),
                             dbf=io.BytesIO(part(".dbf")), encoding=enc, encodingErrors="replace")
        yield n, r, prj, cpg


def crs_name(prj):
    return prj.split('"')[1] if '"' in prj else prj.split("[", 2)[1].split(",")[0] if "[" in prj else "—"


def inspect_shp_layer(n, r, prj, cpg, id_candidates=()):
    fields = [(f[0], f[1], f[2]) for f in r.fields[1:]]
    names = [f[0] for f in fields]
    info = {"layer": n, "crs": crs_name(prj), "epsg_in_prj": prj.split("AUTHORITY[")[-1][:20] if "AUTHORITY" in prj else None,
            "cpg": cpg, "shape_type": r.shapeTypeName, "records": len(r), "fields": fields}
    invalid, empty, reasons = 0, 0, collections.Counter()
    ids = {c: collections.Counter() for c in id_candidates if c in names}
    replaced = 0
    for sr in r.iterShapeRecords():
        rec = sr.record.as_dict()
        for c in ids:
            ids[c][str(rec[c])] += 1
        replaced += sum(isinstance(v, str) and "�" in v for v in rec.values())
        if sr.shape.shapeType == 0 or not sr.shape.points:
            empty += 1
            continue
        try:
            g = shape(sr.shape.__geo_interface__)
        except Exception as e:   # e.g. RingSamplingError on a zero-area ring: cannot even be assembled
            invalid += 1
            reasons[f"unassemblable ({type(e).__name__})"] += 1
            continue
        if not g.is_valid:
            invalid += 1
            reasons[explain_validity(g).split("[")[0].strip()] += 1
    info.update({"empty_geometries": empty, "invalid_geometries": invalid, "invalid_reasons": dict(reasons.most_common(5)),
                 "values_with_replacement_char": replaced,
                 "id_fields": {c: {"distinct": len(cnt), "duplicates": sum(1 for v in cnt.values() if v > 1),
                                   "empty": cnt.get("", 0) + cnt.get("None", 0),
                                   "sample": list(cnt)[:3]} for c, cnt in ids.items()}})
    return info


def part_shp():
    res = []
    cad = ROOT / "cadastre_spatial" / f"{PILOT}_kk_shp.zip"
    by_layer = collections.defaultdict(list)
    for n, r, prj, cpg in shp_layers(cad):
        by_layer[Path(n).stem].append(inspect_shp_layer(n, r, prj, cpg, ("CODE", "PARCELCODE", "OBJECTCODE")))
    for layer, parts in by_layer.items():   # one folder per cadastral group: aggregate
        agg = {"source": "cadastre_spatial", "layer": layer, "folders": len(parts),
               "crs": sorted({p["crs"] for p in parts}), "epsg": sorted({str(p["epsg_in_prj"]) for p in parts}),
               "cpg": sorted({p["cpg"] for p in parts}), "shape_type": sorted({p["shape_type"] for p in parts}),
               "records": sum(p["records"] for p in parts), "fields": parts[0]["fields"],
               "fields_differ_between_folders": len({json.dumps(p["fields"]) for p in parts}) > 1,
               "empty_geometries": sum(p["empty_geometries"] for p in parts),
               "invalid_geometries": sum(p["invalid_geometries"] for p in parts),
               "invalid_reasons": dict(sum((collections.Counter(p["invalid_reasons"]) for p in parts), collections.Counter())),
               "values_with_replacement_char": sum(p["values_with_replacement_char"] for p in parts),
               "id_fields": {k: {"distinct_per_folder_sum": sum(p["id_fields"][k]["distinct"] for p in parts),
                                 "duplicates_within_folders": sum(p["id_fields"][k]["duplicates"] for p in parts),
                                 "empty": sum(p["id_fields"][k]["empty"] for p in parts),
                                 "sample": parts[0]["id_fields"][k]["sample"]}
                             for k in parts[0]["id_fields"]}}
        res.append(agg)
        print(json.dumps(agg, ensure_ascii=False)[:900])
    for key in ("iadt", "mikroliegumi", "dabas_pieminekli", "biotopi"):
        for n, r, prj, cpg in shp_layers(ROOT / "nature" / f"{key}.zip"):
            info = {"source": f"nature/{key}", **inspect_shp_layer(n, r, prj, cpg, ("CODE", "KODS", "ID", "OBJECTID", "Kods"))}
            res.append(info)
            print(json.dumps(info, ensure_ascii=False)[:900])
    for n, r, prj, cpg in shp_layers(ROOT / "varis" / "aw_shp.zip"):
        if Path(n).stem not in ("Ekas", "Novadi", "Pilsetas", "Adm_rob"):
            continue
        info = {"source": "varis/aw_shp", **inspect_shp_layer(n, r, prj, cpg, ("KODS", "ADR_CD"))}
        res.append(info)
        print(json.dumps(info, ensure_ascii=False)[:900])
    return res


def local(tag):
    return tag.rsplit("}", 1)[-1]


def part_xml():
    """Structure of each cadastre text XML: declaration, item count, element paths (leaf counts), sample values."""
    import xml.etree.ElementTree as ET
    res = []
    for d in sorted((ROOT / "cadastre_text").iterdir()):
        f = next(d.glob("*.xml"))
        head = f.open("rb").read(200).decode("utf-8", "replace")
        paths, samples, items, depth_stack = collections.Counter(), {}, 0, []
        for event, el in ET.iterparse(f, events=("start", "end")):
            if event == "start":
                depth_stack.append(local(el.tag))
                continue
            path = "/".join(depth_stack[3:])   # below FullData/ItemList/ItemData
            if local(el.tag).endswith("ItemData") and len(depth_stack) == 3:
                items += 1
                el.clear()
            elif len(el) == 0 and path:
                paths[path] += 1
                if path not in samples and (el.text or "").strip():
                    samples[path] = el.text.strip()[:60]
            depth_stack.pop()
        info = {"source": f"cadastre_text/{d.name}", "file": f.name, "bytes": f.stat().st_size,
                "declaration": head.split("?>")[0] + "?>", "items": items,
                "leaf_paths": {p: {"count": c, "sample": samples.get(p)} for p, c in paths.most_common()}}
        res.append(info)
        print(json.dumps({k: v for k, v in info.items() if k != "leaf_paths"}, ensure_ascii=False))
        for p, c in paths.most_common(60):
            print(f"    {c:>8}  {p}  = {samples.get(p)!r}")
    return res


CSV_KEYS = {  # columns that must be text codes: check digit length distribution and leading zeros
    "varis/aw_eka.csv": ["KODS", "VKUR_CD"],
    "bis/objekti.csv": ["Buves_kadastra_apzimejums", "Buves_objekta_adreses_kods", "Buvniecibas_lietas_numurs"],
    "bis/jaunbuves.csv": ["Buves_kadastra_apzimejums", "Buves_adreses_kods", "Buvniecibas_lietas_numurs"],
    "bis/lietas.csv": ["Buvniecibas_lietas_numurs"],
}


def part_csv():
    res = []
    for rel, keys in CSV_KEYS.items():
        p = ROOT / rel
        raw = p.read_bytes()
        bom = raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8-sig")            # raises if not UTF-8
        first = text.split("\n", 1)[0]
        delim = max([";", ",", "\t", "|"], key=first.count)
        rows = list(csv.DictReader(io.StringIO(text), delimiter=delim))
        info = {"source": rel, "bytes": len(raw), "utf8_bom": bom, "crlf": b"\r\n" in raw[:5000], "delimiter": delim,
                "columns": list(rows[0].keys()) if rows else [], "rows": len(rows), "keys": {}}
        for k in keys:
            vals = [r.get(k) or "" for r in rows]
            lengths = collections.Counter(len(v) for v in vals)
            info["keys"][k] = {"empty": sum(1 for v in vals if not v.strip()),
                               "lengths": dict(sorted(lengths.items())),
                               "non_digit": sum(1 for v in vals if v and not v.isdigit()),
                               "leading_zero": sum(1 for v in vals if v.startswith("0")),
                               "sample": [v for v in vals if v][:3]}
        res.append(info)
        print(json.dumps(info, ensure_ascii=False)[:1500])
    return res


def part_bisrule():
    """PLAN module 5: is the parcel = first 11 digits of the BIS building designation? Checked on pilot rows
    against the cadastre's own building -> parcel links (building.xml and KKBuilding.PARCELCODE),
    and BIS address codes against the cadastre's building/parcel VARIS codes."""
    import xml.etree.ElementTree as ET
    # cadastre: building -> parcels (text), building/parcel -> VARIS code
    b_parcels, b_varis, p_varis = {}, {}, {}
    for _, el in ET.iterparse(next((ROOT / "cadastre_text" / "building").glob("*.xml"))):
        if local(el.tag) != "BuildingItemData":
            continue
        code = el.findtext(".//{*}BuildingBasicData/{*}BuildingCadastreNr")
        parcels = {x.text for x in el.iterfind(".//{*}ParcelCadastreNrList/{*}ObjectCadastreNrData")}
        rel = el.find("{*}ObjectRelation")
        if rel is not None and rel.findtext("{*}ObjectType") == "PARCEL":
            parcels.add(rel.findtext("{*}ObjectCadastreNr"))
        b_parcels[code] = parcels
        b_varis[code] = el.findtext(".//{*}BuildingBasicData/{*}VARISCode")
        el.clear()
    for _, el in ET.iterparse(next((ROOT / "cadastre_text" / "parcel").glob("*.xml"))):
        if local(el.tag) == "ParcelItemData":
            p_varis[el.findtext(".//{*}ParcelCadastreNr")] = el.findtext(".//{*}ParcelVARISCode")
            el.clear()
    kk_parcel = {}
    for n, r, _, _ in shp_layers(ROOT / "cadastre_spatial" / f"{PILOT}_kk_shp.zip"):
        if Path(n).stem == "KKBuilding":
            for rec in r.iterRecords(fields=["CODE", "PARCELCODE"]):
                kk_parcel[rec[0]] = rec[1]
    print(f"cadastre: {len(b_parcels)} buildings (text), {len(kk_parcel)} (map), {len(p_varis)} parcels")

    stats = collections.Counter()
    examples = collections.defaultdict(list)
    for rel_path, addr_col in (("bis/objekti.csv", "Buves_objekta_adreses_kods"), ("bis/jaunbuves.csv", "Buves_adreses_kods")):
        text = (ROOT / rel_path).read_text(encoding="utf-8-sig")
        for row in csv.DictReader(io.StringIO(text)):
            d = (row["Buves_kadastra_apzimejums"] or "").strip()
            if not d.startswith("0900"):        # Jelgava city cadastral territories 0900...
                continue
            src = rel_path.split("/")[1]
            stats[f"{src}: rows"] += 1
            if len(d) not in (14, 17) or not d.isdigit():
                stats[f"{src}: bad designation"] += 1
                continue
            b = d[:14]                           # 17-digit premise group -> its building
            if len(d) == 17:
                stats[f"{src}: 17-digit (premise group)"] += 1
            prefix = b[:11]
            if b not in b_parcels:
                stats[f"{src}: building not in cadastre"] += 1
                examples[f"{src}: building not in cadastre"].append(d)
                continue
            parcels = b_parcels[b]
            if prefix in parcels:
                stats[f"{src}: prefix = cadastre parcel"] += 1
                if len(parcels) > 1:
                    stats[f"{src}: ... building on several parcels"] += 1
            else:
                stats[f"{src}: prefix != cadastre parcel"] += 1
                examples[f"{src}: prefix != cadastre parcel"].append((d, sorted(parcels)))
            if b in kk_parcel:
                stats[f"{src}: map PARCELCODE == prefix" if kk_parcel[b] == prefix else f"{src}: map PARCELCODE != prefix"] += 1
            a = (row.get(addr_col) or "").strip()
            if a:
                if a == b_varis.get(b):
                    stats[f"{src}: address code = building VARIS code"] += 1
                elif any(a == p_varis.get(p) for p in parcels):
                    stats[f"{src}: address code = parcel VARIS code"] += 1
                else:
                    stats[f"{src}: address code matches neither"] += 1
            else:
                stats[f"{src}: no address code"] += 1
    for k in sorted(stats):
        print(f"  {stats[k]:>7}  {k}")
    for k, v in examples.items():
        print(f"  e.g. {k}: {v[:5]}")
    return {"stats": dict(stats), "examples": {k: v[:20] for k, v in examples.items()}}


def part_flood():
    """E7 sample (data/samples/flood_e7/layer0_<ATVK>.geojson, fetched with maxAllowableOffset=0.01):
    validity, repair effect on area, and the seed parcel from PLAN §2.4 against the flood polygons."""
    from shapely import make_valid
    from shapely.ops import unary_union
    fc = json.loads((ROOT / "flood_e7" / f"layer0_{PILOT}.geojson").read_text(encoding="utf-8"))
    geoms = [shape(f["geometry"]) for f in fc["features"]]
    reasons = collections.Counter(explain_validity(g).split("[")[0].strip() for g in geoms if not g.is_valid)
    fixed = [make_valid(g) for g in geoms]
    info = {"source": "flood_e7 layer 0", "features": len(geoms), "invalid": sum(reasons.values()),
            "invalid_reasons": dict(reasons), "geometry_types": dict(collections.Counter(g.geom_type for g in geoms)),
            "area_raw_km2": round(sum(g.area for g in geoms) / 1e6, 3),
            "area_after_make_valid_km2": round(sum(g.area for g in fixed) / 1e6, 3),
            "properties": sorted({k for f in fc["features"] for k in (f.get("properties") or {})})}
    flood = unary_union(fixed)
    seeds = {}
    for n, r, _, _ in shp_layers(ROOT / "cadastre_spatial" / f"{PILOT}_kk_shp.zip"):
        if Path(n).stem != "KKParcel":
            continue
        for sr in r.iterShapeRecords():
            if sr.record["CODE"] == "09000360220":
                seeds["09000360220"] = shape(sr.shape.__geo_interface__)
    if seeds:   # parcel is EPSG:10306, flood EPSG:3059: transform the parcel to 3059 for this check
        from pyproj import Transformer
        from shapely.ops import transform
        t = Transformer.from_crs(10306, 3059, always_xy=True).transform
        for code, g in seeds.items():
            g3059 = transform(t, g)
            inter = g3059.intersection(flood)
            info[f"seed {code}"] = {"parcel_area_m2": round(g3059.area, 1), "flood_overlap_m2": round(inter.area, 1),
                                    "share": round(inter.area / g3059.area, 4) if g3059.area else None}
    else:
        info["seed 09000360220"] = "not found in KKParcel"
    print(json.dumps(info, ensure_ascii=False, indent=1))
    return info


def part_gaps():
    """Explain two count gaps: VARIS aw_eka.csv vs Ekas.shp, and cadastre buildings text vs map."""
    import xml.etree.ElementTree as ET
    res = {}
    # VARIS
    shp_codes = {}
    for n, r, _, _ in shp_layers(ROOT / "varis" / "aw_shp.zip"):
        if Path(n).stem == "Ekas":
            for rec in r.iterRecords(fields=["KODS", "STATUSS"]):
                shp_codes[str(rec[0])] = rec[1]
    rows = list(csv.DictReader(io.StringIO((ROOT / "varis" / "aw_eka.csv").read_text(encoding="utf-8-sig"))))
    missing = [x for x in rows if x["KODS"] not in shp_codes]
    res["varis"] = {"csv_rows": len(rows), "shp_points": len(shp_codes),
                    "csv_by_status": dict(collections.Counter(x["STATUSS"] for x in rows)),
                    "shp_by_status": dict(collections.Counter(shp_codes.values())),
                    "csv_not_in_shp": len(missing),
                    "csv_not_in_shp_by_status": dict(collections.Counter(x["STATUSS"] for x in missing)),
                    "csv_not_in_shp_without_coords": sum(1 for x in missing if not x["KOORD_X"].strip()),
                    "shp_not_in_csv": len(set(shp_codes) - {x["KODS"] for x in rows})}
    # cadastre buildings
    text = {}
    for _, el in ET.iterparse(next((ROOT / "cadastre_text" / "building").glob("*.xml"))):
        if local(el.tag) != "BuildingItemData":
            continue
        b = el.find(".//{*}BuildingBasicData")
        text[b.findtext("{*}BuildingCadastreNr")] = (
            "NotExist" if b.find("{*}NotExist") is not None else
            "Prereg" if b.find("{*}Prereg") is not None else
            f"engineering structure {b.findtext('{*}EngineeringStructureType')}" if b.findtext("{*}EngineeringStructureType") else
            "other")
        el.clear()
    layers = collections.defaultdict(set)
    for n, r, _, _ in shp_layers(ROOT / "cadastre_spatial" / f"{PILOT}_kk_shp.zip"):
        st = Path(n).stem
        if st in ("KKBuilding", "KKEngineeringStructurePoly", "KKEngineeringStructureLine"):
            for rec in r.iterRecords(fields=["CODE"]):
                layers[st].add(rec[0])
    mapped = set().union(*layers.values())
    res["buildings"] = {"text": len(text), **{k: len(v) for k, v in layers.items()},
                        "map_not_in_text": len(mapped - set(text)),
                        "text_without_geometry": sum(1 for c in text if c not in mapped),
                        "text_without_geometry_by_kind": dict(collections.Counter(k for c, k in text.items() if c not in mapped)),
                        "notexist_with_geometry": sum(1 for c, k in text.items() if k == "NotExist" and c in mapped)}
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return res


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    part = sys.argv[1]
    result = globals()[f"part_{part}"]()
    OUT.mkdir(exist_ok=True)
    (OUT / f"inspect_{part}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
