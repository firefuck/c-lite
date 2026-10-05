// Bundle the Electron main process and the preload script. Electron loads CommonJS here.
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

const here = dirname(fileURLToPath(import.meta.url));
const common = { bundle: true, platform: "node", format: "cjs", target: "node22", external: ["electron"], legalComments: "none" };

await build({ ...common, entryPoints: [resolve(here, "src/main.ts")], outfile: resolve(here, "dist/main.cjs") });
await build({ ...common, entryPoints: [resolve(here, "src/preload.ts")], outfile: resolve(here, "dist/preload.cjs") });
console.log("built dist/main.cjs and dist/preload.cjs");
