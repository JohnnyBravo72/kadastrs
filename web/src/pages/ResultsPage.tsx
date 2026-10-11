import { useEffect, useMemo, useState } from "react";
import {
  api,
  type AttentionProps,
  type FeatureCollection,
  type InputRow,
  type OutlineProps,
  type RunSummary,
  type TargetDetail,
  type TargetLine,
} from "../api";
import { FOOTER } from "../App";
import { DEFAULT_LAYERS, MapView, type LayerKey, type Layers } from "../components/MapView";
import { ModuleCard } from "../components/ModuleCard";
import { groupByProject, OverviewTable, targetWorst } from "../components/OverviewTable";
import { RiskPill } from "../components/RiskPill";
import { TYPE_LV } from "../format";
import { cellStyle, STATUS_LV } from "../risk";
import type { UrlState } from "../url";

export const MODULE_SHORT: Record<string, string> = {
  cadastre_facts: "Kadastrs",
  address_consistency: "Adrese",
  nature: "Daba",
  flood_10y: "Plūdi",
  bis: "BIS",
  encumbrances: "Apgrūtinājumi",
};
const MODULE_LAYER: Record<string, LayerKey> = {
  cadastre_facts: "kadastrs",
  address_consistency: "kadastrs",
  nature: "daba",
  flood_10y: "pludi",
  bis: "bis",
  encumbrances: "kadastrs",
};
const INPUT_STATUS_LV: Record<string, string> = {
  not_found: "nav atrasts",
  ambiguous: "neviennozīmīgs",
  unresolved: "nav nosakāms",
  outside_pilot: "ārpus pilota teritorijas",
  invalid: "nederīgs",
  empty: "tukšs",
  kind_mismatch: "veids neatbilst",
  no_objects: "nav kadastra objektu",
  not_stored: "nav saglabāts",
};
const COLUMN_LV: Record<string, string> = { vertiba: "vērtība", adrese: "adrese", veids: "veids", pieteicejs_reg_nr: "pieteicēja reģ. nr." };

interface Props {
  state: UrlState;
  navigate: (s: UrlState, replace?: boolean) => void;
}

export function ResultsPage({ state, navigate }: Props) {
  const runId = state.run!;
  const [run, setRun] = useState<RunSummary | null>(null);
  const [targets, setTargets] = useState<TargetLine[] | null>(null);
  const [inputs, setInputs] = useState<InputRow[]>([]);
  const [outlines, setOutlines] = useState<FeatureCollection<OutlineProps> | null>(null);
  const [detail, setDetail] = useState<TargetDetail | null>(null);
  const [attention, setAttention] = useState<FeatureCollection<AttentionProps> | null>(null);
  const [layers, setLayers] = useState<Layers>(DEFAULT_LAYERS);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    Promise.all([api.run(runId), api.targets(runId), api.inputs(runId)])
      .then(([r, t, i]) => {
        setRun(r);
        setTargets(t);
        setInputs(i);
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
    api.outlines(runId).then(setOutlines, () => setOutlines(null));
  }, [runId]);

  const count = targets?.length ?? 0;
  const target = Math.min(state.target, Math.max(0, count - 1));
  const view = count > 1 ? state.view : "object";

  useEffect(() => {
    if (!targets || count === 0 || view !== "object") return;
    setDetail(null);
    setAttention(null);
    api.target(runId, target).then(setDetail, (e) => setError(String(e)));
    api.attention(runId, target).then(setAttention, () => setAttention(null));
  }, [runId, target, targets, count, view]);

  const go = (t: number, v = view) => navigate({ run: runId, target: t, view: v });
  const notChecked = inputs.filter((i) => i.problems.length > 0);

  if (error) return <p className="center-msg error">{error}</p>;
  if (!run || !targets) return <p className="center-msg"><span className="spinner" /> Ielādē pārbaudes rezultātus…</p>;

  return (
    <main className="results">
      {count === 0 ? (
        <p className="notice">Neviens ievadītais objekts netika atrasts. Iemesli ir zemāk un Excel lapā „Neatrasts”.</p>
      ) : view === "object" ? (
        <ObjectView
          run={run}
          targets={targets}
          target={target}
          detail={detail}
          outlines={outlines}
          attention={attention}
          layers={layers}
          setLayers={setLayers}
          go={go}
          onAll={() => go(target, "all")}
        />
      ) : (
        <AllView run={run} targets={targets} outlines={outlines} layers={layers} setLayers={setLayers} open={(t) => go(t, "object")} />
      )}
      {notChecked.length > 0 && <NotChecked rows={notChecked} />}
      <p className="footer-note">
        {FOOTER}. Pārbaude nr. {run.id}, {new Date(run.created_at).toLocaleString("lv-LV")}; riska noteikumi v
        {run.rule_set.version} ({run.rule_set.status === "agreed" ? "saskaņoti" : "melnraksts"}). Pamatkarte ©
        OpenStreetMap līdzautori.
      </p>
    </main>
  );
}

// --- one object ----------------------------------------------------------------------

function ObjectView({
  run,
  targets,
  target,
  detail,
  outlines,
  attention,
  layers,
  setLayers,
  go,
  onAll,
}: {
  run: RunSummary;
  targets: TargetLine[];
  target: number;
  detail: TargetDetail | null;
  outlines: FeatureCollection<OutlineProps> | null;
  attention: FeatureCollection<AttentionProps> | null;
  layers: Layers;
  setLayers: (l: Layers) => void;
  go: (t: number) => void;
  onAll: () => void;
}) {
  const line = targets[target];
  const address = useMemo(() => {
    const facts = detail?.results.find((r) => r.module === "cadastre_facts");
    const all = [facts?.result, ...(facts?.units ?? [])].flatMap((r) => r?.items ?? []);
    const found = all.map((i) => i.address).find((a) => typeof a === "string" && a);
    return (found as string | undefined) ?? null;
  }, [detail]);

  const chipClick = (module: string) => {
    const layer = MODULE_LAYER[module];
    if (layer && !layers[layer].on) setLayers({ ...layers, [layer]: { ...layers[layer], on: true } });
    document.getElementById(`card-${module}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
    const card = document.getElementById(`card-${module}`) as HTMLDetailsElement | null;
    if (card) card.open = true;
  };

  return (
    <>
      <div className="object-head">
        <div className="title">
          <div className="number mono" data-testid="designation">
            {line.designation}
          </div>
          <div className="address">{address ?? (detail ? "adrese kadastrā nav norādīta" : " ")}</div>
          <div className="meta">
            <span>{TYPE_LV[line.type] ?? line.type}</span>
            {line.label && <span className="badge">{line.label}</span>}
            {line.project_no && <span>Projekts {line.project_no}</span>}
            {line.input && line.input !== line.designation && <span>ievadīts: {line.input}</span>}
            <RiskPill risk={targetWorst(line)} prefix="Kopējais risks:" />
          </div>
        </div>
        <div className="head-actions">
          {targets.length > 1 && <Switcher targets={targets} target={target} go={go} />}
          {targets.length > 1 && (
            <button className="btn" onClick={onAll}>
              Visi objekti ({targets.length})
            </button>
          )}
          <a className="btn primary" href={api.reportUrl(run.id)} download data-testid="excel">
            ⤓ Lejupielādēt Excel
          </a>
        </div>
      </div>

      <div className="strip" data-testid="status-strip">
        {run.modules.map((m) => {
          const s = line.modules[m];
          if (!s) return null;
          const st = cellStyle(s.summary_status, s.risk);
          return (
            <button key={m} className="chip" onClick={() => chipClick(m)} title={`${run.module_names[m]}: ${STATUS_LV[s.summary_status]}`} data-module={m}>
              <span className="ico" style={{ background: st.color, color: st.text }} aria-hidden>
                {st.icon}
              </span>
              <span>
                <span className="name">{MODULE_SHORT[m] ?? run.module_names[m]}</span>
                <br />
                <span className="state">
                  {STATUS_LV[s.summary_status]}
                  {s.summary_status !== "not_applicable" ? ` · ${st.label}` : ""}
                </span>
              </span>
            </button>
          );
        })}
      </div>

      <MapView
        runId={run.id}
        outlines={outlines}
        focus={target}
        attention={attention}
        layers={layers}
        setLayers={setLayers}
        onSelect={(t) => go(t)}
      />

      {!detail ? (
        <p className="center-msg">
          <span className="spinner" /> Ielādē moduļu rezultātus…
        </p>
      ) : (
        <div className="cards">
          {detail.results
            .filter((r) => r.result)
            .sort((a, b) => a.module_no - b.module_no)
            .map((r) => (
              <ModuleCard key={r.module} result={r.result!} units={r.units} versions={run.dataset_versions} />
            ))}
        </div>
      )}
    </>
  );
}

function Switcher({ targets, target, go }: { targets: TargetLine[]; target: number; go: (t: number) => void }) {
  const [q, setQ] = useState("");
  const grouped = groupByProject(targets);
  const label = (t: TargetLine) => `${t.designation}${t.label ? ` (${t.label.replace("divdomīgs: ", "")})` : ""}`;
  return (
    <div className="switcher" data-testid="switcher">
      <button className="btn small" onClick={() => go(Math.max(0, target - 1))} disabled={target === 0} aria-label="Iepriekšējais">
        ◀
      </button>
      <span className="count">
        {target + 1} / {targets.length}
      </span>
      <button className="btn small" onClick={() => go(Math.min(targets.length - 1, target + 1))} disabled={target === targets.length - 1} aria-label="Nākamais">
        ▶
      </button>
      <select value={target} onChange={(e) => go(Number(e.target.value))} aria-label="Objekts">
        {grouped.map(([project, rows]) => (
          <optgroup key={project || "-"} label={project ? `Projekts ${project}` : "Bez projekta"}>
            {rows.map((t) => (
              <option key={t.target_no} value={t.target_no}>
                {t.target_no + 1}. {label(t)}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      <input
        list="targets-list"
        placeholder="Meklēt…"
        value={q}
        onChange={(e) => {
          setQ(e.target.value);
          const hit = targets.find((t) => t.designation === e.target.value.trim() || t.input === e.target.value.trim());
          if (hit) {
            go(hit.target_no);
            setQ("");
          }
        }}
        style={{ width: 120, padding: "6px 8px", border: "1px solid var(--line)", borderRadius: 6 }}
        aria-label="Meklēt objektu"
      />
      <datalist id="targets-list">
        {targets.map((t) => (
          <option key={t.target_no} value={t.designation}>
            {t.input ?? ""}
          </option>
        ))}
      </datalist>
    </div>
  );
}

// --- all objects ----------------------------------------------------------------------

function AllView({
  run,
  targets,
  outlines,
  layers,
  setLayers,
  open,
}: {
  run: RunSummary;
  targets: TargetLine[];
  outlines: FeatureCollection<OutlineProps> | null;
  layers: Layers;
  setLayers: (l: Layers) => void;
  open: (t: number) => void;
}) {
  const byRisk = new Map<string, number>();
  for (const t of targets) {
    const w = targetWorst(t) ?? "none";
    byRisk.set(w, (byRisk.get(w) ?? 0) + 1);
  }
  return (
    <div className="overview-wrap">
      <div className="object-head">
        <div className="title">
          <div className="number">{targets.length} objekti</div>
          <div className="meta" style={{ marginTop: 6 }}>
            {(["high", "medium", "unknown", "low", "none"] as const)
              .filter((r) => byRisk.get(r))
              .map((r) => (
                <span key={r} style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
                  <RiskPill risk={r} /> {byRisk.get(r)}
                </span>
              ))}
          </div>
        </div>
        <div className="head-actions">
          <button className="btn" onClick={() => open(0)}>
            Atvērt pirmo objektu
          </button>
          <a className="btn primary" href={api.reportUrl(run.id)} download data-testid="excel">
            ⤓ Lejupielādēt Excel
          </a>
        </div>
      </div>
      <MapView runId={run.id} outlines={outlines} focus={null} attention={null} layers={layers} setLayers={setLayers} onSelect={open} compact />
      <OverviewTable targets={targets} modules={run.modules} names={MODULE_SHORT} onOpen={open} />
    </div>
  );
}

// --- rows not checked ---------------------------------------------------------------------

function NotChecked({ rows }: { rows: InputRow[] }) {
  return (
    <details className="card" style={{ marginTop: 14, borderLeftColor: "#7A7A7A" }} open={rows.some((r) => r.target_nos.length === 0)}>
      <summary>
        <span className="t">Neatrasts / nav pārbaudīts ({rows.length})</span>
        <span className="st">tāpat kā Excel lapā „Neatrasts”</span>
      </summary>
      <div className="content">
        <table className="overview">
          <thead>
            <tr>
              <th>Rinda</th>
              <th>Kolonna</th>
              <th>Ievadīts</th>
              <th>Statuss</th>
              <th>Iemesls</th>
              <th>Ieteikumi</th>
            </tr>
          </thead>
          <tbody>
            {rows.flatMap((r) =>
              r.problems.map((p, i) => (
                <tr key={`${r.input_no}-${i}`}>
                  <td>{r.row_no}</td>
                  <td>{COLUMN_LV[p.column] ?? p.column}</td>
                  <td>{p.column === "adrese" ? r.address : p.column === "vertiba" ? r.value : ""}</td>
                  <td>{INPUT_STATUS_LV[p.status] ?? p.status}</td>
                  <td>{p.reason}</td>
                  <td>
                    {p.suggestions.slice(0, 3).map((s) => (
                      <div key={s.designation} className="hint">
                        {s.label} {s.designation}
                        {s.description ? ` – ${s.description}` : ""}
                      </div>
                    ))}
                  </td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      </div>
    </details>
  );
}
