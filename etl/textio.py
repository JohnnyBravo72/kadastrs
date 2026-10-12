"""Reading text sources: CSV (rule E3) and XML (rule E4)."""

import codecs
import csv
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path

_WS = re.compile(r"[\r\n\t]+")


def clean_text(value: str | None) -> str | None:
    """E4: CR, LF and tab become a single space; trimmed; empty -> None.
    Backslashes are data and are kept."""
    if value is None:
        return None
    value = _WS.sub(" ", value).strip()
    return value or None


# --- CSV (E3) ------------------------------------------------------------------


def detect_encoding(path: Path, declared: str | None = None) -> tuple[str, str | None]:
    """The file wins over declared metadata (VZD metadata says ISO-8859-1, the
    files are UTF-8 with BOM). Returns (python codec, note or None).

    Only UTF-8 (with or without BOM) is accepted; anything else stops the import
    rather than producing replacement characters.
    """
    with open(path, "rb") as f:
        head = f.read(4)
    codec = "utf-8-sig" if head.startswith(codecs.BOM_UTF8) else "utf-8"
    note = None
    if declared and declared.lower().replace("_", "-") not in ("utf-8", "utf8"):
        note = f"metadata declares {declared}; file read as UTF-8"
    return codec, note


def iter_csv(
    path: Path, declared_encoding: str | None = None, delimiter: str = ","
) -> Iterator[dict[str, str]]:
    """Rows as dicts of str (never numbers). A real CSV parser: `"` quoting and
    `""` escaping, so a field written `\"\"\"4\"\"\"` is the value `"4"`.
    Invalid UTF-8 raises UnicodeDecodeError (strict). UR files use `;`."""
    codec, _ = detect_encoding(path, declared_encoding)
    with open(path, encoding=codec, errors="strict", newline="") as f:
        reader = csv.DictReader(
            f, delimiter=delimiter, quotechar='"', doublequote=True, strict=True
        )
        for row in reader:
            if None in row:
                raise ValueError(f"{path.name} line {reader.line_num}: more fields than the header")
            yield row


def csv_header(path: Path, delimiter: str = ",") -> list[str]:
    codec, _ = detect_encoding(path)
    with open(path, encoding=codec, errors="strict", newline="") as f:
        return next(csv.reader(f, delimiter=delimiter))


# --- XML (E4) ------------------------------------------------------------------


def local(tag: str) -> str:
    """Element name without namespace: '{ns}Parcel' -> 'Parcel'."""
    return tag.rsplit("}", 1)[-1]


def child(elem: ET.Element, *path: str) -> ET.Element | None:
    """First descendant along local names, e.g. child(e, 'ObjectRelation', 'ObjectCadastreNr')."""
    cur: ET.Element | None = elem
    for name in path:
        if cur is None:
            return None
        cur = next((c for c in cur if local(c.tag) == name), None)
    return cur


def children(elem: ET.Element, *path: str) -> list[ET.Element]:
    """All elements at the last step of `path` (namespace-agnostic)."""
    level = [elem]
    for name in path:
        level = [c for e in level for c in e if local(c.tag) == name]
    return level


def text(elem: ET.Element, *path: str) -> str | None:
    """Cleaned text of a descendant (E4), or None."""
    node = child(elem, *path) if path else elem
    return clean_text(node.text) if node is not None else None


def element_paths(elem: ET.Element, prefix: str = "") -> set[str]:
    """All descendant paths of local names below `elem` (for the schema check)."""
    out: set[str] = set()
    for c in elem:
        p = f"{prefix}/{local(c.tag)}" if prefix else local(c.tag)
        out.add(p)
        out |= element_paths(c, p)
    return out
