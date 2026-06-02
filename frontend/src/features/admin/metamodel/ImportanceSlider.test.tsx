import { describe, it, expect } from "vitest";
import { weightToTier } from "./ImportanceSlider";

describe("weightToTier", () => {
  it("maps undefined to Normal (1) so unset weights count by default", () => {
    expect(weightToTier(undefined)).toBe(1);
  });

  it("maps 0 and negatives to Ignore (0)", () => {
    expect(weightToTier(0)).toBe(0);
    expect(weightToTier(-3)).toBe(0);
  });

  it("maps the canonical weights to their tiers", () => {
    expect(weightToTier(1)).toBe(1); // Normal
    expect(weightToTier(2)).toBe(2); // Important
    expect(weightToTier(3)).toBe(3); // Critical
  });

  it("snaps legacy out-of-range weights to the nearest tier without rewriting", () => {
    expect(weightToTier(1.5)).toBe(1);
    expect(weightToTier(5)).toBe(3); // legacy high weight → Critical
  });
});
