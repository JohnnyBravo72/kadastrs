import { useEffect, useState } from "react";
import { api, type JournalRun } from "../api";
import { RiskPill } from "../components/RiskPill";

const ORIGIN_LV: Record<string, string> = { batch: "saraksts", api: "API", cli: "CLI", compare: "salīdzinājums", test: "tests" };
const RERUN_LV: Record<string, string> = { sources: "Atjaunot (avoti)", latest: "jaunākie dati" };

/** Žurnāls (PLAN.md §8.2): earlier runs, newest first; a click reopens one.
 *  Every run on this server is listed until sign-in exists (Phase 10). */
export function JournalPage({ current, open }: { current: number | null; open: (run: number) => void }) {
  const [runs, setRuns] = useState<JournalRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.journal(200).then(setRuns, (e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  if (error) return <p className="center-msg error">{error}</p>;
  if (!runs) return <p className="center-msg"><span className="spinner" /> Ielādē žurnālu…</p>;
  return (
    <main className="page wide">
      <h1 className="page-title">Žurnāls</h1>
      <p className="lead">Iepriekšējās pārbaudes. Saglabātie rezultāti netiek mainīti; atkārtota pārbaude izveido jaunu ierakstu.</p>
      {runs.length === 0 ? (
        <p className="notice">Vēl nav nevienas pārbaudes.</p>
      ) : (
        <table className="overview" data-testid="journal">
          <thead>
            <tr>
              <th>Nr.</th>
              <th>Datums</th>
              <th>Objekti</th>
              <th>Projekti</th>
              <th>Kopējais risks</th>
              <th>Moduļi</th>
              <th>Izcelsme</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr
                key={r.id}
                className={`obj ${r.id === current ? "current" : ""}`}
                onClick={() => open(r.id)}
                onKeyDown={(e) => e.key === "Enter" && open(r.id)}
                tabIndex={0}
                data-run={r.id}
                title="Atvērt pārbaudi"
              >
                <td className="mono">{r.id}</td>
                <td>{new Date(r.created_at).toLocaleString("lv-LV")}</td>
                <td>{r.targets}</td>
                <td>{r.projects.length ? r.projects.join(", ") : <span className="hint">bez projekta</span>}</td>
                <td>{r.risk ? <RiskPill risk={r.risk} /> : "–"}</td>
                <td>{r.modules.length}</td>
                <td>
                  {ORIGIN_LV[r.origin] ?? r.origin}
                  {r.parent_run_id && (
                    <div className="hint">
                      no nr. {r.parent_run_id}: {RERUN_LV[r.rerun_kind ?? ""] ?? r.rerun_kind}
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
