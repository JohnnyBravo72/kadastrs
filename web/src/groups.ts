// Project groups of a run (PLAN.md §8.2): every change is saved as a new
// grouping row on the server (insert-only); these helpers build the next state.
// "Bez projekta" (id "none") always exists and is always last.

import type { Grouping, TargetLine } from "./api";

export const NONE_ID = "none";
export type GroupState = Pick<Grouping, "groups" | "assignment">;

export function newId(state: GroupState): string {
  let n = state.groups.length + 1;
  while (state.groups.some((g) => g.id === `g${n}`)) n++;
  return `g${n}`;
}

const named = (state: GroupState) => state.groups.filter((g) => g.id !== NONE_ID);
const withNone = (groups: GroupState["groups"]) => [...groups, { id: NONE_ID, name: "Bez projekta" }];

export function nameTaken(state: GroupState, name: string, except?: string): boolean {
  const n = name.trim().toLocaleLowerCase("lv");
  return n === "bez projekta" || named(state).some((g) => g.id !== except && g.name.toLocaleLowerCase("lv") === n);
}

export function addGroup(state: GroupState, name: string): GroupState {
  return { groups: withNone([...named(state), { id: newId(state), name: name.trim() }]), assignment: state.assignment };
}

export function renameGroup(state: GroupState, id: string, name: string): GroupState {
  return {
    groups: withNone(named(state).map((g) => (g.id === id ? { ...g, name: name.trim() } : g))),
    assignment: state.assignment,
  };
}

/** A deleted group's objects go to "Bez projekta". */
export function deleteGroup(state: GroupState, id: string): GroupState {
  const assignment = Object.fromEntries(Object.entries(state.assignment).map(([t, g]) => [t, g === id ? NONE_ID : g]));
  return { groups: withNone(named(state).filter((g) => g.id !== id)), assignment };
}

export function moveTargets(state: GroupState, targets: number[], to: string): GroupState {
  const assignment = { ...state.assignment };
  for (const t of targets) assignment[String(t)] = to;
  return { groups: state.groups, assignment };
}

/** Groups in display order with their targets; empty groups kept (just created). */
export function grouped(state: GroupState, targets: TargetLine[]): { id: string; name: string; targets: TargetLine[] }[] {
  return state.groups.map((g) => ({
    ...g,
    targets: targets.filter((t) => (state.assignment[String(t.target_no)] ?? NONE_ID) === g.id),
  }));
}
