const DTMF_CONTROL_DIGIT = /^[0-9A-D*#]$/;

export function validateDtmfDigit(value: unknown): string {
  if (typeof value !== "string" || !DTMF_CONTROL_DIGIT.test(value)) {
    throw new Error("DTMF actions require exactly one control digit");
  }
  return value;
}
