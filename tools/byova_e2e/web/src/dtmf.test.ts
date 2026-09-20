import { describe, expect, it } from "vitest";

import { validateDtmfDigit } from "./dtmf";

describe("validateDtmfDigit", () => {
  it.each(["0", "5", "9", "A", "D", "*", "#"])(
    "accepts one SDK-supported digit: %s",
    (digit) => {
      expect(validateDtmfDigit(digit)).toBe(digit);
    },
  );

  it.each(["", "12", "a", "E", 5, undefined])(
    "rejects invalid or multi-digit input: %s",
    (value) => {
      expect(() => validateDtmfDigit(value)).toThrow(
        "DTMF actions require exactly one control digit",
      );
    },
  );
});
