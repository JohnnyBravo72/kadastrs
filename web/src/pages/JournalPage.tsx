import { useEffect, useState } from "react";
import { api, type JournalPage as Page, type JournalQuery } from "../api";
import { RiskPill } from "../components/RiskPill";

const ORIGIN_LV: Record<string, string> = {
  batch: "saraksts",
  api: "API",
  cli: "CLI",
  compare: "salīdzinājums",
  test: "tests",
  e2e: "e2e tests",
};
const MAX_PROJECTS = 6;
const PAGE = 50;
const RERUN_LV: Record<string, string> = { sources: "Atjaunot (avoti)", latest: "jaunākie dati" };
const START: JournalQuery = { limit: PAGE, offset: 0, tests: false, project: "", date_from: "", date_to: "" };

/** Žurnāls (PLAN.md §8.2): earlier runs, newest first, 50 per page; a click
 *  reopens one. Filters: project number, date range; runs of test servers
 *  (origin test / e2e) only with "Rādīt testa pārbaudes". Every run on this
 *  server is listed until sign-in exists (Phase 10). */
export function JournalPage({ current, open }: { current: number | null; open: (run: number) => void }) {
  const [query, setQuery] = useState<JournalQuery>(START);
  const [project, setProject] = useState(""); // typed; applied after a pause
  const [page, setPage] = useState<Page | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const t = window.setTimeout(() => setQuery((q) => (q.project === project ? q : { ...q, project, offset: 0 })), 300);
    return () => window.clearTimeout(t);
  }, [project]);

  useEffect(() => {
    const ctrl = new AbortController();
    setBusy(true);
    setError(null);
    api
      .journal(query, ctrl.signal)
      .then(setPage, (e) => {
        if (!ctrl.signal.aborted) setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!ctrl.signal.aborted) setBusy(false);
      });
    return () => ctrl.abort();
  }, [query]);

  const set = (patch: Partial<JournalQuery>) => setQuery({ ...query, ...patch, offset: 0 });
  const filtered = query.project.trim() !== "" || query.date_from !== "" || query.date_to !== "";
  const runs = page?.runs ?? [];
  const from = page && page.total > 0 ? page.offset + 1 : 0;
  const to = page ? page.offset + runs.length : 0;

  return (
    <main className="page wide">
      <h1 className="page-title">Žurnāls</h1>
      <p className="lead">Iepriekšējās pārbaudes. Saglabātie rezultāti netiek mainīti; atkārtota pārbaude izveido jaunu ierakstu.</p>
      <div className="journal-filters" role="search">
        <label>
          Projekta Nr.
          <input value={project} onChange={(e) => setProject(e.target.value)} placeholder="meklēt…" aria-label="Meklēt pēc projekta Nr." maxLength={100} />
        </label>
        <label>
          No
          <input type="date" value={query.date_from} onChange={(e) => set({ date_from: e.target.value })} aria-label="Datums no" />
        </label>
        <label>
          Līdz
          <input type="date" value={query.date_to} onChange={(e) => set({ date_to: e.target.value })} aria-label="Datums līdz" />
        </label>
        <label className="check">
          <input type="checkbox" checked={query.tests} onChange={(e) => set({ tests: e.target.checked })} />
          Rādīt testa pārbaudes
        </label>
        {filtered && (
          <button
            className="btn small"
            onClick={() => {
              setProject("");
              setQuery({ ...START, tests: query.tests });
            }}
          >
            Notīrīt filtrus
          </button>
        )}
        {busy && <span className="spinner" aria-label="Ielādē" />}
      </div>
      {error && <p className="error">{error}</p>}
      {!page ? (
        !error && (
          <p className="center-msg">
            <span className="spinner" /> Ielādē žurnālu…
          </p>
        )
      ) : runs.length === 0 ? (
        <p className="notice">{filtered ? "Atlasei neatbilst neviena pārbaude." : "Vēl nav nevienas pārbaudes."}</p>
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
                className={`obj ${r.id === current ? "current" : ""} ${r.test ? "test-run" : ""}`}
                onClick={() => open(r.id)}
                onKeyDown={(e) => e.key === "Enter" && open(r.id)}
                tabIndex={0}
                data-run={r.id}
                title="Atvērt pārbaudi"
              >
                <td className="mono">{r.id}</td>
                <td className="nowrap">{new Date(r.created_at).toLocaleString("lv-LV")}</td>
                <td>{r.targets}</td>
                <td>
                  {r.projects.length ? (
                    <>
                      {r.projects.slice(0, MAX_PROJECTS).join(", ")}
                      {r.projects.length > MAX_PROJECTS && <span className="hint"> un vēl {r.projects.length - MAX_PROJECTS}</span>}
                    </>
                  ) : (
                    <span className="hint">bez projekta</span>
                  )}
                </td>
                <td>{r.risk ? <RiskPill risk={r.risk} /> : "–"}</td>
                <td>{r.modules.length}</td>
                <td>
                  {r.parent_run_id ? (
                    <>
                      {RERUN_LV[r.rerun_kind ?? ""] ?? r.rerun_kind}
                      <div className="hint">
                        no nr. {r.parent_run_id}
                        {r.test ? " · e2e tests" : ""}
                      </div>
                    </>
                  ) : (
                    (ORIGIN_LV[r.origin] ?? r.origin)
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {page && page.total > 0 && (
        <nav className="pager" aria-label="Lapas">
          <button className="btn small" disabled={page.offset === 0} onClick={() => setQuery({ ...query, offset: Math.max(0, query.offset - PAGE) })}>
            ◀ Jaunākās
          </button>
          <span data-testid="journal-range">
            {from}–{to} no {page.total}
          </span>
          <button className="btn small" disabled={to >= page.total} onClick={() => setQuery({ ...query, offset: query.offset + PAGE })}>
            Vecākās ▶
          </button>
        </nav>
      )}
    </main>
  );
}
