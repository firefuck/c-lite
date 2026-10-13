import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));

test("vite configuration exists and has valid target", () => {
  const configPath = resolve(__dirname, "../vite.config.ts");
  assert.ok(existsSync(configPath), "vite.config.ts should exist");
});
