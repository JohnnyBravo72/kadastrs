"""Module contract (PLAN.md §6.2): what every check returns and what a run takes in."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

Status = Literal["found", "clear", "not_covered", "no_data", "source_unavailable", "error"]
Risk = Literal["high", "medium", "low", "none", "unknown"]
UnitType = Literal["property", "parcel", "building", "parcel_part", "premise_group"]
STATUSES: tuple[str, ...] = Status.__args__  # type: ignore[attr-defined]


class Warning_(BaseModel):
    """A warning or notice with a stable code. Extra fields (code, date, …) as needed."""

    model_config = {"extra": "allow"}

    code: str
    message: str


class SourceRef(BaseModel):
    id: str
    name: str
    dataset_date: str  # version_date (from the source, rule E7)
    dataset_version_id: int
    datagov_url: str | None = None


class Display(BaseModel):
    kind: Literal["kv", "table", "badges", "text"]
    columns: list[str] = Field(default_factory=list)


class Subject(BaseModel):
    kind: Literal["object"] = "object"
    type: str  # unit type
    id: str  # designation


class CheckResult(BaseModel):
    module: str
    module_no: int
    module_version: str
    subject: Subject
    scope: Literal["target", "unit"] = "target"
    status: Status
    reason: str | None = None
    risk: Risk = "unknown"
    rule_ids: list[str] = Field(default_factory=list)
    items: list[dict[str, Any]] = Field(default_factory=list)
    match_type: str | None = None
    warnings: list[Warning_] = Field(default_factory=list)
    source: SourceRef | None = None  # the module's primary source
    sources: list[SourceRef] = Field(default_factory=list)  # every version read
    dataset_version_ids: list[int] = Field(default_factory=list)
    computed_at: datetime | None = None
    display: Display

    def comparable(self) -> dict[str, Any]:
        """Everything except the time stamp: equal for the same inputs and versions."""
        return self.model_dump(mode="json", exclude={"computed_at"})


class TargetIn(BaseModel):
    """One resolved object to check (from POST /api/resolve, chosen by the user)."""

    type: UnitType
    designation: str = Field(pattern=r"^[0-9]{11}([0-9]{3,4}|[0-9]{6})?$")
    input: str | None = None  # the value as typed
    given_address: str | None = Field(default=None, pattern=r"^[0-9]{9}$")  # VARIS code
    project_no: str | None = None
    warnings: list[Warning_] = Field(default_factory=list)  # carried over from resolution
