// The view lives in the URL (?run=12&target=3&view=object|all), so a link
// reopens the same run, object and view.

export type View = "object" | "all";

export interface UrlState {
  run: number | null;
  target: number;
  view: View;
}

export function parseUrl(search: string): UrlState {
  const p = new URLSearchParams(search);
  const run = Number.parseInt(p.get("run") ?? "", 10);
  const target = Number.parseInt(p.get("target") ?? "", 10);
  const view = p.get("view") === "all" ? "all" : "object";
  return {
    run: Number.isFinite(run) && run > 0 ? run : null,
    target: Number.isFinite(target) && target >= 0 ? target : 0,
    view,
  };
}

export function toSearch(state: UrlState): string {
  if (state.run === null) return "";
  const p = new URLSearchParams({ run: String(state.run), target: String(state.target) });
  if (state.view === "all") p.set("view", "all");
  return `?${p.toString()}`;
}
