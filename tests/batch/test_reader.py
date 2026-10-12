"""Batch input reader (PLAN.md §8.1 step 6): pasted list, CSV, XLSX."""

import csv
import io
from pathlib import Path

import pytest
from openpyxl import Workbook

from engine.batch.headers import INPUT_COLUMNS
from engine.batch.reader import InputError, read_csv, read_text, read_upload, read_xlsx
from engine.batch.template import input_template

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


# --- header styles (decided 2026-10-12: readable Latvian headers, old names kept) ----

OLD = ["vertiba", "projekta_nr", "pieteicejs_reg_nr", "adrese", "veids"]
ROWS = [
    [5000041006, "P-1", "40003000000", "Tautas iela 11, Daugavpils", "īpašums"],
    ["09000360220", "007", None, None, None],
    ["Institūta iela 4, Jelgava", "P-2", None, "Institūta iela 4, Jelgava", "zemes vienība"],
]


def test_old_and_new_headers_import_identically():
    new = [c.header for c in INPUT_COLUMNS]
    assert read_xlsx(_xlsx([OLD, *ROWS]), LIMIT) == read_xlsx(_xlsx([new, *ROWS]), LIMIT)
    rows = read_xlsx(_xlsx([new, *ROWS]), LIMIT)
    assert (rows[0].value, rows[0].project_no, rows[0].applicant) == (
        5000041006,
        "P-1",
        "40003000000",
    )
    assert (rows[0].address, rows[0].kind) == ("Tautas iela 11, Daugavpils", "īpašums")
    assert rows[1].project_no == "007"


def test_headers_in_another_order_shortened_or_mixed():
    new = [c.header for c in INPUT_COLUMNS]
    order = [4, 3, 2, 1, 0]
    shuffled = read_xlsx(
        _xlsx([[new[i] for i in order], *[[r[i] for i in order] for r in ROWS]]), LIMIT
    )
    assert shuffled == read_xlsx(_xlsx([OLD, *ROWS]), LIMIT)
    short = [
        "KADASTRA NR.",
        "projekta nr",
        "Pieteicēja reģ. Nr.",
        "Adrese pieteikumā",
        "Objekta veids",
    ]
    assert read_xlsx(_xlsx([short, *ROWS]), LIMIT) == read_xlsx(_xlsx([OLD, *ROWS]), LIMIT)
    mixed = [new[0], "projekta_nr", new[2], "adrese", new[4]]
    assert read_xlsx(_xlsx([mixed, *ROWS]), LIMIT) == read_xlsx(_xlsx([OLD, *ROWS]), LIMIT)


@pytest.mark.parametrize("delimiter", [";", "\t", ","])
def test_new_headers_in_csv_and_pasted_text(delimiter):
    new = [c.header for c in INPUT_COLUMNS]

    def table(header):
        out = io.StringIO()
        w = csv.writer(out, delimiter=delimiter, lineterminator="\n")
        w.writerow(header)
        w.writerow(["09000360220", "007", "", "Institūta iela 4, Jelgava", "zemes vienība"])
        return out.getvalue()

    a, b = read_text(table(new), LIMIT), read_text(table(OLD), LIMIT)
    assert a == b
    assert (a[0].value, a[0].project_no, a[0].address, a[0].kind) == (
        "09000360220",
        "007",
        "Institūta iela 4, Jelgava",
        "zemes vienība",
    )
    assert read_csv(table(new).encode("utf-8"), LIMIT) == a


def test_the_downloadable_template_reads_back():
    wb = input_template()
    ws = wb["Saraksts"]
    for c, v in enumerate(["09000360220", "P-1", None, None, "būve"], 1):  # typed into row 2
        ws.cell(row=2, column=c, value=v)
    buf = io.BytesIO()
    wb.save(buf)
    (row,) = read_upload("saraksta_veidne.xlsx", buf.getvalue(), LIMIT)  # not the Instrukcija sheet
    assert (row.row_no, row.value, row.project_no, row.kind) == (2, "09000360220", "P-1", "būve")
