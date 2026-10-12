// The entry dialog's unit checklist (PLAN.md §8.1 step 2): tri-state "Atzīmēt
// visu", the counter "5 no 12" and the type filter. Pure functions, so vitest
// covers them without a browser.

export interface UnitItem {
  type: string;
  designation: string;
}

export type TriState = "all" | "none" | "some";

export const unitKey = (u: UnitItem) => `${u.type}:${u.designation}`;

/** Units shown under a type filter ("" = all types). */
export function visible<T extends UnitItem>(units: T[], filter: string): T[] {
  return filter ? units.filter((u) => u.type === filter) : units;
}

/** State of "Atzīmēt visu" over the units shown. */
export function triState(units: UnitItem[], ticked: Set<string>): TriState {
  const n = units.filter((u) => ticked.has(unitKey(u))).length;
  if (n === 0) return "none";
  return n === units.length ? "all" : "some";
}

/** One click on "Atzīmēt visu": all shown units ticked, or (when all already
 *  are) all shown units unticked. Units hidden by the filter keep their state. */
export function toggleAll(units: UnitItem[], ticked: Set<string>): Set<string> {
  const next = new Set(ticked);
  const all = triState(units, ticked) === "all";
  for (const u of units) {
    if (all) next.delete(unitKey(u));
    else next.add(unitKey(u));
  }
  return next;
}

export function toggleOne(u: UnitItem, ticked: Set<string>): Set<string> {
  const next = new Set(ticked);
  if (next.has(unitKey(u))) next.delete(unitKey(u));
  else next.add(unitKey(u));
  return next;
}

/** "5 no 12" over all units (not only the shown ones). */
export function counter(units: UnitItem[], ticked: Set<string>): string {
  return `${units.filter((u) => ticked.has(unitKey(u))).length} no ${units.length}`;
}

/** What goes to the API: null when every unit is ticked (the whole property). */
export function selection(units: UnitItem[], ticked: Set<string>): UnitItem[] | null {
  const picked = units.filter((u) => ticked.has(unitKey(u)));
  return picked.length === units.length ? null : picked.map(({ type, designation }) => ({ type, designation }));
}

/** Types present, in a fixed order, with counts (the filter buttons). */
export function typeCounts(units: UnitItem[]): [string, number][] {
  const order = ["parcel", "parcel_part", "building", "premise_group"];
  const counts = new Map<string, number>();
  for (const u of units) counts.set(u.type, (counts.get(u.type) ?? 0) + 1);
  return [...counts.entries()].sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]));
}

/** Latvian noun after a number: 1, 21, 31 … take the singular, 11 the plural. */
export function lvCount(n: number, one: string, many: string): string {
  return `${n} ${n % 10 === 1 && n % 100 !== 11 ? one : many}`;
}

export interface Totals {
  objects: number; // targets: a property counts once
  properties: number; // of them, properties
  units: number; // units checked (a property's ticked units; any other object is one)
  sources: number;
}

/** The dialog footer: "1 īpašums · 12 vienības · 9 avoti" when every object is
 *  a property, else "N objekti (M vienības) · K avoti" (units only when they
 *  differ from the objects). */
export function totalsText(t: Totals): string {
  const sources = lvCount(t.sources, "avots", "avoti");
  if (t.objects > 0 && t.properties === t.objects) {
    return `${lvCount(t.properties, "īpašums", "īpašumi")} · ${lvCount(t.units, "vienība", "vienības")} · ${sources}`;
  }
  const units = t.units !== t.objects ? ` (${lvCount(t.units, "vienība", "vienības")})` : "";
  return `${lvCount(t.objects, "objekts", "objekti")}${units} · ${sources}`;
}
