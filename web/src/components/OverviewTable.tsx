import type { TargetLine } from "../api";
import { TYPE_LV } from "../format";
import { worst } from "../risk";
import { RiskPill, StatusCell } from "./RiskPill";

export function targetWorst(t: TargetLine) {
  return worst(Object.values(t.modules).filter((m) => m.summary_status !== "not_applicable").map((m) => m.risk));
}

/** Projects in input order, objects grouped under them ("bez projekta" last). */
export function groupByProject(targets: TargetLine[]): [string, TargetLine[]][] {
  const groups = new Map<string, TargetLine[]>();
  for (const t of targets) {
    const key = t.project_no ?? "";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key)!.push(t);
  }
  const keys = [...groups.keys()].sort((a, b) => (a === "" ? 1 : b === "" ? -1 : 0));
  return keys.map((k) => [k, groups.get(k)!]);
}

/** One row per object, one column per module (status + risk), overall risk. */
export function OverviewTable({
  targets,
  modules,
  names,
  onOpen,
}: {
  targets: TargetLine[];
  modules: string[];
  names: Record<string, string>;
  onOpen: (targetNo: number) => void;
}) {
  const grouped = groupByProject(targets);
  const showGroups = grouped.length > 1 || grouped[0]?.[0] !== "";
  return (
    <table className="overview" data-testid="overview">
      <thead>
        <tr>
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
        {grouped.map(([project, rows]) => (
          <GroupRows key={project || "-"} project={project} rows={rows} modules={modules} onOpen={onOpen} showGroup={showGroups} />
        ))}
      </tbody>
    </table>
  );
}

function GroupRows({
  project,
  rows,
  modules,
  onOpen,
  showGroup,
}: {
  project: string;
  rows: TargetLine[];
  modules: string[];
  onOpen: (n: number) => void;
  showGroup: boolean;
}) {
  return (
    <>
      {showGroup && (
        <tr className="group">
          <td colSpan={modules.length + 5}>
            {project ? `Projekts ${project}` : "Bez projekta numura"} · {rows.length}{" "}
            {rows.length === 1 ? "objekts" : "objekti"}
          </td>
        </tr>
      )}
      {rows.map((t) => (
        <tr key={t.target_no} className="obj" onClick={() => onOpen(t.target_no)} title="Atvērt objektu">
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
    </>
  );
}
