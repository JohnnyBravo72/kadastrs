"""Designations and codes are text (CLAUDE.md rule 8, ETL rule E2)."""

LEADING_ZERO_RESTORED = "leading_zero_restored"
UNEXPECTED_LENGTH = "unexpected_length"

# Expected lengths of cadastre designations (PLAN §5.1).
PARCEL = 11  # also property numbers
BUILDING = 14
PARCEL_PART = 15
PREMISE_GROUP = 17


def normalize_code(value: str | None, length: int | None = None) -> tuple[str | None, list[str]]:
    """Trim a code and, if it is digits-only and exactly one digit short of
    `length`, restore the lost leading zero (rule E2).

    Returns (code, flags). Non-string input is refused: a number here means a
    reader parsed a code as a number, which loses leading zeros (rule 8).
    """
    if value is None:
        return None, []
    if not isinstance(value, str):
        raise TypeError(f"codes must be read as text, got {type(value).__name__}: {value!r}")
    code = value.strip()
    if not code:
        return None, []
    if length is None:
        return code, []
    if code.isdigit() and len(code) == length - 1:
        return "0" + code, [LEADING_ZERO_RESTORED]
    if len(code) != length:
        return code, [UNEXPECTED_LENGTH]
    return code, []
