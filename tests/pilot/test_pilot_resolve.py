"""Input resolution on the real pilot data (Phase 3; marker `pilot`).

Named cases come from the pilot import of 2026-10-10 (docs/data-sources.md
§3.1, PLAN.md §5.1); cases that depend on one object of a kind (a premise
group, a building marked non-existing, ...) are picked from the live data.
The API runs in-process against the dev DB, so the timing excludes only the
network hop.
"""

import time

import pytest
from fastapi.testclient import TestClient

from tests.pilot.support import SEEDS, one

pytestmark = [pytest.mark.pilot, pytest.mark.stack]


@pytest.fixture(scope="module")
def api(db_url):
    mp = pytest.MonkeyPatch()
    mp.setenv("DATABASE_URL", db_url)
    from api.main import app

    with TestClient(app) as client:
        yield client
    mp.undo()


def resolve(api, *values):
    r = api.post("/api/resolve", json={"values": list(values)})
    assert r.status_code == 200, r.text
    return r.json()["rows"]


def row(api, value):
    return resolve(api, value)[0]


def wcodes(r):
    return [w["code"] for w in r["warnings"]]


def suggest(api, q, kind):
    r = api.get("/api/suggest", params={"q": q, "kind": kind})
    assert r.status_code == 200, r.text
    return r.json()


# --- seeds -----------------------------------------------------------------------------


@pytest.mark.parametrize("seed", SEEDS)
def test_seed_resolves_to_property(api, live, seed):
    r = row(api, seed)
    assert (r["status"], r["type"]) == ("resolved", "property"), r
    assert r["matches"][0]["designation"] == seed


def test_seed_units(api, live):
    body = api.get("/api/property/05000041006/units").json()
    assert [(u["type"], u["designation"]) for u in body["units"]] == [("parcel", "05000040014")]
    body = api.get("/api/property/09000360220/units").json()
    assert body["counts"]["parcel"] == 1
    assert body["counts"]["building"] >= 1
    assert all(not u["not_exist"] for u in body["units"] + body["buildings_on_parcels"])


@pytest.mark.parametrize("number", ["13000102702", "09000360220"])
def test_seed_is_property_and_own_parcel(api, live, number):
    r = row(api, number)
    assert [(m["type"], m["designation"]) for m in r["matches"]] == [
        ("property", number),
        ("parcel", number),
    ]
    assert wcodes(r) == ["property_and_parcel"]


# --- ambiguous 11-digit values ----------------------------------------------------------


@pytest.mark.parametrize(
    ("number", "owner"), [("05000010003", "05000010010"), ("05000040014", "05000041006")]
)
def test_ambiguous_property_or_parcel(api, live, number, owner):
    r = row(api, number)
    assert r["status"] == "ambiguous"
    assert [m["type"] for m in r["matches"]] == ["property", "parcel"]
    assert r["matches"][1]["object"]["property_numbers"] == [owner]


def test_every_true_ambiguity_is_reported(api, db_conn, live):
    numbers = [
        n
        for (n,) in db_conn.execute(
            """SELECT pr.number FROM ref.property pr
               JOIN ref.parcel p ON p.dataset_version_id = pr.dataset_version_id
                    AND p.code = pr.number
               WHERE pr.dataset_version_id = %(t)s AND NOT EXISTS (
                   SELECT 1 FROM ref.property_object po
                   WHERE po.dataset_version_id = %(t)s AND po.property_number = pr.number
                     AND po.object_code = pr.number)""",
            {"t": live["cadastre_text"]},
        )
    ]
    assert len(numbers) > 100  # 158 on 2026-10-10
    rows = resolve(api, *numbers)
    assert {r["status"] for r in rows} == {"ambiguous"}


# --- leading zeros and Excel damage --------------------------------------------------------


@pytest.mark.parametrize(
    "raw", [5000041006, "5000041006", "5.000041006E9", "5.000041006E+09", "05000041006.0"]
)
def test_excel_mangled_seed(api, live, raw):
    r = row(api, raw)
    assert (r["status"], r["normalized"], r["type"]) == ("resolved", "05000041006", "property")
    assert r["corrections"]


def test_every_leading_zero_length(api, db_conn, live):
    t = live["cadastre_text"]
    group = one(
        db_conn,
        "SELECT object_code FROM ref.property_object WHERE dataset_version_id = %s"
        " AND object_kind = 'Telpu grupa' AND object_code LIKE '0%%' ORDER BY 1 LIMIT 1",
        t,
    )
    part = one(
        db_conn,
        "SELECT code FROM ref.parcel_part p WHERE dataset_version_id = %s AND code LIKE '0%%'"
        " AND NOT EXISTS (SELECT 1 FROM ref.building b WHERE b.dataset_version_id ="
        " p.dataset_version_id AND b.code = substr(p.code, 2)) ORDER BY 1 LIMIT 1",
        t,
    )
    cases = {
        "5000041006": ("property", "05000041006"),
        "9000360220002": ("building", "09000360220002"),
        group[1:]: ("building", group[:14]),
        part[1:]: ("parcel_part", part),
    }
    rows = resolve(api, *cases)
    for r, (type_, designation) in zip(rows, cases.values(), strict=True):
        assert (r["status"], r["type"]) == ("resolved", type_), r
        assert r["matches"][0]["designation"] == designation
        assert r["matches"][0]["match_type"] == "corrected"


# --- buildings and geometry ------------------------------------------------------------------


def test_non_existing_building(api, db_conn, live):
    code, number = db_conn.execute(
        "SELECT b.code, po.property_number FROM ref.building b JOIN ref.property_object po"
        " ON po.dataset_version_id = b.dataset_version_id AND po.object_code = b.code"
        " WHERE b.dataset_version_id = %s AND b.not_exist ORDER BY 1 LIMIT 1",
        (live["cadastre_text"],),
    ).fetchone()
    r = row(api, code)
    assert r["status"] == "resolved"
    assert "not_exist" in wcodes(r)
    units = api.get(f"/api/property/{number}/units").json()
    assert code not in [u["designation"] for u in units["units"]]
    assert units["non_existing_excluded"] >= 1
    units = api.get(f"/api/property/{number}/units?include_non_existing=true").json()
    assert code in [u["designation"] for u in units["units"]]


def test_building_without_geometry(api, live):
    r = row(api, "13000146022001")  # pre-registered, not on the map
    assert r["status"] == "resolved"
    assert "no_geometry" in wcodes(r)


def test_map_object_outside_pilot(api, live):
    r = row(api, "44600040001")  # Daugavpils zip, cadastral group 4460, outside the city
    assert r["status"] == "outside_pilot"


# --- addresses ---------------------------------------------------------------------------------


def test_riga_tautas(api, live):
    r = row(api, "riga tautas")
    assert (r["status"], r["reason"]) == ("outside_pilot", "Rīga nav pilota teritorijā")
    body = suggest(api, "riga tautas", "address")
    assert [n["message"] for n in body["notices"]] == ["Rīga nav pilota teritorijā"]
    assert body["suggestions"]
    for s in body["suggestions"]:
        assert s["label"].startswith("Tautas iela")
        assert s["city"] == "Daugavpils" and "Daugavpils" in s["label"]


def test_jelgava_liela_iela(api, live):
    body = suggest(api, "jelgava, lielā iela", "address")
    assert body["suggestions"]
    assert all(
        s["label"].startswith("Lielā iela") and s["city"] == "Jelgava" for s in body["suggestions"]
    )
    r = row(api, "jelgava, lielā iela")
    assert r["status"] == "ambiguous"  # no house number


@pytest.mark.parametrize(
    "text",
    [
        "Tautas iela 11, Daugavpils",
        "tautas iela 11 daugavpils",
        "TAUTAS IELA 11, DAUGAVPILS",
        "tautsa iela 11, daugavpls",
        "Tautas ie. 11, Daugavpils",
    ],
)
def test_seed_address_typos(api, live, text):
    r = row(api, text)
    assert r["status"] == "resolved", r
    assert r["matches"][0]["description"] == "Tautas iela 11, Daugavpils, LV-5404"
    if r["matches"][0]["match_type"] == "fuzzy":
        assert r["warnings"][0]["message"] == (
            f"ievadīts: '{text}' → atrasts: 'Tautas iela 11, Daugavpils, LV-5404'"
        )


def test_earlier_name(api, live):
    r = row(api, "Prohorova iela 28A, Jelgava")
    assert r["status"] == "resolved"
    assert r["matches"][0]["address"]["full_text"] == "Sesavas iela 28A, Jelgava, LV-3002"
    assert (
        "atrasts pēc agrākā nosaukuma; pašreizējā adrese: Sesavas iela 28A, Jelgava, LV-3002"
        in [w["message"] for w in r["warnings"]]
    )


def test_deleted_addresses(api, live):
    one_link, split, split3, none = resolve(
        api,
        "Salnas iela 22A, Jelgava",
        "Kalnciema ceļš 80, Jelgava",
        "Zāļu iela 2, Jelgava",
        "Cukura iela 6A, Jelgava",
    )
    assert one_link["status"] == "resolved"
    assert one_link["matches"][0]["address"]["full_text"] == "Salnas iela 22, Jelgava, LV-3008"
    assert wcodes(one_link)[:2] == ["historical_address", "current_address"]
    assert split["status"] == "ambiguous"
    assert {m["description"] for m in split["matches"][:2]} == {
        "Druvu iela 27, Jelgava, LV-3002",
        "Druvu iela 29, Jelgava, LV-3002",
    }
    assert split3["status"] == "ambiguous"
    assert none["status"] == "unresolved"
    assert "pašreizējā adrese nav zināma" in [w["message"] for w in none["warnings"]]


def test_exact_addresses_resolve(api, db_conn, live):
    """300 random existing addresses typed as 'street number, city' resolve; the
    only exceptions are texts that VARIS gives to more than one code."""
    rows = db_conn.execute(
        "SELECT full_text FROM ref.address WHERE dataset_version_id = %s AND status = 'EKS'"
        " ORDER BY md5(code) LIMIT 300",
        (live["varis_addresses"],),
    ).fetchall()
    typed = [", ".join(t.split(", ")[:2]) for (t,) in rows]
    for r, (full,) in zip(resolve(api, *typed), rows, strict=True):
        if r["status"] == "resolved":
            assert r["matches"][0]["address"]["full_text"] == full
            continue
        same = one(
            db_conn,
            "SELECT count(*) FROM ref.address WHERE dataset_version_id = %s AND status = 'EKS'"
            " AND full_text = %s",
            live["varis_addresses"],
            full,
        )
        assert same > 1, r


# --- speed --------------------------------------------------------------------------------------


def test_suggest_p95_under_300ms(api, db_conn, live):
    streets = [
        t.split(" ")[0]
        for (t,) in db_conn.execute(
            "SELECT DISTINCT split_part(full_text, ',', 1) FROM ref.address"
            " WHERE dataset_version_id = %s AND status = 'EKS' ORDER BY 1 LIMIT 400",
            (live["varis_addresses"],),
        )
    ][::4]
    queries = [("riga tautas", "address"), ("jelgava, lielā iela", "address")]
    queries += [(s[:3].lower(), "address") for s in streets[:30]]  # first letters typed
    queries += [(f"{s.lower()} iela 1", "address") for s in streets[30:70]]
    queries += [(s.lower()[:-1] + "x", "address") for s in streets[70:100]]  # typo
    queries += [(p, "cadastre") for p in ("050", "0900036", "13000102702", "500004100")] * 25
    suggest(api, "warm up", "address")
    times = []
    for q, kind in queries:
        t0 = time.perf_counter()
        suggest(api, q, kind)
        times.append((time.perf_counter() - t0) * 1000)
    times.sort()
    p95 = times[int(len(times) * 0.95) - 1]
    print(f"/suggest: n={len(times)} p50={times[len(times) // 2]:.0f} ms p95={p95:.0f} ms")
    assert len(times) >= 200
    assert p95 < 300, f"p95 {p95:.0f} ms"
