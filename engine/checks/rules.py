"""Risk rules from config/rules.yaml (PLAN.md §6.4, CLAUDE.md rule 4).

This module only evaluates the declarative conditions written in the file; it
holds no risk knowledge of its own. Levels, defaults, the risk order and the
spatial thresholds all come from the file.
"""

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

from engine.checks.contract import STATUSES, CheckResult, Risk
from etl.settings import config_dir

CONDITION_KEYS = {"status", "reason", "match_type", "warning", "item"}


class Thresholds(BaseModel):
    inward_buffer_m: float
    min_overlap_m2: float
    min_overlap_share: float
    bis_nearby_m: float


class Rule(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    module: str
    level: Risk
    when: dict[str, Any]
    reason: str
    text_lv: str

    @field_validator("when")
    @classmethod
    def _known_conditions(cls, v: dict[str, Any]) -> dict[str, Any]:
        unknown = set(v) - CONDITION_KEYS
        if unknown:
            raise ValueError(
                f"unknown condition(s) {sorted(unknown)}; use {sorted(CONDITION_KEYS)}"
            )
        if "item" in v and not isinstance(v["item"], dict):
            raise ValueError("item: must be a mapping of field tests")
        return v


class RuleSet(BaseModel):
    version: str
    status: Literal["draft", "agreed"]
    thresholds: Thresholds
    risk_order: list[Risk]
    defaults: dict[str, Risk]
    rules: list[Rule]

    @model_validator(mode="after")
    def _complete(self) -> RuleSet:
        if sorted(self.risk_order) != sorted(Risk.__args__):  # type: ignore[attr-defined]
            raise ValueError(f"risk_order must list each of {Risk.__args__} once")  # type: ignore[attr-defined]
        if set(self.defaults) != set(STATUSES):
            raise ValueError(f"defaults must give a level for each status {STATUSES}")
        ids = [r.id for r in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("rule ids must be unique")
        return self

    # --- identity ------------------------------------------------------------------

    def as_json(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @property
    def sha256(self) -> str:
        text = json.dumps(self.as_json(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(text.encode()).hexdigest()

    # --- evaluation ----------------------------------------------------------------

    def rank(self, risk: str) -> int:
        """0 = worst."""
        return self.risk_order.index(risk)

    def worst(self, risks: list[str]) -> str | None:
        return min(risks, key=self.rank) if risks else None

    def evaluate(self, result: CheckResult) -> tuple[str, list[str]]:
        """(risk, fired rule ids) for one module result."""
        fired = [r for r in self.rules if r.module == result.module and _holds(r.when, result)]
        if not fired:
            return self.defaults[result.status], [f"default_{result.status}"]
        return self.worst([r.level for r in fired]), [r.id for r in fired]

    def apply(self, result: CheckResult) -> CheckResult:
        risk, ids = self.evaluate(result)
        return result.model_copy(update={"risk": risk, "rule_ids": ids})

    def modules(self) -> set[str]:
        return {r.module for r in self.rules}


def _one_of(value: Any, expected: Any) -> bool:
    return value in expected if isinstance(expected, list) else value == expected


def _item_matches(item: dict[str, Any], tests: dict[str, Any]) -> bool:
    for key, expected in tests.items():
        for suffix, op in (("_gte", lambda a, b: a >= b), ("_lt", lambda a, b: a < b)):
            if key.endswith(suffix):
                value = item.get(key[: -len(suffix)])
                if value is None or not op(value, expected):
                    return False
                break
        else:
            if not _one_of(item.get(key), expected):
                return False
    return True


def _holds(when: dict[str, Any], r: CheckResult) -> bool:
    if "status" in when and not _one_of(r.status, when["status"]):
        return False
    if "reason" in when and not _one_of(r.reason, when["reason"]):
        return False
    if "match_type" in when and not _one_of(r.match_type, when["match_type"]):
        return False
    if "warning" in when:
        codes = {w.code for w in r.warnings}
        wanted = when["warning"] if isinstance(when["warning"], list) else [when["warning"]]
        if not codes & set(wanted):
            return False
    return not ("item" in when and not any(_item_matches(i, when["item"]) for i in r.items))


def rules_path() -> Path:
    return config_dir() / "rules.yaml"


def load(path: Path | None = None) -> RuleSet:
    with open(path or rules_path(), encoding="utf-8") as f:
        return RuleSet.model_validate(yaml.safe_load(f))


def from_json(data: dict[str, Any]) -> RuleSet:
    """The rule set stored with a run (work.run.rule_set)."""
    return RuleSet.model_validate(data)
