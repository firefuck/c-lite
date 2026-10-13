// The completion popup menu in the Ink TUI.
//
// Appears right above the composer when typing `/` or pressing Tab with multiple candidates.
// Arrow keys navigate up/down, Enter selects, Esc dismisses.

import { Box, Text } from "ink";
import type { CommandEntry } from "@clite/shared";

export interface CompletionMenuProps {
  candidates: CommandEntry[];
  selectedIndex: number;
}

export function CompletionMenu({ candidates, selectedIndex }: CompletionMenuProps) {
  if (candidates.length === 0) return null;

  // Window to a max of 8 items to prevent blowing up the terminal height
  const MAX_VISIBLE = 8;
  const start = Math.max(0, Math.min(selectedIndex - Math.floor(MAX_VISIBLE / 2), candidates.length - MAX_VISIBLE));
  const visible = candidates.slice(start, start + MAX_VISIBLE);

  return (
    <Box flexDirection="column" borderStyle="single" borderColor="gray" paddingX={1} marginBottom={0}>
      {visible.map((cmd, idx) => {
        const actualIndex = start + idx;
        const isSelected = actualIndex === selectedIndex;
        return (
          <Box key={cmd.name}>
            <Text color={isSelected ? "cyan" : undefined} bold={isSelected}>
              {isSelected ? "❯ " : "  "}/{cmd.name}
            </Text>
            {cmd.description ? (
              <Text dimColor> — {cmd.description.slice(0, 50)}</Text>
            ) : null}
          </Box>
        );
      })}
      <Text dimColor>↑↓ pilih · Tab/Enter lengkapi · Esc tutup · {selectedIndex + 1}/{candidates.length}</Text>
    </Box>
  );
}
