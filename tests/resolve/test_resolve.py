"""POST /api/resolve on synthetic pilot data (conftest.py)."""

import pytest


def resolve(client, values=None, rows=None):
    r = client.post("/api/resolve", json={"values": values or [], "rows": rows or []})
    assert r.status_code == 200, r.text
    return r.json()


def one(client, value, kind="auto"):
    return resolve(client, rows=[{"value": value, "kind": kind}])["rows"][0]


def wcodes(row):
    return [w["code"] for w in row["warnings"]]


def ccodes(row):
    return [c["code"] for c in row["corrections"]]


def matched(row):
    return [(m["type"], m["designation"]) for m in row["matches"]]


# --- seeds and 11-digit values --------------------------------------------------------


def test_seed_property_only(client):
    row = one(client, "05000041006")
    assert (row["status"], row["type"]) == ("resolved", "property")
    assert matched(row) == [("property", "05000041006")]
    assert row["matches"][0]["match_type"] == "exact"


@pytest.mark.parametrize("number", ["09000360220", "13000102702"])
def test_seed_property_and_its_own_parcel(client, number):
    row = one(client, number)
    assert (row["status"], row["type"]) == ("resolved", "property")
    assert matched(row) == [("property", number), ("parcel", number)]
    assert wcodes(row) == ["property_and_parcel"]


@pytest.mark.parametrize(
    ("number", "owner"), [("05000010003", "05000010010"), ("05000040014", "05000041006")]
)
def test_ambiguous_property_or_parcel_shows_both(client, number, owner):
    row = one(client, number)
    assert row["status"] == "ambiguous"
    assert row["type"] is None
    assert matched(row) == [("property", number), ("parcel", number)]
    assert row["matches"][1]["object"]["property_numbers"] == [owner]
    assert wcodes(row) == ["ambiguous_property_parcel"]
    assert owner in row["warnings"][0]["message"]


def test_parcel_only(client):
    row = one(client, "05000040013")
    assert (row["status"], row["type"]) == ("resolved", "parcel")
    assert row["matches"][0]["object"]["property_numbers"] == ["05000040014"]


# --- leading zeros and Excel damage -----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "type_", "designation"),
    [
        ("5000041006", "property", "05000041006"),  # 10 -> 11
        ("9000360220002", "building", "09000360220002"),  # 13 -> 14
        ("5000041006001001", "building", "05000041006001"),  # 16 -> 17 -> its building
        ("90003602200001", "parcel_part", "090003602200001"),  # 14, no building -> 15
    ],
)
def test_every_leading_zero_case(client, raw, type_, designation):
    row = one(client, raw)
    assert (row["status"], row["type"]) == ("resolved", type_)
    assert row["matches"][0]["designation"] == designation
    assert row["matches"][0]["match_type"] == "corrected"
    if len(raw) != 14:
        assert ccodes(row) == ["leading_zero_restored"]
    else:  # the 14-digit value is a valid building length; the zero comes from the lookup
        assert "leading_zero_restored" in wcodes(row)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (5000041006, ["leading_zero_restored"]),
        ("5.000041006E9", ["scientific_notation", "leading_zero_restored"]),
        ("5.000041006E+09", ["scientific_notation", "leading_zero_restored"]),
        ("05000041006.0", ["trailing_decimal"]),
        ("0500 004 1006", ["separators_removed"]),
        ("'05000041006", []),
    ],
)
def test_excel_mangled_inputs_resolve_and_report(client, raw, expected):
    row = one(client, raw)
    assert (row["status"], row["normalized"]) == ("resolved", "05000041006")
    assert ccodes(row) == expected
    assert row["matches"][0]["match_type"] == ("corrected" if expected else "exact")


def test_precision_lost_needs_confirmation(client):
    row = one(client, "5.00004E+09")  # 5000040000: digits may be lost
    assert row["status"] in ("ambiguous", "not_found")
    assert "precision_lost" in wcodes(row)


@pytest.mark.parametrize("raw", ["123", "050000410061", "1.25E1", "---"])
def test_invalid(client, raw):
    row = one(client, raw)
    assert row["status"] == "invalid"
    assert row["reason"]


# --- buildings, premise groups, geometry, pilot area -------------------------------------


def test_premise_group_resolves_to_building(client):
    row = one(client, "05000041006001001")
    assert (row["status"], row["type"]) == ("resolved", "building")
    assert matched(row) == [("building", "05000041006001")]
    assert wcodes(row) == ["premise_group_to_building"]


def test_unknown_premise_group_of_known_building(client):
    row = one(client, "05000041006001002")
    assert row["status"] == "resolved"
    assert wcodes(row) == ["premise_group_to_building", "premise_group_not_found"]


def test_non_existing_building_resolves_with_warning(client):
    row = one(client, "09000360220010")
    assert (row["status"], row["type"]) == ("resolved", "building")
    assert "not_exist" in wcodes(row)
    assert "reģistrā atzīmēta kā neeksistējoša" in [w["message"] for w in row["warnings"]]


def test_building_without_geometry(client):
    row = one(client, "09000360220012")
    assert row["status"] == "resolved"
    assert row["matches"][0]["object"]["has_geometry"] is False
    assert wcodes(row) == ["no_geometry", "prereg"]


def test_map_only_parcel_inside_pilot(client):
    row = one(client, "09000030450")
    assert (row["status"], row["type"]) == ("resolved", "parcel")
    assert wcodes(row) == ["not_in_register"]


def test_map_only_parcel_outside_pilot(client):
    row = one(client, "44600040001")
    assert row["status"] == "outside_pilot"
    assert row["matches"] == []


def test_territory_outside_pilot(client):
    row = one(client, "01000010001")
    assert row["status"] == "outside_pilot"
    assert row["reason"] == "kadastra teritorija 0100 nav pilota teritorijā"


def test_not_found_in_pilot_territory(client):
    assert one(client, "09000999999")["status"] == "not_found"


# --- addresses ---------------------------------------------------------------------------


def test_address_with_objects(client):
    row = one(client, "Institūta iela 4, Jelgava")
    assert (row["status"], row["type"]) == ("resolved", "address")
    assert row["normalized"] == "instituta iela 4 jelgava"
    assert [(o["type"], o["designation"]) for o in row["matches"][0]["objects"]] == [
        ("parcel", "09000360220"),
        ("building", "09000360220002"),
    ]


def test_address_typo_and_diacritics_warns(client):
    row = one(client, "instituta iela 4 jelgva")
    assert row["status"] == "resolved"
    assert row["warnings"][0]["message"] == (
        "ievadīts: 'instituta iela 4 jelgva' → atrasts: 'Institūta iela 4, Jelgava, LV-3004'"
    )


def test_address_without_objects_warns(client):
    row = one(client, "Lielā iela 3, Jelgava")
    assert row["status"] == "resolved"
    assert wcodes(row) == ["no_cadastre_objects"]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("riga tautas", "Rīga nav pilota teritorijā"),
        ("Jelgavas novads, Lielā iela 5", "Jelgavas nov. nav pilota teritorijā"),
    ],
)
def test_address_outside_pilot(client, text, message):
    row = one(client, text)
    assert (row["status"], row["reason"]) == ("outside_pilot", message)


def test_earlier_name_and_deleted(client):
    rows = resolve(
        client,
        values=[
            "Prohorova iela 28A, Jelgava",
            "Salnas iela 22A, Jelgava",
            "Kalnciema ceļš 80, Jelgava",
            "Cukura iela 6A, Jelgava",
        ],
    )["rows"]
    assert [r["status"] for r in rows] == ["resolved", "resolved", "ambiguous", "unresolved"]
    assert rows[0]["matches"][0]["designation"] == "101000004"
    assert "earlier_name" in wcodes(rows[0])
    assert rows[1]["matches"][0]["designation"] == "101000005"
    assert wcodes(rows[1]) == [
        "historical_address",
        "current_address",
        "no_cadastre_objects",  # none at Salnas iela 22 in the fixture
    ]
    assert "current_unknown" in wcodes(rows[3])


def test_varis_code_input(client):
    row = one(client, "101765287")
    assert (row["kind"], row["status"], row["type"]) == ("address_code", "resolved", "address")
    assert row["matches"][0]["objects"]
    deleted = one(client, "101154013")
    assert deleted["status"] == "resolved"
    assert deleted["matches"][0]["designation"] == "101000005"


# --- batch behaviour ----------------------------------------------------------------------


def test_duplicates_flagged(client):
    rows = resolve(
        client,
        values=["05000041006", "5000041006", "Tautas iela 11, Daugavpils", "tautas iela 11"],
    )["rows"]
    assert [r["duplicate_of"] for r in rows] == [None, 0, None, 2]
    assert "duplicate" in wcodes(rows[1])


def test_column_kind_is_respected(client):
    rows = resolve(
        client,
        rows=[
            {"value": "Tautas iela 11", "kind": "cadastre"},
            {"value": "05000041006", "kind": "address"},
            {"value": "05000041006", "kind": "cadastre"},
        ],
    )["rows"]
    assert [r["status"] for r in rows] == ["invalid", "invalid", "resolved"]


def test_summary_versions_and_empty_rows(client):
    body = resolve(client, values=["05000041006", "", None, "05000010003"])
    assert body["summary"] == {"resolved": 1, "empty": 2, "ambiguous": 1}
    assert set(body["versions"]) == {
        "cadastre_text",
        "cadastre_spatial",
        "varis_addresses",
        "admin_boundaries",
    }
    assert [r["index"] for r in body["rows"]] == [0, 1, 2, 3]


def test_row_limit(client):
    r = client.post("/api/resolve", json={"values": ["05000041006"] * 1001})
    assert r.status_code == 413
