import { describe, it, expect } from "vitest";
import { normalizeContactLink } from "./useLoginBranding";

describe("normalizeContactLink", () => {
  it("returns empty for empty input", () => {
    expect(normalizeContactLink("")).toBe("");
    expect(normalizeContactLink("   ")).toBe("");
  });

  it("preserves links that already have a scheme", () => {
    expect(normalizeContactLink("https://example.com")).toBe("https://example.com");
    expect(normalizeContactLink("http://example.com/path")).toBe("http://example.com/path");
    expect(normalizeContactLink("mailto:foo@bar.com")).toBe("mailto:foo@bar.com");
    expect(normalizeContactLink("tel:+1-555-0100")).toBe("tel:+1-555-0100");
  });

  it("prepends mailto: for bare email addresses", () => {
    expect(normalizeContactLink("support@example.com")).toBe("mailto:support@example.com");
    expect(normalizeContactLink("  it.help@company.co.uk  ")).toBe(
      "mailto:it.help@company.co.uk",
    );
  });

  it("returns other values as-is", () => {
    expect(normalizeContactLink("contact us")).toBe("contact us");
    expect(normalizeContactLink("/internal/help")).toBe("/internal/help");
  });
});
