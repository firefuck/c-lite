// The Ink render call lives here (in a .tsx file) because JSX needs the tsx loader.
// `ink-tui.ts` orchestrates around it without containing JSX itself.

import { render } from "ink";
import { stdin, stdout } from "node:process";

import type { GatewayClient, SessionInfo } from "@clite/shared";
import { App } from "./App.tsx";

/** Mount the Ink app; returns the handle whose `waitUntilExit` resolves on unmount. */
export function mountApp(client: GatewayClient, session: SessionInfo) {
  // Ink enables raw input in Composer's passive effect. `waitUntilExit` is only a Promise,
  // so without a referenced handle Node can exit after the first frame before that effect runs.
  stdin.ref();
  try {
    const app = render(<App client={client} session={session} />, { stdin, stdout, exitOnCtrlC: false });
    return { ...app, waitUntilExit: app.waitUntilExit().finally(() => stdin.unref()) };
  } catch (error) {
    stdin.unref();
    throw error;
  }
}
