"""T-E1 (URLs from package_show) and T-E2 (codes are text; leading zeros restored)."""

import re
from pathlib import Path

import pytest

from etl.codes import LEADING_ZERO_RESTORED, normalize_code
from tests.etl import fakes
from tests.etl.test_import_sources import publish_all

ROOT = Path(__file__).resolve().parents[2]


# --- T-E1 -------------------------------------------------------------------------


def test_e1_redated_resource_url_is_fetched(run, server, q):
    """package_show returns a re-dated filename: the import fetches the new file."""
    publish_all(server)
    assert run("admin_boundaries").status == "succeeded"
    new_url = server.publish(
        "admin_boundaries", "aw_shp", "aw_shp_10.10.2026.zip", fakes.admin_zip(novads_name="NovadZ")
    )
    out = run("admin_boundaries")
    assert out.status == "succeeded", out.message
    assert new_url in [str(r.url) for r in server.requests]
    assert q("SELECT resource_urls FROM dataset_version WHERE status = 'live'") == [([new_url],)]
    assert q("SELECT name FROM ref.admin_area_current WHERE level = 'novads'") == [("NovadZ",)]


def test_e1_no_hardcoded_download_urls_in_etl():
    """Static check: no /resource/…/download/ URLs in etl/ outside etl/discovery/."""
    pattern = re.compile(r"/resource/[0-9a-f-]+/download/")
    offenders = [
        str(p.relative_to(ROOT))
        for p in (ROOT / "etl").rglob("*.py")
        if "discovery" not in p.parts and pattern.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == []


# --- T-E2 -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "length", "expected"),
    [
        ("1000040006002", 14, ("01000040006002", [LEADING_ZERO_RESTORED])),
        ("1000040006", 11, ("01000040006", [LEADING_ZERO_RESTORED])),
        ("01000040006", 11, ("01000040006", [])),
        (" 09000360220 ", 11, ("09000360220", [])),
        ("", 11, (None, [])),
        ("123", 11, ("123", ["unexpected_length"])),
    ],
)
def test_e2_normalize_code(value, length, expected):
    assert normalize_code(value, length) == expected


def test_e2_numbers_are_refused():
    with pytest.raises(TypeError, match="codes must be read as text"):
        normalize_code(9000360220, 11)


def test_e2_fixture_rows_import_with_restored_zeros(run, server, q):
    publish_all(server)
    docs = fakes.default_text_docs("property")
    docs["0002000"] = fakes.xml_doc(
        "property",
        "0002000",
        [
            fakes.property_item(
                "1000040006", [("1000040006", "Zemes vienība"), ("1000040006002", "Būve")]
            )
        ],
    )
    server.publish("cadastre_text", "property", "property.zip", fakes.text_zip("property", docs))
    out = run("cadastre_text")
    assert out.status == "succeeded", out.message
    assert q("SELECT number, flags FROM ref.property WHERE number LIKE '0100%'") == [
        ("01000040006", [LEADING_ZERO_RESTORED])
    ]
    assert q(
        "SELECT object_code, flags FROM ref.property_object WHERE property_number = '01000040006'"
        " ORDER BY 1"
    ) == [("01000040006", [LEADING_ZERO_RESTORED]), ("01000040006002", [LEADING_ZERO_RESTORED])]


def test_e2_no_code_column_is_numeric(q):
    code_like = r"(^|_)(code|codes|number|atvk|nr)$|^code_his$"
    rows = q(
        "SELECT table_name, column_name, data_type FROM information_schema.columns"
        " WHERE table_schema = 'ref' AND column_name ~ %s AND data_type <> 'text'"
        " AND table_name NOT LIKE '%%current'",
        code_like,
    )
    assert rows == []
