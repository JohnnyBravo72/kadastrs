import { useCallback, useEffect, useState } from "react";
import { EntryDialog } from "./components/EntryDialog";
import { JournalPage } from "./pages/JournalPage";
import { ResultsPage } from "./pages/ResultsPage";
import { SourcesPage } from "./pages/SourcesPage";
import { parseUrl, toSearch, type Tab, type UrlState } from "./url";

export const FOOTER = "Informatīvs pārskats, balstīts uz atvērtajiem datiem; nav oficiāls reģistra izraksts";

const TABS: [Tab, string][] = [
  ["atlase", "Atlase"],
  ["avoti", "Avoti"],
  ["zurnals", "Žurnāls"],
];

export function App() {
  const [state, setState] = useState<UrlState>(() => parseUrl(window.location.search));
  // the entry dialog opens by itself on first load without a run (§8.1)
  const [entry, setEntry] = useState(() => {
    const s = parseUrl(window.location.search);
    return s.run === null && s.tab === "atlase";
  });

  useEffect(() => {
    const onPop = () => setState(parseUrl(window.location.search));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const navigate = useCallback((next: UrlState, replace = false) => {
    const url = `${window.location.pathname}${toSearch(next)}`;
    if (replace) window.history.replaceState(null, "", url);
    else window.history.pushState(null, "", url);
    setState(next);
  }, []);

  const openRun = (run: number) => navigate({ run, target: 0, view: "object", tab: "atlase" });

  return (
    <>
      <header className="app-header">
        <div className="brand">
          <span className="mark">K</span>
          Kadastra pārbaude
        </div>
        <nav className="head-tabs" aria-label="Sadaļas">
          {TABS.map(([t, label]) => (
            <button key={t} className={state.tab === t ? "on" : ""} aria-current={state.tab === t ? "page" : undefined} onClick={() => navigate({ ...state, tab: t })}>
              {label}
            </button>
          ))}
        </nav>
        <span className="sub">pilota teritorija: Jelgava, Jūrmala, Daugavpils</span>
        <span className="spacer" />
        <button className="btn on-dark" onClick={() => setEntry(true)}>
          + Jauna pārbaude
        </button>
      </header>
      {state.tab === "zurnals" ? (
        <JournalPage current={state.run} open={openRun} />
      ) : state.tab === "avoti" ? (
        <SourcesPage run={state.run} />
      ) : state.run === null ? (
        <main className="page empty-state">
          <h1>Sāciet jaunu pārbaudi</h1>
          <p className="lead">
            Ievadiet kadastra numuru, apzīmējumu vai adresi, vai importējiet sarakstu. Iepriekšējās pārbaudes ir sadaļā „Žurnāls”.
          </p>
          <div className="head-actions">
            <button className="btn primary" onClick={() => setEntry(true)}>
              + Jauna pārbaude
            </button>
            <button className="btn" onClick={() => navigate({ ...state, tab: "zurnals" })}>
              Atvērt žurnālu
            </button>
          </div>
          <p className="footer-note">{FOOTER}.</p>
        </main>
      ) : (
        <ResultsPage state={state} navigate={navigate} />
      )}
      {entry && (
        <EntryDialog
          closable
          onClose={() => setEntry(false)}
          onRun={(run) => {
            setEntry(false);
            openRun(run);
          }}
        />
      )}
    </>
  );
}
