import { useEffect, useRef } from "react";
import type { CadastreObject } from "../api";
import { TYPE_LV } from "../format";
import { counter, toggleAll, toggleOne, triState, typeCounts, unitKey, visible } from "../selection";

/** The units of a property, or the objects at an address, with a tri-state
 *  "Atzīmēt visu", the counter "5 no 12" and a type filter (§8.1 step 2). */
export function UnitChecklist({
  title,
  units,
  ticked,
  setTicked,
  filter,
  setFilter,
}: {
  title: string;
  units: CadastreObject[];
  ticked: Set<string>;
  setTicked: (t: Set<string>) => void;
  filter: string;
  setFilter: (f: string) => void;
}) {
  const shown = visible(units, filter);
  const state = triState(shown, ticked);
  const all = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (all.current) all.current.indeterminate = state === "some";
  }, [state]);
  const types = typeCounts(units);

  return (
    <div className="unit-list" data-testid="unit-list">
      <div className="unit-head">
        <label className="all">
          <input
            ref={all}
            type="checkbox"
            checked={state === "all"}
            onChange={() => setTicked(toggleAll(shown, ticked))}
            aria-label="Atzīmēt visu"
            aria-checked={state === "some" ? "mixed" : state === "all"}
          />
          Atzīmēt visu
        </label>
        <span className="t">{title}</span>
        <span className="counter" data-testid="unit-counter">
          {counter(units, ticked)}
        </span>
      </div>
      {types.length > 1 && (
        <div className="filter-row" role="group" aria-label="Filtrēt pēc veida">
          <button className={filter === "" ? "on" : ""} onClick={() => setFilter("")}>
            Visi ({units.length})
          </button>
          {types.map(([t, n]) => (
            <button key={t} className={filter === t ? "on" : ""} onClick={() => setFilter(t)}>
              {TYPE_LV[t] ?? t} ({n})
            </button>
          ))}
        </div>
      )}
      <ul>
        {shown.map((u) => (
          <li key={unitKey(u)}>
            <label>
              <input type="checkbox" checked={ticked.has(unitKey(u))} onChange={() => setTicked(toggleOne(u, ticked))} />
              <span className="mono">{u.designation}</span>
              <span className="badge">{TYPE_LV[u.type] ?? u.type}</span>
              <span className="hint">
                {[u.description, u.has_geometry === false ? "nav ģeometrijas" : null].filter(Boolean).join(" · ")}
              </span>
            </label>
          </li>
        ))}
      </ul>
    </div>
  );
}
