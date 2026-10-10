"""SQL address normalisation (migration 20261010200000): ref.addr_norm / ref.addr_key."""

import pytest

from tests.etl.conftest import ETL_DB


@pytest.fixture
def sql():
    import psycopg

    with psycopg.connect(ETL_DB, connect_timeout=3) as conn:

        def _one(query, *params):
            return conn.execute(query, params).fetchone()[0]

        yield _one


@pytest.mark.parametrize(
    ("text", "norm"),
    [
        ("Tautas iela 11A, Daugavpils, LV-5404", "tautas iela 11a daugavpils"),
        ("tautas ie. 11 a, daugavpils", "tautas iela 11a daugavpils"),
        ("JELGAVA, LIELĀ IELA", "jelgava liela iela"),
        ("jelgava, liela iela", "jelgava liela iela"),
        ("Dzintaru pr. 2", "dzintaru prospekts 2"),
        ("Dzintaru prosp.2", "dzintaru prospekts 2"),
        ('"Bražas 1", Jūrmala, LV-2010', "brazas 1 jurmala"),
        ("Viktorijas iela 16 k-4, Jūrmala, LV-2015", "viktorijas iela 16k 4 jurmala"),
        ("Jelgavas nov.", "jelgavas novads"),
        ("Valgundes pag.", "valgundes pagasts"),
        ("Čakstes bulv. 5", "cakstes bulvaris 5"),
        ("  Rīga ,, Tautas  iela ", "riga tautas iela"),
    ],
)
def test_addr_norm(sql, text, norm):
    assert sql("SELECT ref.addr_norm(%s)", text) == norm


def test_addr_key_drops_street_type_words(sql):
    assert sql("SELECT ref.addr_key(%s)", "Lielā iela 7, Jelgava, LV-3001") == "liela 7 jelgava"
    assert sql("SELECT ref.addr_key(%s)", "Dzintaru prospekts 2") == "dzintaru 2"
    # only whole words: 'liela' keeps its 'iela'
    assert sql("SELECT ref.addr_key(%s)", "Lielā") == "liela"


def test_norm_columns_are_generated(sql):
    gen = sql(
        "SELECT array_agg(table_name || '.' || column_name ORDER BY table_name, column_name)"
        " FROM"
        " information_schema.columns WHERE table_schema = 'ref' AND is_generated = 'ALWAYS'"
        " AND column_name IN ('norm', 'norm_key')"
    )
    assert gen == [
        "address.norm",
        "address.norm_key",
        "address_history.norm",
        "address_history.norm_key",
    ]
