import { describe, expect, it } from "vitest";

import { calculateRms } from "./audio-level";

describe("calculateRms", () => {
  it("returns zero for digital silence", () => {
    expect(calculateRms(new Uint8Array([128, 128, 128, 128]))).toBe(0);
  });

  it("measures non-silent samples", () => {
    expect(calculateRms(new Uint8Array([0, 128, 255, 128]))).toBeGreaterThan(0.7);
  });
});
