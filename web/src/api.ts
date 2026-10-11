// Typed access to the FastAPI backend (same origin). Every map request names
// the run, so the data comes from the run's pinned dataset versions.

import type { Bucket, Risk } from "./risk";

export interface Suggestion {
  type: string;
  designation: string;
  label: string;
  description: string | null;
  city: string | null;
  match_type: string;
  status: "EKS" | "DEL" | null;
  current_address: string | null;
}

export interface SuggestResponse {
  suggestions: Suggestion[];
  notices: { code: string; message: string }[];
}

export interface DatasetVersion {
  id: string;
  name: string;
  dataset_date: string;
  dataset_version_id: number;
  datagov_url: string | null;
  coverage?: string | null;
  freshness?: { status: string; label_lv: string; text_lv: string; warn: boolean } | null;
}

export interface RunSummary {
  id: number;
  created_at: string;
  origin: string;
  modules: string[];
  module_names: Record<string, string>;
  targets: number;
  rule_set: { version: string; status: string; sha256: string };
  dataset_versions: DatasetVersion[];
  inputs?: { rows: number; checked: number; not_checked: number };
  report_url?: string;
}

export interface TargetLine {
  target_no: number;
  input: string | null;
  type: string;
  designation: string;
  given_address: string | null;
  project_no: string | null;
  label: string | null;
  warnings: { code: string; message: string }[];
  modules: Record<string, { status: string; summary_status: Bucket; reason: string | null; risk: Risk }>;
}

export interface Warning {
  code: string;
  message: string;
  [key: string]: unknown;
}

export interface SourceRef {
  id: string;
  name: string;
  dataset_date: string;
  dataset_version_id: number;
  datagov_url: string | null;
}

export interface ModuleResult {
  module: string;
  module_no: number;
  module_name: string;
  subject: { type: string; id: string };
  scope: "target" | "unit";
  status: string;
  summary_status: Bucket;
  reason: string | null;
  risk: Risk;
  rule_ids: string[];
  rules: { id: string; level: Risk; text_lv: string }[];
  items: Record<string, unknown>[];
  items_text: string[];
  match_type: string | null;
  warnings: Warning[];
  source: SourceRef | null;
}

export interface TargetDetail extends TargetLine {
  results: { module: string; module_no: number; result: ModuleResult | null; units: ModuleResult[] }[];
}

export interface InputRow {
  input_no: number;
  row_no: number;
  value: string | null;
  project_no: string | null;
  address: string | null;
  status: string;
  problems: { column: string; status: string; reason: string | null; suggestions: { designation: string; label: string; description: string | null }[] }[];
  target_nos: number[];
}

export interface Feature<P = Record<string, unknown>> {
  type: "Feature";
  geometry: GeoJSON.Geometry;
  properties: P;
}

export interface FeatureCollection<P = Record<string, unknown>> {
  type: "FeatureCollection";
  features: Feature<P>[];
  sources?: SourceRef[];
  truncated?: boolean;
  bbox_by_target?: Record<string, [number, number, number, number]>;
}

export interface OutlineProps {
  target_no: number;
  unit: string;
  unit_type: string;
  basis: string;
  risk: Risk | null;
  target_risk: Risk | null;
  designation: string;
  project_no: string | null;
}

export interface AttentionProps {
  module: string;
  module_no: number;
  module_name: string;
  unit: string;
  item: string;
  rule_ids: string[];
  rule_texts: string[];
  risk: Risk;
  overlap_m2: number | null;
  share: number | null;
  area_m2?: number;
  kind?: string;
  case_number?: string;
  match_label?: string;
  stage?: string;
}

export type LayerName = "kadastrs" | "pludi" | "daba" | "bis";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function json<T>(resp: Response): Promise<T> {
  if (!resp.ok) {
    let detail = `${resp.status} ${resp.statusText}`;
    try {
      const body = await resp.json();
      if (body?.detail) detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(resp.status, detail);
  }
  return resp.json() as Promise<T>;
}

const get = <T>(url: string, signal?: AbortSignal) => fetch(url, { signal }).then((r) => json<T>(r));

export const api = {
  suggest: (q: string, kind: "cadastre" | "address", signal?: AbortSignal) =>
    get<SuggestResponse>(`/api/suggest?${new URLSearchParams({ q, kind })}`, signal),
  batch: (form: FormData) => fetch("/api/batch", { method: "POST", body: form }).then((r) => json<RunSummary>(r)),
  run: (id: number) => get<RunSummary>(`/api/runs/${id}`),
  targets: (id: number) => get<TargetLine[]>(`/api/runs/${id}/targets`),
  target: (id: number, no: number) => get<TargetDetail>(`/api/runs/${id}/targets/${no}`),
  inputs: (id: number) => get<InputRow[]>(`/api/runs/${id}/inputs`),
  outlines: (id: number) => get<FeatureCollection<OutlineProps>>(`/api/runs/${id}/map/targets`),
  attention: (id: number, no: number) =>
    get<FeatureCollection<AttentionProps>>(`/api/runs/${id}/targets/${no}/attention`),
  layer: (id: number, name: LayerName, bbox: string, signal?: AbortSignal) =>
    get<FeatureCollection>(`/api/runs/${id}/layers/${name}?${new URLSearchParams({ bbox })}`, signal),
  reportUrl: (id: number) => `/api/runs/${id}/report.xlsx`,
};
