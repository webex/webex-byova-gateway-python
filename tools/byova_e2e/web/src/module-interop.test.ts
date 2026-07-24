import { describe, expect, it } from "vitest";

import { unwrapDefaultExport } from "./module-interop";

describe("unwrapDefaultExport", () => {
  it("uses a CommonJS default export when Vite provides one", () => {
    const callingFactory = { init: () => Promise.resolve() };

    expect(unwrapDefaultExport({ default: callingFactory })).toBe(callingFactory);
  });

  it("keeps a direct module export", () => {
    const callingFactory = { init: () => Promise.resolve() };

    expect(unwrapDefaultExport(callingFactory)).toBe(callingFactory);
  });
});
