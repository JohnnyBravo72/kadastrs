"""Check modules (PLAN.md §6.1), in report order: object modules 1–6, 8 and 14,
applicant modules 9 and 17 (Phase 8a, run once per applicant)."""

from engine.checks.modules import (
    address_consistency,
    applicant,
    bis,
    cadastre_facts,
    companies_at_address,
    encumbrances,
    flood,
    nature,
    zoning,
)
from engine.checks.modules.base import ModuleSpec

MODULES: list[ModuleSpec] = [
    cadastre_facts.SPEC,
    address_consistency.SPEC,
    nature.SPEC,
    flood.SPEC,
    bis.SPEC,
    encumbrances.SPEC,
    zoning.SPEC,
    companies_at_address.SPEC,
    applicant.COMPANY,
    applicant.SANCTIONS,
]
BY_ID = {m.id: m for m in MODULES}
# Modules whose subject is the applicant (scope "applicant" in work.check_result).
APPLICANT = {m.id for m in MODULES if m.subject == "applicant"}
# Modules that run once per target (not per unit) and get no aggregate.
PER_TARGET = {"address_consistency"}
