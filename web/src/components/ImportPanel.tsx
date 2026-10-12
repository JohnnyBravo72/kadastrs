import { useRef, useState } from "react";
import { api, type PreviewRow } from "../api";
import { TYPE_LV } from "../format";

export interface ImportState {
  file: File | null;
  text: string;
  rows: PreviewRow[] | null; // the preview, null = not read yet
  removed: Set<number>; // row numbers removed in the preview
}

export const EMPTY_IMPORT: ImportState = { file: null, text: "", rows: null, removed: new Set() };

const STATUS_LV: Record<string, string> = {
  resolved: "atrasts",
  ambiguous: "neviennozīmīgs",
  not_found: "nav atrasts",
  unresolved: "nav nosakāms",
  outside_pilot: "ārpus pilota",
  invalid: "nederīgs",
  empty: "tukšs",
  not_stored: "nav saglabāts",
};
const KIND_LV: Record<string, string> = { cadastre: "kadastrs", address: "adrese", address_code: "adreses kods" };
const TYPE_TEXT: Record<string, string> = { ...TYPE_LV, address: "Adrese" };

/** Rows of the import that will be checked: objects per kept row. */
export function importObjects(s: ImportState): number {
  return (s.rows ?? []).filter((r) => !s.removed.has(r.row_no)).reduce((n, r) => n + r.targets.length, 0);
}

export function hasImport(s: ImportState): boolean {
  return s.file !== null || s.text.trim() !== "";
}

/** Import CSV / XLSX or a pasted list (§8.1 step 6): read on the server with the
 *  batch reader, nothing stored; a preview with the detected type, match status,
 *  corrections and duplicates; rows can be removed before the check. */
export function ImportPanel({ state, setState }: { state: ImportState; setState: (s: ImportState) => void }) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const read = async (file: File | null, text: string) => {
    setError(null);
    if (!file && !text.trim()) {
      setState({ file, text, rows: null, removed: new Set() });
      return;
    }
    const form = new FormData();
    if (file) form.set("file", file);
    else form.set("text", text);
    setBusy(true);
    try {
      const r = await api.preview(form);
      setState({ file, text, rows: r.rows, removed: new Set() });
    } catch (e) {
      setState({ file, text, rows: null, removed: new Set() });
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const toggle = (row: number) => {
    const removed = new Set(state.removed);
    if (removed.has(row)) removed.delete(row);
    else removed.add(row);
    setState({ ...state, removed });
  };

  const kept = (state.rows ?? []).filter((r) => !state.removed.has(r.row_no));
  return (
    <div className="import">
      <div className="import-inputs">
        {!state.file && (
        <div>
          <textarea
            aria-label="Ielīmēt sarakstu"
            placeholder={"09000360220\nTautas iela 11, Daugavpils\n05000040014"}
            value={state.text}
            onChange={(e) => setState({ ...state, text: e.target.value, rows: null, removed: new Set() })}
            disabled={state.file !== null}
          />
          <p className="hint">
            Viena vērtība rindā, vai tabula no Excel ar virsrakstu rindu: <b>Kadastra Nr., apzīmējums vai adrese</b> (obligāta), Projekta Nr.,
            Pieteicēja reģ. Nr., Adrese pieteikumā, Objekta veids. Ne vairāk kā 1000 rindu.
          </p>
        </div>
        )}
        <div className="import-actions">
          <input
            ref={fileInput}
            type="file"
            accept=".csv,.txt,.xlsx,.xlsm"
            aria-label="Fails"
            style={{ display: "none" }}
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              void read(f, "");
            }}
          />
          <button className="btn" onClick={() => fileInput.current?.click()}>
            Augšupielādēt CSV / Excel
          </button>
          {state.file && (
            <span className="tag">
              {state.file.name}
              <button
                className="btn small"
                onClick={() => {
                  if (fileInput.current) fileInput.current.value = "";
                  setState(EMPTY_IMPORT);
                }}
              >
                noņemt
              </button>
            </span>
          )}
          {!state.file && (
            <button className="btn" disabled={!state.text.trim() || busy} onClick={() => void read(null, state.text)}>
              Priekšskatīt
            </button>
          )}
          <a className="btn" href="/api/batch/template.xlsx" download data-testid="template">
            ⤓ Excel veidne
          </a>
          <span className="hint">Fails tiek nolasīts serverī un netiek saglabāts.</span>
        </div>
      </div>
      {busy && (
        <p className="hint">
          <span className="spinner" /> Nolasa un atpazīst rindas…
        </p>
      )}
      {error && <p className="error">{error}</p>}
      {state.rows && (
        <div className="preview" data-testid="preview">
          <div className="preview-head">
            <b>Priekšskatījums</b>
            <span className="hint">
              {kept.length} no {state.rows.length} rindām; pārbaudīs {importObjects(state)} objektus
            </span>
            <span className="preview-counts">
              <span className="st st-ok">atrastas: {kept.filter((r) => r.checked).length}</span>
              <span className="st st-no">netiks pārbaudītas: {kept.filter((r) => !r.checked).length}</span>
              <span className="st">atkārtojas: {kept.filter((r) => r.duplicate_of !== null).length}</span>
              <span className="st">ar labojumiem: {kept.filter((r) => r.corrections.length > 0).length}</span>
            </span>
          </div>
          <div className="preview-scroll">
            <table className="overview">
              <thead>
                <tr>
                  <th>Rinda</th>
                  <th>Ievadīts</th>
                  <th>Atpazīts kā</th>
                  <th>Statuss</th>
                  <th>Labojumi, brīdinājumi</th>
                  <th>Pārbaudīs</th>
                  <th>Projekts</th>
                  <th aria-label="Noņemt" />
                </tr>
              </thead>
              <tbody>
                {state.rows.map((r) => {
                  const out = state.removed.has(r.row_no);
                  const notes = [
                    ...r.corrections,
                    ...r.warnings,
                    ...r.problems.filter((p) => p.column !== "vertiba").map((p) => `${p.column}: ${p.reason}`),
                  ];
                  return (
                    <tr key={r.row_no} className={`${out ? "removed" : ""} ${r.checked ? "" : "not-checked"}`} data-row={r.row_no}>
                      <td>{r.row_no}</td>
                      <td className={r.kind === "address" ? "" : "mono"}>{r.value ?? "—"}</td>
                      <td>{r.type ? (TYPE_TEXT[r.type] ?? r.type) : r.kind ? (KIND_LV[r.kind] ?? r.kind) : "—"}</td>
                      <td>
                        <span className={`st st-${r.checked ? "ok" : "no"}`}>{STATUS_LV[r.status] ?? r.status}</span>
                        {r.duplicate_of !== null && <div className="hint">atkārtojas (rinda {r.duplicate_of})</div>}
                        {!r.checked && r.problems.find((p) => p.column === "vertiba")?.reason && (
                          <div className="hint">{r.problems.find((p) => p.column === "vertiba")!.reason}</div>
                        )}
                      </td>
                      <td className="notes">
                        {notes.map((n) => (
                          <div key={n}>{n}</div>
                        ))}
                      </td>
                      <td>
                        {r.targets.map((t) => (
                          <div key={`${t.type}-${t.designation}`} className="mono">
                            {t.designation}
                            {t.label && <span className="hint"> {t.label}</span>}
                          </div>
                        ))}
                      </td>
                      <td>{r.project_no}</td>
                      <td>
                        <button className="btn small" onClick={() => toggle(r.row_no)} aria-label={out ? `Atjaunot rindu ${r.row_no}` : `Noņemt rindu ${r.row_no}`}>
                          {out ? "atjaunot" : "×"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
