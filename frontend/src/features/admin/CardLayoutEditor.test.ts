import { describe, it, expect } from "vitest";
import { moveFieldBetweenSections } from "./CardLayoutEditor";
import type { SectionDef } from "@/types";

function schema(): SectionDef[] {
  return [
    {
      section: "Application Information",
      fields: [
        { key: "hostingType", label: "Hosting Type", type: "single_select" },
        { key: "commercialApplication", label: "Commercial", type: "boolean" },
      ],
    },
    {
      section: "Assessment",
      fields: [{ key: "timeModel", label: "TIME Model", type: "single_select" }],
    },
  ];
}

describe("moveFieldBetweenSections", () => {
  it("moves a field to the target section, preserving its definition", () => {
    const next = moveFieldBetweenSections(schema(), 0, "hostingType", 1);
    expect(next).not.toBeNull();
    const src = next![0].fields.map((f) => f.key);
    const dst = next![1].fields;
    expect(src).toEqual(["commercialApplication"]);
    expect(dst.map((f) => f.key)).toEqual(["timeModel", "hostingType"]);
    // Definition preserved (type kept), landed ungrouped in column 0.
    const moved = dst.find((f) => f.key === "hostingType")!;
    expect(moved.type).toBe("single_select");
    expect(moved.group).toBeUndefined();
    expect(moved.column).toBe(0);
  });

  it("clears any group when moving (target may not share groups)", () => {
    const s = schema();
    s[0].fields[0].group = "Hosting";
    s[0].fields[0].column = 1;
    const next = moveFieldBetweenSections(s, 0, "hostingType", 1);
    const moved = next![1].fields.find((f) => f.key === "hostingType")!;
    expect(moved.group).toBeUndefined();
    expect(moved.column).toBe(0);
  });

  it("does not mutate the input schema", () => {
    const s = schema();
    const before = JSON.stringify(s);
    moveFieldBetweenSections(s, 0, "hostingType", 1);
    expect(JSON.stringify(s)).toBe(before);
  });

  it("returns null for a no-op (same section), missing field, or bad index", () => {
    expect(moveFieldBetweenSections(schema(), 0, "hostingType", 0)).toBeNull();
    expect(moveFieldBetweenSections(schema(), 0, "doesNotExist", 1)).toBeNull();
    expect(moveFieldBetweenSections(schema(), 0, "hostingType", 5)).toBeNull();
    expect(moveFieldBetweenSections(schema(), -1, "hostingType", 1)).toBeNull();
  });
});
