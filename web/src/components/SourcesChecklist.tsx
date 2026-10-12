import type { RegistrySource } from "../api";

/** Sources grouped as in the registry; the ones that select a check module can
 *  be unticked (their module is then not run), base data is always used (§8.1
 *  step 5). Partial-coverage sources carry a note. */
export function SourcesChecklist({
  sources,
  ticked,
  setTicked,
}: {
  sources: RegistrySource[];
  ticked: Set<string>;
  setTicked: (t: Set<string>) => void;
}) {
  const groups = new Map<string, RegistrySource[]>();
  for (const s of sources) {
    if (!groups.has(s.group)) groups.set(s.group, []);
    groups.get(s.group)!.push(s);
  }
  const toggle = (id: string) => {
    const next = new Set(ticked);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setTicked(next);
  };
  return (
    <div className="sources-list" data-testid="sources-list">
      {[...groups.entries()].map(([group, items]) => (
        <fieldset key={group}>
          <legend>{group}</legend>
          {items.map((s) => (
            <label key={s.id} className={s.selectable ? "" : "fixed"} title={s.coverage ?? ""}>
              <input
                type="checkbox"
                checked={s.selectable ? ticked.has(s.id) : true}
                disabled={!s.selectable}
                onChange={() => toggle(s.id)}
                aria-label={s.name}
              />
              <span>
                {s.name}
                {s.selectable && s.modules.length > 0 && (
                  <span className="hint"> · {s.modules.map((m) => `${m.no}. ${m.name}`).join(", ")}</span>
                )}
                {!s.selectable && <span className="hint"> · vienmēr izmantots{s.used_by.length ? ` (${s.used_by.join(", ")})` : ""}</span>}
                {s.partial_coverage && <span className="partial">daļējs pārklājums: {s.coverage}</span>}
              </span>
            </label>
          ))}
        </fieldset>
      ))}
    </div>
  );
}
