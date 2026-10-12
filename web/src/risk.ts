// Risk and status presentation, used everywhere (chips, map, legend, cards,
// overview table) so one level always looks the same.
// Colours: Paul Tol's "vibrant" scheme, distinguishable with the common forms of
// colour blindness; every level also has an icon and a Latvian word, so colour
// is never the only cue.

export type Risk = "high" | "medium" | "unknown" | "low" | "none";
export type Bucket =
  | "found"
  | "clear"
  | "not_covered"
  | "no_data"
  | "not_applicable"
  | "source_unavailable"
  | "error";

export const RISK_ORDER: Risk[] = ["high", "medium", "unknown", "low", "none"];

export const RISK: Record<Risk, { label: string; icon: string; color: string; text: string }> = {
  high: { label: "augsts", icon: "▲", color: "#CC3311", text: "#FFFFFF" },
  medium: { label: "vidējs", icon: "◆", color: "#EE7733", text: "#1A1A1A" },
  unknown: { label: "nezināms", icon: "?", color: "#7A7A7A", text: "#FFFFFF" },
  low: { label: "zems", icon: "●", color: "#0077BB", text: "#FFFFFF" },
  none: { label: "nav", icon: "✓", color: "#009988", text: "#FFFFFF" },
};

export const NOT_APPLICABLE = { label: "nav piemērojams", icon: "–", color: "#D9D9D9", text: "#333333" };

// The web view says "atrasts / nav atrasts" (review 2026-10-12); the Excel report
// keeps the colleagues' "Ir / Nav".
export const STATUS_LV: Record<Bucket, string> = {
  found: "atrasts",
  clear: "nav atrasts",
  no_data: "nav datu",
  not_covered: "nav pārklājuma",
  not_applicable: "nav piemērojams",
  source_unavailable: "avots nav pieejams",
  error: "kļūda",
};

/** "risks: augsts" (chips and cards). */
export function riskText(risk: string | null | undefined): string {
  return isRisk(risk) ? `risks: ${RISK[risk].label}` : "";
}

/** Risk levels that make a finding worth a map layer: low and up (not none, not unknown). */
export const FINDING_RISKS: Risk[] = ["high", "medium", "low"];

export function isRisk(value: unknown): value is Risk {
  return typeof value === "string" && value in RISK;
}

/** The worst of several levels (order from rules.yaml: high > medium > unknown > low > none). */
export function worst(levels: (string | null | undefined)[]): Risk | null {
  let best: Risk | null = null;
  for (const l of levels) {
    if (!isRisk(l)) continue;
    if (best === null || RISK_ORDER.indexOf(l) < RISK_ORDER.indexOf(best)) best = l;
  }
  return best;
}

/** Style of a module cell: not-applicable results are grey and carry no risk. */
export function cellStyle(bucket: string, risk: string | null) {
  if (bucket === "not_applicable" || !isRisk(risk)) return NOT_APPLICABLE;
  return RISK[risk];
}
