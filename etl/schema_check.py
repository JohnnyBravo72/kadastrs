"""Schema check (PLAN.md §2.2): a changed source stops the import loudly.

Expected schemas live in config/schemas.yaml. Any added, missing, renamed or
retyped column (CSV header, SHP field) or an unknown XML element path is an
error; the last good version stays live.
"""


class SchemaMismatch(Exception):
    pass


def check_columns(name: str, actual: list, expected: list) -> None:
    actual, expected = [list(a) if isinstance(a, tuple) else a for a in actual], list(expected)
    if actual == expected:
        return
    exp_names = [e[0] if isinstance(e, list) else e for e in expected]
    act_names = [a[0] if isinstance(a, list) else a for a in actual]
    parts = []
    if missing := [n for n in exp_names if n not in act_names]:
        parts.append(f"missing {missing}")
    if extra := [n for n in act_names if n not in exp_names]:
        parts.append(f"unexpected {extra}")
    if not parts:
        changed = [(e, a) for e, a in zip(expected, actual, strict=False) if e != a]
        parts.append(f"changed order/type {changed[:5]}")
    raise SchemaMismatch(f"{name}: columns differ from config/schemas.yaml: " + "; ".join(parts))


def check_prj(name: str, prj: str, spec: dict) -> int:
    """Return the SRID the .prj stands for, or raise.

    Compared without quotes and spaces: VZD's cadastre .prj files write the WKT
    unquoted (AUTHORITY[EPSG,10306]), the VARIS ones quoted."""
    flat = prj.replace('"', "").replace(" ", "").strip()
    if "crs_epsg" in spec:
        epsg = int(spec["crs_epsg"])
        if not flat.endswith(f"AUTHORITY[EPSG,{epsg}]]"):
            raise SchemaMismatch(f"{name}: .prj does not name EPSG:{epsg}: {prj[:120]}")
        return epsg
    crs_name = spec["crs_name"]
    if not flat.startswith(f"PROJCS[{crs_name},"):
        raise SchemaMismatch(f"{name}: .prj is not {crs_name}: {prj[:120]}")
    return int(spec["crs_srid"])  # .prj without AUTHORITY: SRID assigned by name


def check_xml_paths(name: str, seen: set[str], expected: list[str], required: list[str]) -> None:
    unknown = sorted(seen - set(expected))
    if unknown:
        raise SchemaMismatch(f"{name}: unknown XML elements {unknown[:10]} (config/schemas.yaml)")
    missing = sorted(set(required) - seen)
    if missing:
        raise SchemaMismatch(f"{name}: required XML elements missing {missing}")
