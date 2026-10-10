"""Input classification (PLAN.md §5.1): lengths, leading zeros, Excel damage. No DB."""

import pytest

from engine.resolve.classify import classify


def codes(c):
    return [x.code for x in c.corrections]


@pytest.mark.parametrize(
    ("raw", "value", "designation"),
    [
        ("05000041006", "05000041006", "property_or_parcel"),
        ("09000360220002", "09000360220002", "building"),
        ("090003602200001", "090003602200001", "parcel_part"),
        ("05000041006001001", "05000041006001001", "premise_group"),
    ],
)
def test_lengths(raw, value, designation):
    c = classify(raw)
    assert (c.kind, c.value, c.designation, c.corrections) == ("cadastre", value, designation, [])


@pytest.mark.parametrize(
    ("raw", "fixed", "designation"),
    [
        ("5000041006", "05000041006", "property_or_parcel"),  # 10 -> 11
        ("9000360220002", "09000360220002", "building"),  # 13 -> 14
        ("5000041006001001", "05000041006001001", "premise_group"),  # 16 -> 17
    ],
)
def test_leading_zero_restored(raw, fixed, designation):
    c = classify(raw)
    assert (c.value, c.designation) == (fixed, designation)
    assert codes(c) == ["leading_zero_restored"]
    assert c.corrections[0].original == raw and c.corrections[0].corrected == fixed
    assert "atjaunota nulle sākumā" in c.corrections[0].message


@pytest.mark.parametrize(
    ("raw", "expected_codes"),
    [
        ("5000041006", ["leading_zero_restored"]),
        (5000041006, ["leading_zero_restored"]),  # JSON number
        ("5.000041006E9", ["scientific_notation", "leading_zero_restored"]),
        ("5.000041006E+09", ["scientific_notation", "leading_zero_restored"]),
        ("5,000041006E+09", ["scientific_notation", "leading_zero_restored"]),  # LV decimal comma
        (5.000041006e9, ["trailing_decimal", "leading_zero_restored"]),  # JSON float
        ("05000041006.0", ["trailing_decimal"]),
        ("5000041006.0", ["trailing_decimal", "leading_zero_restored"]),
        ("5000041006,00", ["trailing_decimal", "leading_zero_restored"]),
        ("'05000041006", []),  # Excel text prefix
        ('"05000041006"', []),
        (" 05000041006 ", []),
        ("0500 004 1006", ["separators_removed"]),
        ("0500-004-1006", ["separators_removed"]),
        ("0500 004 1006", ["separators_removed"]),
        ("0500 004 1006.0", ["separators_removed", "trailing_decimal"]),
    ],
)
def test_excel_mangled_seed(raw, expected_codes):
    c = classify(raw)
    assert c.kind == "cadastre"
    assert c.value == "05000041006"
    assert codes(c) == expected_codes
    assert not c.precision_lost


@pytest.mark.parametrize("raw", ["5E9", "5.00004E+09", "1.00004E+16"])
def test_scientific_with_dropped_digits_is_flagged(raw):
    c = classify(raw)
    assert c.precision_lost
    assert "zaudēti" in c.warnings[0].message


def test_scientific_17_digits_with_15_significant_is_flagged():
    c = classify("1.00004000600211E+16")  # what Excel shows for 10000400060021101
    assert c.value == "10000400060021100"
    assert c.precision_lost


def test_varis_code():
    c = classify("101808322")
    assert (c.kind, c.value) == ("address_code", "101808322")


@pytest.mark.parametrize(
    "raw",
    ["Tautas iela 11, Daugavpils", "riga tautas", "jelgava, lielā iela", "Lielā iela 5 k-2"],
)
def test_text_is_address(raw):
    c = classify(raw)
    assert c.kind == "address"
    assert c.value == " ".join(raw.split())


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        ("", "empty"),
        ("   ", "empty"),
        (None, "empty"),
        ("123", "invalid"),
        ("---", "invalid"),
        ("050000410061", "invalid"),  # 12 digits
        ("1.5E2", "invalid"),  # 150
        ("1.25E1", "invalid"),  # 12.5
    ],
)
def test_empty_and_invalid(raw, kind):
    c = classify(raw)
    assert c.kind == kind
    if kind == "invalid":
        assert c.reason
