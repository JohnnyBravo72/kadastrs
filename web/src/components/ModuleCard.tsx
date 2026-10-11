import type { DatasetVersion, ModuleResult } from "../api";
import { cellStyle, isRisk, RISK, STATUS_LV } from "../risk";
import { RiskPill, StatusCell } from "./RiskPill";

const MAX_ITEMS = 12;

function warningLines(results: ModuleResult[]): string[] {
  const lines: string[] = [];
  let frozen = 0;
  for (const r of results)
    for (const w of r.warnings) {
      if (w.code === "frozen_only") {
        frozen++;
        continue;
      }
      if (!lines.includes(w.message)) lines.push(w.message);
    }
  if (frozen) lines.push(`${frozen} apgrūtinājum(i) tikai 2025-01-31 sarakstā – pārbaudīt manuāli`);
  return lines;
}

/** One module: status, risk, the fired rules' text, items, warnings and the source.
 *  Findings and data gaps open; clean (and not applicable) results collapsed. */
export function ModuleCard({
  result,
  units,
  versions,
}: {
  result: ModuleResult;
  units: ModuleResult[];
  versions: DatasetVersion[];
}) {
  const bucket = result.summary_status;
  const style = cellStyle(bucket, result.risk);
  const open = !["clear", "not_applicable"].includes(bucket);
  const src = result.source;
  const version = versions.find((v) => v.id === src?.id);
  const items = result.items_text;
  const warnings = warningLines(units.length ? units : [result]);
  const rules = bucket === "not_applicable" ? [] : result.rules;
  return (
    <details className="card" id={`card-${result.module}`} open={open} style={{ borderLeftColor: style.color }}>
      <summary>
        {bucket === "not_applicable" ? (
          <span className="risk-pill" style={{ background: style.color, color: style.text }}>
            – nav piemērojams
          </span>
        ) : (
          <RiskPill risk={result.risk} />
        )}
        <span className="t">
          {result.module_no}. {result.module_name}
        </span>
        <span className="st">{STATUS_LV[bucket]}</span>
      </summary>
      <div className="content">
        {rules.length > 0 &&
          rules.map((r) => (
            <div className="rule" key={r.id}>
              {isRisk(r.level) && (
                <span style={{ color: RISK[r.level].color, fontWeight: 700 }} aria-hidden>
                  {RISK[r.level].icon}{" "}
                </span>
              )}
              {r.text_lv}
            </div>
          ))}
        {result.reason && <p className="reason">{result.reason}</p>}
        {items.length > 0 && (
          <ul className="items">
            {items.slice(0, MAX_ITEMS).map((t, i) => (
              <li key={i}>{t}</li>
            ))}
            {items.length > MAX_ITEMS && <li className="hint">… vēl {items.length - MAX_ITEMS} (sk. Excel „Detaļas”)</li>}
          </ul>
        )}
        {warnings.length > 0 && (
          <ul className="warn">
            {warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        )}
        {units.length > 0 && (
          <details className="units">
            <summary>Pa vienībām ({units.length})</summary>
            <table>
              <tbody>
                {units.map((u) => (
                  <tr key={u.subject.id}>
                    <td className="mono">{u.subject.id}</td>
                    <td>
                      <StatusCell bucket={u.summary_status} risk={u.risk} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        )}
        {src && (
          <div className="src">
            Avots: {src.name}, dati no {src.dataset_date}
            {version?.freshness ? ` (${version.freshness.label_lv})` : ""}
            {src.datagov_url && (
              <>
                {" · "}
                <a href={src.datagov_url} target="_blank" rel="noreferrer">
                  data.gov.lv
                </a>
              </>
            )}
          </div>
        )}
      </div>
    </details>
  );
}
