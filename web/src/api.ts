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
  sources: string[];
  parent_run_id: number | null;
  rerun_kind: "sources" | "latest" | null;
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

/** "Skatīt avotā": opens the object in the publisher's public system (engine/links.py).
 *  With `copy`, the page is a search page: paste that number there. */
export interface SourceLink {
  system: string;
  url: string;
  copy?: string;
  note?: string;
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
  item_links: SourceLink[][];
  match_type: string | null;
  warnings: Warning[];
  source: SourceRef | null;
}

export interface TargetDetail extends TargetLine {
  results: { module: string; module_no: number; result: ModuleResult | null; units: ModuleResult[] }[];
  links: SourceLink[];
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
  links?: SourceLink[];
}

/** One unit of a property or object at an address (GET /api/property/{n}/units,
 *  GET /api/address/{code}/objects). */
export interface CadastreObject {
  type: string;
  designation: string;
  label: string;
  description: string | null;
  property_numbers: string[];
  parcel_codes: string[];
  has_geometry: boolean | null;
  not_exist: boolean;
  warnings: { code: string; message: string }[];
}

export interface PropertyUnits {
  number: string;
  kind: string | null;
  name: string | null;
  units: CadastreObject[];
  buildings_on_parcels: CadastreObject[];
  counts: Record<string, number>;
  non_existing_excluded: number;
}

export interface AddressObjects {
  address: { varis_code: string; full_text: string; status: "EKS" | "DEL"; city: string | null };
  objects: CadastreObject[];
  current_addresses: { varis_code: string; full_text: string }[];
  non_existing_excluded: number;
  warnings: { code: string; message: string }[];
}

export interface Freshness {
  status: string;
  label_lv: string;
  text_lv: string;
  warn: boolean;
  source_updated: string | null;
  checked_at: string | null;
}

/** GET /api/sources: the registry for the sources checklist and Avoti. */
export interface RegistrySource {
  id: string;
  name: string;
  owner: string;
  group: string;
  order: number;
  type: string;
  default_selected: boolean;
  modules: { id: string; no: number; name: string }[];
  selectable: boolean;
  used_by: string[];
  coverage: string | null;
  partial_coverage: boolean;
  licence: string | null;
  live_version: { dataset_version_id: number; dataset_date: string } | null;
  freshness: Freshness | null;
  datagov_urls: string[];
}

/** An object chosen in the entry dialog (POST /api/batch `entries`). */
export interface Entry {
  value: string;
  kind?: "property" | "parcel" | "building" | null;
  project_no?: string | null;
  address?: string | null;
  applicant?: string | null;
  selected?: { type: string; designation: string }[] | null;
}

export interface PreviewRow {
  row_no: number;
  value: string | null;
  kind: string | null;
  type: string | null;
  status: string;
  checked: boolean;
  project_no: string | null;
  address: string | null;
  applicant_reg_no: string | null;
  corrections: string[];
  warnings: string[];
  duplicate_of: number | null;
  problems: InputRow["problems"];
  targets: { type: string; designation: string; label: string | null }[];
}

export interface JournalRun {
  id: number;
  created_at: string;
  origin: string;
  status: string;
  targets: number;
  projects: string[];
  risk: Risk | null;
  sources: string[];
  modules: string[];
  parent_run_id: number | null;
  rerun_kind: "sources" | "latest" | null;
}

export interface VersionChange {
  id: string;
  name: string | null;
  old_version_id: number | null;
  old_date: string | null;
  new_version_id: number | null;
  new_date: string | null;
}

export interface Grouping {
  id: number | null;
  created_at: string | null;
  origin: string;
  groups: { id: string; name: string }[];
  assignment: Record<string, string>;
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
  propertyUnits: (n: string, signal?: AbortSignal) => get<PropertyUnits>(`/api/property/${encodeURIComponent(n)}/units`, signal),
  addressObjects: (code: string, signal?: AbortSignal) =>
    get<AddressObjects>(`/api/address/${encodeURIComponent(code)}/objects`, signal),
  sources: () => get<RegistrySource[]>("/api/sources"),
  preview: (form: FormData) => fetch("/api/batch/preview", { method: "POST", body: form }).then((r) => json<{ rows: PreviewRow[]; limit: number }>(r)),
  journal: (limit = 100) => get<JournalRun[]>(`/api/runs?limit=${limit}`),
  rerun: (id: number, kind: "sources" | "latest", sources: string[] | null) =>
    fetch(`/api/runs/${id}/rerun`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, sources }),
    }).then((r) => json<RunSummary & { version_changes: VersionChange[] }>(r)),
  changes: (id: number) => get<VersionChange[]>(`/api/runs/${id}/changes`),
  groups: (id: number) => get<Grouping>(`/api/runs/${id}/groups`),
  saveGroups: (id: number, g: Pick<Grouping, "groups" | "assignment">) =>
    fetch(`/api/runs/${id}/groups`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(g),
    }).then((r) => json<Grouping>(r)),
};
