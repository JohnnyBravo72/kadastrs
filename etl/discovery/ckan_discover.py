"""Find the PLAN.md §2.3 sources on data.gov.lv via the CKAN API.

Re-runnable, stdlib only. Reads metadata, DataStore column names and aggregates; `peek` additionally
reads zip directories, the first bytes of files and a few small files (< 5 MB). No bulk downloads.

    python -I etl/discovery/ckan_discover.py search     # run every search query, list candidates
    python -I etl/discovery/ckan_discover.py show       # package_show for every plan/selected dataset
    python -I etl/discovery/ckan_discover.py show NAME  # package_show for one dataset name
    python -I etl/discovery/ckan_discover.py fields     # column names of DataStore-backed resources (no rows)
    python -I etl/discovery/ckan_discover.py keys       # join-key fill rates via datastore_search_sql (aggregates only)
    python -I etl/discovery/ckan_discover.py peek       # zip listings, CSV header bytes, HTTP HEAD; small files only
    python -I etl/discovery/ckan_discover.py caps       # service type + layer names of OGC links (WFS vs WMS/WMTS)
    python -I etl/discovery/ckan_discover.py report     # write docs/data-sources-resources.md from the show output

Raw API responses go to etl/discovery/out/ (git-ignored). `show` also writes
out/selected_summary.json, which docs/data-sources.md is written from.
"""

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://data.gov.lv/dati/api/3/action/"
PORTAL = "https://data.gov.lv/dati/lv/dataset/"
OUT = Path(__file__).resolve().parent / "out"

# One entry per row of PLAN.md §2.3.
# `queries`:    package_search terms tried for the source.
# `plan_names`: dataset names PLAN.md (Miro doc) gives; checked as-is to confirm or refute them.
# `selected`:   dataset names chosen as the right match after reviewing search results.
SOURCES = {
    "varis": {
        "label": "Address Register (VARIS)",
        "queries": ["adrešu reģistra", "VARIS", "adreses"],
        "plan_names": ["valsts-adresu-registra-informacijas-sistemas-atvertie-dati"],
        "selected": ["varis-atvertie-dati"],
    },
    "cadastre": {
        "label": "Cadastre (parcels, buildings, parts, property numbers)",
        "queries": ["kadastra informācijas sistēmas", "kadastra telpiskie dati", "zemes vienības"],
        "plan_names": ["kadastra-informacijas-sistemas-atvertie-dati"],
        "selected": ["kadastra-informacijas-sistemas-atverti-telpiskie-dati",
                     "kadastra-informacijas-sistemas-atvertie-dati"],
    },
    "admin_boundaries": {
        "label": "Administrative boundaries",
        "queries": ["administratīvās teritorijas", "administratīvo teritoriju robežas"],
        "plan_names": [],
        "selected": ["atr", "administrativas-vienibas-inspire"],
    },
    "atis": {
        "label": "ATIS (apgrūtinātās teritorijas)",
        "queries": ["apgrūtināto teritoriju", "ATIS", "apgrūtinājumi", "aizsargjoslas"],
        "plan_names": [],
        "selected": ["atis-datu-un-kadastra-objektu-apgrutinajumu-klasifikators",
                     "apgrutinajumi-kas-kadastra-registreti-lidz-2025-gada-31-janvarim",
                     "annex-iii-inspire-dataset-for-area-management-restriction-regulation-zones-reporting-units-them1"],
    },
    "flood": {
        "label": "Flood maps",
        "queries": ["plūdu riska", "plūdu kartes", "applūstošās teritorijas"],
        "plan_names": ["pldu-riska-karu-atvrtie-dati-un-servisi5"],
        # plan_names entry turned out to be sea wind-surge 200y WMTS; the spring-flood 10y ones are below.
        "selected": ["pldu-riska-karu-atvrtie-dati-un-servisi",        # spring flood 10y, SHP (link to geolatvija only)
                     "pldu-riska-karu-atvrtie-dati-un-servisi1",       # spring flood 10y, WMTS
                     "3-cikla-latvijas-pldu-postjumu-vietu-un-pldu-riska-kartes",   # 3rd cycle spring flood SHP
                     "3-cikla-latvijas-pldu-postjumu-vietu-un-pldu-riska-kartes1",  # 3rd cycle 2026-2031 boundaries
                     "pldu-riska-karu-atvrtie-dati-un-servisi4",       # hazard zone levels
                     "pldu-riska-zonas"],
    },
    "nature": {
        "label": "Protected areas, microreserves, nature monuments, habitats",
        "queries": ["īpaši aizsargājamās dabas teritorijas", "mikroliegumi", "dabas pieminekļi",
                    "biotopi", "dabas datu pārvaldības sistēma OZOLS"],
        "plan_names": ["ipasi-aizsargajamas-dabas-teritorijas"],
        "selected": ["mikroliegumi", "dabas-pieminekli", "aizsargajamas-dzivotnes-biotopi",
                     "dabas-vertibu-geotelpiskie-dati"],
    },
    "zoning": {
        "label": "Zoning (TAPIS)",
        "queries": ["TAPIS", "teritorijas plānojums", "funkcionālais zonējums"],
        "plan_names": [],
        "selected": ["tapis", "teritorijas-attstbas-plnoanas-informcijas-sistmas-tapis-eotelpiskie-dati",
                     "fz-skelumi"],
    },
    "bis": {
        "label": "Construction cases (BIS)",
        "queries": ["būvniecības lietas", "BIS būvniecība", "būvatļaujas"],
        "plan_names": [],
        "selected": ["bis_04lylzfvt9f25h4divvcfq", "bis_jlyakg7hgslonjnwyrwc6w", "bis_tln9s3hrpjlnucmjip9r3g"],
    },
    "ur": {
        "label": "Companies (UR)",
        "queries": ["uzņēmumu reģistrs", "Uzņēmumu reģistra atvērtie dati"],
        "plan_names": ["uz"],
        "selected": [],
    },
    "vid": {
        "label": "VID taxpayer rating, tax debts",
        "queries": ["nodokļu maksātāju reitings", "nodokļu parādi", "nodokļu parādnieki",
                    "VID nodokļu parādnieki"],
        "plan_names": [],
        "selected": ["nodoklu-maksataju-reitings"],
    },
    "deminimis": {
        "label": "De minimis aid",
        "queries": ["de minimis", "komercdarbības atbalsts"],
        "plan_names": [],
        "selected": ["pieskirtais-de-minimis-atbalsts-latvija"],
    },
    "eu_projects": {
        "label": "EU co-financed projects",
        "queries": ["ES fondu projekti", "Eiropas Savienības fondu", "kohēzijas politikas projekti"],
        "plan_names": [],
        "selected": ["eiropas-savienibas-fondu-21-27-perioda-lidzfinansetie-projekti",
                     "es-lidzfinansetie-projekti",
                     "eiropas-savienibas-atveselosanas-fonda-lidzfinansetie-projekti"],
    },
    "procurement": {
        "label": "Procurement (EIS / IUB)",
        "queries": ["iepirkumi", "publiskie iepirkumi", "EIS"],
        "plan_names": [],
        "selected": ["ligumi", "publisko-iepirkumu-pazinojumi", "iepirkumu-rezultatu-datu-grupa"],
    },
    "heritage": {
        "label": "Cultural heritage",
        "queries": ["kultūras pieminekļi", "kultūras mantojums"],
        "plan_names": [],
        "selected": ["valsts-aizsargajamo-nekustamo-piemineklu-saraksts"],
    },
    "municipal_liabilities": {
        "label": "Municipal liabilities",
        "queries": ["pašvaldību saistības", "pašvaldību aizņēmumi"],
        "plan_names": [],
        "selected": ["pasvaldibu-saistibu-apmers"],
    },
    "ownership": {
        "label": "Ownership (īpašumtiesības)",
        "queries": ["īpašumtiesības", "īpašnieku statuss", "zemes īpašnieki"],
        "plan_names": [],
        "selected": ["kadastra-informacijas-sistemas-atvertie-dati", "dalitais-ipasums"],
    },
    "sanctions": {
        "label": "Sanctions lists",
        "queries": ["sankcijas", "sankciju saraksts"],
        "plan_names": [],
        "selected": ["sanctions", "sankciju-subjektu-lidzekli-un-saimnieciskie-resursi-kas-iesaldeti-latvija"],
    },
}


def call(action, **params):
    url = API + action + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "kadastrs-discovery/0.1"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.load(resp)
            if not body.get("success"):
                raise RuntimeError(f"{action} failed: {body.get('error')}")
            return body["result"]
        except urllib.error.HTTPError as e:
            if e.code in (403, 404) or attempt == 2:
                return e.code
        except urllib.error.URLError:
            if attempt == 2:
                raise
        time.sleep(2)


def save(rel, data):
    path = OUT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def org_title(pkg):
    return (pkg.get("organization") or {}).get("title")


def search():
    for sid, src in SOURCES.items():
        print(f"\n=== {sid}: {src['label']}")
        seen = {}
        for q in src["queries"]:
            res = call("package_search", q=q, rows=25)
            save(f"search/{sid}/{q.replace(' ', '_')}.json", res)
            print(f"  q={q!r}: {res['count']} hits")
            for pkg in res["results"]:
                seen.setdefault(pkg["name"], pkg)
        for name, pkg in seen.items():
            print(f"    - {name} | {pkg['title']} | {org_title(pkg)}")


def summarize(pkg):
    return {
        "name": pkg["name"],
        "id": pkg["id"],
        "title": pkg["title"],
        "url": PORTAL + pkg["name"],
        "publisher": org_title(pkg),
        "maintainer_email": pkg.get("maintainer_email"),
        "frequency": pkg.get("frequency"),
        "metadata_modified": pkg.get("metadata_modified"),
        "modified": pkg.get("modified"),
        "license_id": pkg.get("license_id"),
        "license_title": pkg.get("license_title"),
        "notes": pkg.get("notes"),
        "resources": [
            {
                "name": r.get("name"),
                "format": r.get("format"),
                "url": r.get("url"),
                "host": urllib.parse.urlparse(r.get("url") or "").netloc,
                "size": r.get("size"),
                "last_modified": r.get("last_modified") or r.get("metadata_modified"),
                "datastore_active": r.get("datastore_active"),
            }
            for r in pkg.get("resources", [])
        ],
    }


def show(names=None):
    if names:
        targets = {"adhoc": names}
    else:
        targets = {sid: list(dict.fromkeys(s["plan_names"] + s["selected"])) for sid, s in SOURCES.items()}
    summary = {}
    for sid, dataset_names in targets.items():
        summary[sid] = []
        for name in dataset_names:
            pkg = call("package_show", id=name)
            if isinstance(pkg, int):
                error = {403: "NOT ACCESSIBLE (403: exists but private or deleted)",
                         404: "NOT FOUND (404)"}[pkg]
                print(f"\n[{sid}] {name}: {error}")
                summary[sid].append({"name": name, "error": error})
                continue
            save(f"show/{name}.json", pkg)
            s = summarize(pkg)
            summary[sid].append(s)
            print(f"\n[{sid}] {s['title']} ({s['name']}) | {s['publisher']}")
            print(f"  freq={s['frequency']} modified={s['metadata_modified']} licence={s['license_id']}")
            for r in s["resources"]:
                print(f"  - {r['format']:8} {r['name']} | {r['url']}")
    if not names:
        save("selected_summary.json", summary)


def fields():
    """Column names of every DataStore-backed resource (datastore_search limit=0: no rows fetched)."""
    summary = json.loads((OUT / "selected_summary.json").read_text(encoding="utf-8"))
    result = {}
    for sid, pkgs in summary.items():
        for pkg in pkgs:
            if "error" in pkg:
                continue
            raw = json.loads((OUT / "show" / f"{pkg['name']}.json").read_text(encoding="utf-8"))
            for r in raw.get("resources", []):
                if not r.get("datastore_active"):
                    continue
                res = call("datastore_search", resource_id=r["id"], limit=0)
                if isinstance(res, int):
                    cols = f"HTTP {res}"
                else:
                    cols = {f["id"]: f["type"] for f in res["fields"] if f["id"] != "_id"}
                result.setdefault(sid, {}).setdefault(pkg["name"], {})[r.get("name")] = {
                    "resource_id": r["id"], "total_rows": None if isinstance(res, int) else res.get("total"),
                    "fields": cols,
                }
                print(f"[{sid}] {pkg['name']} / {r.get('name')}: {cols}")
    save("fields.json", result)


# Join-key checks (PLAN.md §2.4 step 3). Aggregates and key-column samples only: never names.
# (source id, dataset name, resource-name prefix, SQL with {t} = resource table)
KEY_CHECKS = [
    ("bis", "bis_tln9s3hrpjlnucmjip9r3g", "buvniecibas_lietu_objekti",
     'SELECT count(*) total, count("Buves_kadastra_apzimejums") with_building_cad, '
     'count("Buves_objekta_adreses_kods") with_address_code, '
     'count(DISTINCT "Buvniecibas_lietas_numurs") cases FROM {t}'),
    ("bis", "bis_tln9s3hrpjlnucmjip9r3g", "buvniecibas_lietu_objekti",
     'SELECT "Buvniecibas_veids", count(*) n FROM {t} GROUP BY 1 ORDER BY 2 DESC'),
    ("bis", "bis_tln9s3hrpjlnucmjip9r3g", "buvniecibas_lietu_objekti",
     'SELECT "Buves_kadastra_apzimejums" FROM {t} WHERE "Buves_kadastra_apzimejums" IS NOT NULL LIMIT 5'),
    ("bis", "bis_04lylzfvt9f25h4divvcfq", "jaunbuvju",
     'SELECT count(*) total, count("Buves_kadastra_apzimejums") with_building_cad, '
     'count("Buves_adreses_kods") with_address_code, '
     'count("Buves_atrasanas_vieta_geografiskais_garums") with_coords FROM {t}'),
    ("bis", "bis_jlyakg7hgslonjnwyrwc6w", "Būvniecības lietas",
     'SELECT count(*) total, count(DISTINCT "Buvniecibas_lietas_numurs") cases FROM {t}'),
    ("bis", "bis_jlyakg7hgslonjnwyrwc6w", "Būvniecības lietas",
     'SELECT "Buvniecibas_veids", count(*) n FROM {t} GROUP BY 1 ORDER BY 2 DESC'),
    ("ur", "uz", "Uzņēmumu",
     'SELECT count(*) total, sum(CASE WHEN "addressid" > 0 THEN 1 ELSE 0 END) with_addressid, '
     'count("atvk") with_atvk, sum(CASE WHEN "terminated" IS NULL THEN 1 ELSE 0 END) not_terminated FROM {t}'),
    ("ur", "uz", "Uzņēmumu",
     'SELECT "addressid", "atvk" FROM {t} WHERE "addressid" > 0 LIMIT 5'),
    ("eu_projects", "eiropas-savienibas-fondu-21-27-perioda-lidzfinansetie-projekti", "ES fondu projektu īstenošanas",
     'SELECT count(*) total, sum(CASE WHEN "KadastraNumurs" <> \'\' THEN 1 ELSE 0 END) with_cad, '
     'sum(CASE WHEN "Adrese" <> \'\' THEN 1 ELSE 0 END) with_address, count(DISTINCT "ProjektaNumurs") projects FROM {t}'),
    ("eu_projects", "eiropas-savienibas-fondu-21-27-perioda-lidzfinansetie-projekti", "ES fondu projektu īstenošanas",
     'SELECT "KadastraNumurs", "Regions" FROM {t} WHERE "KadastraNumurs" <> \'\' LIMIT 5'),
    # In these two tables KadastraNumurs is typed numeric (leading zeros lost in the DataStore copy).
    ("eu_projects", "es-lidzfinansetie-projekti", "ES fondu projektu īstenošanas",
     'SELECT count(*) total, count("KadastraNumurs") with_cad, '
     'sum(CASE WHEN "Adrese" <> \'\' THEN 1 ELSE 0 END) with_address, count(DISTINCT "ProjektaNumurs") projects FROM {t}'),
    ("eu_projects", "eiropas-savienibas-atveselosanas-fonda-lidzfinansetie-projekti", "AF projektu īstenošanas",
     'SELECT count(*) total, count("KadastraNumurs") with_cad, '
     'sum(CASE WHEN "Adrese" <> \'\' THEN 1 ELSE 0 END) with_address, count(DISTINCT "ProjektaNumurs") projects FROM {t}'),
    ("atis", "atis-datu-un-kadastra-objektu-apgrutinajumu-klasifikators", "ATIS un Kadastra objekta datu klasifikators",
     'SELECT "Dati", "Visparpieejami_dati", "Ierobezoti_dati", count(*) n FROM {t} GROUP BY 1,2,3 ORDER BY 1,2,3'),
    ("vid", "nodoklu-maksataju-reitings", "Reitings",
     'SELECT "Reitings", "Skaidrojums", count(*) n FROM {t} GROUP BY 1,2 ORDER BY 1'),
    ("vid", "nodoklu-maksataju-reitings", "Reitings",
     'SELECT count(*) total, min("Informacijas_atjaunosanas_datums"::text) min_date, '
     'max("Informacijas_atjaunosanas_datums"::text) max_date FROM {t}'),
    ("heritage", "valsts-aizsargajamo-nekustamo-piemineklu-saraksts", "Valsts",
     'SELECT count(*) total, sum(CASE WHEN "Kadastra_apzimejums" <> \'\' THEN 1 ELSE 0 END) with_cad FROM {t}'),
]


def keys():
    flds = json.loads((OUT / "fields.json").read_text(encoding="utf-8"))
    results = []
    for sid, pkg, prefix, sql in KEY_CHECKS:
        rid = next(v["resource_id"] for name, v in flds[sid][pkg].items() if name.strip().startswith(prefix))
        q = sql.format(t=f'"{rid}"')
        res = call("datastore_search_sql", sql=q)
        records = f"HTTP {res}" if isinstance(res, int) else res["records"]
        results.append({"source": sid, "dataset": pkg, "sql": q, "records": records})
        print(f"\n[{sid}] {pkg}\n  {q}\n  -> {records}")
    save("keys.json", results)


# Cheap looks at resource files without downloading them in full.
# ("zip", url): list the zip's files via HTTP Range on the central directory.
# ("head", url): first bytes of a file (CSV header line).
# ("http", url): status, content type and length only.
# ("get", url): small file (< 1 MB) saved to out/samples/.
# ("prj", url): small zip (< 5 MB) read in memory; distinct .prj (CRS) texts printed.
PEEKS = [
    ("prj", "https://data.gov.lv/dati/lv/dataset/b28f0eed-73b0-4e44-94e7-b04b11bf0b69/resource/"
            "e0cdfc6c-836f-4263-99f6-a65a1a0275cd/download/0007000_kk_shp.zip"),
    ("get", "https://data.gov.lv/dati/dataset/be841486-4af9-4d38-aa14-6502a2ddb517/resource/"
            "dc113f7a-80a3-4e4c-8975-a8ac7424cdc7/download/ad_xsdshemas_05032026.zip"),
    ("zip", "https://data.gov.lv/dati/lv/dataset/b28f0eed-73b0-4e44-94e7-b04b11bf0b69/resource/"
            "e0cdfc6c-836f-4263-99f6-a65a1a0275cd/download/0007000_kk_shp.zip"),
    ("zip", "https://data.gov.lv/dati/dataset/6b06a7e8-dedf-4705-a47b-2a7c51177473/resource/"
            "b643b1b3-223f-4394-9beb-18524f8b0b82/download/aw_shp.zip"),
    ("head", "https://data.gov.lv/dati/dataset/9911ae4c-f18f-44d3-84b5-a45ae4c9b59a/resource/"
             "f41f3ee3-5040-4c65-8c80-f71495c817d9/download/"
             "translation-missing-lv.activerecord.attributes.case_building.csv.filename"),
    ("head", "https://data.gov.lv/dati/dataset/be841486-4af9-4d38-aa14-6502a2ddb517/resource/"
             "a0d801da-8eb0-4426-9087-50e8139bce39/download/ownership.zip"),
    ("http", "https://geo-dpps.viss.gov.lv/api/DPPSPackage/client/Pludu_risk_441_pcw3lv/"
             "cd1adaff-6c0c-492d-b0a7-2943827a1240"),
    ("http", "https://geo-dpps.viss.gov.lv/api/DPPSPackage/client/Pludu_risk_288_JzBggF/"
             "51087a26-eaad-4eec-a511-73d4874ea638"),
    ("http", "https://geo-dpps.viss.gov.lv/api/DPPSPackage/client/Teritorija_454_4DUoZx/"
             "e4ab2161-88bf-4f35-85b8-f1ca8dd5ebb3"),
    ("http", "https://deminimis.fm.gov.lv/public/mekletajs/export_csv"),
    ("http", "https://open.iub.gov.lv/data/notice"),
]


# OGC service links (geolatvija DPPS proxies) listed as resources: which are WFS (vector) vs WMS/WMTS (images).
DPPS = "https://geo-dpps.viss.gov.lv/api/DPPSPackage/client/"
CAPS = {
    "flood 3rd cycle 2026-2031 (3-cikla-...-kartes1)": [
        DPPS + "3._cikla_L_556_karVbb/cc6f2ed3-dbfb-42d0-98e1-4d9f10f57fea",
        DPPS + "3._cikla_L_557_7iFPTq/b7ad025f-833a-4b4f-a845-d5cec9d24092",
        DPPS + "3._cikla_L_558_jIS73E/3322e012-8cb3-4a4c-8acf-a467e25a17b3"],
    "flood hazard zone levels (pldu-...-servisi4)": [
        DPPS + "Pludu_risk_438_VM2yn5/a2c91dbc-f813-4b29-95d7-cf586ab98941",
        DPPS + "Pludu_risk_442_YX2DFo/18d92c73-4073-4ec3-baff-f8217e27c987",
        DPPS + "Pludu_risk_440_JMMMhK/16e57214-11f4-47fd-87cd-700c9e501b68",
        DPPS + "Pludu_risk_436_WTD8Ns/5e95ad7d-1362-47a1-9fd0-8226a06f7989",
        DPPS + "Pludu_risk_446_u8AhHX/92f26ecf-aaea-43b0-b838-04c1c288915f",
        DPPS + "Pludu_risk_444_xjvsLc/5c71094f-67db-4a85-be19-a9c4aff2f08b"],
    "spring flood 10y WMTS (pldu-...-servisi1)": [
        DPPS + "Pludu_risk_443_Dv50WI/5acd43d2-15bf-4fb6-b163-6628576c15cb"],
    "flood risk zones (pldu-riska-zonas)": [
        DPPS + "Pludu_risk_288_JzBggF/51087a26-eaad-4eec-a511-73d4874ea638",
        DPPS + "Pludu_risk_289_dchGXE/457870f3-deaf-400b-8d4d-32dfab44f96f"],
    "TAPIS geodata (teritorijas-...-tapis-eotelpiskie-dati)": [
        DPPS + "Teritorija_454_4DUoZx/e4ab2161-88bf-4f35-85b8-f1ca8dd5ebb3",
        DPPS + "Teritorija_451_GKJOzb/96f059e4-9ed2-479c-976f-dcbed668972f"],
    "INSPIRE area management (annex-iii-...-them1)": [
        DPPS + "Annex_III._223_5yhFly/5db14115-5006-4a2c-9a61-b221929db312",
        DPPS + "Annex_III._224_LoBPIF/5b9945cf-7d56-460a-a791-074b260e7dea"],
}


def caps():
    import re
    results = {}
    for label, urls in CAPS.items():
        for url in urls:
            status, _, body = fetch(url)
            text = body.decode("utf-8", "replace")
            if "WFS_Capabilities" in text:
                kind = "WFS"
                names = re.findall(r"<FeatureType[^>]*>\s*<Name>([^<]+)</Name>", text)
                crs = sorted(set(re.findall(r"<DefaultCRS>([^<]+)</DefaultCRS>", text)))
            elif "WMS_Capabilities" in text:
                kind = "WMS"
                names = re.findall(r"<Layer[^>]*>\s*<Name>([^<]+)</Name>", text)
                crs = []
            elif "wmts" in text[:2000].lower():
                kind = "WMTS"
                names = re.findall(r"<Layer>\s*<ows:Title>([^<]+)</ows:Title>", text)
                crs = []
            else:
                kind, names, crs = f"other (HTTP {status})", [], []
            results.setdefault(label, []).append({"url": url, "service": kind, "layers": names, "crs": crs})
            print(f"[{label}] {kind} {crs} {names[:30]}")
    save("caps.json", results)


def fetch(url, headers=None, method="GET"):
    req = urllib.request.Request(url, method=method,
                                 headers={"User-Agent": "kadastrs-discovery/0.1", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.status, dict(resp.headers), resp.read() if method == "GET" else b""
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), b""
    except urllib.error.URLError as e:
        return f"URLError: {e.reason}", {}, b""


def zip_listing(url):
    import struct
    status, hdr, tail = fetch(url, {"Range": "bytes=-65536"})
    if status != 206:
        return {"status": status, "error": "range request not honoured"}
    eocd = tail.rfind(b"PK\x05\x06")
    cd_size, cd_offset = struct.unpack("<II", tail[eocd + 12:eocd + 20])
    total = int(hdr["Content-Range"].split("/")[1])
    cd_start_in_tail = len(tail) - (total - cd_offset)
    if cd_start_in_tail < 0:
        _, _, cd = fetch(url, {"Range": f"bytes={cd_offset}-{cd_offset + cd_size - 1}"})
    else:
        cd = tail[cd_start_in_tail:cd_start_in_tail + cd_size]
    files, i = [], 0
    while cd[i:i + 4] == b"PK\x01\x02":
        usize = struct.unpack("<I", cd[i + 24:i + 28])[0]
        n, m, k = struct.unpack("<HHH", cd[i + 28:i + 34])
        files.append((cd[i + 46:i + 46 + n].decode("utf-8", "replace"), usize))
        i += 46 + n + m + k
    return {"status": status, "zip_bytes": total, "files": files}


def peek():
    results = []
    for kind, url in PEEKS:
        if kind == "zip":
            r = zip_listing(url)
        elif kind == "head":
            status, hdr, body = fetch(url, {"Range": "bytes=0-1999"})
            r = {"status": status, "content_range": hdr.get("Content-Range"),
                 "first_bytes": body[:2000].decode("utf-8", "replace")}
        elif kind == "http":
            status, hdr, _ = fetch(url, method="HEAD")
            r = {"status": status, "content_type": hdr.get("Content-Type"),
                 "content_length": hdr.get("Content-Length"),
                 "content_disposition": hdr.get("Content-Disposition")}
        elif kind == "prj":
            import io
            import zipfile
            status, hdr, body = fetch(url)
            if len(body) > 5_000_000:
                r = {"status": status, "error": "zip larger than 5 MB, not opened"}
            else:
                z = zipfile.ZipFile(io.BytesIO(body))
                r = {"status": status, "bytes": len(body),
                     "prj": sorted({z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith(".prj")})}
        else:
            status, hdr, body = fetch(url)
            dest = OUT / "samples" / url.rsplit("/", 1)[-1]
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(body[:1_000_000])
            r = {"status": status, "saved": str(dest), "bytes": len(body)}
        results.append({"kind": kind, "url": url, **r})
        print(f"\n[{kind}] {url}\n  {json.dumps(r, ensure_ascii=False)[:1500]}")
    save("peek.json", results)


def report():
    """Write docs/data-sources-resources.md: every resource of every plan/selected dataset (generated)."""
    summary = json.loads((OUT / "selected_summary.json").read_text(encoding="utf-8"))
    freq = lambda f: (f or "").rsplit("/", 1)[-1] or "—"
    lines = ["# Data sources: resource appendix",
             "",
             "Generated by `python -I etl/discovery/ckan_discover.py report` from CKAN `package_show`. "
             "Do not edit by hand; re-run the script. Narrative and findings: [data-sources.md](data-sources.md).",
             ""]
    for sid, pkgs in summary.items():
        lines += [f"## {SOURCES[sid]['label']} (`{sid}`)", ""]
        for p in pkgs:
            if "error" in p:
                lines += [f"### `{p['name']}`: {p['error']}", ""]
                continue
            lines += [f"### [{p['title']}]({p['url']})", "",
                      f"- id `{p['id']}`, name `{p['name']}`",
                      f"- publisher: {p['publisher']}; frequency: {freq(p['frequency'])}; "
                      f"metadata modified: {(p['metadata_modified'] or '')[:10]}; licence: {p['license_id']}",
                      "", "| # | Resource | Format | Host | Size (bytes) | URL |", "|---|---|---|---|---|---|"]
            for i, r in enumerate(p["resources"], 1):
                name = (r["name"] or "").strip().replace("|", "/")
                lines.append(f"| {i} | {name} | {r['format'] or '—'} | {r['host'] or '—'} | "
                             f"{r['size'] if r['size'] is not None else '—'} | {r['url'] or '—'} |")
            lines.append("")
    dest = Path(__file__).resolve().parents[2] / "docs" / "data-sources-resources.md"
    dest.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"wrote {dest}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    cmd = sys.argv[1] if len(sys.argv) > 1 else "search"
    if cmd == "search":
        search()
    elif cmd == "show":
        show(sys.argv[2:] or None)
    elif cmd == "fields":
        fields()
    elif cmd == "report":
        report()
    elif cmd == "caps":
        caps()
    elif cmd == "peek":
        peek()
    elif cmd == "keys":
        keys()
    else:
        sys.exit(__doc__)
