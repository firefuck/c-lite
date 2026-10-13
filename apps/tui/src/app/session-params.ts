// Session-create payload helpers shared by the TUI entry surfaces.
//
// The RPC contract forbids unknown keys, so UI identity must use the declared `platform`
// field rather than an ad-hoc `source` field.

import type { SessionCreateParams } from "@clite/shared";

/** Create a contract-valid session payload for the terminal UI. */
export function createTuiSessionParams(session: Partial<SessionCreateParams>): SessionCreateParams {
  return { ...session, platform: "tui" };
}
