import type { TargetLine } from "../api";
import { TYPE_LV } from "../format";
import { worst } from "../risk";
import { RiskPill, StatusCell } from "./RiskPill";

export function targetWorst(t: TargetLine) {
  return worst(Object.values(t.modules).filter((m) => m.summary_status !== "not_applicable").map((m) => m.risk));
}

/** One row per object, one column per module (status + risk), overall risk
 *  (same as the Excel "Kopsavilkums"). With `picked`, a checkbox per row for
 *  moving objects between project groups. */
export function OverviewTable({
  targets,
  modules,
  names,
  onOpen,
  picked,
  onPick,
  testId = "overview",
}: {
  targets: TargetLine[];
  modules: string[];
  names: Record<string, string>;
  onOpen: (targetNo: number) => void;
  picked?: Set<number>;
  onPick?: (targetNo: number) => void;
  testId?: string;
}) {
  return (
    <table className="overview" data-testid={testId}>
      <thead>
        <tr>
          {picked && <th aria-label="Atzīmēt" />}
          <th>Nr.</th>
          <th>Ievadīts</th>
          <th>Objekts</th>
          <th>Veids</th>
          {modules.map((m, i) => (
            <th key={m} title={names[m]}>
              {i + 1}. {names[m]}
            </th>
          ))}
          <th>Kopējais risks</th>
        </tr>
      </thead>
      <tbody>
        {targets.map((t) => (
          <tr key={t.target_no} className="obj" onClick={() => onOpen(t.target_no)} title="Atvērt objektu">
            {picked && (
              <td onClick={(e) => e.stopPropagation()}>
                <input
                  type="checkbox"
                  checked={picked.has(t.target_no)}
                  onChange={() => onPick?.(t.target_no)}
                  aria-label={`Atzīmēt ${t.designation}`}
                />
              </td>
            )}
            <td>{t.target_no + 1}</td>
            <td>{t.input}</td>
            <td className="mono">{t.designation}</td>
            <td>
              {TYPE_LV[t.type] ?? t.type}
              {t.label && <div className="hint">{t.label}</div>}
            </td>
            {modules.map((m) => (
              <td key={m}>{t.modules[m] ? <StatusCell bucket={t.modules[m].summary_status} risk={t.modules[m].risk} /> : "–"}</td>
            ))}
            <td>
              <RiskPill risk={targetWorst(t)} />
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
