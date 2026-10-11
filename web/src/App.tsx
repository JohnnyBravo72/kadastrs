import { useCallback, useEffect, useState } from "react";
import { InputPage } from "./pages/InputPage";
import { ResultsPage } from "./pages/ResultsPage";
import { parseUrl, toSearch, type UrlState } from "./url";

export const FOOTER = "Informatīvs pārskats, balstīts uz atvērtajiem datiem; nav oficiāls reģistra izraksts";

export function App() {
  const [state, setState] = useState<UrlState>(() => parseUrl(window.location.search));

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

  const newCheck = () => navigate({ run: null, target: 0, view: "object" });

  return (
    <>
      <header className="app-header">
        <div className="brand">
          <span className="mark">K</span>
          Kadastra pārbaude
        </div>
        <span className="sub">atvērto datu pārbaude pilota teritorijā: Jelgava, Jūrmala, Daugavpils</span>
        <span className="spacer" />
        {state.run !== null && (
          <button className="btn on-dark" onClick={newCheck}>
            + Jauna pārbaude
          </button>
        )}
      </header>
      {state.run === null ? (
        <InputPage onRun={(run) => navigate({ run, target: 0, view: "object" })} />
      ) : (
        <ResultsPage state={state} navigate={navigate} />
      )}
    </>
  );
}
