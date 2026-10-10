"""Phase 2c verification (docs/data-sources.md §7): BIS cases, cadastre
encumbrances, the ATIS classifier and the frozen pre-2025 encumbrance list.

Runs in the etl container (CLAUDE.md rule 12), writing to a mounted /out:

    docker compose run --rm -v <dir>:/out --entrypoint python etl -m etl.discovery.verify_2c show
    ... fetch      # current BIS CSVs, classifier CSV, frozen-list CSVs, pilot encumbrance members
    ... bis        # headers, pilot scope, ATVK and designation lengths
    ... enc        # encumbrance XML paths, codes vs classifier
    ... frozen         # frozen list vs current encumbrances (per object and code)
    ... frozen_detail  # the frozen-only rows by cause; needs /out/objects_now.txt
    ... dap            # DAP ATIS_CODE vs classifier and encumbrances; needs /out/dap_codes.txt

The two DB exports come from the live dev database:

    psql -At -c "SELECT code FROM ref.parcel WHERE dataset_version_id = ref.live_version('cadastre_text')
                 UNION ALL SELECT code FROM ref.parcel_part
                 WHERE dataset_version_id = ref.live_version('cadastre_text')" > objects_now.txt
    psql -At -F '|' -c "SELECT source_layer, coalesce(atis_code, ''), coalesce(atis_description, ''),
                 count(*) FROM ref.nature_area_current GROUP BY 1, 2, 3" > dap_codes.txt

`etl/discovery/` is exempt from rule E1: URLs here come from package_show anyway.
"""

import collections
import csv
import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from etl.ckan import Ckan, http_client
from etl.remote import RemoteZip, download

API = "https://data.gov.lv/dati/api/3/action/"
OUT = Path("/out")
PILOT = ("0002000", "0003000", "0004000")

DATASETS = {
    "bis_cases": "bis_jlyakg7hgslonjnwyrwc6w",
    "bis_objects": "bis_tln9s3hrpjlnucmjip9r3g",
    "cadastre_text": "kadastra-informacijas-sistemas-atvertie-dati",
    "atis_classifier": "atis-datu-un-kadastra-objektu-apgrutinajumu-klasifikators",
    "frozen": "apgrutinajumi-kas-kadastra-registreti-lidz-2025-gada-31-janvarim",
}
ENCUMBRANCE_ZIP = "ca8a415c-a894-427f-b14d-d1e44c582620"
_MEMBER = re.compile(r"^[^/]+/(?P<atvk>[0-9]{7})_(?P<date>[0-9]{8})_[0-9]+/[^/]+\.xml$")


def out(name: str) -> Path:
    p = OUT / name
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def show():
    ck = Ckan(http_client(), API)
    summary = {}
    for key, ds in DATASETS.items():
        pkg = ck.package(ds)
        summary[key] = {
            "name": pkg["name"],
            "id": pkg["id"],
            "license_id": pkg.get("license_id"),
            "metadata_modified": pkg.get("metadata_modified"),
            "frequency": next(
                (e["value"] for e in pkg.get("extras", []) if e["key"] == "frequency"), None
            ),
            "resources": [
                {
                    k: r.get(k)
                    for k in (
                        "id",
                        "name",
                        "format",
                        "url",
                        "size",
                        "last_modified",
                        "metadata_modified",
                        "created",
                    )
                }
                for r in pkg["resources"]
            ],
        }
    out("show.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), "utf-8")
    for key, s in summary.items():
        print(f"== {key}: {s['name']} {s['id']} {s['license_id']} {s['metadata_modified']}")
        for r in s["resources"]:
            print(
                f"   {r['id']} {r['format']:5} {r['size']!s:>10} lm={r['last_modified']}"
                f" {r['name'][:60]} | {r['url'].rsplit('/', 1)[-1]}"
            )


def fetch():
    client = http_client()
    show_data = json.loads(out("show.json").read_text("utf-8"))
    for key in ("bis_cases", "bis_objects", "atis_classifier", "frozen"):
        for r in show_data[key]["resources"]:
            if (r["format"] or "").upper() != "CSV":  # BIS objects file is not named .csv
                continue
            fname = r["url"].rsplit("/", 1)[-1]
            info = download(client, r["url"], out(f"{key}/{fname}"))
            print(key, fname, info.size, info.sha256[:16])
    url = next(
        r["url"]
        for r in show_data["cadastre_text"]["resources"]
        if r["id"] == ENCUMBRANCE_ZIP
    )
    rz = RemoteZip(client, url, out("_full")).open()
    print("range_supported", rz.range_supported, "members", len(rz.members))
    for m in rz.members:
        hit = _MEMBER.match(m.name)
        if hit and hit["atvk"] in PILOT:
            sha = rz.extract(m, out(f"encumbrance/{Path(m.name).name}"))
            print(m.name, m.usize, sha[:16])


def _csv(path: Path):
    head = path.read_bytes()[:3]
    enc = "utf-8-sig" if head == b"\xef\xbb\xbf" else "utf-8"
    with open(path, encoding=enc, newline="") as f:
        yield from csv.DictReader(f)


def _one(pattern: str) -> Path:
    found = sorted(OUT.glob(pattern))
    if len(found) != 1:
        raise SystemExit(f"{pattern}: {found}")
    return found[0]


def bis():
    cases_p, objects_p = _one("bis_cases/*"), _one("bis_objects/*")
    for p in (cases_p, objects_p):
        with open(p, "rb") as f:
            first = f.readline()
        print(p.name, "BOM" if first.startswith(b"\xef\xbb\xbf") else "no BOM", first[:400])
    atvk_len, des_len, flags, scope = (collections.Counter() for _ in range(4))
    pre = {"0500", "0900", "1300"}
    pilot_atvk_short = {a.lstrip("0") for a in PILOT}
    cases, n, zeros = set(), 0, 0
    junk = collections.Counter()
    for r in _csv(objects_p):
        n += 1
        a = r["Administrativas_teritorijas_kods"]
        atvk_len[len(a)] += 1
        d = r["Buves_kadastra_apzimejums"]
        des_len[len(d.strip())] += 1
        if d != d.strip() or (d.strip() and not d.strip().isdigit()):
            junk[d] += 1
        if d.startswith("0"):
            zeros += 1
        in_a = a.lstrip("0") in pilot_atvk_short and a != ""
        in_p = d.strip()[:4] in pre
        if in_a or in_p:
            scope[(in_a, in_p)] += 1
            cases.add(r["Buvniecibas_lietas_numurs"])
            if len(d.strip()) == 17:
                flags["room_group"] += 1
            if not d.strip():
                flags["no_designation"] += 1
    n_cases, in_list = 0, 0
    for r in _csv(cases_p):
        n_cases += 1
        in_list += r["Buvniecibas_lietas_numurs"] in cases
    res = {
        "object_rows": n,
        "case_rows": n_cases,
        "atvk_len": dict(atvk_len),
        "designation_len": dict(des_len),
        "designation_starts_with_0": zeros,
        "junk_designations": dict(junk),
        "pilot_scope_(atvk,prefix)": {str(k): v for k, v in scope.items()},
        "pilot_object_rows": sum(scope.values()),
        "pilot_cases": len(cases),
        "pilot_cases_in_list": in_list,
        "pilot_flags": dict(flags),
    }
    out("bis.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _paths(el, prefix=""):
    s = set()
    for c in el:
        p = f"{prefix}/{_local(c.tag)}" if prefix else _local(c.tag)
        s.add(p)
        s |= _paths(c, p)
    return s


def iter_encumbrances(path: Path):
    """(atvk, object code, object type, row dict) per encumbrance row."""
    atvk, depth = None, 0
    for ev, el in ET.iterparse(path, events=("start", "end")):  # noqa: S314 discovery on agency files
        if ev == "start":
            depth += 1
            continue
        if depth == 2 and _local(el.tag) == "ATVK":
            atvk = el.text
        if depth == 3:
            code = typ = None
            for c in el.iter():
                if _local(c.tag) == "ObjectCadastreNr":
                    code = c.text
                if _local(c.tag) == "ObjectType":
                    typ = c.text
            rows = [c for c in el.iter() if _local(c.tag) == "EncumbranceRowData"]
            for row in rows:
                d = {}
                for c in row.iter():
                    if len(c) == 0:
                        d[_local(c.tag)] = (c.text or "").strip()
                yield atvk, code, typ, d, el
            el.clear()
        depth -= 1


def enc():
    paths, root, items = set(), set(), collections.Counter()
    rows, kinds, types, lens = collections.Counter(), {}, collections.Counter(), collections.Counter()
    measures, dates = collections.Counter(), collections.Counter()
    before_2025 = 0
    for p in sorted(OUT.glob("encumbrance/*.xml")):
        tree_root = None
        for ev, el in ET.iterparse(p, events=("start",)):  # noqa: S314 discovery on agency files
            tree_root = el
            break
        print(p.name, "root", _local(tree_root.tag))
        seen_items = set()
        for atvk, code, typ, d, item in iter_encumbrances(p):
            rows[atvk] += 1
            if id(item) not in seen_items:
                seen_items.add(id(item))
                items[atvk] += 1
                paths |= _paths(item)
                types[typ] += 1
                lens[len(code or "")] += 1
            kinds[d.get("EncumbranceKindId")] = d.get("EncumbranceKindName")
            measures[d.get("EncumbranceMeasure")] += 1
            dt = d.get("EncumbranceEstablishDate", "")
            dates[dt[:4]] += 1
            if dt and dt < "2025-02-01":
                before_2025 += 1
    classifier = {}
    for r in _csv(_one("atis_classifier/*.csv")):
        classifier.setdefault(r["Kods"], r)
    print("classifier columns", list(r.keys()))
    missing = {k: v for k, v in kinds.items() if k not in classifier}
    res = {
        "items_by_atvk": dict(items),
        "rows_by_atvk": dict(rows),
        "object_types": dict(types),
        "code_lengths": dict(lens),
        "measures": dict(measures),
        "establish_year": dict(sorted(dates.items())),
        "rows_established_before_2025_02_01": before_2025,
        "item_paths": sorted(paths),
        "distinct_kind_ids": len(kinds),
        "kind_ids_not_in_classifier": missing,
        "classifier_rows": sum(1 for _ in _csv(_one("atis_classifier/*.csv"))),
        "classifier_distinct_codes": len(classifier),
        "classifier_code_lengths": dict(collections.Counter(len(k) for k in classifier)),
        "name_differs_from_classifier": sum(
            1
            for k, v in kinds.items()
            if k in classifier and classifier[k]["Apraksts"].strip() != (v or "").strip()
        ),
    }
    out("enc.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))


def frozen():
    """Does the current encumbrance data hold every pilot encumbrance of the frozen list?"""
    current = collections.defaultdict(collections.Counter)  # object -> code -> n
    current_dates = collections.defaultdict(set)
    for p in sorted(OUT.glob("encumbrance/*.xml")):
        for _atvk, code, _typ, d, _ in iter_encumbrances(p):
            current[code][d.get("EncumbranceKindId")] += 1
            current_dates[(code, d.get("EncumbranceKindId"))].add(d.get("EncumbranceEstablishDate"))
    files = sorted(OUT.glob("frozen/*.csv"))
    header = {}
    admin = collections.Counter()
    pilot_rows = []
    for p in files:
        for r in _csv(p):
            header.setdefault(p.name, list(r.keys()))
            admin[(r.get("ADMRKIND"), r.get("ADMTKIND"))] += 0  # keys seen
            cad = (r.get("CAD_NR") or "").strip()
            g = cad[:4]
            if g in ("0500", "0900", "1300"):
                pilot_rows.append((p.name, r))
    print(json.dumps(header, ensure_ascii=False, indent=1))
    lens = collections.Counter(len((r["CAD_NR"] or "").strip()) for _, r in pilot_rows)
    res = collections.Counter()
    only_frozen_objects = collections.Counter()
    examples = []
    obj_absent = set()
    for fname, r in pilot_rows:
        cad = r["CAD_NR"].strip()
        code = (r.get("ENCD_ID") or "").strip()
        if cad not in current:
            res["object_has_no_current_encumbrance"] += 1
            obj_absent.add(cad)
            continue
        if current[cad][code] > 0:
            res["same_object_same_code"] += 1
        else:
            res["object_present_code_absent"] += 1
            only_frozen_objects[cad] += 1
            if len(examples) < 15:
                examples.append(
                    {
                        "file": fname,
                        "cad": cad,
                        "code": code,
                        "descr": r.get("DESCRIPTION"),
                        "date": r.get("ENC_DATE"),
                        "current_codes": dict(current[cad]),
                    }
                )
    by_date = collections.Counter()
    for (_c, _k), ds in current_dates.items():
        for d in ds:
            by_date["<2025-02-01" if d and d < "2025-02-01" else ">=2025-02-01"] += 1
    result = {
        "frozen_files": [p.name for p in files],
        "pilot_frozen_rows": len(pilot_rows),
        "pilot_frozen_code_lengths": dict(lens),
        "comparison": dict(res),
        "objects_without_any_current_encumbrance": len(obj_absent),
        "objects_with_codes_only_in_frozen": len(only_frozen_objects),
        "current_object_codes": len(current),
        "current_pairs_by_establish_date": dict(by_date),
        "examples": examples,
        "absent_object_examples": sorted(obj_absent)[:20],
    }
    out("frozen.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


def _classifier():
    return {r["Kods"]: r for r in _csv(_one("atis_classifier/*.csv"))}


def _current_codes():
    """object code -> set of current EncumbranceKindId, and kind id -> row count."""
    by_object, rows = collections.defaultdict(set), collections.Counter()
    for p in sorted(OUT.glob("encumbrance/*.xml")):
        for _a, code, _t, d, _ in iter_encumbrances(p):
            by_object[code].add(d.get("EncumbranceKindId"))
            rows[d.get("EncumbranceKindId")] += 1
    return by_object, rows


def frozen_detail():
    """Why frozen pilot rows are missing from the current list (data-sources.md §7.3)."""
    cls = _classifier()
    now = set((OUT / "objects_now.txt").read_text().split())
    current, _ = _current_codes()
    res, flags, codes, years = (collections.Counter() for _ in range(4))
    for p in sorted(OUT.glob("frozen/apgrutinajumi_*.csv")):
        for r in _csv(p):
            cad, k = r["CAD_NR"].strip(), r["ENCD_ID"].strip()
            if cad[:4] not in ("0500", "0900", "1300"):
                continue
            if cad not in now:
                res["object_gone_from_cadastre"] += 1
            elif k in current.get(cad, ()):
                res["also_current"] += 1
            elif len(k) != 10:
                res[f"old_code_len_{len(k)}"] += 1
            elif k not in cls:
                res["10digit_not_in_classifier"] += 1
            else:
                res["only_frozen_classifier_code"] += 1
                c = cls[k]
                flags[f"Ierobezoti_dati={c['Ierobezoti_dati']}"] += 1
                codes[f"{k} {c['Apraksts'][:60]}"] += 1
                years[r["ENC_DATE"][:4]] += 1
    result = {
        "causes": dict(res),
        "restricted_flag": dict(flags),
        "top_codes": codes.most_common(12),
        "years": dict(sorted(years.items())),
    }
    out("frozen_detail.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), "utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))


def dap():
    """DAP ATIS_CODE values vs classifier and pilot encumbrance codes (§7.4)."""
    cls = _classifier()
    _, enc_rows = _current_codes()
    res = collections.defaultdict(list)
    for line in (OUT / "dap_codes.txt").read_text("utf-8").splitlines():
        layer, code, descr, n = line.split("|")
        c = cls.get(code)
        res[layer].append(
            {
                "code": code,
                "n": int(n),
                "in_classifier": c is not None,
                "same_text": bool(c) and c["Apraksts"].strip().lower() == descr.strip().lower(),
                "pilot_encumbrance_rows": enc_rows.get(code, 0),
            }
        )
    nonempty = [x for v in res.values() for x in v if x["code"]]
    summary = {
        "nonempty_rows": sum(x["n"] for x in nonempty),
        "nonempty_rows_in_classifier": sum(x["n"] for x in nonempty if x["in_classifier"]),
        "distinct_codes": len({x["code"] for x in nonempty}),
        "distinct_codes_in_pilot_encumbrances": len(
            {x["code"] for x in nonempty if x["pilot_encumbrance_rows"]}
        ),
        "empty_by_layer": {k: sum(x["n"] for x in v if not x["code"]) for k, v in res.items()},
    }
    out("dap.json").write_text(
        json.dumps({"summary": summary, "layers": res}, ensure_ascii=False, indent=1), "utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    commands = {
        "show": show,
        "fetch": fetch,
        "bis": bis,
        "enc": enc,
        "frozen": frozen,
        "frozen_detail": frozen_detail,
        "dap": dap,
    }
    commands[sys.argv[1]]()
