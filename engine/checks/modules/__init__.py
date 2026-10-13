"""Check modules (PLAN.md §6.1), in report order: object modules 1–7, 12, 14, 18;
applicant modules 9–13 and 17 (Phase 8a/8b, run once per applicant)."""

from engine.checks.modules import (
    address_consistency,
    applicant,
    bis,
    cadastre_facts,
    companies_at_address,
    encumbrances,
    flood,
    nature,
    phase8b,
)
from engine.checks.modules.base import ModuleSpec

MODULES: list[ModuleSpec] = [
    cadastre_facts.SPEC,
    address_consistency.SPEC,
    nature.SPEC,
    flood.SPEC,
    bis.SPEC,
    encumbrances.SPEC,
    phase8b.OWNERSHIP,
    phase8b.EU_OBJECT,
    companies_at_address.SPEC,
    phase8b.FID_FROZEN,
    applicant.COMPANY,
    phase8b.VID,
    phase8b.DEMINIMIS,
    phase8b.EU_APPLICANT,
    phase8b.PROCUREMENT,
    applicant.SANCTIONS,
]
BY_ID = {m.id: m for m in MODULES}
# Modules whose subject is the applicant (scope "applicant" in work.check_result).
APPLICANT = {m.id for m in MODULES if m.subject == "applicant"}
# Modules that run once per target (not per unit) and get no aggregate.
PER_TARGET = {"address_consistency"}
