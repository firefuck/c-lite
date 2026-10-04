// Starting and stopping the Python backend for the desktop app.
//
// No Electron imports here, on purpose: this is the part that can break in ways a user sees
// ("the window stays blank"), so it is plain Node code with tests.
//
// The contract with `clite serve` (see src/clite/server/run.py):
//   * the session token is passed in the environment, never on the command line, so it does
//     not show up in a process listing;
//   * once the server is listening it prints one line, `CLITE_BACKEND_READY port=<n>`, to
//     stdout. With `--port 0` that line is how we learn the port.

import { spawn } from "node:child_process";
import type { ChildProcess } from "node:child_process";
import { randomBytes } from "node:crypto";

export const READY_SENTINEL = "CLITE_BACKEND_READY";
export const TOKEN_ENV = "CLITE_SESSION_TOKEN";
const DEFAULT_START_TIMEOUT_MS = 30_000;
const STDERR_LINES = 40;

export interface BackendCommand {
  command: string;
  args: string[];
}

export interface StartOptions {
  /** How to launch the backend. Default: see resolveBackendCommand. */
  backend?: BackendCommand;
  env?: NodeJS.ProcessEnv;
  cwd?: string;
  startTimeoutMs?: number;
}

export interface RunningBackend {
  port: number;
  token: string;
  /** Origin of the backend, e.g. http://127.0.0.1:43123 */
  origin: string;
  /** The dashboard URL with the token in the fragment. */
  url: string;
  process: ChildProcess;
  stop(): Promise<void>;
}

/** The port from a ready line, or null for any other line. */
export function parseReadyLine(line: string): number | null {
  const match = /^CLITE_BACKEND_READY port=(\d{1,5})\s*$/.exec(line);
  if (!match) return null;
  const port = Number(match[1]);
  return port > 0 && port < 65536 ? port : null;
}

export function createToken(): string {
  return randomBytes(32).toString("base64url");
}

export function dashboardUrl(port: number, token: string): string {
  // The fragment is never sent to a server and never written to an access log.
  return `http://127.0.0.1:${port}/#token=${encodeURIComponent(token)}`;
}

/**
 * How to launch the backend:
 *   CLITE_DESKTOP_BACKEND  a full command line, for development ("python -m clite")
 *   otherwise              the `clite` executable on PATH
 */
export function resolveBackendCommand(env: NodeJS.ProcessEnv = process.env): BackendCommand {
  const override = env["CLITE_DESKTOP_BACKEND"]?.trim();
  const [command, ...rest] = override ? override.split(/\s+/) : ["clite"];
  return { command: command ?? "clite", args: [...rest, "serve", "--host", "127.0.0.1", "--port", "0"] };
}

export function startBackend(options: StartOptions = {}): Promise<RunningBackend> {
  const token = createToken();
  const { command, args } = options.backend ?? resolveBackendCommand(options.env ?? process.env);
  const child = spawn(command, args, {
    cwd: options.cwd,
    env: { ...process.env, ...options.env, [TOKEN_ENV]: token, PYTHONUNBUFFERED: "1" },
    stdio: ["ignore", "pipe", "pipe"],
  });

  const stderr: string[] = [];
  child.stderr.setEncoding("utf8");
  child.stderr.on("data", (chunk: string) => {
    stderr.push(...chunk.split("\n").filter(Boolean));
    stderr.splice(0, Math.max(0, stderr.length - STDERR_LINES));
  });

  const stop = (): Promise<void> =>
    new Promise((resolve) => {
      if (child.exitCode !== null || child.signalCode !== null) return resolve();
      const force = setTimeout(() => child.kill("SIGKILL"), 5000);
      child.once("exit", () => {
        clearTimeout(force);
        resolve();
      });
      child.kill();
    });

  return new Promise((resolve, reject) => {
    let settled = false;
    let buffer = "";
    const fail = (message: string): void => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      void stop();
      reject(new Error(stderr.length ? `${message}\n${stderr.join("\n")}` : message));
    };
    const timer = setTimeout(
      () => fail(`the backend did not become ready within ${(options.startTimeoutMs ?? DEFAULT_START_TIMEOUT_MS) / 1000}s`),
      options.startTimeoutMs ?? DEFAULT_START_TIMEOUT_MS,
    );

    child.once("error", (error) => fail(`could not start the backend (${command}): ${error.message}`));
    child.once("exit", (code) => fail(`the backend exited with code ${code} before it was ready`));
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      if (settled) return;
      buffer += chunk;
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";
      for (const line of lines) {
        const port = parseReadyLine(line);
        if (port === null) continue;
        settled = true;
        clearTimeout(timer);
        const origin = `http://127.0.0.1:${port}`;
        resolve({ port, token, origin, url: dashboardUrl(port, token), process: child, stop });
        return;
      }
    });
  });
}
