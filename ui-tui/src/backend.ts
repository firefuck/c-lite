// Starting the Python backend and connecting to it.
//
// The TUI owns the backend's lifetime: it spawns `python -m clite.rpc.entry`, speaks JSON-RPC
// over the child's stdin and stdout, and the child exits when its stdin closes. Anything the
// backend writes to stderr is log output, kept here so a crash can be explained to the user.

import { spawn } from "node:child_process";
import type { ChildProcess } from "node:child_process";

import { GatewayClient } from "../../apps/shared/src/gateway-client.ts";
import { LineTransport } from "../../apps/shared/src/transports.ts";
import type { ReadyPayload } from "../../apps/shared/src/contracts.generated.ts";

export interface BackendOptions {
  /** Python executable. Default: $CLITE_PYTHON, then python3, then python. */
  python?: string;
  cwd?: string;
  env?: NodeJS.ProcessEnv;
  /** Extra arguments for the backend, e.g. ["-p", "work"] to pick a profile. */
  args?: string[];
}

export interface Backend {
  client: GatewayClient;
  process: ChildProcess;
  /** Resolves when the backend announces itself; rejects if it exits first. */
  ready: Promise<ReadyPayload>;
  /** The last lines the backend wrote to stderr. */
  stderrTail(): string;
  stop(): Promise<number | null>;
}

const STDERR_LINES = 40;

export function resolvePython(env: NodeJS.ProcessEnv = process.env): string {
  return env["CLITE_PYTHON"] || (process.platform === "win32" ? "python" : "python3");
}

export function spawnBackend(options: BackendOptions = {}): Backend {
  const env = { ...process.env, ...options.env, CLITE_RPC_PLATFORM: "tui", PYTHONUNBUFFERED: "1" };
  const child = spawn(options.python ?? resolvePython(env), ["-m", "clite.rpc.entry", ...(options.args ?? [])], {
    cwd: options.cwd,
    env,
    stdio: ["pipe", "pipe", "pipe"],
  });

  const stderr: string[] = [];
  child.stderr.setEncoding("utf8");
  child.stderr.on("data", (chunk: string) => {
    stderr.push(...chunk.split("\n").filter(Boolean));
    stderr.splice(0, Math.max(0, stderr.length - STDERR_LINES));
  });

  const client = new GatewayClient(new LineTransport(child.stdout, child.stdin));
  const exited = new Promise<number | null>((resolve) => child.on("exit", (code) => resolve(code)));

  const ready = new Promise<ReadyPayload>((resolve, reject) => {
    const stop = client.on("gateway.ready", (payload) => {
      stop();
      resolve(payload);
    });
    child.on("error", (error) => reject(new Error(`could not start the backend (${error.message}). Is Python installed?`)));
    void exited.then((code) => reject(new Error(`the backend exited with code ${code} before it was ready.\n${stderr.join("\n")}`)));
  });
  ready.catch(() => {}); // the caller awaits it; this only prevents an unhandled-rejection crash

  return {
    client,
    process: child,
    ready,
    stderrTail: () => stderr.join("\n"),
    stop: async () => {
      client.close(); // closes the child's stdin, which is its signal to exit
      const timer = setTimeout(() => child.kill(), 3000);
      const code = await exited;
      clearTimeout(timer);
      return code;
    },
  };
}
