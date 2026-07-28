export function calculateRms(values: Uint8Array): number {
  let squaredTotal = 0;
  for (const value of values) {
    const sample = (value - 128) / 128;
    squaredTotal += sample * sample;
  }
  return Math.sqrt(squaredTotal / values.length);
}
