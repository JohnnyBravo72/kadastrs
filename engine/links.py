"""Source deep links, "Skatīt avotā" (decided 2026-10-12, docs/decisions.md
"Source deep links"; patterns, test date and limits in docs/data-sources.md §8).

A link only OPENS the object in the publisher's own public system, next to the
data.gov.lv dataset link; nothing is ever fetched from these systems (CLAUDE.md
rule 1 unchanged). Every pattern was checked on 2026-10-12 with real requests on
the seed objects, logged out:

  kadastrs.lv  parcels / buildings / properties: GET search by designation opens
               the object's row (no login); VARIS address: GET search by code
  BIS          public "Plānotie būvdarbi" search by case number shows the case
  LVĢMC        3rd-cycle flood map viewer centred on the object (no marker)

Where no such pattern opens the right object without login (parcel parts,
deleted addresses, Ozols, encumbrance details), the link goes to the system's
public search page and carries the number to paste (`copy`).
"""

from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlencode

KADASTRS = "https://www.kadastrs.lv"
BIS_SEARCH = "https://bis.gov.lv/bisp/lv/planned_constructions"
OZOLS = "https://ozols.gov.lv/pub"
LVGMC_VIEWER = "https://geodata.lvgmc.lv/portal/apps/webappviewer/index.html"
LVGMC_APP_ID = "45020161703b4e1b936b5d8d65e144c2"  # 3. cikla … plūdu riska kartes
LVGMC_LEVEL = 17
UR_SEARCH = "https://info.ur.gov.lv/#/data-search"
FID_SEARCH = "https://sankcijas.fid.gov.lv/lv/meklet-sankciju-sarakstos/1/0"


@dataclass(frozen=True)
class Link:
    system: str  # shown as "Skatīt avotā: <system>"
    url: str
    copy: str | None = None  # when set, the page is a search page: paste this there
    note: str | None = None
    label: str | None = None  # own link text instead of "Skatīt avotā: <system>"

    def as_json(self) -> dict[str, Any]:
        return {k: v for k, v in asdict(self).items() if v is not None}


def _kadastrs(path: str, **params: str) -> str:
    return f"{KADASTRS}/{path}?{urlencode(params)}"


def object_link(object_type: str, code: str) -> Link | None:
    """The cadastre object on kadastrs.lv."""
    if object_type == "parcel":
        return Link("kadastrs.lv", _kadastrs("parcels/search", cad_num=code))
    if object_type == "property":
        return Link("kadastrs.lv", _kadastrs("properties/search", cad_num=code))
    if object_type in ("building", "premise_group"):
        return Link("kadastrs.lv", _kadastrs("buildings/search", cad_num=code[:14]))
    if object_type == "parcel_part":
        # the search by parcel part designation finds nothing (tested 2026-10-12)
        return Link(
            "kadastrs.lv",
            f"{KADASTRS}/parcels",
            copy=code,
            note="zemes vienības daļu meklē laukā „Zemes vienības daļa”",
        )
    return None


def address_link(code: str, status: str | None = "EKS") -> Link:
    """A VARIS address on kadastrs.lv (deleted addresses are not found by code)."""
    if status == "DEL":
        return Link("VARIS (kadastrs.lv)", f"{KADASTRS}/varis", copy=code, note="likvidēta adrese")
    return Link("VARIS (kadastrs.lv)", _kadastrs("varis/search", add_id=code))


def bis_link(case_number: str) -> Link:
    params = {"search[case_number]": case_number, "search_type": "simple"}
    return Link("BIS", f"{BIS_SEARCH}?{urlencode(params)}")


def flood_link(centre: tuple[float, float] | None) -> Link:
    params = {"id": LVGMC_APP_ID}
    if centre:
        params |= {"center": f"{centre[0]:.6f},{centre[1]:.6f},4326", "level": str(LVGMC_LEVEL)}
    return Link("LVĢMC plūdu karte", f"{LVGMC_VIEWER}?{urlencode(params)}",
                note=None if centre else "karte bez objekta atrašanās vietas")  # fmt: skip


def nature_link(code: str) -> Link:
    # the public Ozols app reads no URL parameters (checked 2026-10-12)
    return Link("Ozols (DAP)", OZOLS, copy=code, note="meklēt pēc kadastra numura")


def ur_link(reg_no: str) -> Link:
    # the UR portal runs a search only from its own box; no URL opens a company
    # (tested 2026-10-12, docs/data-sources.md §8)
    return Link(
        "UR",
        UR_SEARCH,
        copy=reg_no,
        note="meklēt pēc reģistrācijas numura",
        label="Skatīt UR",
    )


def sanctions_link(reg_no: str, name: str | None) -> Link:
    """FID's public search of the sanctions lists (EU, UN, OFAC, LV), by the
    company name; by the reg. no. when the name is not stored (IK, IND)."""
    query = name or reg_no
    return Link(
        "FID sankciju saraksti",
        f"{FID_SEARCH}?{urlencode({'searchText': query, 'exactSearch': '0'})}",
        note=None if name else "meklēts pēc reģistrācijas numura",
        label="Skatīt sankciju sarakstā",
    )


def applicant_links(reg_no: str, name: str | None) -> list[Link]:
    """ "Skatīt UR" and "Skatīt sankciju sarakstā" for one applicant."""
    return [ur_link(reg_no), sanctions_link(reg_no, name)]


def kind_of(code: str, known: str | None = None) -> str:
    """Object type from a designation's length (11 parcel or property, 14 building,
    15 parcel part, 17 premise group); `known` wins when given."""
    if known:
        return known
    return {14: "building", 15: "parcel_part", 17: "premise_group"}.get(len(code), "parcel")


def item_links(
    module: str,
    item: dict[str, Any],
    unit_type: str,
    unit_code: str,
    centre: tuple[float, float] | None = None,
) -> list[Link]:
    """The links of one check-result item (none for items without a source object)."""
    if module == "bis" and item.get("case_number"):
        return [bis_link(str(item["case_number"]))]
    if module == "cadastre_facts":
        code = str(item.get("designation") or unit_code)
        link = object_link(kind_of(code, unit_type if code == unit_code else None), code)
        links = [link] if link else []
        if item.get("varis_code"):
            links.append(address_link(str(item["varis_code"])))
        return links
    if module == "address_consistency":
        if item.get("given_address"):
            return [address_link(str(item["given_address"]), item.get("given_status"))]
        if item.get("varis_code"):
            return [address_link(str(item["varis_code"]))]
        return []
    if module == "nature":
        return [nature_link(unit_code)]
    if module == "flood_10y":
        return [flood_link(centre)]
    if module == "applicant_company":
        return [ur_link(str(item.get("reg_no") or unit_code))]
    if module == "sanctions":
        if (item.get("legal_base_url") or "").startswith("https://"):
            return [Link("Izpildrīkojums", item["legal_base_url"])]
        return []
    if module == "companies_at_address" and item.get("varis_code"):
        return [address_link(str(item["varis_code"]))]
    if module == "encumbrances":
        obj = str(item.get("object_code") or unit_code)
        link = object_link(kind_of(obj), obj)
        if link is None:
            return []
        code = item.get("code")
        # the object's record; the encumbrance itself has no public page (tested 2026-10-12)
        return [Link(link.system, link.url, copy=link.copy or (str(code) if code else None),
                     note=link.note or "apgrūtinājuma kods")]  # fmt: skip
    return []
