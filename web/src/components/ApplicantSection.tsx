import type { Applicant, RunSummary } from "../api";
import { cellStyle, riskText, STATUS_LV } from "../risk";
import { isOpenCard, ModuleCard } from "./ModuleCard";
import { worst } from "../risk";
import { RiskPill } from "./RiskPill";
import { SourceLinks } from "./SourceLinks";

const SHORT: Record<string, string> = { applicant_company: "Pieteicējs (UR)", sanctions: "Sankcijas" };

/** The applicant section (Phase 8a): modules 9 "Pieteicējs (UR)" and 17
 *  "Sankcijas", checked once per applicant reg. no., with "Skatīt UR" and
 *  "Skatīt sankciju sarakstā". `compact`: one line per applicant (all objects). */
export function ApplicantSection({
  run,
  applicants,
  compact,
}: {
  run: RunSummary;
  applicants: Applicant[];
  compact?: boolean;
}) {
  if (applicants.length === 0) return null;
  return (
    <section className="applicants" data-testid="applicants" aria-label="Pieteicējs">
      <h2>{applicants.length === 1 ? "Pieteicējs" : `Pieteicēji (${applicants.length})`}</h2>
      {applicants.map((a) => {
        const risk = worst(a.results.map((r) => r.risk));
        return (
          <div className="applicant" key={a.reg_no} data-reg={a.reg_no}>
            <div className="applicant-head">
              <span className="mono big">{a.reg_no}</span>
              <span className="name">{a.name ?? <span className="hint">nosaukums nav saglabāts</span>}</span>
              <RiskPill risk={risk} prefix="risks:" />
              <span className="chips">
                {a.results.map((r) => {
                  const st = cellStyle(r.summary_status, r.risk);
                  return (
                    <span key={r.module} className="mini-chip" data-module={r.module} title={r.module_name}>
                      <span className="ico" style={{ background: st.color, color: st.text }} aria-hidden>
                        {st.icon}
                      </span>
                      {SHORT[r.module] ?? r.module_name}: {STATUS_LV[r.summary_status]}
                      {r.summary_status !== "not_applicable" ? ` · ${riskText(r.risk)}` : ""}
                    </span>
                  );
                })}
              </span>
              <SourceLinks links={a.links} />
            </div>
            {!compact && (
              <div className="cards">
                {a.results
                  .slice()
                  .sort((x, y) => Number(isOpenCard(y)) - Number(isOpenCard(x)))
                  .map((r) => (
                    <ModuleCard key={r.module} result={r} units={[]} versions={run.dataset_versions} />
                  ))}
              </div>
            )}
            {compact && a.target_nos.length > 0 && (
              <div className="hint">objekti: {a.target_nos.map((n) => n + 1).join(", ")}</div>
            )}
          </div>
        );
      })}
    </section>
  );
}
