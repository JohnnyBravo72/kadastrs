"""Phase 0 step 2: download one sample per MVP source for the pilot municipality into data/samples/.

Stdlib only. Each source goes into its own folder. Files over 200 MB are refused (ask first).
From the national cadastre XML zips only the pilot municipality's member is fetched (HTTP Range).
A manifest with URL, size, SHA-256 and download time is written to data/samples/manifest.json.

    python -I etl/discovery/samples.py 0003000          # ATVK of the pilot municipality
"""

import hashlib
import json
import struct
import sys
import time
import urllib.request
import zlib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "data" / "samples"
LIMIT = 200_000_000
UA = {"User-Agent": "kadastrs-discovery/0.1"}

DS = "https://data.gov.lv/dati/dataset/"
CAD_TEXT = DS + "be841486-4af9-4d38-aa14-6502a2ddb517/resource/"
CADASTRE_TEXT = {  # resource -> national zip with one XML per municipality
    "property": CAD_TEXT + "931e6299-61ba-477b-ba8d-f0fb30db9667/download/property.zip",
    "parcel": CAD_TEXT + "1618f19a-c818-4966-8183-a2e3c108597a/download/parcel.zip",
    "parcelpart": CAD_TEXT + "58635c63-8c04-4193-a9f2-ec674c57ae93/download/parcelpart.zip",
    "building": CAD_TEXT + "9fe29b57-07cd-4458-b22c-b0b9f2bc8915/download/building.zip",
    "address": CAD_TEXT + "2aeea249-6948-4713-92c2-e01543ea0f33/download/address.zip",
    "encumbrance": CAD_TEXT + "ca8a415c-a894-427f-b14d-d1e44c582620/download/encumbrance.zip",
}
VARIS = DS + "6b06a7e8-dedf-4705-a47b-2a7c51177473/resource/"
DAP = {
    "iadt": DS + "b2de2313-c20e-4ebf-a9c0-b8099566320a/resource/aa165932-8835-41a0-baa2-3336d2e8e6ef/download/ipasi_aizsargajamas_dabas_teritorijas.zip",
    "mikroliegumi": DS + "fa50b0fb-04f2-452f-ade9-f8448d94eefa/resource/4770cc11-02eb-42e1-98c9-e640e3d8b7ff/download/mikroliegumi.zip",
    "dabas_pieminekli": DS + "d156b6f2-fd1f-437f-89d9-5c84efd649f3/resource/18139898-7119-4ff8-b769-5ab956209bd3/download/dabas_pieminekli.zip",
    "biotopi": DS + "7b5ac3e9-aaa5-44d6-a828-777736edeb71/resource/e52b8094-f563-4706-b59f-401f7113a133/download/biotopi.zip",
}
BIS = {
    "objekti.csv": DS + "9911ae4c-f18f-44d3-84b5-a45ae4c9b59a/resource/f41f3ee3-5040-4c65-8c80-f71495c817d9/download/translation-missing-lv.activerecord.attributes.case_building.csv.filename",
    "jaunbuves.csv": DS + "9833285e-6529-49dc-b5ee-fb8de3881380/resource/10e7b228-845e-4345-b3c7-4d1774e27b85/download/jaunbuvju_geotelpiskie_dati_09.10.2026.csv",
    "lietas.csv": DS + "37072983-16ac-41a0-93c0-9c9ad711279d/resource/4f5648b2-fed8-4722-987f-9a36dfa331dc/download/buvniecibas-lietu-saraksts-09.10.2026.csv",
}
manifest = []


def get(url, headers=None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=600) as r:
        return r.status, dict(r.headers), r.read()


def size_of(url):
    req = urllib.request.Request(url, method="HEAD", headers=UA)
    with urllib.request.urlopen(req, timeout=120) as r:
        return int(r.headers.get("Content-Length") or 0)


def record(path, url, note=""):
    data = path.read_bytes()
    manifest.append({"path": str(path.relative_to(ROOT)), "url": url, "bytes": len(data),
                     "sha256": hashlib.sha256(data).hexdigest(),
                     "downloaded": datetime.now(timezone.utc).isoformat(timespec="seconds"), "note": note})
    print(f"  {path.relative_to(ROOT)}  {len(data)/1e6:.1f} MB")


def download(url, dest, note=""):
    n = size_of(url)
    if n > LIMIT:
        print(f"  SKIPPED {dest.name}: {n/1e6:.0f} MB > 200 MB, ask first")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    _, _, body = get(url)
    dest.write_bytes(body)
    record(dest, url, note)


def zip_member(url, match, dest_dir):
    """Fetch only the zip members whose name contains `match`, via HTTP Range."""
    _, hdr, tail = get(url, {"Range": "bytes=-65536"})
    total = int(hdr["Content-Range"].split("/")[1])
    eocd = tail.rfind(b"PK\x05\x06")
    cd_size, cd_offset = struct.unpack("<II", tail[eocd + 12:eocd + 20])
    _, _, cd = get(url, {"Range": f"bytes={cd_offset}-{cd_offset + cd_size - 1}"})
    i = 0
    while cd[i:i + 4] == b"PK\x01\x02":
        method = struct.unpack("<H", cd[i + 10:i + 12])[0]
        csize, usize = struct.unpack("<II", cd[i + 20:i + 28])
        n, m, k = struct.unpack("<HHH", cd[i + 28:i + 34])
        local = struct.unpack("<I", cd[i + 42:i + 46])[0]
        name = cd[i + 46:i + 46 + n].decode("utf-8", "replace")
        i += 46 + n + m + k
        if match not in name or name.endswith("/"):
            continue
        if usize > LIMIT:
            print(f"  SKIPPED {name}: {usize/1e6:.0f} MB uncompressed > 200 MB, ask first")
            continue
        _, _, lh = get(url, {"Range": f"bytes={local}-{local + 29}"})
        ln, lm = struct.unpack("<HH", lh[26:30])
        start = local + 30 + ln + lm
        _, _, comp = get(url, {"Range": f"bytes={start}-{start + csize - 1}"})
        body = zlib.decompress(comp, -15) if method == 8 else comp
        dest = dest_dir / Path(name).name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body)
        record(dest, url, f"member {name} of {total} byte zip")


def main(atvk):
    sys.stdout.reconfigure(encoding="utf-8")
    print("cadastre spatial")
    download(DS.replace("/dati/dataset/", "/dati/lv/dataset/") +
             "b28f0eed-73b0-4e44-94e7-b04b11bf0b69/resource/" + {
                 "0002000": "a55953fb-b4ce-4c10-aa0d-c89119b3428f",
                 "0003000": "269dadbd-f504-4bb5-98f4-7f4c01f773bc",
                 "0004000": "0d6779e2-f4ba-4a89-849c-0c2aee99b43c"}[atvk] + f"/download/{atvk}_kk_shp.zip",
             ROOT / "cadastre_spatial" / f"{atvk}_kk_shp.zip")
    print("cadastre text (pilot member only)")
    for key, url in CADASTRE_TEXT.items():
        zip_member(url, f"/{atvk}_", ROOT / "cadastre_text" / key)
    print("VARIS")
    download(VARIS + "a510737a-18ce-400f-ad4b-04fce5228272/download/aw_eka.csv", ROOT / "varis" / "aw_eka.csv")
    download(VARIS + "b643b1b3-223f-4394-9beb-18524f8b0b82/download/aw_shp.zip", ROOT / "varis" / "aw_shp.zip")
    download(VARIS + "d07443d7-15a8-4db6-9e53-7a68eec3c0dd/download/aw_eka_his.csv", ROOT / "varis" / "aw_eka_his.csv")
    print("DAP nature (national SHP)")
    for key, url in DAP.items():
        download(url, ROOT / "nature" / f"{key}.zip")
    print("BIS")
    for key, url in BIS.items():
        download(url, ROOT / "bis" / key)
    path = ROOT / "manifest.json"
    old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    keep = [m for m in old if m["path"] not in {x["path"] for x in manifest}]
    path.write_text(json.dumps(keep + manifest, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    t = time.time()
    main(sys.argv[1])
    print(f"done in {time.time() - t:.0f}s")
