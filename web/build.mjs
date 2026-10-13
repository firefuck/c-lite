// Build the dashboard into the Python package (src/clite/server/static/), so `pip install`
// ships a working dashboard without a Node build step on the user's machine.
// Run with: npm run build
//
// The build also records a hash of the sources it was made from (build-info.json). A Python
// test recomputes that hash, so a bundle that was not rebuilt after a source change fails the
// test suite instead of shipping stale.
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, relative, resolve, sep } from "node:path";
import { fileURLToPath } from "node:url";

import { build, version as viteVersion } from "vite";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(here, "..");
const packagedDir = resolve(repoRoot, "src/clite/server/static");

// Everything that ends up in the bundle. Keep in sync with tests/server/test_dashboard_bundle.py.
const SOURCE_DIRS = ["apps/shared/src", "web/src"];
const SOURCE_FILES = ["web/index.html"];
const EXTENSIONS = [".ts", ".tsx", ".css"];

function sourceFiles(dir) {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = resolve(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return EXTENSIONS.some((extension) => entry.name.endsWith(extension)) ? [path] : [];
  });
}

export function sourceHash() {
  const hash = createHash("sha256");
  const files = [
    ...SOURCE_DIRS.flatMap((dir) => sourceFiles(resolve(repoRoot, dir))),
    ...SOURCE_FILES.map((file) => resolve(repoRoot, file)),
  ]
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

await build({ root: here, configFile: resolve(here, "vite.config.ts"), logLevel: "warn" });
writeFileSync(
  resolve(packagedDir, "build-info.json"),
  `${JSON.stringify({ source_hash: sourceHash(), vite: viteVersion }, null, 2)}\n`,
);
console.log(`built the dashboard into ${packagedDir}`);
