// The full-screen TUI: start the Ink app on this terminal, wired to the backend client.
//
// This is the Ink counterpart of `PlainTui`. It owns nothing conversation-related: it renders
// the shared transcript reducer and sends `prompt.submit`. The `--plain` flag and piped input
// still go through `PlainTui`; `entry.ts` makes that choice.

import type { SessionCreateParams, SessionInfo } from "@clite/shared";
import { mountApp } from "./app/mount.tsx";
import type { Backend } from "./backend.ts";

export interface InkTuiOptions {
  backend: Backend;
  version: string;
  session: Partial<SessionCreateParams>;
}

/** Run the Ink TUI until the user quits. Returns the process exit code. */
export async function runInkTui(options: InkTuiOptions): Promise<number> {
  const { backend, session } = options;
  let info: SessionInfo;
  try {
    info = await backend.client.request("session.create", session);
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    return 1;
  }

  const { waitUntilExit, unmount } = mountApp(backend.client, info);

  // When the backend dies, unmount so the process can exit.
  backend.process.on("exit", () => unmount());

  try {
    await waitUntilExit;
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    return 1;
  }
  return 0;
}
