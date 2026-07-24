/** Resolve the Calling SDK's bundler-dependent CommonJS default export. */
export function unwrapDefaultExport<T>(module: T | { default?: T }): T {
  if (
    typeof module === "object" &&
    module !== null &&
    "default" in module &&
    module.default !== undefined
  ) {
    return module.default;
  }
  return module as T;
}
