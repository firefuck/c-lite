// What the installers are built from, checked against the Python package.
//
// These are the facts a user meets before the app even starts: the name in the installer, the
// version it installs, and the icon on the dock. They come from three files in two languages,
// so the test is what keeps them from drifting apart.

import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { DISPLAY_NAME } from "../src/brand.ts";
import { menuTemplate } from "../src/menu.ts";

const here = dirname(fileURLToPath(import.meta.url));
const desktop = resolve(here, "..");
const repoRoot = resolve(desktop, "../..");
const require = createRequire(import.meta.url);

const pkg = JSON.parse(readFileSync(join(desktop, "package.json"), "utf8")) as {
  version: string;
  main: string;
};
const config = require(join(desktop, "electron-builder.config.cjs")) as {
  appId: string;
  productName: string;
  files: string[];
  extraMetadata: { main: string };
  directories: { output: string; buildResources: string };
  mac: { icon: string; identity: unknown };
  win: { icon: string };
  linux: { icon: string };
};

/** The name and version the Python package reports, read from Python itself. */
function pythonFacts(): { version: string; displayName: string } {
  const source = [
    "import json",
    "from clite import __version__",
    "from clite.core.brand import DISPLAY_NAME",
    "print(json.dumps({'version': __version__, 'displayName': DISPLAY_NAME}))",
  ].join("\n");
  const out = execFileSync(process.env["CLITE_PYTHON"] ?? "python3", ["-c", source], {
    env: { ...process.env, PYTHONPATH: join(repoRoot, "src") },
    encoding: "utf8",
  });
  return JSON.parse(out) as { version: string; displayName: string };
}

test("the installer's name and version are the package's", () => {
  const facts = pythonFacts();
  assert.equal(config.productName, facts.displayName);
  assert.equal(DISPLAY_NAME, facts.displayName);
  assert.equal(pkg.version, facts.version);
  assert.equal(config.appId, "dev.clite.desktop");
});

test("the packaged app carries both bundles and nothing else", () => {
  assert.deepEqual(config.files, ["dist/main.cjs", "dist/preload.cjs", "package.json"]);
  assert.equal(config.extraMetadata.main, pkg.main);
  assert.equal(pkg.main, "dist/main.cjs");
  // Not `dist`: that is where build.mjs puts the bundles, and electron-builder would stage the
  // packaged app on top of them.
  assert.equal(config.directories.output, "release");
  assert.equal(config.directories.buildResources, "assets");
});

test("every installer points at the same square icon, big enough for all of them", () => {
  const png = readFileSync(join(desktop, "assets", "icon.png"));
  assert.deepEqual(
    [...png.subarray(0, 8)],
    [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a],
    "assets/icon.png is not a PNG",
  );
  const width = png.readUInt32BE(16);
  const height = png.readUInt32BE(20);
  assert.equal(width, height, "an installer icon has to be square");
  assert.ok(width >= 512, `the icon is ${width}px; 512 is the smallest that scales cleanly`);

  assert.equal(config.mac.icon, "assets/icon.png");
  assert.equal(config.win.icon, "assets/icon.png");
  assert.equal(config.linux.icon, "assets/icon.png");
});

test("macOS builds are unsigned unless a certificate is supplied", () => {
  // `identity: null` is what makes a certificate-less build produce an artifact instead of
  // failing. Signing is a CI secret, not a repository fact.
  assert.equal(config.mac.identity, null);
});

test("the menu is the standard one, and its shape follows the platform", () => {
  const opened: string[] = [];
  const hooks = { openExternal: (url: string) => opened.push(url), docsUrl: "https://docs.test/" };

  const linux = menuTemplate(DISPLAY_NAME, "linux", hooks);
  assert.deepEqual(
    linux.map((item) => item.label),
    ["File", "Edit", "View", "Window", "Help"],
  );

  const mac = menuTemplate(DISPLAY_NAME, "darwin", hooks);
  // macOS puts the app's own menu first, so About and Quit have somewhere to live.
  assert.equal(mac[0]?.label, DISPLAY_NAME);
  assert.deepEqual(
    mac.slice(1).map((item) => item.label),
    ["File", "Edit", "View", "Window", "Help"],
  );

  // File quits the app on Linux; on macOS the app menu already has Quit, so File closes.
  const fileItem = (template: ReturnType<typeof menuTemplate>): unknown =>
    (template.find((item) => item.label === "File")?.submenu as { role: string }[])[0]?.role;
  assert.equal(fileItem(linux), "quit");
  assert.equal(fileItem(mac), "close");

  // Help opens the documentation in the user's browser, never in the window.
  const help = linux.at(-1)?.submenu as { click: () => void }[];
  help[0]?.click();
  assert.deepEqual(opened, [hooks.docsUrl]);
});
