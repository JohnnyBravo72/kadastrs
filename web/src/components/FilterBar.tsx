import { useEffect, useState } from "react";
import { api, type RegistrySource, type RunSummary, type VersionChange } from "../api";

const sameSet = (a: Set<string>, b: Set<string>) => a.size === b.size && [...a].every((x) => b.has(x));

/** Source chips (PLAN.md §8.2 step 2). Toggling marks "Atjaunot" as pending;
 *  Atjaunot makes a NEW run with the same targets, the run's pinned data
 *  versions and the new source set (the open run is not changed).
 *  "Pārbaudīt ar jaunākajiem datiem" makes a new run on the live versions. */
export function FilterBar({ run, onNewRun }: { run: RunSummary; onNewRun: (id: number) => void }) {
  const [sources, setSources] = useState<RegistrySource[] | null>(null);
  const applied = new Set(run.sources);
  const [chosen, setChosen] = useState<Set<string>>(applied);
  const [busy, setBusy] = useState<"sources" | "latest" | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.sources().then(setSources, () => setSources([]));
  }, []);
  useEffect(() => {
    setChosen(new Set(run.sources));
    setError(null);
  }, [run.id, run.sources]);

  const selectable = (sources ?? []).filter((s) => s.selectable);
  const appliedSel = new Set(selectable.filter((s) => applied.has(s.id)).map((s) => s.id));
  const chosenSel = new Set(selectable.filter((s) => chosen.has(s.id)).map((s) => s.id));
  const pending = sources !== null && !sameSet(appliedSel, chosenSel);

  const toggle = (id: string) => {
    const next = new Set(chosen);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setChosen(next);
  };

  const go = async (kind: "sources" | "latest") => {
    setBusy(kind);
    setError(null);
    try {
      // the base data the run used stays; only the selectable sources change
      const base = run.sources.filter((s) => !selectable.some((x) => x.id === s));
      const list = kind === "sources" ? [...base, ...chosenSel] : null;
      const r = await api.rerun(run.id, kind, list);
      onNewRun(r.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="filter-bar" data-testid="filter-bar">
      <div className="chips" role="group" aria-label="Avoti">
        <span className="label">Avoti:</span>
        {selectable.map((s) => {
          const on = chosen.has(s.id);
          const changed = on !== applied.has(s.id);
          return (
            <button
              key={s.id}
              className={`src-chip ${on ? "on" : "off"} ${changed ? "changed" : ""}`}
              aria-pressed={on}
              onClick={() => toggle(s.id)}
              title={s.modules.map((m) => `${m.no}. ${m.name}`).join(", ")}
              data-source={s.id}
            >
              {on ? "✓ " : ""}
              {s.name}
            </button>
          );
        })}
      </div>
      <div className="actions">
        <button className="btn primary" disabled={!pending || busy !== null || chosenSel.size === 0} onClick={() => void go("sources")}>
          {busy === "sources" ? <span className="spinner" /> : null} Atjaunot
        </button>
        <button className="btn" disabled={busy !== null} onClick={() => void go("latest")} title="Jauna pārbaude ar jaunākajām importētajām datu versijām">
          {busy === "latest" ? <span className="spinner" /> : null} Pārbaudīt ar jaunākajiem datiem
        </button>
      </div>
      {pending && (
        <div className="pending-banner" role="status" data-testid="pending">
          Filtru izmaiņas nav pielietotas. Nospiediet „Atjaunot”: tiks izveidota jauna pārbaude ar tām pašām datu versijām; šī pārbaude
          paliek nemainīta.
          <button className="btn small" onClick={() => setChosen(new Set(run.sources))}>
            Atcelt izmaiņas
          </button>
        </div>
      )}
      {error && <p className="error">{error}</p>}
    </div>
  );
}

/** On a run made from another: where it came from and, for "latest", which
 *  sources changed version. */
export function ParentNote({ run, open }: { run: RunSummary; open: (id: number) => void }) {
  const [changes, setChanges] = useState<VersionChange[] | null>(null);
  useEffect(() => {
    if (run.rerun_kind === "latest") api.changes(run.id).then(setChanges, () => setChanges(null));
    else setChanges(null);
  }, [run.id, run.rerun_kind]);
  if (!run.parent_run_id) return null;
  const parent = (
    <button className="linklike" onClick={() => open(run.parent_run_id!)}>
      nr. {run.parent_run_id}
    </button>
  );
  if (run.rerun_kind === "sources")
    return (
      <p className="info-banner" data-testid="parent-note">
        Atjaunots no pārbaudes {parent}: tās pašas datu versijas, mainīta avotu izvēle.
      </p>
    );
  return (
    <div className="info-banner" data-testid="parent-note">
      Pārbaudīts ar jaunākajiem datiem (no pārbaudes {parent}).{" "}
      {changes === null ? null : changes.length === 0 ? (
        "Datu versijas nav mainījušās."
      ) : (
        <>
          Mainītas versijas:
          <ul>
            {changes.map((c) => (
              <li key={c.id}>
                {c.name ?? c.id}: {c.old_date ?? "nebija"} → {c.new_date ?? "nav"}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
