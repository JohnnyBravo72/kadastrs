"""Batch input reader (PLAN.md §8.1 step 6): pasted list, CSV, XLSX."""

import io
from pathlib import Path

import pytest
from openpyxl import Workbook

from engine.batch.reader import InputError, read_csv, read_text, read_upload, read_xlsx

LIMIT = 1000
TEMPLATE = Path(__file__).resolve().parents[1] / "data" / "test_set_template.xlsx"


def _xlsx(rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_pasted_list_one_value_per_line():
    rows = read_text("09000360220\n\n  Tautas iela 11, Daugavpils \r\n5000041006\n", LIMIT)
    assert [(r.row_no, r.value) for r in rows] == [
        (1, "09000360220"),
        (3, "Tautas iela 11, Daugavpils"),  # the comma stays: no header, no split
        (4, "5000041006"),
    ]


def test_pasted_table_from_excel_with_header():
    text = "Vērtība\tProjekta Nr.\tadrese\tVeids\n05000040014\tP-1\tTautas iela 11\tīpašums\n"
    (row,) = read_text(text, LIMIT)
    assert (row.value, row.project_no, row.address, row.kind) == (
        "05000040014",
        "P-1",
        "Tautas iela 11",
        "īpašums",
    )
    assert row.row_no == 2


@pytest.mark.parametrize("delimiter", [";", ","])
def test_csv_delimiters_and_quoted_addresses(delimiter):
    d = delimiter
    data = (
        f'projekta_nr{d}vertiba{d}adrese\nP-1{d}09000360220{d}"Institūta iela 4, Jelgava"\n'
    ).encode()
    (row,) = read_csv(data, LIMIT)
    assert (row.project_no, row.value, row.address) == (
        "P-1",
        "09000360220",
        "Institūta iela 4, Jelgava",
    )


def test_csv_encodings_utf8_bom_and_windows_1257():
    text = "vertiba;adrese\n09000360220;Ģertrūdes iela 5, Rīga\n"
    for data in (b"\xef\xbb\xbf" + text.encode("utf-8"), text.encode("cp1257")):
        (row,) = read_csv(data, LIMIT)
        assert row.address == "Ģertrūdes iela 5, Rīga"


def test_xlsx_keeps_numeric_cells_for_the_classifier_and_codes_as_text():
    data = _xlsx(
        [
            ["vertiba", "projekta_nr", "pieteicejs_reg_nr"],
            [5000041006, 1.0, 40003000000.0],  # lost leading zero; numbers in code columns
            ["09000360220", "007", None],
        ]
    )
    a, b = read_xlsx(data, LIMIT)
    assert a.value == 5000041006  # repaired and flagged by classify(), not here
    assert (a.project_no, a.applicant) == ("1", "40003000000")
    assert (b.value, b.project_no) == ("09000360220", "007")


def test_template_sheet_is_read_and_examples_skipped():
    rows = read_upload("test_set_template.xlsx", TEMPLATE.read_bytes(), LIMIT)
    assert rows == []  # only the two PIEMĒRS rows


def test_headerless_xlsx_uses_the_first_column():
    rows = read_xlsx(_xlsx([["09000360220"], [None], ["13000102702"]]), LIMIT)
    assert [(r.row_no, r.value) for r in rows] == [(1, "09000360220"), (3, "13000102702")]


def test_row_limit():
    assert len(read_text("\n".join(["09000360220"] * LIMIT), LIMIT)) == LIMIT
    with pytest.raises(InputError, match="ne vairāk kā 1000"):
        read_text("\n".join(["09000360220"] * (LIMIT + 1)), LIMIT)
    with pytest.raises(InputError, match="ne vairāk kā 1000"):
        read_xlsx(_xlsx([["vertiba"]] + [["09000360220"]] * (LIMIT + 1)), LIMIT)


def test_old_xls_and_broken_xlsx_are_refused():
    with pytest.raises(InputError, match=".xlsx"):
        read_upload("saraksts.xls", b"\xd0\xcf\x11\xe0", LIMIT)
    with pytest.raises(InputError, match="Excel"):
        read_upload("saraksts.xlsx", b"PK not really a zip", LIMIT)
