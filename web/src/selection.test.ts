import { describe, expect, it } from "vitest";
import type { TargetLine } from "./api";
import { addGroup, deleteGroup, grouped, moveTargets, nameTaken, NONE_ID, renameGroup } from "./groups";
import { counter, selection, toggleAll, toggleOne, triState, typeCounts, unitKey, visible } from "./selection";

const UNITS = [
  { type: "parcel", designation: "09000360220" },
  { type: "parcel_part", designation: "09000360220001" },
  { type: "building", designation: "09000360220002" },
  { type: "building", designation: "09000360220012" },
  { type: "building", designation: "09000360220013" },
];
const all = () => new Set(UNITS.map(unitKey));

describe("unit checklist", () => {
  it("starts with every unit ticked", () => {
    expect(triState(UNITS, all())).toBe("all");
    expect(counter(UNITS, all())).toBe("5 no 5");
    expect(selection(UNITS, all())).toBeNull();
  });

  it("unticking one gives the mixed state and a selection", () => {
    const t = toggleOne(UNITS[2], all());
    expect(triState(UNITS, t)).toBe("some");
    expect(counter(UNITS, t)).toBe("4 no 5");
    expect(selection(UNITS, t)?.map((u) => u.designation)).not.toContain("09000360220002");
  });

  it("select all: one click from mixed or none ticks all, from all unticks all", () => {
    const some = toggleOne(UNITS[0], all());
    expect(triState(UNITS, toggleAll(UNITS, some))).toBe("all");
    const none = toggleAll(UNITS, all());
    expect(triState(UNITS, none)).toBe("none");
    expect(counter(UNITS, none)).toBe("0 no 5");
    expect(triState(UNITS, toggleAll(UNITS, none))).toBe("all");
  });

  it("the type filter limits select all to the shown units", () => {
    const buildings = visible(UNITS, "building");
    expect(buildings).toHaveLength(3);
    const t = toggleAll(buildings, all()); // all buildings were ticked: untick them
    expect(counter(UNITS, t)).toBe("2 no 5");
    expect(triState(visible(UNITS, "parcel"), t)).toBe("all");
    expect(typeCounts(UNITS)).toEqual([
      ["parcel", 1],
      ["parcel_part", 1],
      ["building", 3],
    ]);
  });
});

const line = (n: number, project: string | null = null) => ({ target_no: n, project_no: project }) as TargetLine;

describe("project groups", () => {
  const start = { groups: [{ id: "p1", name: "P-1" }, { id: NONE_ID, name: "Bez projekta" }], assignment: { "0": "p1", "1": NONE_ID } };

  it("creates, renames and keeps Bez projekta last", () => {
    const a = addGroup(start, " Jauns ");
    expect(a.groups.map((g) => g.name)).toEqual(["P-1", "Jauns", "Bez projekta"]);
    const r = renameGroup(a, a.groups[1].id, "Pārdēvēts");
    expect(r.groups[1].name).toBe("Pārdēvēts");
    expect(nameTaken(r, "p-1")).toBe(true);
    expect(nameTaken(r, "bez projekta")).toBe(true);
    expect(nameTaken(r, "P-1", "p1")).toBe(false);
  });

  it("moves objects and deleting a group sends them to Bez projekta", () => {
    const m = moveTargets(start, [1], "p1");
    expect(grouped(m, [line(0), line(1)])[0].targets).toHaveLength(2);
    const d = deleteGroup(m, "p1");
    expect(d.groups.map((g) => g.id)).toEqual([NONE_ID]);
    expect(d.assignment).toEqual({ "0": NONE_ID, "1": NONE_ID });
  });
});
