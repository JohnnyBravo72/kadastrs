import L from "leaflet";
import { useEffect, useRef, useState } from "react";
import { api, type AttentionProps, type FeatureCollection, type LayerName, type OutlineProps } from "../api";
import { m2, pct, popup } from "../format";
import { isRisk, RISK, RISK_ORDER } from "../risk";

export type LayerKey = LayerName | "attention";
export type Layers = Record<LayerKey, { on: boolean; opacity: number }>;

export const DEFAULT_LAYERS: Layers = {
  attention: { on: true, opacity: 1 },
  kadastrs: { on: true, opacity: 0.9 },
  pludi: { on: false, opacity: 0.75 },
  daba: { on: false, opacity: 0.8 },
  bis: { on: false, opacity: 1 },
};

const DATA_LAYERS: LayerName[] = ["kadastrs", "pludi", "daba", "bis"];
const PANES: [string, number][] = [
  ["kadastrs", 405],
  ["pludi", 410],
  ["daba", 415],
  ["targets", 430],
  ["attention", 440],
  ["bis", 450],
];
const MAX_VIEW_M = 5800; // the API refuses a view over 6 km

export const NATURE_STYLE: Record<string, { label: string; color: string; dash?: string }> = {
  protected_area: { label: "Īpaši aizsargājama dabas teritorija", color: "#2E7D32" },
  protected_area_zone: { label: "ĪADT funkcionālā zona", color: "#66BB6A", dash: "4 3" },
  microreserve: { label: "Mikroliegums", color: "#7B1FA2" },
  microreserve_buffer: { label: "Mikrolieguma buferzona", color: "#BA68C8", dash: "5 4" },
  nature_monument: { label: "Dabas piemineklis", color: "#6D4C41" },
  habitat: { label: "Aizsargājams biotops", color: "#9E9D24" },
};
const FLOOD_COLOR = "#2F6FD0";
const BIS_COLOR = "#3F2A7A";

interface Props {
  runId: number;
  outlines: FeatureCollection<OutlineProps> | null;
  focus: number | null; // a target, or null = all targets
  attention: FeatureCollection<AttentionProps> | null;
  layers: Layers;
  setLayers: (l: Layers) => void;
  onSelect?: (targetNo: number) => void;
  compact?: boolean;
}

/** Leaflet map: OSM basemap, the checked objects coloured by worst risk, the
 *  attention areas (hatched, risk of the fired rule) and the data layers of the
 *  run's pinned versions, loaded for the current view. */
export function MapView({ runId, outlines, focus, attention, layers, setLayers, onSelect, compact }: Props) {
  const div = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const groups = useRef<Partial<Record<string, L.Layer>>>({});
  const layersRef = useRef(layers);
  const [dates, setDates] = useState<Partial<Record<LayerName, string>>>({});
  const [tooLarge, setTooLarge] = useState(false);
  const [loading, setLoading] = useState(0);
  const [truncated, setTruncated] = useState(false);
  const [panelOpen, setPanelOpen] = useState(!compact);
  layersRef.current = layers;

  // --- map ------------------------------------------------------------------------
  useEffect(() => {
    const m = L.map(div.current!, { minZoom: 7, maxZoom: 19, zoomSnap: 0.5 }).setView([56.95, 24.1], 8);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> līdzautori',
    }).addTo(m);
    m.attributionControl.setPrefix("Leaflet");
    L.control.scale({ imperial: false }).addTo(m);
    for (const [name, z] of PANES) m.createPane(name).style.zIndex = String(z);
    map.current = m;
    return () => {
      m.remove();
      map.current = null;
    };
  }, []);

  const replace = (key: string, layer: L.Layer | null) => {
    const m = map.current;
    if (!m) return;
    const old = groups.current[key];
    if (old) m.removeLayer(old);
    delete groups.current[key];
    if (layer) {
      layer.addTo(m);
      groups.current[key] = layer;
    }
  };

  // --- checked objects ------------------------------------------------------------
  useEffect(() => {
    if (!map.current || !outlines) return;
    const layer = L.geoJSON(outlines as GeoJSON.FeatureCollection, {
      pane: "targets",
      style: (f) => {
        const p = f!.properties as OutlineProps;
        const color = isRisk(p.risk) ? RISK[p.risk].color : "#555";
        const mine = focus === null || p.target_no === focus;
        return {
          color,
          weight: mine ? 3.5 : 1.5,
          opacity: mine ? 1 : 0.7,
          fillColor: color,
          fillOpacity: mine ? 0.12 : 0.08,
          dashArray: p.basis === "parcel" ? "6 4" : undefined,
        };
      },
      onEachFeature: (f, l) => {
        const p = f.properties as OutlineProps;
        const r = isRisk(p.risk) ? RISK[p.risk] : null;
        l.bindTooltip(`${p.unit}${r ? ` · ${r.icon} ${r.label}` : ""}`, { sticky: true });
        if (onSelect && focus !== p.target_no) l.on("click", () => onSelect(p.target_no));
        else
          l.bindPopup(
            popup(p.unit, [
              ["Objekts", p.designation],
              ["Risks (sliktākais)", r ? `${r.icon} ${r.label}` : "–"],
              ["Ģeometrija", p.basis === "parcel" ? "pēc zemes vienības" : "objekta"],
              ["Projekts", p.project_no],
            ]),
          );
      },
    });
    replace("targets", layer);
    // all objects: a marker per object too, so objects far apart stay visible
    if (focus === null && outlines.bbox_by_target) {
      const worstOf = new Map<number, OutlineProps>();
      for (const f of outlines.features) worstOf.set(f.properties.target_no, f.properties);
      const markers = Object.entries(outlines.bbox_by_target).map(([no, b]) => {
        const p = worstOf.get(Number(no));
        const r = isRisk(p?.target_risk) ? RISK[p!.target_risk!] : null;
        const marker = L.circleMarker([(b[1] + b[3]) / 2, (b[0] + b[2]) / 2], {
          pane: "attention",
          radius: 7,
          color: "#fff",
          weight: 2,
          fillColor: r?.color ?? "#555",
          fillOpacity: 1,
        });
        marker.bindTooltip(`${p?.designation ?? ""}${r ? ` · ${r.icon} ${r.label}` : ""}`);
        if (onSelect) marker.on("click", () => onSelect(Number(no)));
        return marker;
      });
      replace("markers", L.layerGroup(markers));
    } else {
      replace("markers", null);
    }
    // zoom to the object (or to all objects)
    const box = focus !== null ? outlines.bbox_by_target?.[String(focus)] : null;
    const bounds = box
      ? L.latLngBounds([box[1], box[0]], [box[3], box[2]])
      : layer.getBounds().isValid()
        ? layer.getBounds()
        : null;
    // ~30 % around the object(s): a single parcel lands at about zoom 17-18
    if (bounds) map.current.fitBounds(bounds.pad(0.3), { maxZoom: 18 });
  }, [outlines, focus]);

  // --- attention areas --------------------------------------------------------------
  useEffect(() => {
    if (!map.current) return;
    if (!attention || !layers.attention.on) {
      replace("attention", null);
      return;
    }
    const layer = L.geoJSON(attention as GeoJSON.FeatureCollection, {
      pane: "attention",
      style: (f) => {
        const p = f!.properties as AttentionProps;
        const r = isRisk(p.risk) ? p.risk : "unknown";
        return { color: RISK[r].color, weight: 2.5, fillColor: `url(#hatch-${r})`, fillOpacity: 1 };
      },
      pointToLayer: (f, latlng) => {
        const r = isRisk(f.properties?.risk) ? f.properties.risk : "unknown";
        return L.circleMarker(latlng, {
          pane: "attention",
          radius: 8,
          color: RISK[r as keyof typeof RISK].color,
          weight: 3,
          fillColor: "#fff",
          fillOpacity: 0.95,
        });
      },
      onEachFeature: (f, l) => l.bindPopup(attentionPopup(f.properties as AttentionProps)),
    });
    replace("attention", layer);
  }, [attention, layers.attention.on]);

  // --- data layers for the view ---------------------------------------------------------
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    let timer = 0;
    let ctrl = new AbortController();
    const refresh = () => {
      ctrl.abort();
      ctrl = new AbortController();
      const b = m.getBounds();
      const w = m.distance(b.getSouthWest(), b.getSouthEast());
      const h = m.distance(b.getSouthWest(), b.getNorthWest());
      const big = Math.max(w, h) > MAX_VIEW_M;
      const wanted = DATA_LAYERS.filter((k) => layersRef.current[k].on);
      setTooLarge(big && wanted.length > 0);
      for (const k of DATA_LAYERS) if (!layersRef.current[k].on || big) replace(k, null);
      if (big) return;
      const bbox = [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()].map((v) => v.toFixed(6)).join(",");
      setTruncated(false);
      for (const k of wanted) {
        setLoading((n) => n + 1);
        api
          .layer(runId, k, bbox, ctrl.signal)
          .then((fc) => {
            replace(k, dataLayer(k, fc));
            if (fc.truncated) setTruncated(true);
            const d = (fc.sources ?? []).map((s) => s.dataset_date).sort();
            if (d.length) setDates((old) => ({ ...old, [k]: d.length > 1 && d[0] !== d[d.length - 1] ? `${d[0]} – ${d[d.length - 1]}` : d[0] }));
          })
          .catch(() => undefined)
          .finally(() => setLoading((n) => Math.max(0, n - 1)));
      }
    };
    const onMove = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(refresh, 250);
    };
    m.on("moveend", onMove);
    onMove();
    return () => {
      m.off("moveend", onMove);
      window.clearTimeout(timer);
      ctrl.abort();
    };
  }, [runId, layers.kadastrs.on, layers.pludi.on, layers.daba.on, layers.bis.on]);

  // --- opacity per layer (its pane) -------------------------------------------------------
  useEffect(() => {
    const m = map.current;
    if (!m) return;
    for (const k of Object.keys(layers) as LayerKey[]) {
      const pane = m.getPane(k);
      if (pane) pane.style.opacity = String(layers[k].opacity);
    }
  }, [layers]);

  return (
    <div className={compact ? "overview-map" : "map-wrap"}>
      <Patterns />
      <div ref={div} className="map" data-testid="map" />
      {tooLarge && !compact && <div className="map-msg">Pietuviniet karti, lai redzētu slāņus</div>}
      {!tooLarge && loading > 0 && <div className="map-msg">Ielādē slāņus…</div>}
      {!tooLarge && loading === 0 && truncated && <div className="map-msg">Parādīta daļa objektu: pietuviniet karti</div>}
      <LayerPanel layers={layers} setLayers={setLayers} dates={dates} open={panelOpen} setOpen={setPanelOpen} />
    </div>
  );
}

// --- layer rendering -----------------------------------------------------------------------

function dataLayer(key: LayerName, fc: FeatureCollection): L.Layer {
  return L.geoJSON(fc as GeoJSON.FeatureCollection, {
    pane: key,
    style: (f) => styleOf(key, (f?.properties ?? {}) as Record<string, unknown>),
    pointToLayer: (_f, latlng) =>
      L.circleMarker(latlng, { pane: key, radius: 5, color: "#fff", weight: 1.5, fillColor: BIS_COLOR, fillOpacity: 0.95 }),
    onEachFeature: (f, l) => l.bindPopup(layerPopup(key, (f.properties ?? {}) as Record<string, unknown>)),
  });
}

function styleOf(key: LayerName, p: Record<string, unknown>): L.PathOptions {
  if (key === "kadastrs") {
    return p.kind === "building"
      ? { color: "#6d5d4b", weight: 0.8, fillColor: "#b9a58f", fillOpacity: 0.35 }
      : { color: "#56677a", weight: 0.8, fillColor: "#ffffff", fillOpacity: 0.01 };
  }
  if (key === "pludi") {
    return p.kind === "no_flood_map"
      ? { color: "#8a8a8a", weight: 0.6, fillColor: "url(#hatch-noflood)", fillOpacity: 1 }
      : { color: FLOOD_COLOR, weight: 1, fillColor: FLOOD_COLOR, fillOpacity: 0.35 };
  }
  if (key === "daba") {
    const s = NATURE_STYLE[String(p.kind)] ?? { color: "#2E7D32" };
    return { color: s.color, weight: 1.6, dashArray: s.dash, fillColor: s.color, fillOpacity: 0.16 };
  }
  return {};
}

function layerPopup(key: LayerName, p: Record<string, unknown>): string {
  if (key === "kadastrs")
    return popup(p.kind === "building" ? "Būve" : "Zemes vienība", [["Kadastra apzīmējums", p.code]]);
  if (key === "pludi")
    return p.kind === "no_flood_map"
      ? popup("Nav plūdu kartes", [["", "Ārpus 200 gadu applūšanas robežas: plūdu karte šeit nav pieejama vai teritorija nav applūstoša"]])
      : popup("10 gadu plūdu zona", [["Slānis", p.layer_name], ["Avots", "LVĢMC, 3. cikla pavasara palu karte"]]);
  if (key === "daba")
    return popup(String(p.kind_lv ?? "Daba"), [
      ["Nosaukums", p.name],
      ["Zonas veids", p.zone_type],
      ["Kategorija", p.category],
    ]);
  return popup(`Būvniecības lieta ${String(p.case_number ?? "")}`, [
    ["Objekts", p.object_name],
    ["Stadija", p.stage],
    ["Būvniecības veids", p.construction_kind],
    ["Izveidota", p.created_date],
  ]);
}

function attentionPopup(p: AttentionProps): string {
  const r = isRisk(p.risk) ? RISK[p.risk] : null;
  const rows: [string, unknown][] = [
    ["Risks", r ? `${r.icon} ${r.label}` : "–"],
    ["Ieraksts", p.item],
    ["Noteikums", p.rule_texts.join(" ")],
  ];
  if (p.module === "bis") rows.push(["Saistība", p.match_label], ["Stadija", p.stage]);
  else rows.push(["Pārklājums", `${m2(p.overlap_m2)} (${pct(p.share)})`]);
  rows.push(["Vienība", p.unit]);
  return popup(`${p.module_no}. ${p.module_name}`, rows, p.rule_ids.join(", "), p.links);
}

// --- hatch patterns (SVG fill url(#…), shared by every Leaflet SVG pane) ----------------

function Patterns() {
  return (
    <svg width="0" height="0" style={{ position: "absolute" }} aria-hidden focusable="false">
      <defs>
        {RISK_ORDER.map((r) => (
          <pattern key={r} id={`hatch-${r}`} patternUnits="userSpaceOnUse" width="8" height="8" patternTransform="rotate(45)">
            <rect width="8" height="8" fill={RISK[r].color} fillOpacity="0.28" />
            <line x1="0" y1="0" x2="0" y2="8" stroke={RISK[r].color} strokeWidth="3.2" />
          </pattern>
        ))}
        <pattern id="hatch-noflood" patternUnits="userSpaceOnUse" width="9" height="9" patternTransform="rotate(-45)">
          <line x1="0" y1="0" x2="0" y2="9" stroke="#6b6b6b" strokeWidth="1.4" strokeOpacity="0.7" />
        </pattern>
      </defs>
    </svg>
  );
}

// --- layer panel with legend ----------------------------------------------------------

interface LegendEntry {
  label: string;
  swatch: React.CSSProperties;
  className?: string;
}

const LEGEND: { key: LayerKey; title: string; entries: LegendEntry[] }[] = [
  {
    key: "attention",
    title: "Uzmanības zonas",
    entries: RISK_ORDER.filter((r) => r !== "none").map((r) => ({
      label: `${RISK[r].icon} ${RISK[r].label} risks`,
      swatch: {
        borderColor: RISK[r].color,
        background: `repeating-linear-gradient(45deg, ${RISK[r].color} 0 2px, ${RISK[r].color}40 2px 6px)`,
      },
    })),
  },
  {
    key: "kadastrs",
    title: "Kadastrs",
    entries: [
      { label: "Zemes vienības", swatch: { background: "#fff", borderColor: "#56677a" } },
      { label: "Būves", swatch: { background: "#b9a58f", borderColor: "#6d5d4b" } },
    ],
  },
  {
    key: "pludi",
    title: "Plūdi (10 gadu)",
    entries: [
      { label: "10 gadu plūdu zona", swatch: { background: `${FLOOD_COLOR}66`, borderColor: FLOOD_COLOR } },
      { label: "Nav plūdu kartes", swatch: { backgroundColor: "#fff", borderColor: "#8a8a8a" }, className: "hatch" },
    ],
  },
  {
    key: "daba",
    title: "Daba",
    entries: Object.values(NATURE_STYLE).map((s) => ({
      label: s.label,
      swatch: { background: `${s.color}33`, borderColor: s.color, borderStyle: s.dash ? "dashed" : "solid" },
    })),
  },
  {
    key: "bis",
    title: "Būvniecības lietas (BIS)",
    entries: [{ label: "BIS objekts", swatch: { background: BIS_COLOR, borderColor: "#fff" }, className: "dot" }],
  },
];

function LayerPanel({
  layers,
  setLayers,
  dates,
  open,
  setOpen,
}: {
  layers: Layers;
  setLayers: (l: Layers) => void;
  dates: Partial<Record<LayerName, string>>;
  open: boolean;
  setOpen: (o: boolean) => void;
}) {
  const set = (k: LayerKey, patch: Partial<Layers[LayerKey]>) => setLayers({ ...layers, [k]: { ...layers[k], ...patch } });
  return (
    <div className="layer-panel" data-testid="layer-panel">
      <h3>
        Slāņi un apzīmējumi
        <button onClick={() => setOpen(!open)} aria-label={open ? "Sakļaut" : "Izvērst"}>
          {open ? "▾" : "▸"}
        </button>
      </h3>
      {open &&
        LEGEND.map((g) => (
          <div className="layer" key={g.key}>
            <div className="row">
              <label>
                <input
                  type="checkbox"
                  checked={layers[g.key].on}
                  onChange={(e) => set(g.key, { on: e.target.checked })}
                  aria-label={g.title}
                />
                {g.title}
              </label>
              <input
                type="range"
                min={0.2}
                max={1}
                step={0.1}
                value={layers[g.key].opacity}
                onChange={(e) => set(g.key, { opacity: Number(e.target.value) })}
                aria-label={`${g.title}: necaurspīdīgums`}
                title="Necaurspīdīgums"
              />
            </div>
            {g.key !== "attention" && dates[g.key as LayerName] && (
              <div className="date">dati: {dates[g.key as LayerName]}</div>
            )}
            {layers[g.key].on && (
              <div className="legend">
                {g.entries.map((e) => (
                  <div className="item" key={e.label}>
                    <span className={`swatch ${e.className ?? ""}`} style={e.swatch} />
                    {e.label}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      {open && (
        <div className="layer">
          <div className="legend" style={{ marginLeft: 0 }}>
            <div className="item">
              <span className="swatch" style={{ background: "transparent", borderColor: "#333", borderWidth: 2 }} />
              Pārbaudītais objekts (krāsa = sliktākais risks; raustīta līnija = pēc zemes vienības)
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
