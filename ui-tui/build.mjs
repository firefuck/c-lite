// Bundle the TUI into one file and place a copy inside the Python package, so that
// `pip install clite` ships a working `clite tui` without a Node build step on the user's
// machine. Run with: npm run build
import { copyFileSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const here = dirname(fileURLToPath(import.meta.url));
const outfile = resolve(here, "dist/clite-tui.mjs");
const packaged = resolve(here, "../src/clite/tui_dist/clite-tui.mjs");

await build({
  entryPoints: [resolve(here, "src/entry.ts")],
  outfile,
  bundle: true,
  platform: "node",
  format: "esm",
  target: "node22",
  banner: { js: "#!/usr/bin/env node" },
  legalComments: "none",
});
mkdirSync(dirname(packaged), { recursive: true });
copyFileSync(outfile, packaged);
console.log(`built ${outfile}\ncopied to ${packaged}`);
