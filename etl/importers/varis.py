"""varis_addresses: building and parcel addresses of the pilot cities (EKS and
DEL; ERR is never imported, CLAUDE.md rule 11) with their earlier texts.

Pilot filter (docs/data-sources.md §5.1): an address belongs to a pilot city
when its VKUR_CD is the city or a street of the city. Coordinates: KOORD_X is
the northing and KOORD_Y the easting (EPSG:10306).
"""

import re
from collections import Counter

from etl.importers.common import copy_rows, fetch_whole, parse_varis_date, resource_date
from etl.schema_check import check_columns
from etl.settings import schemas
from etl.textio import csv_header, iter_csv

FILES = {
    "aw_eka": "aw_eka.csv",
    "aw_eka_his": "aw_eka_his.csv",
    "aw_iela": "aw_iela.csv",
    "aw_pilseta": "aw_pilseta.csv",
}
_CODE = re.compile(r"^[0-9]{9}$")
_NUM = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")

ADDRESS_COLUMNS = [
    "dataset_version_id",
    "code",
    "status",
    "type_code",
    "parent_code",
    "parent_type",
    "city_code",
    "city_atvk",
    "name",
    "sort_name",
    "postal_code",
    "full_text",
    "for_build",
    "plan_adr",
    "date_start",
    "date_modified",
    "date_end",
    "geom",
    "flags",
]
HISTORY_COLUMNS = [
    "dataset_version_id",
    "row_no",
    "code",
    "code_his",
    "type_code",
    "full_text",
    "name",
    "parent_code",
    "parent_type",
    "date_start",
    "date_modified",
    "date_end",
]


def _code(value: str, what: str) -> str:
    if not _CODE.match(value):
        raise ValueError(f"{what}: VARIS code {value!r} is not 9 digits")
    return value


class VarisAddresses:
    source_id = "varis_addresses"

    def fetch(self, ctx):
        return [fetch_whole(ctx, role, name) for role, name in FILES.items()]

    def version_date(self, ctx, files):
        return resource_date(ctx, FILES)

    def check_schema(self, ctx):
        for name in FILES.values():
            check_columns(name, csv_header(ctx.workdir / name), schemas()["csv"][name])

    def load(self, ctx, conn, version_id, files):
        self.check_schema(ctx)
        w = ctx.workdir
        pilot = set(ctx.cfg.pilot_atvk)

        cities = {}
        for row in iter_csv(w / "aw_pilseta.csv"):
            if row["ATRIB"] in pilot:
                if row["STATUSS"] != "EKS":
                    raise ValueError(f"pilot city {row['ATRIB']} has status {row['STATUSS']}")
                cities[_code(row["KODS"], "aw_pilseta")] = row["ATRIB"]
        if sorted(cities.values()) != sorted(pilot):
            raise ValueError(f"pilot cities found in aw_pilseta: {sorted(cities.values())}")

        street_city = {}
        for row in iter_csv(w / "aw_iela.csv"):
            if row["VKUR_CD"] in cities:
                street_city[_code(row["KODS"], "aw_iela")] = row["VKUR_CD"]

        by_status: Counter = Counter()
        pilot_codes: set[str] = set()

        def addresses():
            for row in iter_csv(w / "aw_eka.csv"):
                parent = row["VKUR_CD"]
                city = parent if parent in cities else street_city.get(parent)
                if city is None:
                    continue
                status = row["STATUSS"]
                by_status[status] += 1
                if status not in ("EKS", "DEL"):
                    continue  # ERR is never imported
                code = _code(row["KODS"], "aw_eka")
                pilot_codes.add(code)
                geom = None
                if row["KOORD_X"] or row["KOORD_Y"]:
                    north, east = row["KOORD_X"], row["KOORD_Y"]
                    if not (_NUM.match(north) and _NUM.match(east)):
                        raise ValueError(f"aw_eka {code}: bad coordinates {north!r}, {east!r}")
                    geom = f"SRID=10306;POINT({east} {north})"
                yield (
                    version_id,
                    code,
                    status,
                    row["TIPS_CD"],
                    parent,
                    row["VKUR_TIPS"],
                    city,
                    cities[city],
                    row["NOSAUKUMS"] or None,
                    row["SORT_NOS"] or None,
                    row["ATRIB"] or None,
                    row["STD"],
                    row["FOR_BUILD"] or None,
                    row["PLAN_ADR"] or None,
                    parse_varis_date(row["DAT_SAK"]),
                    parse_varis_date(row["DAT_MOD"]),
                    parse_varis_date(row["DAT_BEIG"]),
                    geom,
                    [],
                )

        loaded = copy_rows(conn, "ref.address", ADDRESS_COLUMNS, addresses())
        expected = by_status["EKS"] + by_status["DEL"]
        if loaded != expected:
            raise ValueError(f"address: {expected} EKS+DEL rows in the pilot but {loaded} loaded")

        his_total = 0

        def history():
            nonlocal his_total
            for row_no, row in enumerate(iter_csv(w / "aw_eka_his.csv"), start=1):
                his_total += 1
                code, his = row["KODS"], row["KODS_HIS"] or None
                if code not in pilot_codes and his not in pilot_codes:
                    continue
                yield (
                    version_id,
                    row_no,
                    code,
                    his,
                    row["TIPS_CD"] or None,
                    row["STD"] or None,
                    row["NOSAUKUMS"] or None,
                    row["VKUR_CD"] or None,
                    row["VKUR_TIPS"] or None,
                    parse_varis_date(row["DAT_SAK"]),
                    parse_varis_date(row["DAT_MOD"]),
                    parse_varis_date(row["DAT_BEIG"]),
                )

        his_loaded = copy_rows(conn, "ref.address_history", HISTORY_COLUMNS, history())
        return {
            "address": {
                "source_pilot_by_status": dict(by_status),
                "loaded": loaded,
                "pilot_cities": len(cities),
                "pilot_streets": len(street_city),
            },
            "address_history": {"source_rows": his_total, "loaded": his_loaded},
        }
