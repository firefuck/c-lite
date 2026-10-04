// End to end: this Node code against the real Python backend, over real pipes.
//
// The backend runs with the offline `mock` provider, so the suite needs no network and no
// API key. Requirements: a `python3` that can import the `clite` package (the repository's
// src/ directory is put on PYTHONPATH here) and its dependencies.

import assert from "node:assert/strict";
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { PassThrough } from "node:stream";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";

import { spawnBackend } from "../src/backend.ts";
import type { Backend } from "../src/backend.ts";
import { PlainTui } from "../src/plain.ts";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
let sandbox = "";
let home = "";
let workdir = "";

function backendEnv(): NodeJS.ProcessEnv {
  const pythonPath = [join(repoRoot, "src"), process.env["PYTHONPATH"]].filter(Boolean).join(":");
  return { CLITE_HOME: home, PYTHONPATH: pythonPath, HOME: sandbox };
}

before(() => {
  sandbox = mkdtempSync(join(tmpdir(), "clite-tui-"));
  home = join(sandbox, ".clite");
  workdir = join(sandbox, "work");
  mkdirSync(home);
  mkdirSync(workdir);
  writeFileSync(join(home, "config.yaml"), "model:\n  provider: mock\n  default: mock-1\n");
});

after(() => rmSync(sandbox, { recursive: true, force: true }));

/** A TUI wired to in-memory streams, with helpers to type and to wait for output. */
async function startTui(): Promise<{
  type: (line: string) => void;
  waitFor: (pattern: RegExp, timeoutMs?: number) => Promise<string>;
  output: () => string;
  tui: PlainTui;
  backend: Backend;
  exit: Promise<number>;
}> {
  const backend = spawnBackend({ env: backendEnv(), cwd: workdir });
  const ready = await backend.ready;
  const input = new PassThrough();
  const sink = new PassThrough();
  let text = "";
  sink.on("data", (chunk: Buffer) => {
    text += chunk.toString();
  });
  const tui = new PlainTui({ client: backend.client, input, output: sink, version: ready.version, session: { cwd: workdir } });
  const exit = tui.run();
  const waitFor = async (pattern: RegExp, timeoutMs = 15000): Promise<string> => {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      if (pattern.test(text)) return text;
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
    throw new Error(`timed out waiting for ${pattern}; output so far:\n${text}\nbackend stderr:\n${backend.stderrTail()}`);
  };
  await waitFor(/Type a message/);
  return { type: (line) => input.write(`${line}\n`), waitFor, output: () => text, tui, backend, exit };
}

test("the protocol works over a real child process", async () => {
  const backend = spawnBackend({ env: backendEnv(), cwd: workdir });
  try {
    const ready = await backend.ready;
    assert.equal(ready.protocol_version, 1);
    const session = await backend.client.request("session.create", { cwd: workdir });
    assert.equal(session.model, "mock-1");
    assert.equal(session.platform, "tui");

    const deltas: string[] = [];
    backend.client.on("message.delta", (payload) => deltas.push(payload.text));
    const done = backend.client.waitFor("turn.complete", session.session_id);
    const submitted = await backend.client.request("prompt.submit", { session_id: session.session_id, text: "hello from node" });
    assert.equal(submitted.accepted, true);
    const result = await done;
    assert.equal(result.final_response, "You said: hello from node");
    assert.equal(deltas.join(""), "You said: hello from node");

    const catalog = await backend.client.request("commands.catalog", { session_id: session.session_id });
    assert.ok(catalog.commands.some((command) => command.name === "model"));
  } finally {
    assert.equal(await backend.stop(), 0);
  }
});

test("a chat session: banner, answer, slash command, quit", async () => {
  const { type, waitFor, exit, backend } = await startTui();
  type("hello there");
  await waitFor(/You said: hello there\n/);
  type("/status");
  await waitFor(/mock-1 via mock/);
  type("/no-such-command");
  await waitFor(/Unknown command: \/no-such-command/);
  type("/quit");
  assert.equal(await exit, 0);
  const output = await waitFor(/Resume this session with: clite chat --resume \d{8}_\d{6}_[0-9a-f]{8}/);
  assert.match(output, /^C-lite 0\.1\.0\nmock-1 via mock/);
  await backend.stop();
});

test("tool calls are shown, and a dangerous one waits for the answer", async () => {
  const scratch = join(workdir, "scratch");
  mkdirSync(scratch);
  writeFileSync(join(workdir, "notes.txt"), "remember the milk\n");
  const { type, waitFor, exit, backend } = await startTui();

  type('!read_file {"path": "notes.txt"}');
  await waitFor(/┊ ✓ read_file notes\.txt {2}\(\d+\.\ds\)/);
  await waitFor(/remember the milk/);

  type('!terminal {"command": "rm -rf ./scratch"}');
  await waitFor(/This command needs your approval[\s\S]*rm -rf \.\/scratch[\s\S]*\[d\]eny > $/);
  assert.equal(existsSync(scratch), true); // nothing ran while the question was open
  type("o");
  await waitFor(/┊ ✓ terminal rm -rf \.\/scratch/);
  assert.equal(existsSync(scratch), false);

  type("/quit");
  assert.equal(await exit, 0);
  await backend.stop();
});

test("a question from the agent is answered by number", async () => {
  const { type, waitFor, exit, backend } = await startTui();
  type('!clarify {"question": "Which environment?", "choices": ["staging", "production"]}');
  await waitFor(/Which environment\?\n {2}1\. staging\n {2}2\. production\n {2}answer > $/);
  type("2");
  await waitFor(/"answer": "production"/);
  type("/quit");
  assert.equal(await exit, 0);
  await backend.stop();
});

test("typing during a turn interrupts it and runs the new message", async () => {
  const { type, waitFor, exit, backend } = await startTui();
  type("!sleep 20");
  await waitFor(/sleeping/);
  type("never mind, say hi");
  const output = await waitFor(/You said: never mind, say hi/);
  assert.match(output, /\(interrupted\)/);
  type("/quit");
  assert.equal(await exit, 0);
  await backend.stop();
});

test("Ctrl+C stops a running turn and leaves the session usable", async () => {
  const { type, waitFor, tui, exit, backend } = await startTui();
  type("!sleep 20");
  await waitFor(/sleeping/);
  await tui.handleInterrupt();
  await waitFor(/Interrupting…[\s\S]*\(interrupted\)/);
  type("still there?");
  await waitFor(/You said: still there\?/);
  await tui.handleInterrupt(); // nothing is running now: this exits
  assert.equal(await exit, 130);
  await backend.stop();
});

test("end of input closes the session cleanly", async () => {
  const backend = spawnBackend({ env: backendEnv(), cwd: workdir });
  await backend.ready;
  const input = new PassThrough();
  const sink = new PassThrough();
  sink.resume();
  const tui = new PlainTui({ client: backend.client, input, output: sink, session: { cwd: workdir } });
  const exit = tui.run();
  input.end("one last message\n");
  assert.equal(await exit, 0);
  assert.equal(await backend.stop(), 0);
});

test("a backend that cannot start is reported, not hung on", async () => {
  const missing = spawnBackend({ python: "/no/such/python" });
  await assert.rejects(missing.ready, /could not start the backend/);

  const broken = spawnBackend({ env: { ...backendEnv(), PYTHONPATH: "/nonexistent" }, python: "python3", args: [] , cwd: sandbox });
  // With the package missing from the path, Python exits with an import error.
  await assert.rejects(broken.ready, /exited with code 1 before it was ready[\s\S]*No module named/);
});

test("an unconfigured install explains what to do", async () => {
  const emptyHome = join(sandbox, "empty-home");
  mkdirSync(emptyHome, { recursive: true });
  const backend = spawnBackend({ env: { ...backendEnv(), CLITE_HOME: emptyHome }, cwd: workdir });
  await backend.ready;
  const sink = new PassThrough();
  let text = "";
  sink.on("data", (chunk: Buffer) => {
    text += chunk.toString();
  });
  const tui = new PlainTui({ client: backend.client, input: new PassThrough(), output: sink });
  assert.equal(await tui.run(), 1);
  assert.match(text, /clite setup/);
  await backend.stop();
});
