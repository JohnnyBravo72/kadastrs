"""Warnings and notices of input resolution: stable codes, Latvian messages."""

from engine.resolve.models import Note


def no_geometry() -> Note:
    return Note(code="no_geometry", message="nav ģeometrijas kadastra kartē")


def not_in_register() -> Note:
    return Note(code="not_in_register", message="ir kadastra kartē, bet nav kadastra teksta datos")


def not_exist() -> Note:
    return Note(code="not_exist", message="reģistrā atzīmēta kā neeksistējoša")


def prereg() -> Note:
    return Note(code="prereg", message="pirmsreģistrēta būve")


def premise_group_to_building(group: str, building: str) -> Note:
    return Note(
        code="premise_group_to_building",
        message=f"telpu grupa {group}: pārbauda būvi {building}",
    )


def premise_group_unknown(group: str) -> Note:
    return Note(
        code="premise_group_not_found",
        message=f"telpu grupa {group} kadastra datos nav atrasta; būve atrasta",
    )


def property_is_own_parcel(number: str) -> Note:
    return Note(
        code="property_and_parcel",
        message=f"{number} ir gan īpašuma numurs, gan šī īpašuma zemes vienības apzīmējums",
    )


def property_or_parcel(number: str, parcel_properties: list[str]) -> Note:
    owners = ", ".join(parcel_properties) or "nav zināms"
    return Note(
        code="ambiguous_property_parcel",
        message=(
            f"{number} ir gan īpašuma numurs, gan citam īpašumam ({owners}) piederošas"
            " zemes vienības apzīmējums; izvēlieties vajadzīgo"
        ),
    )


def outside_pilot(place: str) -> str:
    return f"{place} nav pilota teritorijā"


def fuzzy_address(typed: str, found: str) -> Note:
    return Note(code="fuzzy_match", message=f"ievadīts: '{typed}' → atrasts: '{found}'")


def earlier_name(current: str) -> Note:
    return Note(
        code="earlier_name",
        message=f"atrasts pēc agrākā nosaukuma; pašreizējā adrese: {current}",
    )


def historical_address() -> Note:
    return Note(code="historical_address", message="vēsturiska adrese")


def current_address(current: str) -> Note:
    return Note(code="current_address", message=f"pašreizējā adrese: {current}")


def current_unknown() -> Note:
    return Note(code="current_unknown", message="pašreizējā adrese nav zināma")


def no_objects_at_address() -> Note:
    return Note(
        code="no_cadastre_objects",
        message="adresei kadastra datos nav piesaistītu zemes vienību vai būvju",
    )
