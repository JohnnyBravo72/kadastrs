import { describe, expect, it } from "vitest";
import { cellStyle, NOT_APPLICABLE, RISK, RISK_ORDER, worst } from "./risk";
import { parseUrl, toSearch } from "./url";

describe("risk", () => {
  it("orders levels like rules.yaml", () => {
    expect(worst(["low", "unknown", "none"])).toBe("unknown");
    expect(worst(["medium", "unknown"])).toBe("medium");
    expect(worst(["none", null, undefined, "bogus"])).toBe("none");
    expect(worst([])).toBeNull();
  });

  it("gives every level a colour, an icon and a Latvian word", () => {
    const colours = new Set(RISK_ORDER.map((r) => RISK[r].color));
    expect(colours.size).toBe(RISK_ORDER.length);
    for (const r of RISK_ORDER) {
      expect(RISK[r].icon.length).toBeGreaterThan(0);
      expect(RISK[r].label.length).toBeGreaterThan(0);
    }
  });

  it("shows not-applicable results without a risk", () => {
    expect(cellStyle("not_applicable", "none")).toBe(NOT_APPLICABLE);
    expect(cellStyle("found", "high")).toBe(RISK.high);
  });
});

describe("url", () => {
  it("round-trips the view state", () => {
    const s = { run: 48, target: 3, view: "all" as const };
    expect(parseUrl(toSearch(s))).toEqual(s);
    expect(parseUrl("?run=x&target=-1")).toEqual({ run: null, target: 0, view: "object" });
    expect(toSearch({ run: null, target: 0, view: "object" })).toBe("");
  });
});
