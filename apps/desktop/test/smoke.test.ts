// Smoke test: the real Electron app, end to end, with the mock provider.
//
// It launches `electron .` (the actual `dist/main.cjs` built from `src/main.ts`), waits for the
// window to load the dashboard, types one message into the page, and reads the answer back.
// The page is driven over the DevTools protocol, so `main.ts` needs no test hooks: what runs
// here is exactly what a user runs.
//
// Skipped where a window cannot be opened (no Electron binary, no display). On CI Linux it
// runs under a virtual display (`xvfb-run`). Chromium switches can be added through
// CLITE_SMOKE_FLAGS, e.g. to disable the GPU or the sandbox in a container.

import assert from "node:assert/strict";
import { execFileSync, spawn } from "node:child_process";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { connect, createServer } from "node:net";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const appRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = resolve(appRoot, "../..");

const START_TIMEOUT_MS = 60_000;
const INTERACTION_TIMEOUT_MS = 30_000;

interface CdpTarget {
  type: string;
  url: string;
  webSocketDebuggerUrl?: string;
}

interface CdpMessage {
  id?: number;
  method?: string;
  params?: unknown;
  result?: unknown;
  error?: { message?: string };
}

interface CdpConnection {
  send(method: string, params?: Record<string, unknown>): Promise<unknown>;
  on(method: string, handler: (params: unknown) => void): void;
  close(): void;
}

/** The Electron binary `npm install` downloaded, or null when it is not installed. */
function electronBinary(): string | null {
  try {
    return require("electron") as string;
  } catch {
    return null;
  }
}

/** Why this test cannot run here, or false when it can. */
function skipReason(): string | false {
  if (!electronBinary()) return "the electron package is not installed";
  if (process.platform === "linux" && !process.env["DISPLAY"] && !process.env["WAYLAND_DISPLAY"]) {
    return "no display; run under xvfb-run (Linux) or a desktop session";
  }
  return false;
}

function freePort(): Promise<number> {
  return new Promise((resolvePort, reject) => {
    const server = createServer();
    server.once("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(() => (port > 0 ? resolvePort(port) : reject(new Error("no free port"))));
    });
  });
}

async function waitFor<T>(probe: () => Promise<T | null>, timeoutMs: number, what: string): Promise<T> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const value = await probe().catch(() => null);
    if (value !== null) return value;
    if (Date.now() > deadline) throw new Error(`timed out after ${timeoutMs}ms waiting for ${what}`);
    await new Promise((wake) => setTimeout(wake, 200));
  }
}

function isPortOpen(port: number): Promise<boolean> {
  return new Promise((open) => {
    const socket = connect({ port, host: "127.0.0.1" });
    socket.once("connect", () => {
      socket.destroy();
      open(true);
    });
    socket.once("error", () => open(false));
  });
}

function connectCdp(url: string): Promise<CdpConnection> {
  return new Promise((resolveConnection, reject) => {
    const socket = new WebSocket(url);
    let nextId = 1;
    const pending = new Map<number, { resolve: (value: unknown) => void; reject: (error: Error) => void }>();
    const handlers = new Map<string, (params: unknown) => void>();

    socket.onopen = () =>
      resolveConnection({
        send(method, params = {}) {
          const id = nextId++;
          return new Promise((resolveMessage, rejectMessage) => {
            pending.set(id, { resolve: resolveMessage, reject: rejectMessage });
            socket.send(JSON.stringify({ id, method, params }));
          });
        },
        on(method, handler) {
          handlers.set(method, handler);
        },
        close() {
          socket.close();
        },
      });
    socket.onerror = () => reject(new Error("the DevTools socket failed"));
    socket.onmessage = (event) => {
      const message = JSON.parse(String(event.data)) as CdpMessage;
      if (typeof message.id === "number") {
        const slot = pending.get(message.id);
        if (!slot) return;
        pending.delete(message.id);
        if (message.error) slot.reject(new Error(message.error.message ?? "DevTools error"));
        else slot.resolve(message.result);
        return;
      }
      if (message.method) handlers.get(message.method)?.(message.params);
    };
  });
}

/** The script the page runs: wait for the session, send a message, return what was rendered. */
const INTERACTION = `(async () => {
  const wait = (probe, ms) => new Promise((done, fail) => {
    const start = Date.now();
    const tick = () => {
      let value = null;
      try { value = probe(); } catch (error) { value = null; }
      if (value) return done(value);
      if (Date.now() - start > ms) return fail(new Error("the page timed out"));
      setTimeout(tick, 50);
    };
    tick();
  });
  await wait(() => document.querySelector("#status-connection.online"), ${INTERACTION_TIMEOUT_MS});
  await wait(() => (document.querySelector("#status-model")?.textContent || "") !== "", ${INTERACTION_TIMEOUT_MS});
  const prompt = document.querySelector("#prompt");
  prompt.value = "hello from the desktop smoke test";
  prompt.dispatchEvent(new Event("input", { bubbles: true }));
  prompt.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  const assistant = await wait(() => document.querySelector(".message.assistant"), ${INTERACTION_TIMEOUT_MS});
  return {
    user: document.querySelector(".message.user")?.textContent || "",
    answer: assistant.textContent || "",
  };
})()`;

let sandbox = "";
let electron: ReturnType<typeof spawn> | null = null;

before(() => {
  sandbox = mkdtempSync(join(tmpdir(), "clite-desktop-smoke-"));
  writeFileSync(join(sandbox, "config.yaml"), "model:\n  provider: mock\n  default: mock-1\n");
  // The app loads dist/main.cjs; make sure it matches src/.
  execFileSync(process.execPath, ["build.mjs"], { cwd: appRoot, stdio: "ignore" });
});

after(() => {
  if (electron && electron.exitCode === null && electron.signalCode === null) electron.kill("SIGKILL");
  rmSync(sandbox, { recursive: true, force: true });
});

/** Stop the app the way a user does, and make sure nothing is left behind. */
async function shutdown(): Promise<void> {
  const running = electron;
  electron = null;
  if (!running) return;
  if (running.exitCode === null && running.signalCode === null) {
    running.kill("SIGTERM");
    await Promise.race([
      new Promise<void>((exited) => running.once("exit", () => exited())),
      new Promise<void>((wake) => setTimeout(wake, 10_000)),
    ]);
    if (running.exitCode === null && running.signalCode === null) running.kill("SIGKILL");
  }
}

test("the app opens the dashboard, sends a message to the mock provider, and shows the answer", { skip: skipReason(), timeout: 120_000 }, async () => {
  const binary = electronBinary();
  assert.ok(binary, "electron is installed");
  const debugPort = await freePort();
  const python = process.env["CLITE_PYTHON"] ?? "python3";
  // Chromium switches must come before the app path, or Electron hands them to the app instead.
  const flags = (process.env["CLITE_SMOKE_FLAGS"] ?? "--disable-gpu --no-sandbox").split(/\s+/).filter(Boolean);

  electron = spawn(binary, [`--remote-debugging-port=${debugPort}`, ...flags, appRoot], {
    cwd: appRoot,
    env: {
      ...process.env,
      CLITE_HOME: sandbox,
      CLITE_DESKTOP_BACKEND: `${python} -m clite`,
      PYTHONPATH: [join(repoRoot, "src"), process.env["PYTHONPATH"]].filter(Boolean).join(":"),
      PYTHONUNBUFFERED: "1",
    },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const stderr: string[] = [];
  electron.stderr?.setEncoding("utf8");
  electron.stderr?.on("data", (chunk: string) => stderr.push(chunk));

  let cdp: CdpConnection | null = null;
  let backendPort = 0;
  try {
    const page = await waitFor(async () => {
      const response = await fetch(`http://127.0.0.1:${debugPort}/json/list`);
      const targets = (await response.json()) as CdpTarget[];
      return targets.find((target) => target.type === "page" && target.url.startsWith("http://127.0.0.1")) ?? null;
    }, START_TIMEOUT_MS, `the dashboard window (stderr: ${stderr.join("").trim() || "empty"})`);

    backendPort = Number(new URL(page.url).port);
    assert.ok(backendPort > 0, "the page was served by the backend");

    cdp = await connectCdp(page.webSocketDebuggerUrl ?? "");
    const pageErrors: string[] = [];
    cdp.on("Runtime.exceptionThrown", (params) => {
      const details = (params as { exceptionDetails?: { text?: string; exception?: { description?: string } } }).exceptionDetails;
      pageErrors.push(details?.exception?.description ?? details?.text ?? "unknown page error");
    });
    await cdp.send("Runtime.enable");

    // A slow runner can reload the page (a renderer restart) while the interaction is in
    // flight; CDP answers that with "Execution context was destroyed". The interaction is
    // safe to rerun from scratch, so let the page settle and try again.
    let evaluated: { result?: { value?: { user?: string; answer?: string } } };
    for (let attempt = 1; ; attempt++) {
      try {
        evaluated = (await cdp.send("Runtime.evaluate", {
          expression: INTERACTION,
          awaitPromise: true,
          returnByValue: true,
        })) as { result?: { value?: { user?: string; answer?: string } } };
        break;
      } catch (error) {
        const message = error instanceof Error ? error.message : String(error);
        if (attempt >= 3 || !message.includes("context was destroyed")) throw error;
        await new Promise((wake) => setTimeout(wake, 2_000));
      }
    }
    const rendered = evaluated.result?.value ?? {};
    assert.equal(rendered.user, "hello from the desktop smoke test");
    assert.equal(rendered.answer, "You said: hello from the desktop smoke test");
    assert.deepEqual(pageErrors, [], `JavaScript errors on the page: ${pageErrors.join("; ")}`);

    // Closing the window must take the backend with it: no orphaned Python process.
    // Page.close closes the only window, which quits the app; its reply may not arrive, so it
    // is not awaited.
    void cdp.send("Page.close").catch(() => undefined);
    await waitFor(async () => ((await isPortOpen(backendPort)) ? null : true), 15_000, "the backend to stop");
  } finally {
    cdp?.close();
    await shutdown();
  }
});
