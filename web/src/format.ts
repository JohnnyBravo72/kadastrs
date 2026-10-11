// Latvian number formatting and HTML escaping for Leaflet popups (strings).

const nf0 = new Intl.NumberFormat("lv-LV", { maximumFractionDigits: 0 });
const nf1 = new Intl.NumberFormat("lv-LV", { maximumFractionDigits: 1 });
const nf2 = new Intl.NumberFormat("lv-LV", { maximumFractionDigits: 2 });

export function m2(value: number | null | undefined): string {
  if (value === null || value === undefined) return "–";
  return `${value >= 100 ? nf0.format(value) : nf2.format(value)} m²`;
}

export function pct(share: number | null | undefined): string {
  if (share === null || share === undefined) return "–";
  const p = share * 100;
  return `${p > 0 && p < 0.1 ? "< 0,1" : nf1.format(p)} %`;
}

export function esc(text: unknown): string {
  return String(text ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

/** A popup: a title and label/value rows (values escaped; empty rows left out). */
export function popup(title: string, rows: [string, unknown][], footer?: string): string {
  const body = rows
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`)
    .join("");
  return `<div class="popup"><h4>${esc(title)}</h4><table>${body}</table>${footer ? `<div class="hint">${esc(footer)}</div>` : ""}</div>`;
}

export const TYPE_LV: Record<string, string> = {
  property: "Nekustamais īpašums",
  parcel: "Zemes vienība",
  building: "Būve",
  parcel_part: "Zemes vienības daļa",
  premise_group: "Telpu grupa",
};
