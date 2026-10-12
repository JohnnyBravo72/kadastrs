import type { RunSummary } from "./api";

/** The run's object modules (chips, cards, overview columns); applicant modules
 *  (9, 17) have their own section (Phase 8a). */
export function objectModules(run: RunSummary): string[] {
  return run.modules.filter((m) => (run.module_subjects?.[m] ?? "object") === "object");
}
