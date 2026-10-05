// Bundle the TUI into one file and place a copy inside the Python package, so that
// `pip install clite` ships a working `clite tui` without a Node build step on the user's
// machine. Run with: npm run build
//
// The build also records a hash of the sources it was made from (build-info.json). A Python
// test recomputes that hash, so a bundle that was not rebuilt after a source change fails
// the test suite instead of shipping stale.
import { createHash } from "node:crypto";
import { copyFileSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

import { build, version as esbuildVersion } from "esbuild";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "..");
const outfile = resolve(here, "dist/clite-tui.mjs");
const packagedDir = resolve(repoRoot, "src/clite/tui_dist");

// Every directory whose TypeScript ends up in the bundle. Keep in sync with
// tests/cli/test_tui_bundle.py (BUNDLE_SOURCE_DIRS).
const SOURCE_DIRS = ["apps/shared/src", "ui-tui/src"];

function sourceFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return entry.name.endsWith(".ts") ? [path] : [];
  });
}

export function sourceHash() {
  const hash = createHash("sha256");
  const files = SOURCE_DIRS.flatMap((dir) => sourceFiles(resolve(repoRoot, dir)))
    .map((path) => ({ path, name: relative(repoRoot, path).split(sep).join("/") }))
    .sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
  for (const file of files) {
    hash.update(file.name);
    hash.update("\0");
    hash.update(readFileSync(file.path, "utf8").replaceAll("\r\n", "\n"));
    hash.update("\0");
  }
  return hash.digest("hex");
}

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
mkdirSync(packagedDir, { recursive: true });
copyFileSync(outfile, resolve(packagedDir, "clite-tui.mjs"));
writeFileSync(
  resolve(packagedDir, "build-info.json"),
  `${JSON.stringify({ source_hash: sourceHash(), esbuild: esbuildVersion }, null, 2)}\n`,
);
console.log(`built ${outfile}\ncopied to ${packagedDir}`);
