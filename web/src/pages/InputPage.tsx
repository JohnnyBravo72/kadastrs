import { useEffect, useRef, useState } from "react";
import { api, type Suggestion } from "../api";
import { FOOTER } from "../App";

interface Chosen {
  value: string; // what goes to /api/batch: a designation or the full address
  label: string;
  description: string | null;
}

const TYPE_LV: Record<string, string> = {
  property: "Īpašums",
  parcel: "Zemes vienība",
  building: "Būve",
  parcel_part: "Zemes vienības daļa",
  premise_group: "Telpu grupa",
  address: "Adrese",
};

/** Search (kadastrs or address), a paste box and a file: all go through
 *  POST /api/batch, so the batch rules apply (ambiguous numbers checked both
 *  ways, unresolved rows listed as "Neatrasts"). */
export function InputPage({ onRun }: { onRun: (run: number) => void }) {
  const [kind, setKind] = useState<"cadastre" | "address">("cadastre");
  const [q, setQ] = useState("");
  const [suggestions, setSuggestions] = useState<Suggestion[]>([]);
  const [notices, setNotices] = useState<string[]>([]);
  const [active, setActive] = useState(0);
  const [open, setOpen] = useState(false);
  const [chosen, setChosen] = useState<Chosen[]>([]);
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const term = q.trim();
    const min = kind === "cadastre" ? 3 : 2;
    if (term.length < min) {
      setSuggestions([]);
      setNotices([]);
      return;
    }
    const ctrl = new AbortController();
    const timer = window.setTimeout(() => {
      api
        .suggest(term, kind, ctrl.signal)
        .then((r) => {
          setSuggestions(r.suggestions);
          setNotices(r.notices.map((n) => n.message));
          setActive(0);
          setOpen(true);
        })
        .catch(() => undefined);
    }, 200);
    return () => {
      ctrl.abort();
      window.clearTimeout(timer);
    };
  }, [q, kind]);

  const pick = (s: Suggestion) => {
    const value = s.type === "address" ? (s.description ?? s.label) : s.designation;
    if (!chosen.some((c) => c.value === value)) {
      const description =
        s.type === "address" ? null : `${TYPE_LV[s.type] ?? s.label}${s.description ? `, ${s.description}` : ""}`;
      setChosen([...chosen, { value, label: value, description }]);
    }
    setQ("");
    setOpen(false);
  };

  const onKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!open || suggestions.length === 0) {
      if (e.key === "Enter" && q.trim()) {
        setChosen([...chosen, { value: q.trim(), label: q.trim(), description: "kā ievadīts" }]);
        setQ("");
      }
      return;
    }
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
      setOpen(false);
    }
  };

  const lines = text.split(/\r?\n/).filter((l) => l.trim()).length;
  const total = file ? null : chosen.length + lines;
  const canSubmit = !busy && (file !== null || chosen.length > 0 || lines > 0);

  const submit = async () => {
    setBusy(true);
    setError(null);
    const form = new FormData();
    if (file) {
      form.set("file", file);
    } else {
      // A pasted table keeps its header first; chosen values are added as rows.
      const pasted = text.trim();
      const values = chosen.map((c) => c.value);
      const hasHeader = /^\s*v[eē]rt[iī]ba/i.test(pasted);
      const rows = hasHeader ? [pasted, ...values] : [...values, pasted];
      form.set("text", rows.filter(Boolean).join("\n"));
    }
    try {
      const run = await api.batch(form);
      onRun(run.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="page">
      <p className="lead">
        Atrodiet objektu pēc kadastra numura, apzīmējuma vai adreses, vai ielīmējiet sarakstu. Katrs objekts tiek
        pārbaudīts pret atvērtajiem datiem: kadastrs, adrese, aizsargājamā daba, plūdi, būvniecības lietas un
        apgrūtinājumi.
      </p>
      <div className="input-grid">
        <section className="panel">
          <h2>Meklēt objektu</h2>
          <div className="body">
            <div className="kind-switch" role="tablist">
              <button className={kind === "cadastre" ? "on" : ""} onClick={() => setKind("cadastre")}>
                Kadastrs
              </button>
              <button className={kind === "address" ? "on" : ""} onClick={() => setKind("address")}>
                Adrese
              </button>
            </div>
            <div className="search">
              <input
                aria-label="Meklēt"
                placeholder={kind === "cadastre" ? "Kadastra numurs vai apzīmējums, piem. 09000050400" : "Adrese, piem. Tautas iela 11, Daugavpils"}
                value={q}
                onChange={(e) => setQ(e.target.value)}
                onKeyDown={onKey}
                onFocus={() => suggestions.length && setOpen(true)}
                onBlur={() => window.setTimeout(() => setOpen(false), 150)}
                autoFocus
              />
              {open && suggestions.length > 0 && (
                <ul className="suggestions" role="listbox">
                  {suggestions.map((s, i) => (
                    <li
                      key={`${s.type}-${s.designation}`}
                      className={i === active ? "active" : ""}
                      onMouseDown={() => pick(s)}
                      onMouseEnter={() => setActive(i)}
                    >
                      <span className="badge">{TYPE_LV[s.type] ?? s.label}</span>
                      <span className={s.type === "address" ? "" : "mono"}>
                        {s.type === "address" ? (s.description ?? s.label) : s.designation}
                      </span>
                      <span className="hint">
                        {s.type === "address"
                          ? [s.status === "DEL" ? "likvidēta" : null, s.current_address ? `pašreiz: ${s.current_address}` : null]
                              .filter(Boolean)
                              .join("; ")
                          : (s.description ?? "")}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
            {notices.map((n) => (
              <p key={n} className="hint">
                {n}
              </p>
            ))}
            <div className="chosen">
              {chosen.length === 0 && <span className="hint">Izvēlētie objekti parādīsies šeit.</span>}
              {chosen.map((c) => (
                <span className="tag" key={c.value} title={c.description ?? ""}>
                  <span className={/^\d+$/.test(c.value) ? "mono" : ""}>{c.label}</span>
                  {c.description && <span className="hint">{c.description}</span>}
                  <button aria-label="Noņemt" onClick={() => setChosen(chosen.filter((x) => x !== c))}>
                    ×
                  </button>
                </span>
              ))}
            </div>
          </div>
        </section>

        <section className="panel">
          <h2>Saraksts vai fails</h2>
          <div className="body">
            <textarea
              aria-label="Ielīmēt sarakstu"
              placeholder={"09000360220\nTautas iela 11, Daugavpils\n05000040014"}
              value={text}
              onChange={(e) => setText(e.target.value)}
              disabled={file !== null}
            />
            <p className="hint">
              Viena vērtība rindā, vai tabula no Excel ar virsrakstu (<code>vertiba</code>, <code>projekta_nr</code>,{" "}
              <code>adrese</code>, <code>veids</code>, <code>pieteicejs_reg_nr</code>). Ne vairāk kā 1000 rindu.
            </p>
            <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
              <input
                ref={fileInput}
                type="file"
                accept=".csv,.txt,.xlsx,.xlsm"
                aria-label="Fails"
                style={{ display: "none" }}
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
              <button className="btn" onClick={() => fileInput.current?.click()}>
                Augšupielādēt CSV / Excel
              </button>
              {file && (
                <span className="tag" style={{ display: "inline-flex", gap: 6 }}>
                  {file.name}
                  <button
                    className="btn small"
                    onClick={() => {
                      setFile(null);
                      if (fileInput.current) fileInput.current.value = "";
                    }}
                  >
                    noņemt
                  </button>
                </span>
              )}
              <a className="hint" href="/api/batch/template.xlsx">
                Lejupielādēt veidni
              </a>
            </div>
            <p className="hint">Augšupielādētais fails netiek saglabāts; tiek saglabāts tikai sakārtotais saraksts un rezultāti.</p>
          </div>
        </section>
      </div>

      <div className="submit-row">
        <button className="btn primary" disabled={!canSubmit} onClick={submit}>
          {busy ? <span className="spinner" /> : null} Pārbaudīt
        </button>
        <span className="hint">
          {file ? `Fails: ${file.name}` : total ? `${total} ${total === 1 ? "vērtība" : "vērtības"}` : "Nav izvēlētu objektu"}
        </span>
        {error && <span className="error">{error}</span>}
      </div>
      <p className="footer-note">{FOOTER}. Pamatkarte © OpenStreetMap līdzautori.</p>
    </main>
  );
}
