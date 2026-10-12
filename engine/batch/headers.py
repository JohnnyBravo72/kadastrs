"""Column headers of the input template and the test-set template (decided
2026-10-12): readable Latvian headers for colleagues, the old technical names
still accepted. One place for both, so templates, the batch reader and
`check compare` agree.

A header is matched without case, diacritics and punctuation, by its leading
words (so "Kadastra Nr." and the full "Kadastra Nr., apzīmējums vai adrese"
both work), or by its old name (`vertiba`, `projekta_nr`, …).
"""

import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class Column:
    name: str  # canonical (old technical) name
    header: str  # Latvian header in the templates
    required: bool
    prefixes: tuple[str, ...]  # folded leading words that identify the column


INPUT_COLUMNS: tuple[Column, ...] = (
    Column("vertiba", "Kadastra Nr., apzīmējums vai adrese", True, ("vertiba", "kadastra_nr")),
    Column("projekta_nr", "Projekta Nr.", False, ("projekta_nr", "projekts")),
    Column(
        "pieteicejs_reg_nr",
        "Pieteicēja reģ. Nr. (tikai juridiskām personām)",
        False,
        ("pieteicejs_reg_nr", "pieteiceja_reg"),
    ),
    Column("adrese", "Adrese pieteikumā (atbilstības pārbaudei)", False, ("adrese",)),
    Column(
        "veids",
        "Objekta veids: īpašums / zemes vienība / būve (ja numurs divdomīgs)",
        False,
        ("veids", "objekta_veids"),
    ),
)

# The test set adds the manual answers per module, the check date and notes.
TEST_SET_COLUMNS: tuple[Column, ...] = (
    Column("m1_kadastra_dati", "M1 Kadastra dati", False, ("m1",)),
    Column("m2_adreses_atbilstiba", "M2 Adreses atbilstība", False, ("m2",)),
    Column("m3_aizsargajama_daba", "M3 Aizsargājamā daba", False, ("m3",)),
    Column("m4_pludi_10_gadi", "M4 Plūdi (10 gadi)", False, ("m4",)),
    Column("m5_buvniecibas_lietas", "M5 Būvniecības lietas (BIS)", False, ("m5",)),
    Column("m6_apgrutinajumi", "M6 Apgrūtinājumi", False, ("m6",)),
    Column("parbaudes_datums", "Pārbaudes datums", False, ("parbaudes_datums",)),
    Column("avots_piezimes", "Avoti un piezīmes", False, ("avots_piezimes", "avoti_un_piezimes")),
)

KIND_CHOICES = ("īpašums", "zemes vienība", "būve")


def fold(text: str) -> str:
    """Lowercase, no diacritics, runs of spaces, dots and hyphens as one '_'."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower().strip()
    return re.sub(r"[\s.\-]+", "_", text).strip("_")


def _starts(folded: str, prefix: str) -> bool:
    return folded == prefix or (folded.startswith(prefix) and not folded[len(prefix)].isalnum())


def canonical(
    header: object, columns: tuple[Column, ...] = INPUT_COLUMNS + TEST_SET_COLUMNS
) -> str | None:
    """The canonical name of a header cell, or None when it is not a known column."""
    if header is None:
        return None
    f = fold(str(header))
    if not f:
        return None
    for col in columns:
        if any(_starts(f, p) for p in col.prefixes):
            return col.name
    return None
