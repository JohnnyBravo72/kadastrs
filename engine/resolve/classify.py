"""Classify one raw input value (PLAN.md §5.1). Pure Python, no database.

Cleans what spreadsheets do to designations, then decides by length:
  11 digits  property number or parcel (both are looked up)
  14         building (if no such building: a parcel part that lost its leading 0)
  15         parcel part
  17         premise group (telpu grupa), checked as its building
  10/13/16   one digit short of 11/14/17: a lost leading zero is restored (flagged)
   9         VARIS address code
Anything with letters is an address. Codes stay text throughout (CLAUDE.md rule 8).
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Literal

from engine.resolve.models import Correction, Note

Kind = Literal["cadastre", "address", "address_code", "empty", "invalid"]
Designation = Literal["property_or_parcel", "building", "parcel_part", "premise_group"]

BY_LENGTH: dict[int, Designation] = {
    11: "property_or_parcel",
    14: "building",
    15: "parcel_part",
    17: "premise_group",
}
SHORT_BY_ONE = {10: 11, 13: 14, 16: 17}
VARIS_CODE_LENGTH = 9
# Excel keeps 15 significant digits; scientific notation may keep fewer.
PRECISION_LOST = "precision_lost"

_SEPARATORS = re.compile(r"[\s  \-‐‑‒–—]+")
_QUOTES = "'\"‘’“”„"
_DIGITS = re.compile(r"^[0-9]+$")
_TRAILING_DECIMAL = re.compile(r"^([0-9]+)[.,]0+$")
_SCIENTIFIC = re.compile(r"^([0-9]+)(?:[.,]([0-9]+))?[eE]\+?([0-9]+)$")
_LETTER = re.compile(r"[^\W\d_]")


@dataclass
class Classified:
    input: str
    kind: Kind
    value: str | None = None  # digits, or the trimmed address text
    designation: Designation | None = None
    corrections: list[Correction] = field(default_factory=list)
    warnings: list[Note] = field(default_factory=list)
    reason: str | None = None

    @property
    def precision_lost(self) -> bool:
        return any(w.code == PRECISION_LOST for w in self.warnings)


def to_text(raw: object) -> str:
    """Input as text. JSON numbers arrive as int/float; floats are written without
    exponent loss where possible (Decimal of their shortest repr)."""
    if raw is None:
        return ""
    if isinstance(raw, bool):
        return str(raw)
    if isinstance(raw, int):
        return str(raw)
    if isinstance(raw, float):
        return repr(raw)
    return str(raw)


def classify(raw: object) -> Classified:
    text = to_text(raw)
    trimmed = text.strip()
    if not trimmed:
        return Classified(input=text, kind="empty", reason="tukša vērtība")

    value = trimmed.strip(_QUOTES).strip()  # Excel text prefix ', or quoted CSV
    compact = _SEPARATORS.sub("", value)
    corrections: list[Correction] = []
    warnings: list[Note] = []
    digits: str | None = None

    if _DIGITS.match(compact):
        digits = compact
    elif m := _TRAILING_DECIMAL.match(compact):
        digits = m.group(1)
        corrections.append(
            Correction(
                code="trailing_decimal",
                original=compact,
                corrected=digits,
                message=f"noņemta decimāldaļa (Excel skaitļa formāts): {compact} → {digits}",
            )
        )
    elif m := _SCIENTIFIC.match(compact):
        digits, lost = _expand_scientific(m)
        if digits is None:
            return Classified(
                input=text,
                kind="invalid",
                value=compact,
                reason=f"eksponentpierakstu {compact} nevar pārvērst veselā skaitlī",
            )
        corrections.append(
            Correction(
                code="scientific_notation",
                original=compact,
                corrected=digits,
                message=f"eksponentpieraksts pārveidots: {compact} → {digits}",
            )
        )
        if lost:
            warnings.append(
                Note(
                    code=PRECISION_LOST,
                    message=(
                        f"eksponentpierakstā {compact} var būt zaudēti pēdējie cipari"
                        " (Excel); pārbaudiet numuru"
                    ),
                )
            )

    if digits is None:
        if _LETTER.search(value):
            return Classified(input=text, kind="address", value=" ".join(value.split()))
        return Classified(
            input=text,
            kind="invalid",
            value=value,
            reason="nav ne kadastra apzīmējums, ne adrese",
        )

    if compact != value:
        corrections.insert(
            0,
            Correction(
                code="separators_removed",
                original=value,
                corrected=compact,
                message=f"noņemtas atstarpes vai defises: {value} → {compact}",
            ),
        )

    if len(digits) == VARIS_CODE_LENGTH:
        return Classified(
            input=text,
            kind="address_code",
            value=digits,
            corrections=corrections,
            warnings=warnings,
        )
    if len(digits) in SHORT_BY_ONE:
        fixed = "0" + digits
        corrections.append(
            Correction(
                code="leading_zero_restored",
                original=digits,
                corrected=fixed,
                message=f"atjaunota nulle sākumā: {digits} → {fixed}",
            )
        )
        digits = fixed
    designation = BY_LENGTH.get(len(digits))
    if designation is None:
        return Classified(
            input=text,
            kind="invalid",
            value=digits,
            corrections=corrections,
            warnings=warnings,
            reason=(
                f"{len(digits)} cipari: kadastra apzīmējumam jābūt 11, 14, 15 vai 17"
                " ciparus garam (VARIS adreses kodam 9)"
            ),
        )
    return Classified(
        input=text,
        kind="cadastre",
        value=digits,
        designation=designation,
        corrections=corrections,
        warnings=warnings,
    )


def _expand_scientific(m: re.Match) -> tuple[str | None, bool]:
    """'5.000041006E9' -> ('5000041006', False). The second value is True when
    the mantissa has fewer significant digits than the number, i.e. trailing
    zeros may stand for digits Excel dropped."""
    whole, frac, exp = m.group(1), m.group(2) or "", int(m.group(3))
    try:
        number = Decimal(f"{whole}.{frac or '0'}").scaleb(exp)
    except InvalidOperation:
        return None, False
    if number != number.to_integral_value():
        return None, False
    digits = str(int(number))
    written = len((whole + frac).lstrip("0"))  # significant digits as written
    return digits, written < len(digits)
