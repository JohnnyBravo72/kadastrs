"""Result shapes of input resolution (PLAN.md §5). Shared by the engine and the API."""

from typing import Literal

from pydantic import BaseModel, Field

ObjectType = Literal["property", "parcel", "building", "parcel_part", "premise_group"]
MatchType = Literal["exact", "corrected", "fuzzy", "earlier_name", "historical"]
Status = Literal[
    "resolved",  # one object; use it
    "ambiguous",  # several candidates (or one that needs confirmation); the user picks
    "not_found",  # well-formed, nothing matches
    "unresolved",  # found, but cannot be taken automatically (deleted address, no successor)
    "outside_pilot",  # names a place, territory or map object outside the pilot cities
    "invalid",  # not a designation and not an address
    "empty",
]


class Note(BaseModel):
    """A warning or notice. `code` is stable; `message` is the Latvian text for reports."""

    code: str
    message: str


class Correction(BaseModel):
    code: str
    original: str
    corrected: str
    message: str


class CadastreObject(BaseModel):
    type: ObjectType
    designation: str
    label: str  # type label, e.g. "Zemes vienība"
    description: str | None = None  # property name, address or building use
    property_numbers: list[str] = Field(default_factory=list)
    parcel_codes: list[str] = Field(default_factory=list)  # buildings and parcel parts
    building_code: str | None = None  # premise groups
    varis_code: str | None = None
    in_register: bool = True  # in the cadastre text data
    has_geometry: bool | None = None  # None for properties and premise groups
    not_exist: bool = False
    prereg: bool = False
    warnings: list[Note] = Field(default_factory=list)


class AddressRef(BaseModel):
    varis_code: str
    full_text: str
    status: Literal["EKS", "DEL"]
    city: str | None = None


class Match(BaseModel):
    type: Literal["property", "parcel", "building", "parcel_part", "premise_group", "address"]
    designation: str  # cadastre designation or VARIS code
    label: str
    description: str | None = None
    match_type: MatchType
    score: float | None = None  # address matching only, 0..1
    object: CadastreObject | None = None
    address: AddressRef | None = None
    objects: list[CadastreObject] = Field(default_factory=list)  # cadastre objects at an address
    warnings: list[Note] = Field(default_factory=list)


class ResolvedRow(BaseModel):
    index: int
    input: str
    kind: Literal["cadastre", "address", "address_code", "empty", "invalid"]
    normalized: str | None = None
    status: Status
    type: str | None = None  # type of the resolved object when status = resolved
    matches: list[Match] = Field(default_factory=list)
    corrections: list[Correction] = Field(default_factory=list)
    warnings: list[Note] = Field(default_factory=list)
    reason: str | None = None
    duplicate_of: int | None = None
