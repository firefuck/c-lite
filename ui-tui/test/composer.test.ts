// Real Ink rendering and useInput events, not mocks of the completion helpers.
// Bundle TSX in memory, adding a test-only export to avoid changing production code.
import assert from "node:assert/strict";
import { after, before, test } from "node:test";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { PassThrough, Writable } from "node:stream";
import { setTimeout as delay } from "node:timers/promises";
import { stripVTControlCharacters } from "node:util";
import { build } from "esbuild";
import React from "react";
import { render } from "ink";

let Composer: React.ComponentType<any>;
let bundleDir: string;
before(async () => {
  const source = new URL("../src/app/App.tsx", import.meta.url);
  const result = await build({
    stdin: {
      contents: `${await readFile(source, "utf8")}\nexport { Composer };\n`,
      resolveDir: fileURLToPath(new URL("../src/app/", import.meta.url)),
      sourcefile: "App.tsx",
      loader: "tsx",
    },
    bundle: true,
    packages: "external",
    platform: "node",
    format: "esm",
    jsx: "automatic",
    write: false,
  });
  // Keep external React/Ink imports resolving to the project's existing dependencies.
  bundleDir = await mkdtemp(fileURLToPath(new URL(".composer-test-", import.meta.url)));
  await writeFile(`${bundleDir}/composer.mjs`, result.outputFiles[0]!.text);
  ({ Composer } = await import(`${bundleDir}/composer.mjs`));
});
after(async () => {
  if (bundleDir) await rm(bundleDir, { recursive: true, force: true });
});

const catalog = [
  ["help", "Show available commands"],
  ["model", "Choose a model"],
  ["models", "List available models"],
].map(([name, description]) => ({
  name, description, aliases: [], subcommands: [], args_hint: "", category: "test", kind: "builtin",
}));

async function mount(t: { after: (fn: () => void) => void }) {
  const stdin = new PassThrough() as PassThrough & { isTTY: boolean; setRawMode: (raw: boolean) => void };
  stdin.isTTY = true;
  stdin.setRawMode = () => {};
  Object.assign(stdin, { ref() {}, unref() {} });
  let frame = "";
  const stdout = new Writable({
    write(chunk, _encoding, callback) {
      frame = stripVTControlCharacters(chunk.toString());
      callback();
    },
  });
  Object.assign(stdout, { columns: 100, rows: 30 });
  const submissions: string[] = [];
  const instance = render(React.createElement(Composer, {
    prompt: ">", catalog,
    onSubmit: (text: string) => submissions.push(text),
    onInterrupt: () => assert.fail("Unexpected interrupt"),
    onQuit: () => assert.fail("Unexpected quit"),
  }), {
    // Ink types require full TTY streams; these implement the stream/TTY subset it uses.
    stdin: stdin as unknown as NodeJS.ReadStream,
    stdout: stdout as unknown as NodeJS.WriteStream,
    stderr: stdout as unknown as NodeJS.WriteStream,
    debug: true, exitOnCtrlC: false, patchConsole: false,
  });
  t.after(() => {
    instance.unmount();
    instance.cleanup();
    stdin.destroy();
    stdout.destroy();
  });
  // Ink installs input effects asynchronously and throttles rendering (~32ms).
  await delay(80);
  return {
    submissions,
    frame: () => frame,
    async key(sequence: string) { stdin.write(sequence); await delay(80); },
    async type(text: string) { for (const char of text) { stdin.write(char); await delay(80); } },
  };
}

const down = "\u001b[B";
const up = "\u001b[A";
const escape = "\u001b";
const backspace = "\u007f";

test("Composer automatically shows descriptions on slash and narrows while typing", async (t) => {
  const ui = await mount(t);
  assert.doesNotMatch(ui.frame(), /Show available commands/);
  await ui.type("/");
  assert.match(ui.frame(), /❯ \/help/);
  for (const command of catalog) assert.ok(ui.frame().includes(command.description!), ui.frame());
  await ui.type("mo");
  assert.doesNotMatch(ui.frame(), /Show available commands/);
  assert.match(ui.frame(), /❯ \/model\s+— Choose a model/);
  assert.match(ui.frame(), /\/models\s+— List available models/);
  await ui.type("dels");
  assert.doesNotMatch(ui.frame(), /Choose a model/);
  assert.match(ui.frame(), /❯ \/models/);
  assert.deepEqual(ui.submissions, []);
});

test("Composer arrows move and wrap selection; Tab accepts the highlighted command", async (t) => {
  const ui = await mount(t);
  await ui.type("/");
  await ui.key(up);
  assert.match(ui.frame(), /❯ \/models/);
  await ui.key(down);
  assert.match(ui.frame(), /❯ \/help/);
  await ui.key(down);
  assert.match(ui.frame(), /❯ \/model\s/);
  await ui.key("\t");
  assert.equal(ui.frame().trimEnd(), "> /model");
  assert.deepEqual(ui.submissions, []);
  await ui.key("\r");
  assert.deepEqual(ui.submissions, ["/model "]);
});

test("Composer first Enter completes without submitting; second Enter submits", async (t) => {
  const ui = await mount(t);
  await ui.type("/mo");
  await ui.key(down);
  assert.match(ui.frame(), /❯ \/models/);
  await ui.key("\r");
  assert.equal(ui.frame().trimEnd(), "> /models");
  assert.deepEqual(ui.submissions, []);
  await ui.key("\r");
  assert.deepEqual(ui.submissions, ["/models "]);
  assert.equal(ui.frame().trimEnd(), ">");
});

test("Composer Escape closes menu; backspace reopens it and resets selection", async (t) => {
  const ui = await mount(t);
  await ui.type("/mo");
  await ui.key(down);
  assert.match(ui.frame(), /❯ \/models/);
  await ui.key(escape);
  assert.equal(ui.frame().trimEnd(), "> /mo");
  assert.deepEqual(ui.submissions, []);
  await ui.key(backspace);
  assert.match(ui.frame(), /> \/m\s*$/);
  assert.match(ui.frame(), /❯ \/model\s+— Choose a model/);
  assert.doesNotMatch(ui.frame(), /❯ \/models/);
  await ui.key("\t");
  assert.equal(ui.frame().trimEnd(), "> /model");
  assert.deepEqual(ui.submissions, []);
});
