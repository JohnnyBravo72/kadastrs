"""Check modules 1-6 (PLAN.md §6.1), in report order."""

from engine.checks.modules import (
    address_consistency,
    bis,
    cadastre_facts,
    encumbrances,
    flood,
    nature,
)
from engine.checks.modules.base import ModuleSpec

MODULES: list[ModuleSpec] = [
    cadastre_facts.SPEC,
    address_consistency.SPEC,
    nature.SPEC,
    flood.SPEC,
    bis.SPEC,
    encumbrances.SPEC,
]
BY_ID = {m.id: m for m in MODULES}
# Modules that run once per target (not per unit) and get no aggregate.
PER_TARGET = {"address_consistency"}
