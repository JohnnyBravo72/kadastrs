import type { DatasetVersion, ModuleResult, SourceLink } from "../api";
import { cellStyle, isRisk, RISK, riskText, STATUS_LV } from "../risk";
import { StatusCell } from "./RiskPill";
import { SourceLinks } from "./SourceLinks";

const MAX_ITEMS = 12;
const TECHNICAL_LABEL = "Tehniskie apgrūtinājumi (kadastrālās vērtības aprēķinam)";

interface Line {
  text: string;
  links: SourceLink[];
}

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

/** Item lines with their source links; technical records (rules not_findings) apart. */
function lines(results: ModuleResult[]): { findings: Line[]; technical: Line[] } {
  const findings: Line[] = [];
  const technical: Line[] = [];
  for (const r of results)
    r.items.forEach((item, i) => {
      const line = { text: r.items_text[i] ?? "", links: r.item_links?.[i] ?? [] };
      (item.technical ? technical : findings).push(line);
    });
  return { findings, technical };
}

export function isOpenCard(result: ModuleResult) {
  return !["clear", "not_applicable"].includes(result.summary_status);
}

/** One module: status, risk, the fired rules' text, items with "Skatīt avotā",
 *  warnings and the source. Clean and not-applicable results: one line. */
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
  const open = isOpenCard(result);
  const src = result.source;
  const version = versions.find((v) => v.id === src?.id);
  const { findings, technical } = lines(units.length ? units : [result]);
  const warnings = warningLines(units.length ? units : [result]);
  const rules = bucket === "not_applicable" ? [] : result.rules;
  const status = STATUS_LV[bucket];
  return (
    <details
      className={`card ${open ? "" : "compact"}`}
      id={`card-${result.module}`}
      open={open}
      style={{ borderLeftColor: style.color }}
    >
      <summary>
        <span className="ico" style={{ background: style.color, color: style.text }} aria-hidden>
          {style.icon}
        </span>
        <span className="t">
          {result.module_no}. {result.module_name}
        </span>
        <span className="st">
          {status}
          {bucket !== "not_applicable" && isRisk(result.risk) ? ` · ${riskText(result.risk)}` : ""}
          {!open && technical.length > 0 ? ` · ${technical.length} tehniskie` : ""}
        </span>
      </summary>
      <div className="content">
        {rules.map((r) => (
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
        {findings.length > 0 && (
          <ul className="items">
            {findings.slice(0, MAX_ITEMS).map((l, i) => (
              <li key={i}>
                {l.text} <SourceLinks links={l.links} compact />
              </li>
            ))}
            {findings.length > MAX_ITEMS && (
              <li className="hint">… vēl {findings.length - MAX_ITEMS} (sk. Excel „Detaļas”)</li>
            )}
          </ul>
        )}
        {technical.length > 0 && (
          <details className="units">
            <summary>
              {TECHNICAL_LABEL}: {technical.length} – nav atradnes
            </summary>
            <ul className="items">
              {technical.map((l, i) => (
                <li key={i}>
                  {l.text} <SourceLinks links={l.links} compact />
                </li>
              ))}
            </ul>
          </details>
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
