"""Source deep links (engine/links.py): the patterns verified on 2026-10-12
(docs/data-sources.md §8). Links only open the source; nothing is fetched."""

from engine.links import address_link, bis_link, flood_link, item_links, nature_link, object_link


def test_kadastrs_objects():
    assert object_link("parcel", "09000050400").url == (
        "https://www.kadastrs.lv/parcels/search?cad_num=09000050400"
    )
    assert object_link("property", "09000360220").url.endswith(
        "/properties/search?cad_num=09000360220"
    )
    assert object_link("building", "09000360220002").url.endswith(
        "/buildings/search?cad_num=09000360220002"
    )
    group = object_link("premise_group", "05000041006001001")
    assert group.url.endswith("cad_num=05000041006001")  # checked as its building
    part = object_link("parcel_part", "090003602200001")
    assert (part.url, part.copy) == ("https://www.kadastrs.lv/parcels", "090003602200001")


def test_addresses():
    assert address_link("101765287").url == "https://www.kadastrs.lv/varis/search?add_id=101765287"
    deleted = address_link("101093868", "DEL")
    assert (deleted.url, deleted.copy) == ("https://www.kadastrs.lv/varis", "101093868")


def test_bis_flood_and_nature():
    assert bis_link("BIS-BL-895076-16218").url == (
        "https://bis.gov.lv/bisp/lv/planned_constructions"
        "?search%5Bcase_number%5D=BIS-BL-895076-16218&search_type=simple"
    )
    flood = flood_link((23.720678, 56.659918))
    assert flood.url == (
        "https://geodata.lvgmc.lv/portal/apps/webappviewer/index.html"
        "?id=45020161703b4e1b936b5d8d65e144c2&center=23.720678%2C56.659918%2C4326&level=17"
    )
    assert flood_link(None).note
    ozols = nature_link("09000130004")
    assert (ozols.url, ozols.copy) == ("https://ozols.gov.lv/pub", "09000130004")


def test_item_links_per_module():
    assert item_links("bis", {"case_number": "BIS-1"}, "parcel", "09000050400")[0].system == "BIS"
    item = {"designation": "09000360220002", "varis_code": "101765287"}
    facts = item_links("cadastre_facts", item, "property", "09000360220")
    assert [lk.system for lk in facts] == ["kadastrs.lv", "VARIS (kadastrs.lv)"]
    assert "buildings/search" in facts[0].url
    enc = item_links("encumbrances", {"object_code": "090003602200001", "code": "7312050500"},
                     "parcel", "09000360220")  # fmt: skip
    assert enc[0].copy == "090003602200001"  # a parcel part: search page + its designation
    enc = item_links("encumbrances", {"object_code": "09000360220", "code": "7312030100"},
                     "parcel", "09000360220")  # fmt: skip
    assert enc[0].url.endswith("parcels/search?cad_num=09000360220") and enc[0].copy == "7312030100"
    given = item_links("address_consistency", {"given_address": "101154013", "given_status": "DEL"},
                       "parcel", "09000050405")  # fmt: skip
    assert given[0].copy == "101154013"
