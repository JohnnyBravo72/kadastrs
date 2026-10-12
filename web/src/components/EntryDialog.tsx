import { useEffect, useMemo, useState } from "react";
import { api, type CadastreObject, type Entry, type RegistrySource, type Suggestion } from "../api";
import { selection, totalsText, unitKey, type Totals } from "../selection";
import { EMPTY_IMPORT, hasImport, ImportPanel, importTotals, type ImportState } from "./ImportPanel";
import { SourcesChecklist } from "./SourcesChecklist";
import { BADGE_LV, SuggestField } from "./SuggestField";
import { UnitChecklist } from "./UnitChecklist";

const LEGAL_REG_NO = /^[459]\d{10}$/;
const ENTRY_KIND: Record<string, Entry["kind"]> = {
  property: "property",
  parcel: "parcel",
  parcel_part: "parcel",
  building: "building",
  premise_group: "building",
};

interface Picked {
  type: string;
  designation: string;
  description: string | null;
}

interface Draft {
  cad: Picked | null;
  addr: { code: string; text: string } | null;
  units: CadastreObject[] | null; // the property's units or the address's objects
  unitsOf: "property" | "address" | null;
  ticked: Set<string>;
  filter: string;
  propertyOfParcel: string[]; // a parcel entered directly: its properties
  addrObjects: CadastreObject[] | null;
  addrNotes: string[];
  loading: boolean;
}

const EMPTY_DRAFT: Draft = {
  cad: null,
  addr: null,
  units: null,
  unitsOf: null,
  ticked: new Set(),
  filter: "",
  propertyOfParcel: [],
  addrObjects: null,
  addrNotes: [],
  loading: false,
};

type Counts = Omit<Totals, "sources">;

interface Added {
  entry: Entry;
  title: string;
  counts: Counts;
}

const tickedCount = (d: Draft) => (d.units ?? []).filter((u) => d.ticked.has(unitKey(u))).length;

/** What the draft object checks: a property is one object with its ticked
 *  units; each ticked object at an address is one object. */
function draftCounts(d: Draft): Counts {
  if (d.unitsOf === "property") return { objects: 1, properties: 1, units: tickedCount(d) };
  if (d.unitsOf === "address") return { objects: tickedCount(d), properties: 0, units: tickedCount(d) };
  return d.cad || d.addr ? { objects: 1, properties: 0, units: 1 } : { objects: 0, properties: 0, units: 0 };
}

const sum = (list: Counts[]): Counts =>
  list.reduce((a, c) => ({ objects: a.objects + c.objects, properties: a.properties + c.properties, units: a.units + c.units }), {
    objects: 0,
    properties: 0,
    units: 0,
  });

function toEntry(d: Draft, project: string, applicant: string): Entry | null {
  const common = { project_no: project.trim() || null, applicant: applicant.trim() || null };
  if (d.cad) {
    return {
      ...common,
      value: d.cad.designation,
      kind: ENTRY_KIND[d.cad.type] ?? null,
      address: d.addr?.text ?? null,
      selected: d.unitsOf === "property" && d.units ? selection(d.units, d.ticked) : null,
    };
  }
  if (d.addr) {
    return { ...common, value: d.addr.code, selected: d.units ? selection(d.units, d.ticked) : null };
  }
  return null;
}

/** Kadastrs and address point to different objects: module 2 checks it. */
function mismatch(d: Draft): boolean {
  if (!d.cad || !d.addrObjects || d.addrObjects.length === 0) return false;
  const mine = new Set<string>([d.cad.designation]);
  for (const u of d.unitsOf === "property" ? (d.units ?? []) : []) {
    mine.add(u.designation);
    for (const p of u.parcel_codes) mine.add(p);
  }
  return !d.addrObjects.some((o) => mine.has(o.designation) || o.parcel_codes.some((p) => mine.has(p)));
}

/** "Jauna pārbaude" (PLAN.md §8.1): kadastrs and address with suggestions, the
 *  units checklist, project and applicant, the sources checklist and the import;
 *  everything goes to POST /api/batch. */
export function EntryDialog({
  onClose,
  onRun,
  closable,
}: {
  onClose: () => void;
  onRun: (run: number) => void;
  closable: boolean;
}) {
  const [tab, setTab] = useState<"object" | "import">("object");
  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [added, setAdded] = useState<Added[]>([]);
  const [project, setProject] = useState("");
  const [applicant, setApplicant] = useState("");
  const [imp, setImp] = useState<ImportState>(EMPTY_IMPORT);
  const [sources, setSources] = useState<RegistrySource[] | null>(null);
  const [sourcesTicked, setSourcesTicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.sources().then(
      (s) => {
        setSources(s);
        setSourcesTicked(new Set(s.filter((x) => x.selectable && x.default_selected).map((x) => x.id)));
      },
      (e) => setError(`Avotu saraksts nav pieejams: ${e instanceof Error ? e.message : e}`),
    );
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && closable) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [closable, onClose]);

  // --- picking -------------------------------------------------------------------------

  const loadProperty = async (number: string, onlyParcel?: string) => {
    setDraft((d) => ({ ...d, loading: true }));
    try {
      const pu = await api.propertyUnits(number);
      const units = pu.units;
      const tick = onlyParcel ? units.filter((u) => u.designation === onlyParcel) : units;
      setDraft((d) => ({
        ...d,
        cad: { type: "property", designation: pu.number, description: [pu.kind, pu.name].filter(Boolean).join(", ") || null },
        units,
        unitsOf: "property",
        ticked: new Set(tick.map(unitKey)),
        filter: "",
        propertyOfParcel: [],
        loading: false,
      }));
    } catch (e) {
      setDraft((d) => ({ ...d, loading: false }));
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const pickCadastre = async (s: Suggestion) => {
    setError(null);
    const cad = { type: s.type, designation: s.designation, description: s.description };
    setDraft((d) => ({
      ...d,
      cad,
      units: d.unitsOf === "address" ? null : d.units,
      unitsOf: null,
      ticked: new Set(),
      propertyOfParcel: [],
    }));
    if (s.type === "property") {
      await loadProperty(s.designation);
      return;
    }
    if (s.type === "parcel") {
      const r = await fetch("/api/resolve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ values: [s.designation] }),
      }).then((x) => (x.ok ? x.json() : null));
      const m = r?.rows?.[0]?.matches?.find((x: { type: string }) => x.type === "parcel");
      setDraft((d) => ({ ...d, units: null, propertyOfParcel: m?.object?.property_numbers ?? [] }));
    } else {
      setDraft((d) => ({ ...d, units: null }));
    }
  };

  const pickAddress = async (s: Suggestion) => {
    setError(null);
    const addr = { code: s.designation, text: s.label };
    setDraft((d) => ({ ...d, addr, addrObjects: null, addrNotes: [], loading: true }));
    try {
      const a = await api.addressObjects(s.designation);
      setDraft((d) => {
        const next = {
          ...d,
          addrObjects: a.objects,
          addrNotes: [
            ...a.warnings.map((w) => w.message),
            ...(a.non_existing_excluded ? [`${a.non_existing_excluded} neeksistējošas būves nav sarakstā`] : []),
          ],
          loading: false,
        };
        if (!d.cad) {
          next.units = a.objects;
          next.unitsOf = "address";
          next.ticked = new Set(a.objects.map(unitKey));
          next.filter = "";
        }
        return next;
      });
    } catch (e) {
      setDraft((d) => ({ ...d, loading: false }));
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const clearCadastre = () =>
    setDraft((d) =>
      d.addr && d.addrObjects
        ? { ...d, cad: null, units: d.addrObjects, unitsOf: "address", ticked: new Set(d.addrObjects.map(unitKey)), propertyOfParcel: [] }
        : { ...d, cad: null, units: null, unitsOf: null, ticked: new Set(), propertyOfParcel: [] },
    );
  const clearAddress = () =>
    setDraft((d) =>
      d.unitsOf === "address"
        ? { ...d, addr: null, addrObjects: null, addrNotes: [], units: null, unitsOf: null, ticked: new Set() }
        : { ...d, addr: null, addrObjects: null, addrNotes: [] },
    );

  // --- totals and submit -----------------------------------------------------------------

  const applicantBad = applicant.trim() !== "" && !LEGAL_REG_NO.test(applicant.replace(/\s+/g, ""));
  const draftEntry = useMemo(() => toEntry(draft, project, applicant), [draft, project, applicant]);
  const draftC = draftCounts(draft);
  const nDraft = draftC.units;
  const totals = sum([...added.map((a) => a.counts), draftC, importTotals(imp)]);
  const nObjects = totals.objects;
  const nSources = sourcesTicked.size;
  const importPending = hasImport(imp) && imp.rows === null;
  const canRun =
    !busy && !draft.loading && !applicantBad && nSources > 0 && (nObjects > 0 || importPending) && !(draftEntry && nDraft === 0);

  const addDraft = () => {
    if (!draftEntry || nDraft === 0) return;
    const title = draft.cad ? draft.cad.designation : (draft.addr?.text ?? "");
    setAdded([...added, { entry: draftEntry, title, counts: draftC }]);
    setDraft(EMPTY_DRAFT);
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    const form = new FormData();
    if (imp.file) form.set("file", imp.file);
    else if (imp.text.trim()) form.set("text", imp.text);
    if (imp.removed.size) form.set("skip_rows", [...imp.removed].join(","));
    const entries = [...added.map((a) => a.entry), ...(draftEntry && nDraft > 0 ? [draftEntry] : [])];
    if (entries.length) form.set("entries", JSON.stringify(entries));
    form.set("sources", [...sourcesTicked].join(","));
    try {
      const run = await api.batch(form);
      onRun(run.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const differ = mismatch(draft);

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && closable && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="entry-title">
        <header className="modal-head">
          <h2 id="entry-title">Jauna pārbaude</h2>
          <div className="tabs inline" role="tablist">
            <button role="tab" aria-selected={tab === "object"} className={tab === "object" ? "on" : ""} onClick={() => setTab("object")}>
              Objekts
            </button>
            <button role="tab" aria-selected={tab === "import"} className={tab === "import" ? "on" : ""} onClick={() => setTab("import")}>
              Importēt CSV / Excel{hasImport(imp) ? " ●" : ""}
            </button>
          </div>
          <span className="spacer" />
          {closable && (
            <button className="icon-btn" onClick={onClose} aria-label="Aizvērt">
              ×
            </button>
          )}
        </header>

        <div className="modal-body">
          <div className="modal-main">
            {tab === "object" ? (
              <>
                <div className="field">
                  <span className="field-label">Kadastrs</span>
                  {draft.cad ? (
                    <div className="picked">
                      <span className={`badge t-${draft.cad.type}`}>{BADGE_LV[draft.cad.type] ?? draft.cad.type}</span>
                      <span className="mono big">{draft.cad.designation}</span>
                      <span className="hint">{draft.cad.description}</span>
                      <button className="icon-btn" onClick={clearCadastre} aria-label="Noņemt kadastru">
                        ×
                      </button>
                    </div>
                  ) : (
                    <SuggestField
                      kind="cadastre"
                      label="Kadastrs"
                      placeholder="Kadastra numurs vai apzīmējums, piem. 09000360220"
                      onPick={(s) => void pickCadastre(s)}
                      autoFocus
                    />
                  )}
                  {draft.cad?.type === "parcel" && draft.propertyOfParcel.length > 0 && (
                    <div className="parcel-of">
                      Zemes vienība pieder īpašumam{draft.propertyOfParcel.length > 1 ? "iem" : ""}{" "}
                      {draft.propertyOfParcel.map((p) => (
                        <button key={p} className="btn small" onClick={() => void loadProperty(p, draft.cad!.designation)}>
                          Rādīt visas īpašuma vienības ({p})
                        </button>
                      ))}
                    </div>
                  )}
                </div>

                <div className="field">
                  <span className="field-label">Adrese</span>
                  {draft.addr ? (
                    <div className="picked">
                      <span className="badge t-address">adrese</span>
                      <span>{draft.addr.text}</span>
                      <button className="icon-btn" onClick={clearAddress} aria-label="Noņemt adresi">
                        ×
                      </button>
                    </div>
                  ) : (
                    <SuggestField kind="address" label="Adrese" placeholder="Adrese, piem. Tautas iela 11, Daugavpils" onPick={(s) => void pickAddress(s)} />
                  )}
                  {draft.addrNotes.map((n) => (
                    <p className="hint" key={n}>
                      {n}
                    </p>
                  ))}
                  {differ && (
                    <p className="notice" data-testid="mismatch">
                      Adrese un kadastra apzīmējums norāda uz dažādiem objektiem. Tiks pārbaudīts kadastra objekts; adreses atbilstību
                      pārbaudīs modulis „Adreses atbilstība”.
                    </p>
                  )}
                </div>

                {draft.loading && (
                  <p className="hint">
                    <span className="spinner" /> Ielādē vienības…
                  </p>
                )}
                {draft.units && draft.unitsOf && (
                  draft.units.length === 0 ? (
                    <p className="notice">{draft.unitsOf === "address" ? "Adresei nav piesaistītu kadastra objektu." : "Īpašumam nav pārbaudāmu vienību."}</p>
                  ) : (
                    <UnitChecklist
                      title={draft.unitsOf === "property" ? `Īpašuma ${draft.cad?.designation} vienības` : "Adreses objekti"}
                      units={draft.units}
                      ticked={draft.ticked}
                      setTicked={(t) => setDraft({ ...draft, ticked: t })}
                      filter={draft.filter}
                      setFilter={(f) => setDraft({ ...draft, filter: f })}
                    />
                  )
                )}
                {draftEntry && nDraft === 0 && <p className="notice">Atzīmējiet vismaz vienu vienību.</p>}

                <div className="field-row">
                  <label className="field">
                    <span className="field-label">Projekta Nr.</span>
                    <input value={project} onChange={(e) => setProject(e.target.value)} placeholder="nav obligāts" maxLength={100} />
                  </label>
                  <label className="field">
                    <span className="field-label">Pieteicēja reģ. Nr.</span>
                    <input
                      value={applicant}
                      onChange={(e) => setApplicant(e.target.value)}
                      placeholder="nav obligāts, piem. 40003000000"
                      aria-invalid={applicantBad}
                      maxLength={20}
                    />
                    {applicantBad && <span className="field-error">Juridiskas personas reģ. Nr.: 11 cipari, sākas ar 4, 5 vai 9.</span>}
                  </label>
                </div>

                <div className="added">
                  <button className="btn small" onClick={addDraft} disabled={!draftEntry || nDraft === 0}>
                    + Pievienot sarakstam un ievadīt vēl vienu
                  </button>
                  {added.map((a, i) => (
                    <span className="tag" key={`${a.title}-${i}`}>
                      <span className={/^\d+$/.test(a.title) ? "mono" : ""}>{a.title}</span>
                      <span className="hint">
                        {totalsText({ ...a.counts, sources: 0 }).replace(/ · 0 avoti$/, "")}
                        {a.entry.project_no ? ` · ${a.entry.project_no}` : ""}
                      </span>
                      <button aria-label="Noņemt" onClick={() => setAdded(added.filter((_, j) => j !== i))}>
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              </>
            ) : (
              <ImportPanel state={imp} setState={setImp} />
            )}
          </div>

          <aside className="modal-side">
            <h3>Avoti</h3>
            {sources ? <SourcesChecklist sources={sources} ticked={sourcesTicked} setTicked={setSourcesTicked} /> : <span className="spinner" />}
          </aside>
        </div>

        <footer className="modal-foot">
          {error && <span className="error">{error}</span>}
          <span className="spacer" />
          <span className="totals" data-testid="totals">
            {importPending ? "fails vēl nav nolasīts · " : ""}
            {totalsText({ ...totals, sources: nSources })}
          </span>
          {closable && (
            <button className="btn" onClick={onClose}>
              Atcelt
            </button>
          )}
          <button className="btn primary" disabled={!canRun} onClick={() => void submit()}>
            {busy ? <span className="spinner" /> : null} Pārbaudīt
          </button>
        </footer>
      </div>
    </div>
  );
}
