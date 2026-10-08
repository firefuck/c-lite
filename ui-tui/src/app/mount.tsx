// The Ink render call lives here (in a .tsx file) because JSX needs the tsx loader.
// `ink-tui.ts` orchestrates around it without containing JSX itself.

import { render } from "ink";
import { stdin, stdout } from "node:process";

import type { GatewayClient } from "../../../apps/shared/src/gateway-client.ts";
import { App } from "./App.tsx";

/** Mount the Ink app; returns the handle whose `waitUntilExit` resolves on unmount. */
export function mountApp(client: GatewayClient, sessionId: string) {
  return render(<App client={client} sessionId={sessionId} />, { stdin, stdout, exitOnCtrlC: false });
}
