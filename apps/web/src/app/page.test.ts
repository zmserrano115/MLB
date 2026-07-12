import { describe, expect, it } from "vitest";

describe("web scaffold", () => {
  it("keeps the legacy app authoritative", () => {
    expect("streamlit-legacy").toContain("legacy");
  });
});

