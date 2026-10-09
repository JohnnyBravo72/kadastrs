"""A fake data.gov.lv (CKAN package_show + file server with HTTP Range) and
builders for small synthetic source files shaped like the verified ones
(docs/data-sources.md §5). No real data is committed."""

import csv
import io
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime

import httpx
import shapefile

from etl.settings import etl_config, schemas

API = "https://ckan.test/dati/api/3/action/"
FILES = "https://files.test/"

DATASETS = {
    "admin_boundaries": "varis-atvertie-dati",
    "varis_addresses": "varis-atvertie-dati",
    "cadastre_spatial": "kadastra-informacijas-sistemas-atverti-telpiskie-dati",
    "cadastre_text": "kadastra-informacijas-sistemas-atvertie-dati",
}


@dataclass
class FakeServer:
    """Serves package_show for the configured datasets and the files behind them."""

    files: dict[str, bytes] = field(default_factory=dict)  # url -> body
    resources: dict[str, dict] = field(default_factory=dict)  # resource id -> CKAN dict
    requests: list[httpx.Request] = field(default_factory=list)
    ignore_range: bool = False
    licence: str = "CC-BY-4.0"

    def publish(
        self,
        source_id: str,
        role: str,
        filename: str,
        body: bytes,
        last_modified: str = "2026-01-15T08:00:00",
    ) -> str:
        """Put a file behind the resource id that config/etl.yaml maps `role` to."""
        rid = etl_config().files[source_id][role]
        url = f"{FILES}{rid}/{filename}"
        old = self.resources.get(rid)
        if old and old["url"] != url:
            self.files.pop(old["url"], None)
        self.files[url] = body
        self.resources[rid] = {
            "id": rid,
            "name": filename,
            "url": url,
            "last_modified": last_modified,
            "size": len(body),
            "_dataset": DATASETS[source_id],
        }
        return url

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url.startswith(API + "package_show"):
            name = request.url.params["id"]
            res = [
                {k: v for k, v in r.items() if k != "_dataset"}
                for r in self.resources.values()
                if r["_dataset"] == name
            ]
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "result": {
                        "id": f"uuid-{name}",
                        "name": name,
                        "license_id": self.licence,
                        "resources": res,
                    },
                },
            )
        body = self.files.get(url)
        if body is None:
            return httpx.Response(404)
        rng = request.headers.get("Range")
        if rng and not self.ignore_range:
            m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng)
            a, b = m.group(1), m.group(2)
            if a == "":
                start, end = max(0, len(body) - int(b)), len(body) - 1
            else:
                start, end = int(a), int(b) if b else len(body) - 1
            return httpx.Response(
                206,
                content=body[start : end + 1],
                headers={
                    "Content-Range": f"bytes {start}-{end}/{len(body)}",
                    "Accept-Ranges": "bytes",
                },
            )
        return httpx.Response(200, content=body)

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handler))

    def range_requests(self) -> list[str]:
        return [r.headers.get("Range") for r in self.requests if r.headers.get("Range")]


# --- VARIS CSV -------------------------------------------------------------------


def csv_bytes(name: str, rows: list[dict], bom: bool = True) -> bytes:
    header = schemas()["csv"][name]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=header, lineterminator="\r\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: r.get(k, "") for k in header})
    data = buf.getvalue().encode("utf-8")
    return (b"\xef\xbb\xbf" + data) if bom else data


CITY = {"0002000": "100003011", "0003000": "100003028", "0004000": "100003036"}
STREET = "105000001"  # a street in Jelgava


def varis_files(extra_eka: list[dict] | None = None) -> dict[str, bytes]:
    pilseta = [
        {
            "KODS": code,
            "TIPS_CD": "104",
            "NOSAUKUMS": name,
            "STATUSS": "EKS",
            "ATRIB": atvk,
            "STD": name,
        }
        for atvk, code, name in [
            ("0002000", CITY["0002000"], "Daugavpils"),
            ("0003000", CITY["0003000"], "Jelgava"),
            ("0004000", CITY["0004000"], "Jūrmala"),
            ("0011000", "100003999", "Citapilsēta"),
        ]
    ]
    iela = [
        {
            "KODS": STREET,
            "TIPS_CD": "107",
            "NOSAUKUMS": "Elektriķu iela",
            "VKUR_CD": CITY["0003000"],
            "VKUR_TIPS": "104",
            "STATUSS": "EKS",
        },
        {
            "KODS": "105000002",
            "TIPS_CD": "107",
            "NOSAUKUMS": "Cita iela",
            "VKUR_CD": "100003999",
            "VKUR_TIPS": "104",
            "STATUSS": "EKS",
        },
    ]
    eka = [
        {
            "KODS": "101000001",
            "TIPS_CD": "108",
            "STATUSS": "EKS",
            "VKUR_CD": STREET,
            "VKUR_TIPS": "107",
            "NOSAUKUMS": '"4"',
            "STD": "Elektriķu iela 4, Jelgava, LV-3001",
            "DAT_SAK": "1999.03.16",
            "DAT_MOD": "2024.01.02",
            "KOORD_X": "279028.676",
            "KOORD_Y": "479264.618",
        },
        {
            "KODS": "101000002",
            "TIPS_CD": "108",
            "STATUSS": "DEL",
            "VKUR_CD": STREET,
            "VKUR_TIPS": "107",
            "NOSAUKUMS": '"Elektriķi 2"',
            "STD": "Elektriķu iela 2, Jelgava",
            "DAT_SAK": "1999.03.16",
            "DAT_MOD": "2020.05.05",
            "DAT_BEIG": "2020.05.05",
        },
        {
            "KODS": "101000003",
            "TIPS_CD": "108",
            "STATUSS": "ERR",
            "VKUR_CD": STREET,
            "VKUR_TIPS": "107",
            "NOSAUKUMS": "9",
            "STD": "kļūda",
            "DAT_SAK": "2000.01.01",
            "DAT_MOD": "2000.01.01",
        },
        {
            "KODS": "101000004",
            "TIPS_CD": "108",
            "STATUSS": "EKS",
            "VKUR_CD": CITY["0004000"],
            "VKUR_TIPS": "104",
            "NOSAUKUMS": "Māja",
            "STD": "Māja, Jūrmala",
            "DAT_SAK": "2001.01.01",
            "DAT_MOD": "2001.01.01",
            "KOORD_X": "311000.5",
            "KOORD_Y": "480000.25",
        },
        {
            "KODS": "101000005",
            "TIPS_CD": "108",
            "STATUSS": "EKS",
            "VKUR_CD": "105000002",
            "VKUR_TIPS": "107",
            "NOSAUKUMS": "1",
            "STD": "Cita iela 1, Citapilsēta",
            "DAT_SAK": "2001.01.01",
            "DAT_MOD": "2001.01.01",
            "KOORD_X": "1",
            "KOORD_Y": "2",
        },
        *(extra_eka or []),
    ]
    his = [
        {
            "KODS": "101000001",
            "KODS_HIS": "",
            "TIPS_CD": "108",
            "DAT_SAK": "1990.01.01",
            "DAT_MOD": "1999.03.16",
            "DAT_BEIG": "1999.03.16",
            "STD": "Elektriķu iela 4, Jelgava, Jelgavas raj.",
        },
        {
            "KODS": "101000099",
            "KODS_HIS": "101000002",
            "TIPS_CD": "108",
            "DAT_SAK": "2020.05.05",
            "DAT_MOD": "2020.05.05",
            "DAT_BEIG": "2020.05.05",
            "STD": "linked",
        },
        {
            "KODS": "101000005",
            "KODS_HIS": "",
            "TIPS_CD": "108",
            "DAT_SAK": "1990.01.01",
            "DAT_MOD": "1990.01.01",
            "DAT_BEIG": "1990.01.01",
            "STD": "not pilot",
        },
    ]
    return {
        "aw_eka.csv": csv_bytes("aw_eka.csv", eka),
        "aw_eka_his.csv": csv_bytes("aw_eka_his.csv", his),
        "aw_iela.csv": csv_bytes("aw_iela.csv", iela),
        "aw_pilseta.csv": csv_bytes("aw_pilseta.csv", pilseta),
    }


# --- SHP -------------------------------------------------------------------------

# Real VZD style: unquoted WKT (docs/data-sources.md §5.2).
PRJ_10306 = (
    "PROJCS[LKS_2020_Latvia_TM,GEOGCS[GCS_LKS-2020,DATUM[D_LKS-2020,SPHEROID[GRS_1980,"
    "6378137.0,298.257222101]],PRIMEM[Greenwich,0.0],UNIT[Degree,0.0174532925199433]],"
    "PROJECTION[Transverse_Mercator],PARAMETER[False_Easting,500000.0],"
    "PARAMETER[False_Northing,-6000000],UNIT[Meter,1],AUTHORITY[EPSG,10306]]"
)
PRJ_VARIS = (
    'PROJCS["LKS-2020_Latvia_TM_EPSG_10306",GEOGCS["GCS_LKS-2020",DATUM["D_LKS-2020",'
    'SPHEROID["Geodetic_Reference_System_of_1980",6378137.0,298.257222101]],'
    'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]],'
    'PROJECTION["Transverse_Mercator"],UNIT["Meter",1.0]]'
)


def shp_layer(
    z: zipfile.ZipFile,
    path: str,
    layer: str,
    records: list[tuple[dict, list]],
    prj: str = PRJ_10306,
    fields: list | None = None,
) -> None:
    """Write one polygon layer into zip `z` at `path` (no extension)."""
    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    w = shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POLYGON, encoding="utf-8")
    for name, ftype, size in fields or schemas()["shp"][layer]["fields"]:
        w.field(name, ftype, size, 3 if (ftype == "N" and name == "AREA_SCALE") else 0)
    for rec, rings in records:
        if rings:
            w.poly(rings)
        else:
            w.null()
        w.record(**rec)
    w.close()
    z.writestr(path + ".shp", shp.getvalue())
    z.writestr(path + ".shx", shx.getvalue())
    z.writestr(path + ".dbf", dbf.getvalue())
    z.writestr(path + ".prj", prj)
    z.writestr(path + ".cpg", "UTF-8")


def square(x: float, y: float, s: float = 10.0) -> list:
    """Clockwise outer ring (shapefile convention)."""
    return [[x, y], [x, y + s], [x + s, y + s], [x + s, y], [x, y]]


def admin_zip(novads_name: str = "Novads") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:

        def rec(code, name, atrib):
            return {
                "KODS": int(code),
                "TIPS_CD": 104,
                "NOSAUKUMS": name,
                "VKUR_CD": 100000000,
                "VKUR_TIPS": 101,
                "APSTIPR": "Y",
                "APST_PAK": 252,
                "STATUSS": "EKS",
                "SORT_NOS": name,
                "DAT_SAK": "1999.03.16",
                "DAT_MOD": "24.04.2025 00:00:00",
                "DAT_BEIG": "",
                "ATRIB": atrib,
                "STD": name,
            }

        shp_layer(
            z,
            "aw_shp/Novadi",
            "Novadi",
            [(rec("100000001", novads_name, "0020000"), [square(500000, 300000, 1000)])],
            PRJ_VARIS,
        )
        shp_layer(
            z,
            "aw_shp/Pilsetas",
            "Pilsetas",
            [(rec(CITY["0003000"], "Jelgava", "0003000"), [square(480000, 270000, 1000)])],
            PRJ_VARIS,
        )
        shp_layer(
            z,
            "aw_shp/Pagasti",
            "Pagasti",
            [(rec("100000002", "Pagasts", "0020001"), [square(510000, 300000, 1000)])],
            PRJ_VARIS,
        )
    return buf.getvalue()


def kk_rec(code, objectcode, parcelcode=None, group="0900001", geom_date=None):
    r = {"CODE": code, "OBJECTCODE": objectcode, "GROUP_CODE": group, "AREA_SCALE": 100.0}
    if parcelcode is not None:
        r["PARCELCODE"] = parcelcode
    if geom_date is not None:
        r["GEOM_ACT_D"] = geom_date
    return r


def kk_zip(
    layers: dict[str, list[tuple[dict, list]]],
    folder: str = "ExportCadGroup_0900001",
    extra_folders: dict[str, dict[str, list]] | None = None,
) -> bytes:
    """A cadastre map zip: {layer: [(record, rings)]} in one cadastral-group folder."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for fld, lays in {folder: layers, **(extra_folders or {})}.items():
            for layer, recs in lays.items():
                for rec, _ in recs:
                    if layer == "KKParcel":
                        rec.setdefault("GEOM_ACT_D", datetime(2020, 1, 1).date())
                shp_layer(z, f"{fld}/{layer}", layer, recs)
    return buf.getvalue()


# --- cadastre text XML ----------------------------------------------------------------

NS = "http://ivis.eps.gov.lv/XMLSchemas/100007/CadastreRegistry/v1-0"
ROOTS = {
    "parcel": ("ParcelFullData", "ParcelItemList"),
    "parcelpart": ("ParcelPartFullData", "ParcelPartItemList"),
    "building": ("BuildingFullData", "BuildingItemList"),
    "property": ("PropertyFullData", "PropertyItemList"),
}
KINDS = {
    "parcel": "Parcel",
    "parcelpart": "ParcelPart",
    "building": "Building",
    "property": "Property",
}


def xml_doc(
    role: str,
    atvk: str,
    items: list[str],
    prepared: str = "2026-09-26",
    namespace: bool = True,
    part: int = 1,
    parts: int = 1,
) -> bytes:
    root, item_list = ROOTS[role]
    ns = f' xmlns="{NS}"' if namespace else ""
    body = "".join(items)
    return (
        f'<?xml version="1.0" encoding="UTF-8"?><{root}{ns}><PreparedDate>{prepared}</PreparedDate>'
        f"<PacketId>1</PacketId><FilePartCount>{parts}</FilePartCount><FilePartNr>{part}</FilePartNr>"
        f"<ATVK>{atvk}</ATVK><{item_list}>{body}</{item_list}></{root}>"
    ).encode()


def parcel_item(code: str, atvk: str = "0003000", area: str = "1234") -> str:
    return (
        f"<ParcelItemData><ParcelBasicData><ParcelCadastreNr>{code}</ParcelCadastreNr>"
        f"<ATVKCode>{atvk}</ATVKCode><ParcelArea>{area}</ParcelArea>"
        "<ParcelStatus><ParcelStatusKindId>1</ParcelStatusKindId>"
        "<ParcelStatusKindName>nekustamais īpašums</ParcelStatusKindName></ParcelStatus>"
        "<ParcelVARISCode>101000001</ParcelVARISCode></ParcelBasicData>"
        "<LandPurposeList><LandPurposeData><LandPurposeArea>1234</LandPurposeArea>"
        "<LandPurposeExplicationData><AgricultDetails/><UnderWaterDetails/></LandPurposeExplicationData>"
        "<LandPurposeKind><LandPurposeKindId>0601</LandPurposeKindId>"
        "<LandPurposeKindName>individuālo dzīvojamo māju apbūve</LandPurposeKindName>"
        "</LandPurposeKind>"
        "</LandPurposeData></LandPurposeList></ParcelItemData>"
    )


def parcelpart_item(code: str, parcel: str) -> str:
    return (
        f"<ParcelPartItemData><ParcelPartBasicData><ParcelPartArea>50</ParcelPartArea>"
        f"<ParcelPartCadastreNr>{code}</ParcelPartCadastreNr></ParcelPartBasicData>"
        f"<ObjectRelation><ObjectCadastreNr>{parcel}</ObjectCadastreNr><ObjectType>PARCEL</ObjectType>"
        "</ObjectRelation></ParcelPartItemData>"
    )


def building_item(
    code: str, parcel: str, name: str = "Dzīvojamā māja", extra_parcels=(), not_exist=False
) -> str:
    plist = ""
    if extra_parcels:
        plist = (
            "<ParcelCadastreNrList>"
            + "".join(f"<ObjectCadastreNrData>{p}</ObjectCadastreNrData>" for p in extra_parcels)
            + "</ParcelCadastreNrList>"
        )
    ne = "<NotExist>Būve apvidū nav konstatēta</NotExist>" if not_exist else ""
    return (
        f"<BuildingItemData><BuildingBasicData><BuildingCadastreNr>{code}</BuildingCadastreNr>"
        f"<BuildingName>{name}</BuildingName><BuildingMaterialKind/>"
        "<BuildingUseKind><BuildingUseKindId>1110</BuildingUseKindId>"
        "<BuildingUseKindName>Viena dzīvokļa mājas</BuildingUseKindName></BuildingUseKind>"
        f"<BuildingArea>120.5</BuildingArea><BuildingGroundFloors>2</BuildingGroundFloors>"
        f"<BuildingExploitYear>1985</BuildingExploitYear><VARISCode>101000001</VARISCode>{ne}{plist}"
        "</BuildingBasicData><BuildingHistoricalData/><ImprovementItemData><ImprovementCommonData/>"
        "</ImprovementItemData><BuildingOrPremiseGroupExplicationData><TotalAreaDetails>"
        "<ExpedientAreaDetails><FlatTotalAreaDetails><FlatAreaDetails/></FlatTotalAreaDetails>"
        "<NonlivingAreaDetails/></ExpedientAreaDetails><SharedAreaDetails/></TotalAreaDetails>"
        "</BuildingOrPremiseGroupExplicationData>"
        f"<ObjectRelation><ObjectCadastreNr>{parcel}</ObjectCadastreNr><ObjectType>PARCEL</ObjectType>"
        "</ObjectRelation></BuildingItemData>"
    )


def property_item(
    number: str, objects: list[tuple[str, str]], kind="Zemes un būvju īpašums"
) -> str:
    objs = "".join(
        f"<ObjectData><ObjectCadastreNrData>{c}</ObjectCadastreNrData>"
        f"<ObjectKindData>{k}</ObjectKindData></ObjectData>"
        for c, k in objects
    )
    return (
        f"<PropertyItemData><CadastreObjectIdData><ProCadastreNr>{number}</ProCadastreNr>"
        f"<PropertyKind>{kind}</PropertyKind></CadastreObjectIdData>"
        "<LandbookData><LandbookFolioNr>100</LandbookFolioNr></LandbookData>"
        "<PropertyBasicData><PropertyName>Elektriķu iela 4</PropertyName></PropertyBasicData>"
        f"<PropertyContentData><ObjectList>{objs}</ObjectList></PropertyContentData></PropertyItemData>"
    )


def text_zip(
    role: str, docs: dict[str, bytes], other: dict[str, bytes] | None = None, date: str = "20260926"
) -> bytes:
    """National zip: one member per ATVK (`docs`), plus non-pilot members (`other`)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for i, (atvk, body) in enumerate(sorted({**docs, **(other or {})}.items())):
            z.writestr(f"{KINDS[role]}/{atvk}_{date}_{540000 + i}/GUID-{role}-{atvk}.xml", body)
    return buf.getvalue()


def default_text_docs(
    role: str,
    *,
    namespace: bool = True,
    building_name: str = "Dzīvojamā māja",
    parcel_code: str = "09000360220",
    property_number: str = "05000041006",
):
    """Minimal pilot XML members for every pilot city."""
    out = {}
    for atvk in etl_config().pilot_atvk:
        prefix = {"0002000": "0500", "0003000": "0900", "0004000": "1300"}[atvk]
        if role == "parcel":
            items = [parcel_item(parcel_code if atvk == "0003000" else f"{prefix}0000001", atvk)]
        elif role == "parcelpart":
            items = [parcelpart_item(f"{prefix}00000010001", f"{prefix}0000001")]
        elif role == "building":
            items = [
                building_item(
                    f"{prefix}0000001001",
                    f"{prefix}0000001",
                    name=building_name if atvk == "0003000" else "Šķūnis",
                )
            ]
        else:
            items = [
                property_item(
                    property_number if atvk == "0002000" else f"{prefix}0000099",
                    [(f"{prefix}0000001", "Zemes vienība"), (f"{prefix}0000001001", "Būve")],
                )
            ]
        out[atvk] = xml_doc(role, atvk, items, namespace=namespace)
    return out
