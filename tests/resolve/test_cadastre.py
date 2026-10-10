"""Cadastre type-ahead and property units on synthetic pilot data (conftest.py)."""


def suggest(client, q):
    r = client.get("/api/suggest", params={"q": q, "kind": "cadastre"})
    assert r.status_code == 200, r.text
    return r.json()["suggestions"]


def units(client, number, **params):
    return client.get(f"/api/property/{number}/units", params=params)


def test_suggest_needs_three_digits(client):
    assert suggest(client, "05") == []
    assert suggest(client, "Tautas") == []


def test_suggest_prefix_with_type_labels(client):
    items = suggest(client, "09000360220")
    got = [(s["type"], s["designation"], s["label"]) for s in items]
    assert got[:2] == [
        ("property", "09000360220", "Nekustamais īpašums"),
        ("parcel", "09000360220", "Zemes vienība"),
    ]
    assert ("building", "09000360220002", "Būve") in got
    assert ("parcel_part", "090003602200001", "Zemes vienības daļa") in got
    assert all(s["city"] == "Jelgava" for s in items)
    assert all(s["match_type"] == "exact" for s in items)


def test_suggest_restores_leading_zero(client):
    items = suggest(client, "500004100")
    assert items[0]["designation"] == "05000041006"
    assert items[0]["match_type"] == "corrected"
    assert items[0]["description"] == "Tautas iela 11 · Zemes un būvju īpašums"


def test_suggest_premise_group(client):
    items = suggest(client, "0500004100600")
    assert ("premise_group", "05000041006001001") in [(s["type"], s["designation"]) for s in items]


def test_units_of_seed_property(client):
    r = units(client, "05000041006")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "Zemes un būvju īpašums"
    assert [(u["type"], u["designation"]) for u in body["units"]] == [("parcel", "05000040014")]
    assert body["corrections"] == []


def test_units_leading_zero_in_path(client):
    body = units(client, "5000041006").json()
    assert body["number"] == "05000041006"
    assert [c["code"] for c in body["corrections"]] == ["leading_zero_restored"]


def test_units_exclude_non_existing_unless_asked(client):
    body = units(client, "09000360220").json()
    designations = [u["designation"] for u in body["units"]]
    assert "09000360220010" not in designations
    assert body["non_existing_excluded"] == 1
    assert designations == [
        "09000360220",
        "090003602200001",
        "09000360220002",
        "09000360220012",
    ]
    assert body["counts"] == {"parcel": 1, "building": 2, "parcel_part": 1, "premise_group": 0}

    body = units(client, "09000360220", include_non_existing="true").json()
    nx = [u for u in body["units"] if u["designation"] == "09000360220010"]
    assert nx and nx[0]["not_exist"] is True
    assert "not_exist" in [w["code"] for w in nx[0]["warnings"]]
    assert body["non_existing_excluded"] == 0


def test_units_no_geometry_and_prereg_warnings(client):
    body = units(client, "09000360220").json()
    nojume = next(u for u in body["units"] if u["designation"] == "09000360220012")
    assert nojume["has_geometry"] is False
    assert [w["code"] for w in nojume["warnings"]] == ["no_geometry", "prereg"]


def test_units_buildings_on_parcels_of_other_properties(client):
    body = units(client, "09000360220").json()
    others = body["buildings_on_parcels"]
    assert [(b["designation"], b["property_numbers"]) for b in others] == [
        ("09000360220011", ["09000360299"])
    ]


def test_units_premise_groups(client):
    body = units(client, "05000049999").json()
    assert [(u["type"], u["designation"], u["building_code"]) for u in body["units"]] == [
        ("premise_group", "05000041006001001", "05000041006001")
    ]


def test_units_of_a_parcel_number_is_404_with_its_property(client):
    r = units(client, "05000040013")
    assert r.status_code == 404
    assert r.json()["detail"]["parcel_of"] == ["05000040014"]


def test_units_rejects_non_property_lengths(client):
    assert units(client, "09000360220002").status_code == 422
    assert units(client, "abc").status_code == 422
