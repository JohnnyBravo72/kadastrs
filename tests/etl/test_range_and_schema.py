"""Version identity of Range-fetched zip members (docs/data-sources.md §5.4) and
the schema check (a changed source stops the import; the last good version stays)."""

from tests.etl import fakes
from tests.etl.conftest import RESET
from tests.etl.test_import_sources import publish_all
from tests.etl.test_rules_e3_e7 import live

ROLES = ("parcel", "parcelpart", "building", "property")


def _republish(server, role, docs=None, other=None, last_modified="2026-01-15T08:00:00"):
    docs = docs or fakes.default_text_docs(role)
    if other is None:
        other = {"0011000": fakes.xml_doc(role, "0011000", [])}
    server.publish(
        "cadastre_text",
        role,
        f"{role}.zip",
        fakes.text_zip(role, docs, other),
        last_modified=last_modified,
    )


def _member_fetches(server) -> int:
    """Range requests other than the tail and central-directory reads."""
    return sum(1 for r in server.range_requests() if not r.startswith("bytes=-"))


# --- Range-fetched members -----------------------------------------------------------


def test_fast_path_leaves_no_work_dir(run, server, tmp_path):
    server.ignore_range = True  # full downloads land in the work dir
    publish_all(server)
    assert run("cadastre_text").status == "succeeded"
    assert run("cadastre_text").status == "unchanged"
    left = sorted(p.name for p in (tmp_path / "raw" / "cadastre_text").iterdir())
    assert left == ["1"]  # only the live version's raw files


def test_unchanged_remote_zip_is_unchanged_without_fetching_members(run, server, q):
    publish_all(server)
    assert run("cadastre_text").status == "succeeded"
    server.requests.clear()
    out = run("cadastre_text")
    assert out.status == "unchanged" and "fingerprints" in out.message
    # per zip: one tail read + one central-directory read, no member data
    assert len(server.range_requests()) == 2 * len(ROLES)
    assert q("SELECT count(*) FROM dataset_version") == [(1,)]


def test_change_outside_the_pilot_gives_no_new_version(run, server, q):
    publish_all(server)
    assert run("cadastre_text").status == "succeeded"
    _republish(
        server,
        "parcel",
        other={
            "0011000": fakes.xml_doc(
                "parcel", "0011000", [fakes.parcel_item("11000000001", "0011000")]
            )
        },
    )
    server.requests.clear()
    out = run("cadastre_text")
    assert out.status == "unchanged" and "same checksum" in out.message
    assert _member_fetches(server) > 0  # central directory changed, so members were checked
    assert q("SELECT count(*) FROM dataset_version") == [(1,)]


def test_metadata_only_change_gives_no_new_version(run, server, q):
    publish_all(server)
    assert run("cadastre_text").status == "succeeded"
    _republish(server, "building", last_modified="2026-03-01T00:00:00")
    out = run("cadastre_text")
    assert out.status == "unchanged"
    assert q("SELECT count(*) FROM dataset_version") == [(1,)]


def test_changed_pilot_member_gives_new_version(run, server, q):
    publish_all(server)
    v1 = run("cadastre_text").version_id
    docs = fakes.default_text_docs("parcel")
    docs["0003000"] = fakes.xml_doc(
        "parcel", "0003000", [fakes.parcel_item("09000360220", area="999")]
    )
    _republish(server, "parcel", docs)
    out = run("cadastre_text")
    assert out.status == "succeeded" and out.version_id != v1
    assert q("SELECT area_m2::text FROM ref.parcel_current WHERE code = '09000360220'") == [
        ("999",)
    ]


def test_server_ignoring_range_falls_back_to_full_download(run, server, q):
    publish_all(server)
    first = run("cadastre_text")
    checksum = live(q, "cadastre_text")[0][1]
    server.ignore_range = True
    _republish(server, "property", last_modified="2026-03-01T00:00:00")  # fingerprint differs
    out = run("cadastre_text")
    assert out.status == "unchanged", out.message
    assert "range_unsupported" in out.message
    assert q(
        "SELECT checksum, message LIKE '%%range_unsupported%%' FROM import_log"
        " WHERE id = (SELECT max(id) FROM import_log)"
    ) == [(checksum, True)]
    assert first.version_id == live(q, "cadastre_text")[0][0]


def test_full_download_path_gives_the_same_checksum(run, server, q, etl_db):
    server.ignore_range = True
    publish_all(server)
    assert run("cadastre_text").status == "succeeded"
    full = live(q, "cadastre_text")[0][1]
    assert "range_unsupported" in q("SELECT message FROM import_log")[0][0]
    with etl_db() as c:  # start again from an empty DB, this time with Range
        c.execute(RESET)
    server.ignore_range = False
    assert run("cadastre_text").status == "succeeded"
    assert live(q, "cadastre_text")[0][1] == full


# --- schema check ----------------------------------------------------------------------


def _assert_failed_and_kept(out, q, source, before, text):
    assert out.status == "failed", out.message
    assert text in out.message, out.message
    assert live(q, source) == before
    assert q("SELECT status FROM import_log WHERE id = (SELECT max(id) FROM import_log)") == [
        ("failed",)
    ]


def test_extra_csv_column_stops_the_import(run, server, q):
    publish_all(server)
    assert run("varis_addresses").status == "succeeded"
    before = live(q, "varis_addresses")
    body = fakes.varis_files()["aw_iela.csv"].replace(b"STD\r\n", b"STD,JAUNS\r\n", 1)
    server.publish("varis_addresses", "aw_iela", "aw_iela.csv", body)
    _assert_failed_and_kept(
        run("varis_addresses"), q, "varis_addresses", before, "unexpected ['JAUNS']"
    )


def test_changed_shp_field_stops_the_import(run, server, q):
    publish_all(server)
    assert run("cadastre_spatial").status == "succeeded"
    before = live(q, "cadastre_spatial")
    fields = [
        ["CODE", "C", 12] if f[0] == "CODE" else f
        for f in fakes.schemas()["shp"]["KKParcel"]["fields"]
    ]
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        fakes.shp_layer(
            z,
            "ExportCadGroup_0900001/KKParcel",
            "KKParcel",
            [(fakes.kk_rec("09000000001", "7201060310", geom_date=None), [fakes.square(0, 0)])],
            fields=fields,
        )
    server.publish("cadastre_spatial", "0003000", "0003000_kk_shp.zip", buf.getvalue())
    _assert_failed_and_kept(
        run("cadastre_spatial"), q, "cadastre_spatial", before, "changed order/type"
    )


def test_unknown_xml_element_stops_the_import(run, server, q):
    publish_all(server)
    assert run("cadastre_text").status == "succeeded"
    before = live(q, "cadastre_text")
    docs = fakes.default_text_docs("parcel")
    docs["0003000"] = docs["0003000"].replace(
        b"</ParcelBasicData>", b"<UseRight>x</UseRight></ParcelBasicData>"
    )
    _republish(server, "parcel", docs)
    _assert_failed_and_kept(
        run("cadastre_text"),
        q,
        "cadastre_text",
        before,
        "unknown XML elements ['ParcelBasicData/UseRight']",
    )


def test_missing_file_part_stops_the_import(run, server, q):
    publish_all(server)
    docs = fakes.default_text_docs("building")
    docs["0004000"] = docs["0004000"].replace(b"<FilePartCount>1<", b"<FilePartCount>2<")
    _republish(server, "building", docs)
    out = run("cadastre_text")
    assert out.status == "failed" and "FilePartCount 2" in out.message
