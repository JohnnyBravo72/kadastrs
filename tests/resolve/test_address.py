"""Address matching on synthetic pilot data (conftest.py): suggestions, decisions,
objects at an address, and place names outside the pilot."""

import re

import pytest

from engine.resolve import address
from engine.resolve.context import live_versions, pilot, resolve_config
from engine.resolve.places import KEY_DROP, load_places


@pytest.fixture
def decide(seeded, client):  # client: the API must see the same seeded data
    def _decide(text):
        with seeded() as conn:
            v = live_versions(conn)
            places = load_places(conn, v, pilot())
            d, _ = address.decide(conn, v, places, resolve_config().address, text)
            return d

    return _decide


def suggest(client, q):
    r = client.get("/api/suggest", params={"q": q, "kind": "address"})
    assert r.status_code == 200, r.text
    return r.json()


def codes(d):
    return [w.code for w in d.warnings]


def test_key_words_match_sql(seeded):
    with seeded() as conn:
        src = conn.execute("SELECT prosrc FROM pg_proc WHERE proname = 'addr_key'").fetchone()[0]
    words = re.search(r"\\m\(([a-z|]+)\)\\M", src).group(1).split("|")
    assert sorted(words) == sorted(KEY_DROP)


# --- decisions -----------------------------------------------------------------------


def test_exact_address(decide):
    d = decide("Tautas iela 11, Daugavpils")
    assert (d.status, d.resolved_code) == ("resolved", "101808322")
    assert d.matches[0].match_type == "exact"
    assert d.warnings == []


@pytest.mark.parametrize(
    "text",
    ["tautas iela 11 daugavpils", "TAUTAS IELA 11, DAUGAVPILS", "Tautas ie. 11, Daugavpils"],
)
def test_case_and_abbreviations_are_exact(decide, text):
    d = decide(text)
    assert (d.status, d.resolved_code, d.warnings) == ("resolved", "101808322", [])


@pytest.mark.parametrize(
    "text",
    [
        "tautsa iela 11 daugavpls",
        "Tautas iela 11",
        "Tautas 11, Daugavpils",
        "Tautas iel 11 Daugavpils",
    ],
)
def test_fuzzy_match_shows_input_and_found(decide, text):
    d = decide(text)
    assert (d.status, d.resolved_code) == ("resolved", "101808322")
    assert d.matches[0].match_type == "fuzzy"
    assert [w.message for w in d.warnings] == [
        f"ievadīts: '{text}' → atrasts: 'Tautas iela 11, Daugavpils, LV-5404'"
    ]


def test_street_word_lookalikes(decide):
    # misspelt street-type word: not a search word
    assert decide("Tautas iel 11 Daugavpils").resolved_code == "101808322"
    # a real street whose name looks like a street-type word stays a search word
    d = decide("Lauku iela 4, Jūrmala")
    assert (d.status, d.resolved_code) == ("resolved", "102485599")


def test_near_identical_street_names(decide):
    assert decide("Ārijas iela 3, Jūrmala").resolved_code == "102400001"
    assert decide("arijas iela 3").resolved_code == "102400001"
    assert decide("Marijas iela 3").resolved_code == "102400002"
    d = decide("Arijs iela 3, Jūrmala")  # a typo resolves to the closer name, visibly
    assert (d.resolved_code, d.warnings[0].code) == ("102400001", "fuzzy_match")


def test_identical_texts_of_two_codes_are_ambiguous(decide):
    # real VARIS data has a few (e.g. "Narcišu iela 26, Daugavpils" twice)
    d = decide("Druvu iela 31, Jelgava")
    assert d.status == "ambiguous"
    assert [m.designation for m in d.matches[:2]] == ["101000010", "101000011"]


def test_house_number_must_match(decide):
    d = decide("Tautas iela 12, Daugavpils")
    assert d.status == "ambiguous"
    assert d.matches  # suggestions on the same street


def test_same_address_in_two_cities_is_ambiguous(decide):
    d = decide("Lielā iela 5")
    assert d.status == "ambiguous"
    assert {m.address.city for m in d.matches[:2]} == {"Jelgava", "Daugavpils"}
    assert decide("lielā iela 5, jelgava").resolved_code == "101000002"


def test_street_without_number_is_ambiguous(decide):
    d = decide("jelgava, lielā iela")
    assert d.status == "ambiguous"
    assert {m.address.city for m in d.matches} == {"Jelgava"}


def test_earlier_name(decide):
    d = decide("Prohorova iela 28A, Jelgava")
    assert (d.status, d.resolved_code) == ("resolved", "101000004")
    assert d.matches[0].match_type == "earlier_name"
    assert [w.message for w in d.warnings] == [
        "atrasts pēc agrākā nosaukuma; pašreizējā adrese: Sesavas iela 28A, Jelgava, LV-3002"
    ]


def test_current_text_wins_over_earlier_text(decide):
    d = decide("Sesavas iela 28A, Jelgava")
    assert d.matches[0].match_type == "exact"
    assert d.warnings == []


def test_current_text_beats_earlier_text_of_another_address(decide):
    d = decide("Ganību iela 86, Jelgava")
    assert (d.status, d.resolved_code, d.warnings) == ("resolved", "101061534", [])


def test_deleted_with_one_successor(decide):
    d = decide("Salnas iela 22A, Jelgava")
    assert (d.status, d.resolved_code) == ("resolved", "101000005")
    assert codes(d) == ["historical_address", "current_address"]
    assert d.warnings[1].message == "pašreizējā adrese: Salnas iela 22, Jelgava, LV-3008"
    assert [m.designation for m in d.matches] == ["101000005", "101154013"]


def test_deleted_split_into_two(decide):
    d = decide("Kalnciema ceļš 80, Jelgava")
    assert d.status == "ambiguous"
    assert [m.designation for m in d.matches[:2]] == ["101000006", "101000007"]
    assert codes(d) == ["historical_address", "current_address", "current_address"]


def test_deleted_without_successor_is_not_resolved(decide):
    d = decide("Cukura iela 6A, Jelgava")
    assert d.status == "unresolved"
    assert d.resolved_code is None
    assert codes(d) == ["historical_address", "current_unknown"]
    assert "pašreizējā adrese nav zināma" in [w.message for w in d.warnings]


# --- outside the pilot ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "place"),
    [
        ("riga tautas", "Rīga"),
        ("Rīga, Tautas iela 11", "Rīga"),
        ("Ventspils, Lielā iela 5", "Ventspils"),
        ("Jelgavas nov., Lielā iela 5", "Jelgavas nov."),
        ("Lielā iela 5, Jelgavas novads", "Jelgavas nov."),
        ("Valgundes pag., Lielā iela 5", "Valgundes pag."),
    ],
)
def test_place_outside_pilot(decide, text, place):
    d = decide(text)
    assert d.status == "outside_pilot"
    assert d.reason == f"{place} nav pilota teritorijā"


def test_city_name_used_as_street_is_not_a_place(decide):
    d = decide("Ventspils iela 70, Daugavpils")
    assert (d.status, d.resolved_code) == ("resolved", "101000008")
    d = decide("Ventspils iela 70")
    assert (d.status, d.resolved_code) == ("resolved", "101000008")


def test_pilot_city_with_nothing_there_does_not_resolve(decide):
    d = decide("Tautas iela 11, Jelgava")
    assert d.status == "ambiguous"
    assert "city_mismatch" in codes(d)
    assert d.matches[0].address.city == "Daugavpils"


# --- suggestions -----------------------------------------------------------------------


def test_suggest_outside_pilot_shows_city(client):
    body = suggest(client, "riga tautas")
    assert [n["message"] for n in body["notices"]] == ["Rīga nav pilota teritorijā"]
    items = body["suggestions"]
    assert items, "pilot addresses on the same street are still suggested"
    for s in items:
        assert s["city"] == "Daugavpils"
        assert "Daugavpils" in s["label"]


def test_suggest_diacritics_and_order(client):
    items = suggest(client, "jelgava, liela iela")["suggestions"]
    assert items and all(s["city"] == "Jelgava" for s in items)
    assert {s["label"] for s in items} == {
        "Lielā iela 3, Jelgava, LV-3001",
        "Lielā iela 5, Jelgava, LV-3001",
    }


def test_suggest_while_typing(client):
    items = suggest(client, "tautas iela 1")["suggestions"]
    assert [s["label"] for s in items][:3] == [
        "Tautas iela 11, Daugavpils, LV-5404",
        "Tautas iela 11A, Daugavpils, LV-5404",
        "Tautas iela 13, Daugavpils, LV-5404",
    ]


def test_suggest_earlier_and_deleted(client):
    items = suggest(client, "prohorova 28")["suggestions"]
    assert items[0]["match_type"] == "earlier_name"
    assert items[0]["current_address"] == "Sesavas iela 28A, Jelgava, LV-3002"
    items = suggest(client, "salnas iela 22a")["suggestions"]
    assert (items[0]["status"], items[0]["match_type"]) == ("DEL", "historical")
    assert items[0]["current_address"] == "Salnas iela 22, Jelgava, LV-3008"


# --- objects at an address -------------------------------------------------------------


def objects(client, code, **params):
    return client.get(f"/api/address/{code}/objects", params=params)


def test_objects_at_address(client):
    body = objects(client, "101765287").json()
    assert body["address"]["city"] == "Jelgava"
    assert [(o["type"], o["designation"]) for o in body["objects"]] == [
        ("parcel", "09000360220"),
        ("building", "09000360220002"),
    ]


def test_objects_of_deleted_address(client):
    body = objects(client, "101154013").json()
    assert body["objects"] == []
    assert [a["full_text"] for a in body["current_addresses"]] == [
        "Salnas iela 22, Jelgava, LV-3008"
    ]
    assert [w["code"] for w in body["warnings"]] == ["historical_address", "current_address"]


def test_objects_errors(client):
    assert objects(client, "12345").status_code == 422
    assert objects(client, "999999999").status_code == 404
