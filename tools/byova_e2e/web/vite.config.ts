import { defineConfig } from "vite";
import { nodePolyfills } from "vite-plugin-node-polyfills";

export default defineConfig({
  // The Webex SDK includes browser-safe modules that still reference the
  // Node-style global alias. Resolve it to the actual browser global.
  define: { global: "globalThis" },
  plugins: [
    nodePolyfills({
      globals: { Buffer: true, global: true, process: true },
      protocolImports: true,
    }),
  ],
  build: { target: "es2022" },
});
