// Full-screen overlay pickers for sessions and models in the Ink TUI.
//
// Replaces manual typing of session IDs and model identifiers.
// Navigated via arrow keys, confirmed with Enter, canceled with Esc.

import { Box, Text, useInput } from "ink";
import { useState } from "react";

import type { ModelEntry, StoredSession } from "@clite/shared";
import { formatModelItem, formatSessionItem } from "./pickers.ts";

export interface SessionPickerProps {
  sessions: StoredSession[];
  onSelect: (session: StoredSession) => void;
  onClose: () => void;
}

export function SessionPicker({ sessions, onSelect, onClose }: SessionPickerProps) {
  const [selected, setSelected] = useState(0);

  useInput((_input, key) => {
    if (key.escape) {
      onClose();
      return;
    }
    if (key.upArrow) {
      setSelected((i) => (i > 0 ? i - 1 : Math.max(0, sessions.length - 1)));
      return;
    }
    if (key.downArrow) {
      setSelected((i) => (i < sessions.length - 1 ? i + 1 : 0));
      return;
    }
    if (key.return) {
      const picked = sessions[selected];
      if (picked) onSelect(picked);
    }
  });

  const MAX_VISIBLE = 10;
  const start = Math.max(0, Math.min(selected - Math.floor(MAX_VISIBLE / 2), sessions.length - MAX_VISIBLE));
  const visible = sessions.slice(start, start + MAX_VISIBLE);

  return (
    <Box flexDirection="column" borderStyle="round" borderColor="cyan" paddingX={1} marginY={1}>
      <Text bold color="cyan">Select Session to Resume (Esc to cancel):</Text>
      {sessions.length === 0 ? (
        <Text dimColor>No previous sessions found.</Text>
      ) : (
        visible.map((session, idx) => {
          const actualIndex = start + idx;
          const isSelected = actualIndex === selected;
          return (
            <Text key={session.id} color={isSelected ? "cyan" : undefined} bold={isSelected}>
              {formatSessionItem(session, isSelected)}
            </Text>
          );
        })
      )}
    </Box>
  );
}

export interface ModelPickerProps {
  models: ModelEntry[];
  current: string;
  onSelect: (model: ModelEntry) => void;
  onClose: () => void;
}

export function ModelPicker({ models, current, onSelect, onClose }: ModelPickerProps) {
  const [selected, setSelected] = useState(0);

  useInput((_input, key) => {
    if (key.escape) {
      onClose();
      return;
    }
    if (key.upArrow) {
      setSelected((i) => (i > 0 ? i - 1 : Math.max(0, models.length - 1)));
      return;
    }
    if (key.downArrow) {
      setSelected((i) => (i < models.length - 1 ? i + 1 : 0));
      return;
    }
    if (key.return) {
      const picked = models[selected];
      if (picked) onSelect(picked);
    }
  });

  const MAX_VISIBLE = 10;
  const start = Math.max(0, Math.min(selected - Math.floor(MAX_VISIBLE / 2), models.length - MAX_VISIBLE));
  const visible = models.slice(start, start + MAX_VISIBLE);

  return (
    <Box flexDirection="column" borderStyle="round" borderColor="green" paddingX={1} marginY={1}>
      <Text bold color="green">Select Model (Esc to cancel):</Text>
      {models.length === 0 ? (
        <Text dimColor>No models available.</Text>
      ) : (
        visible.map((model, idx) => {
          const actualIndex = start + idx;
          const isSelected = actualIndex === selected;
          return (
            <Text key={model.id} color={isSelected ? "green" : undefined} bold={isSelected}>
              {formatModelItem(model, current, isSelected)}
            </Text>
          );
        })
      )}
    </Box>
  );
}
