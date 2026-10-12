import { useState } from "react";
import { api, type Grouping, type RunSummary, type TargetLine } from "../api";
import { addGroup, deleteGroup, grouped, moveTargets, nameTaken, NONE_ID, renameGroup, type GroupState } from "../groups";
import { worst } from "../risk";
import { OverviewTable, targetWorst } from "./OverviewTable";
import { RiskPill } from "./RiskPill";

/** Projects of a run (PLAN.md §8.2 steps 3 and 7): objects grouped by project,
 *  an overview table per group; groups can be created, renamed and deleted and
 *  objects moved. Every change is stored as a new grouping row; check results
 *  are never touched. The Excel report follows the current grouping. */
export function ProjectsPanel({
  run,
  targets,
  grouping,
  setGrouping,
  names,
  open,
}: {
  run: RunSummary;
  targets: TargetLine[];
  grouping: Grouping;
  setGrouping: (g: Grouping) => void;
  names: Record<string, string>;
  open: (t: number) => void;
}) {
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [newName, setNewName] = useState("");
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null);
  const [moveTo, setMoveTo] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async (next: GroupState) => {
    setBusy(true);
    setError(null);
    try {
      setGrouping(await api.saveGroups(run.id, next));
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const pick = (t: number) => {
    const next = new Set(picked);
    if (next.has(t)) next.delete(t);
    else next.add(t);
    setPicked(next);
  };

  const create = async () => {
    const name = newName.trim();
    if (!name || nameTaken(grouping, name)) return setError(name ? `Projekts „${name}” jau ir.` : null);
    if (await save(addGroup(grouping, name))) setNewName("");
  };

  const groups = grouped(grouping, targets);
  return (
    <section className="projects" data-testid="projects">
      <div className="projects-bar">
        <h2>Projekti</h2>
        <span className="hint">
          {grouping.id === null
            ? "pēc ievadītajiem projekta numuriem"
            : `grupējums nr. ${grouping.id}, saglabāts ${new Date(grouping.created_at!).toLocaleString("lv-LV")}`}
        </span>
        <span className="spacer" />
        <input
          value={newName}
          onChange={(e) => setNewName(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && void create()}
          placeholder="Jauna projekta Nr."
          aria-label="Jauna projekta Nr."
          maxLength={100}
        />
        <button className="btn" onClick={() => void create()} disabled={busy || !newName.trim()}>
          + Izveidot projektu
        </button>
        <select value={moveTo} onChange={(e) => setMoveTo(e.target.value)} aria-label="Pārvietot uz projektu">
          <option value="">Pārvietot atzīmētos uz…</option>
          {grouping.groups.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name}
            </option>
          ))}
        </select>
        <button
          className="btn"
          disabled={busy || picked.size === 0 || !moveTo}
          onClick={async () => {
            if (await save(moveTargets(grouping, [...picked], moveTo))) setPicked(new Set());
          }}
        >
          Pārvietot ({picked.size})
        </button>
      </div>
      {error && <p className="error">{error}</p>}
      {groups.map((g) => (
        <div className="project" key={g.id} data-group={g.name}>
          <div className="project-head">
            {renaming?.id === g.id ? (
              <>
                <input
                  value={renaming.name}
                  onChange={(e) => setRenaming({ ...renaming, name: e.target.value })}
                  aria-label="Projekta nosaukums"
                  autoFocus
                  maxLength={100}
                />
                <button
                  className="btn small primary"
                  disabled={busy || !renaming.name.trim() || nameTaken(grouping, renaming.name, g.id)}
                  onClick={async () => {
                    if (await save(renameGroup(grouping, g.id, renaming.name))) setRenaming(null);
                  }}
                >
                  Saglabāt
                </button>
                <button className="btn small" onClick={() => setRenaming(null)}>
                  Atcelt
                </button>
              </>
            ) : (
              <>
                <h3>{g.id === NONE_ID ? "Bez projekta" : `Projekts ${g.name}`}</h3>
                <span className="hint">
                  {g.targets.length} {g.targets.length === 1 ? "objekts" : "objekti"}
                </span>
                {g.targets.length > 0 && <RiskPill risk={worst(g.targets.map(targetWorst).filter((r) => r !== null))} prefix="risks:" />}
                {g.id !== NONE_ID && (
                  <>
                    <button className="btn small" onClick={() => setRenaming({ id: g.id, name: g.name })} disabled={busy}>
                      Pārdēvēt
                    </button>
                    <button className="btn small" onClick={() => void save(deleteGroup(grouping, g.id))} disabled={busy} title="Objekti pāries uz „Bez projekta”">
                      Dzēst
                    </button>
                  </>
                )}
              </>
            )}
          </div>
          {g.targets.length > 0 ? (
            <OverviewTable
              targets={g.targets}
              modules={run.modules}
              names={names}
              onOpen={open}
              picked={picked}
              onPick={pick}
              testId={`overview-${g.id}`}
            />
          ) : (
            <p className="hint empty-group">Nav objektu. Atzīmējiet objektus un pārvietojiet tos šeit.</p>
          )}
        </div>
      ))}
    </section>
  );
}
