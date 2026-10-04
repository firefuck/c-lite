import assert from "node:assert/strict";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";

import { createToken, dashboardUrl, parseReadyLine, resolveBackendCommand, startBackend } from "../src/backend-process.ts";
import { decideNavigation } from "../src/window-policy.ts";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
let sandbox = "";

before(() => {
  sandbox = mkdtempSync(join(tmpdir(), "clite-desktop-"));
  writeFileSync(join(sandbox, "config.yaml"), "model:\n  provider: mock\n  default: mock-1\n");
});
after(() => rmSync(sandbox, { recursive: true, force: true }));

test("only a well-formed ready line yields a port", () => {
  assert.equal(parseReadyLine("CLITE_BACKEND_READY port=43123"), 43123);
  assert.equal(parseReadyLine("CLITE_BACKEND_READY port=43123\r"), 43123);
  for (const line of ["", "starting…", "CLITE_BACKEND_READY", "CLITE_BACKEND_READY port=0", "CLITE_BACKEND_READY port=99999",
                      "CLITE_BACKEND_READY port=abc", " CLITE_BACKEND_READY port=80", "log: CLITE_BACKEND_READY port=80"]) {
    assert.equal(parseReadyLine(line), null, line);
  }
});

test("tokens are long, random and URL-safe; the URL keeps them in the fragment", () => {
  const first = createToken();
  assert.match(first, /^[A-Za-z0-9_-]{43}$/);
  assert.notEqual(first, createToken());
  assert.equal(dashboardUrl(8123, "a b/c"), "http://127.0.0.1:8123/#token=a%20b%2Fc");
});

test("the backend command can be overridden for development", () => {
  assert.deepEqual(resolveBackendCommand({}), { command: "clite", args: ["serve", "--host", "127.0.0.1", "--port", "0"] });
  assert.deepEqual(resolveBackendCommand({ CLITE_DESKTOP_BACKEND: "python3 -m clite" }), {
    command: "python3", args: ["-m", "clite", "serve", "--host", "127.0.0.1", "--port", "0"],
  });
});

test("navigation stays on the backend; web links leave the app; the rest is refused", () => {
  const origin = "http://127.0.0.1:43123";
  assert.equal(decideNavigation("http://127.0.0.1:43123/static/app.js", origin), "allow");
  assert.equal(decideNavigation("https://example.com/docs", origin), "external");
  assert.equal(decideNavigation("http://127.0.0.1:9999/", origin), "external"); // another local service is not ours
  assert.equal(decideNavigation("mailto:someone@example.com", origin), "external");
  assert.equal(decideNavigation("file:///etc/passwd", origin), "deny");
  assert.equal(decideNavigation("javascript:alert(1)", origin), "deny");
  assert.equal(decideNavigation("not a url", origin), "deny");
});

test("starts the real backend, learns the port, and the token opens the API", async () => {
  const pythonPath = [join(repoRoot, "src"), process.env["PYTHONPATH"]].filter(Boolean).join(":");
  const backend = await startBackend({
    backend: { command: process.env["CLITE_PYTHON"] ?? "python3", args: ["-m", "clite", "serve", "--port", "0"] },
    env: { CLITE_HOME: sandbox, PYTHONPATH: pythonPath },
  });
  try {
    assert.ok(backend.port > 0);
    assert.equal(backend.url, `http://127.0.0.1:${backend.port}/#token=${backend.token}`);

    const denied = await fetch(`${backend.origin}/api/status`);
    assert.equal(denied.status, 401);
    const allowed = await fetch(`${backend.origin}/api/status`, { headers: { Authorization: `Bearer ${backend.token}` } });
    assert.equal(allowed.status, 200);
    assert.equal(((await allowed.json()) as { model: string }).model, "mock-1");

    const page = await fetch(`${backend.origin}/`);
    assert.match(await page.text(), /<title>C-lite<\/title>/);

    // The same WebSocket the dashboard opens, from Node's built-in client.
    const socket = new WebSocket(`ws://127.0.0.1:${backend.port}/api/ws?token=${backend.token}`);
    const first = await new Promise<string>((resolveMessage, reject) => {
      socket.addEventListener("message", (event) => resolveMessage(String(event.data)));
      socket.addEventListener("error", () => reject(new Error("websocket failed")));
    });
    assert.equal(JSON.parse(first).params.type, "gateway.ready");
    socket.close();
  } finally {
    await backend.stop();
  }
  assert.notEqual(backend.process.exitCode ?? backend.process.signalCode, null); // it is really gone
});

test("a backend that exits early is reported with what it printed", async () => {
  await assert.rejects(
    startBackend({ backend: { command: process.execPath, args: ["-e", "console.error('missing dependency: uvicorn'); process.exit(3)"] } }),
    /exited with code 3 before it was ready\nmissing dependency: uvicorn/,
  );
});

test("a missing executable and a silent backend both fail clearly", async () => {
  await assert.rejects(startBackend({ backend: { command: "/no/such/clite", args: [] } }), /could not start the backend/);
  await assert.rejects(
    startBackend({ backend: { command: process.execPath, args: ["-e", "setTimeout(() => {}, 60000)"] }, startTimeoutMs: 300 }),
    /did not become ready within 0\.3s/,
  );
});
