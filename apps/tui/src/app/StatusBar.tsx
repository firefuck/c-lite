// The status bar: one line at the bottom of the full-screen TUI.
//
// Data flows from `session.info` (RPC, on create) and the `session.info` event (on model/cwd
// change) into the shared `StatusBarState`; `turn.start`/`turn.complete` toggle `busy`.

import { Box, Text, useStdout } from "ink";
import type { StatusBarState } from "./status-bar.ts";
import { fitStatusLine, formatStatus } from "./status-bar.ts";

export type { StatusBarState };

export function StatusBar({ state, width }: { state: StatusBarState; width?: number }) {
  const { stdout } = useStdout();
  const columns = width ?? stdout?.columns ?? 80;
  const line = fitStatusLine(formatStatus(state, columns), columns);

  return (
    <Box height={1} overflow="hidden">
      <Text dimColor wrap="truncate">
        {line}
      </Text>
    </Box>
  );
}
