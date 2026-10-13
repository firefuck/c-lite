import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const here = fileURLToPath(new URL(".", import.meta.url));

// The build lands inside the Python package, so `clite dashboard` serves it with no Node on the
// user's machine. File names carry no content hash: the committed bundle keeps stable paths,
// and the server sends it with `Cache-Control: no-store`.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: resolve(here, "../src/clite/server/static"),
    emptyOutDir: true,
    assetsDir: "assets",
    rollupOptions: {
      output: {
        entryFileNames: "assets/app.js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: "assets/app[extname]",
      },
    },
  },
  server: {
    port: 9120,
  },
});
