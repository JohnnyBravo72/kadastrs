// The view lives in the URL (?run=12&target=3&view=object|all&tab=avoti), so a
// link reopens the same run, object, view and header tab.

export type View = "object" | "all";
export type Tab = "atlase" | "avoti" | "zurnals";

export interface UrlState {
  run: number | null;
  target: number;
  view: View;
  tab: Tab;
}

const TABS: Tab[] = ["atlase", "avoti", "zurnals"];

export function parseUrl(search: string): UrlState {
  const p = new URLSearchParams(search);
  const run = Number.parseInt(p.get("run") ?? "", 10);
  const target = Number.parseInt(p.get("target") ?? "", 10);
  const view = p.get("view") === "all" ? "all" : "object";
  const tab = (TABS as string[]).includes(p.get("tab") ?? "") ? (p.get("tab") as Tab) : "atlase";
  return {
    run: Number.isFinite(run) && run > 0 ? run : null,
    target: Number.isFinite(target) && target >= 0 ? target : 0,
    view,
    tab,
  };
}

export function toSearch(state: UrlState): string {
  const p = new URLSearchParams();
  if (state.run !== null) {
    p.set("run", String(state.run));
    p.set("target", String(state.target));
    if (state.view === "all") p.set("view", "all");
  }
  if (state.tab !== "atlase") p.set("tab", state.tab);
  const s = p.toString();
  return s ? `?${s}` : "";
}
