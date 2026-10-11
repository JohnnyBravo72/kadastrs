import { useEffect, useState } from "react";
import { api, type RunSummary } from "../api";
import type { UrlState } from "../url";

/** Placeholder until the results view (Phase 6 step 3). */
export function ResultsPage({ state }: { state: UrlState; navigate: (s: UrlState, replace?: boolean) => void }) {
  const [run, setRun] = useState<RunSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (state.run !== null) api.run(state.run).then(setRun, (e) => setError(String(e)));
  }, [state.run]);
  if (error) return <p className="center-msg error">{error}</p>;
  if (!run) return <p className="center-msg">Ielādē…</p>;
  return (
    <main className="results">
      <p>
        Pārbaude {run.id}: {run.targets} objekti.{" "}
        <a className="btn" href={api.reportUrl(run.id)}>
          Lejupielādēt Excel
        </a>
      </p>
    </main>
  );
}
