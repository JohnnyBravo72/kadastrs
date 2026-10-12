import { useEffect, useState } from "react";
import { api, type RegistrySource, type RunSummary } from "../api";

/** Avoti (PLAN.md §8.2): every source with its data date, freshness, coverage
 *  and links; with a run open, also the version that run read. */
export function SourcesPage({ run }: { run: number | null }) {
  const [sources, setSources] = useState<RegistrySource[] | null>(null);
  const [summary, setSummary] = useState<RunSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.sources().then(setSources, (e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);
  useEffect(() => {
    if (run === null) return setSummary(null);
    api.run(run).then(setSummary, () => setSummary(null));
  }, [run]);

  if (error) return <p className="center-msg error">{error}</p>;
  if (!sources) return <p className="center-msg"><span className="spinner" /> Ielādē avotus…</p>;
  const pinned = new Map((summary?.dataset_versions ?? []).map((v) => [v.id, v]));
  const used = new Set(summary?.sources ?? []);
  return (
    <main className="page wide">
      <h1 className="page-title">Avoti</h1>
      <p className="lead">
        Visi dati ir no data.gov.lv. Svaigums: vai mums ir jaunākā avota publicētā versija.
        {summary && ` Kolonna „Pārbaudē nr. ${summary.id}” rāda versiju, ko lasīja šī pārbaude.`}
      </p>
      <table className="overview" data-testid="sources">
        <thead>
          <tr>
            <th>Avots</th>
            <th>Grupa</th>
            <th>Datu datums</th>
            <th>Svaigums</th>
            {summary && <th>Pārbaudē nr. {summary.id}</th>}
            <th>Pārklājums</th>
            <th>Saites</th>
          </tr>
        </thead>
        <tbody>
          {sources.map((s) => {
            const p = pinned.get(s.id);
            return (
              <tr key={s.id} data-source={s.id}>
                <td>
                  <b>{s.name}</b>
                  <div className="hint">
                    {s.owner}
                    {s.modules.length ? ` · ${s.modules.map((m) => `${m.no}. ${m.name}`).join(", ")}` : ""}
                  </div>
                </td>
                <td>{s.group}</td>
                <td>{s.live_version?.dataset_date ?? <span className="hint">nav importēts</span>}</td>
                <td>
                  {s.freshness ? (
                    <span className={`fresh ${s.freshness.warn ? "warn" : "ok"}`} title={s.freshness.text_lv}>
                      {s.freshness.label_lv}
                    </span>
                  ) : (
                    "–"
                  )}
                  {s.freshness && <div className="hint">{s.freshness.text_lv}</div>}
                </td>
                {summary && (
                  <td>
                    {p ? p.dataset_date : "–"}
                    {s.selectable && !used.has(s.id) && <div className="hint">nav atlasīts</div>}
                  </td>
                )}
                <td>
                  {s.coverage}
                  {s.partial_coverage && <div className="partial">daļējs pārklājums</div>}
                </td>
                <td>
                  {s.datagov_urls.map((u) => (
                    <div key={u}>
                      <a href={u} target="_blank" rel="noreferrer">
                        data.gov.lv ↗
                      </a>
                    </div>
                  ))}
                  {s.licence && <div className="hint">{s.licence}</div>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </main>
  );
}
