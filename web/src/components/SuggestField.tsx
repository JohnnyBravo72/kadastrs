import { useEffect, useId, useState } from "react";
import { api, type Suggestion } from "../api";

/** Type badges of the entry dialog (§8.1 step 1). */
export const BADGE_LV: Record<string, string> = {
  property: "nekustamā īpašuma Nr.",
  parcel: "zemes vienības apzīmējums",
  building: "būves apzīmējums",
  parcel_part: "zemes vienības daļas apzīmējums",
  premise_group: "telpu grupas apzīmējums",
  address: "adrese",
};

/** A type-ahead field on GET /api/suggest: kadastrs from 3 digits, an address
 *  from 2 characters, ~200 ms debounce; arrow keys, Enter and Escape. */
export function SuggestField({
  kind,
  label,
  placeholder,
  onPick,
  autoFocus,
}: {
  kind: "cadastre" | "address";
  label: string;
  placeholder: string;
  onPick: (s: Suggestion) => void;
  autoFocus?: boolean;
}) {
  const [q, setQ] = useState("");
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [notices, setNotices] = useState<string[]>([]);
  const [active, setActive] = useState(0);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const listId = useId();

  useEffect(() => {
    const term = q.trim();
    const min = kind === "cadastre" ? 3 : 2;
    if (term.length < min) {
      setSuggestions([]);
      setNotices([]);
      setOpen(false);
      return;
    }
    const ctrl = new AbortController();
    const timer = window.setTimeout(() => {
      setBusy(true);
      api
        .suggest(term, kind, ctrl.signal)
        .then((r) => {
          setSuggestions(r.suggestions);
          setNotices(r.notices.map((n) => n.message));
          setActive(0);
          setOpen(true);
        })
        .catch(() => undefined)
        .finally(() => setBusy(false));
    }, 200);
    return () => {
      ctrl.abort();
      window.clearTimeout(timer);
    };
  }, [q, kind]);

  const pick = (s: Suggestion) => {
    onPick(s);
    setQ("");
    setOpen(false);
  };

  const onKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open || suggestions.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, suggestions.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      pick(suggestions[active]);
    } else if (e.key === "Escape") {
      e.stopPropagation();
      setOpen(false);
    }
  };

  const empty = open && !busy && suggestions.length === 0 && q.trim().length >= (kind === "cadastre" ? 3 : 2);
  return (
    <div className="search">
      <input
        aria-label={label}
        placeholder={placeholder}
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={onKey}
        onFocus={() => suggestions.length && setOpen(true)}
        onBlur={() => window.setTimeout(() => setOpen(false), 150)}
        role="combobox"
        aria-expanded={open && suggestions.length > 0}
        aria-controls={listId}
        autoComplete="off"
        autoFocus={autoFocus}
      />
      {busy && <span className="spinner field-spinner" aria-hidden />}
      {open && suggestions.length > 0 && (
        <ul className="suggestions" role="listbox" id={listId} aria-label={`${label}: ieteikumi`}>
          {suggestions.map((s, i) => (
            <li
              key={`${s.type}-${s.designation}`}
              role="option"
              aria-selected={i === active}
              className={i === active ? "active" : ""}
              onMouseDown={() => pick(s)}
              onMouseEnter={() => setActive(i)}
            >
              <span className={`badge t-${s.type}`}>{BADGE_LV[s.type] ?? s.label}</span>
              <span className={s.type === "address" ? "" : "mono"}>{s.type === "address" ? s.label : s.designation}</span>
              <span className="hint">
                {s.type === "address"
                  ? [s.status === "DEL" ? "likvidēta" : null, s.current_address ? `pašreiz: ${s.current_address}` : null]
                      .filter(Boolean)
                      .join("; ")
                  : [s.description, s.city].filter(Boolean).join(" · ")}
              </span>
            </li>
          ))}
        </ul>
      )}
      {empty && <p className="hint">Nekas nav atrasts.</p>}
      {notices.map((n) => (
        <p key={n} className="hint">
          {n}
        </p>
      ))}
    </div>
  );
}
