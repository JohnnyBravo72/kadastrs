"""Each Phase 2a source imports from synthetic files into one live version."""

import json

from tests.etl import fakes


def publish_all(server, **text_kwargs):
    server.publish("admin_boundaries", "aw_shp", "aw_shp.zip", fakes.admin_zip())
    for name, body in fakes.varis_files().items():
        server.publish("varis_addresses", name.removesuffix(".csv"), name, body)
    for atvk in ("0002000", "0003000", "0004000"):
        layers = {}
        if atvk == "0003000":
            layers = {
                "KKParcel": [
                    (fakes.kk_rec("09000360220", "7201060310"), [fakes.square(480000, 270000)])
                ],
                "KKBuilding": [
                    (
                        fakes.kk_rec("09000360220001", "5201011110", "09000360220"),
                        [fakes.square(480001, 270001, 2)],
                    )
                ],
                "KKEngineeringStructurePoly": [
                    (
                        fakes.kk_rec("09000360220002", "6201011110", "09000360220"),
                        [fakes.square(480004, 270004, 1)],
                    )
                ],
                "KKParcelPart": [
                    (
                        fakes.kk_rec("090003602200001", "7301060310", "09000360220"),
                        [fakes.square(480000, 270000, 3)],
                    )
                ],
                "KKWayRestriction": [
                    (
                        fakes.kk_rec("09000360220900000001", "7401060310", "09000360220"),
                        [fakes.square(480000, 270005, 2)],
                    )
                ],
            }
        server.publish("cadastre_spatial", atvk, f"{atvk}_kk_shp.zip", fakes.kk_zip(layers))
    for role in ("parcel", "parcelpart", "building", "property"):
        docs = fakes.default_text_docs(role, **text_kwargs)
        server.publish(
            "cadastre_text",
            role,
            f"{role}.zip",
            fakes.text_zip(role, docs, other={"0011000": fakes.xml_doc(role, "0011000", [])}),
        )


def test_admin_boundaries(run, server, q):
    publish_all(server)
    out = run("admin_boundaries")
    assert out.status == "succeeded"
    rows = q(
        "SELECT varis_code, level, atvk, GeometryType(geom), ST_SRID(geom)"
        " FROM ref.admin_area_current ORDER BY level, atvk"
    )
    assert rows == [
        ("100000001", "novads", "0020000", "MULTIPOLYGON", 10306),
        ("100000002", "pagasts", "0020001", "MULTIPOLYGON", 10306),
        ("100003011", "pilseta", "0002000", "MULTIPOLYGON", 10306),
        ("100003028", "pilseta", "0003000", "MULTIPOLYGON", 10306),
        ("100003036", "pilseta", "0004000", "MULTIPOLYGON", 10306),
    ]


def test_varis_addresses(run, server, q):
    publish_all(server)
    out = run("varis_addresses")
    assert out.status == "succeeded", out.message
    rows = q(
        "SELECT code, status, city_atvk, ST_X(geom), ST_Y(geom)"
        " FROM ref.address_current ORDER BY code"
    )
    # ERR (101000003) and the non-pilot city (101000005) are not imported;
    # KOORD_Y is the easting (x), KOORD_X the northing (y).
    assert rows == [
        ("101000001", "EKS", "0003000", 479264.618, 279028.676),
        ("101000002", "DEL", "0003000", None, None),
        ("101000004", "EKS", "0004000", 480000.25, 311000.5),
    ]
    his = q("SELECT code, code_his FROM ref.address_history_current ORDER BY row_no")
    assert his == [("101000001", None), ("101000099", "101000002")]  # linked either way
    counts = out.row_counts["address"]["source_pilot_by_status"]
    assert counts == {"EKS": 2, "DEL": 1, "ERR": 1}


def test_cadastre_spatial(run, server, q):
    publish_all(server)
    out = run("cadastre_spatial")
    assert out.status == "succeeded", out.message
    assert q("SELECT code, object_kind FROM ref.kk_building ORDER BY code") == [
        ("09000360220001", "building"),
        ("09000360220002", "engineering_structure"),
    ]
    assert q("SELECT code, parcel_code FROM ref.kk_servitude") == [
        ("09000360220900000001", "09000360220")
    ]
    assert q("SELECT count(*) FROM ref.kk_parcel_part") == [(1,)]


def test_cadastre_text(run, server, q):
    publish_all(server)
    out = run("cadastre_text")
    assert out.status == "succeeded", out.message
    assert q("SELECT count(*) FROM ref.parcel") == [(3,)]  # one per pilot city, not 0011000
    assert q(
        "SELECT building_code, parcel_code, relation FROM ref.building_parcel"
        " WHERE building_code LIKE '0900%'"
    ) == [("09000000001001", "09000000001", "object_relation")]
    prop = q(
        "SELECT object_code, object_kind FROM ref.property_object"
        " WHERE property_number = '05000041006' ORDER BY 1"
    )
    assert prop == [("05000000001", "Zemes vienība"), ("05000000001001", "Būve")]
    lp = q("SELECT land_purposes FROM ref.parcel WHERE code = '09000360220'")[0][0]
    assert lp == [{"id": "0601", "name": "individuālo dzīvojamo māju apbūve", "area": "1234"}]
    v = q("SELECT version_date::text, files FROM dataset_version WHERE status = 'live'")[0]
    assert v[0] == "2026-09-26"  # PreparedDate, the file's own date (E7)
    assert all(len(f["members"]) == 3 for f in v[1]), json.dumps(v[1])[:300]


def test_seed_parcel_resolves_with_geometry_after_full_import(run, server, q):
    publish_all(server)
    for sid in ("admin_boundaries", "varis_addresses", "cadastre_spatial", "cadastre_text"):
        assert run(sid).status == "succeeded"
    row = q("SELECT in_register, has_geometry FROM ref.parcel_current WHERE code = '09000360220'")
    assert row == [(True, True)]


def test_map_objects_outside_the_pilot_are_flagged(run, server, q):
    """outside_pilot = no cadastre text record AND interior point outside the
    city boundary; such objects are left out of the pilot views."""
    publish_all(server)
    city_x, city_y = 480000, 270000  # Jelgava in fakes.admin_zip(): 1 km square
    rec = fakes.kk_rec
    server.publish(
        "cadastre_spatial",
        "0003000",
        "0003000_kk_shp.zip",
        fakes.kk_zip(
            {
                "KKParcel": [
                    (
                        rec("09000360220", "7201060310"),
                        [fakes.square(city_x, city_y)],
                    ),  # registered, inside
                    (
                        rec("09000000777", "7201060310"),
                        [fakes.square(city_x + 500, city_y)],
                    ),  # map-only, inside
                    (
                        rec("44600000001", "7201060310"),
                        [fakes.square(city_x - 5000, city_y)],
                    ),  # map-only, outside
                    (
                        rec("09000000888", "7201060310"),
                        [fakes.square(city_x + 5000, city_y)],
                    ),  # registered, outside
                ],
                "KKBuilding": [
                    (
                        rec("44600000001001", "5201011110", "44600000001"),
                        [fakes.square(city_x - 4998, city_y + 2, 2)],
                    )
                ],
                "KKWayRestriction": [
                    (
                        rec("73150000000000000001", "7401060310", "44600000001"),
                        [fakes.square(city_x - 5000, city_y, 3)],
                    )
                ],
            }
        ),
    )
    docs = fakes.default_text_docs("parcel")
    docs["0003000"] = fakes.xml_doc(
        "parcel", "0003000", [fakes.parcel_item("09000360220"), fakes.parcel_item("09000000888")]
    )
    server.publish("cadastre_text", "parcel", "parcel.zip", fakes.text_zip("parcel", docs))
    for sid in ("admin_boundaries", "cadastre_spatial", "cadastre_text"):
        assert run(sid).status == "succeeded"

    pilot = {
        r[0]
        for r in q(
            "SELECT code FROM ref.parcel_current WHERE code LIKE '0900%' OR code LIKE '4460%'"
        )
    }
    assert pilot == {"09000360220", "09000000777", "09000000888"}
    assert q("SELECT kind, code FROM ref.map_outside_pilot ORDER BY kind") == [
        ("building", "44600000001001"),
        ("parcel", "44600000001"),
        ("servitude", "73150000000000000001"),
    ]
    assert q("SELECT count(*) FROM ref.building_current WHERE code = '44600000001001'") == [(0,)]
    assert q("SELECT outside_pilot FROM ref.parcel_current_all WHERE code = '44600000001'") == [
        (True,)
    ]
