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
  /** The profile to serve. One backend serves exactly one. */
  profile?: string | null;
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
 * How to invoke the CLI itself (no subcommand):
 *   CLITE_DESKTOP_BACKEND  a full command line, for development ("python -m clite")
 *   otherwise              the `clite` executable on PATH
 */
export function resolveCliCommand(env: NodeJS.ProcessEnv = process.env): BackendCommand {
  const override = env["CLITE_DESKTOP_BACKEND"]?.trim();
  const [command, ...rest] = override ? override.split(/\s+/) : ["clite"];
  return { command: command ?? "clite", args: rest };
}

/**
 * How to launch the backend.
 *
 * `profile` picks a profile: one backend serves exactly one profile, so this is how the shell
 * chooses. `--profile` is stripped from the arguments by the CLI before argparse sees them, so
 * it does not matter where it sits.
 */
export function resolveBackendCommand(
  env: NodeJS.ProcessEnv = process.env,
  profile?: string | null,
): BackendCommand {
  const { command, args } = resolveCliCommand(env);
  const chosen = profile ? ["--profile", profile] : [];
  return {
    command,
    args: [...args, ...chosen, "serve", "--host", "127.0.0.1", "--port", "0"],
  };
}

/**
 * The profiles on this machine, for the picker at start.
 *
 * This runs the CLI rather than asking a backend, because the choice has to be made before
 * there is a backend to ask. A failure is not fatal: the caller starts on the default profile.
 */
export function listProfiles(
  env: NodeJS.ProcessEnv = process.env,
  timeoutMs = 10_000,
): Promise<string[]> {
  const { command, args } = resolveCliCommand(env);
  return new Promise((resolve, reject) => {
    const child = spawn(command, [...args, "profile", "list", "--json"], {
      env,
      stdio: ["ignore", "pipe", "ignore"],
    });
    let out = "";
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("`clite profile list` timed out"));
    }, timeoutMs);
    child.stdout.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      out += chunk;
    });
    child.once("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.once("close", () => {
      clearTimeout(timer);
      try {
        const parsed = JSON.parse(out) as { profiles?: { name?: string }[] };
        resolve((parsed.profiles ?? []).map((entry) => entry.name ?? "").filter(Boolean));
      } catch (error) {
        reject(error instanceof Error ? error : new Error(String(error)));
      }
    });
  });
}

export function startBackend(options: StartOptions = {}): Promise<RunningBackend> {
  const token = createToken();
  const { command, args } =
    options.backend ?? resolveBackendCommand(options.env ?? process.env, options.profile);
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
    // "exit" may arrive before stderr is drained; "close" waits for the pipes too.
    child.once("close", (code) => fail(`the backend exited with code ${code} before it was ready`));
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
