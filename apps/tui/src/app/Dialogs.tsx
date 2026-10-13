// Full-screen dialogs for command approval and clarify questions.
//
// These replace the line-based prompts in `plain.ts`. The backend sends an
// `approval.request` or `clarify.request` server request; `App.tsx` mounts the matching
// dialog and resolves the request when the user picks. Arrow keys move, Enter confirms, and
// the approval dialog also accepts the single-letter shorthand (`o`, `s`, `a`, `d`) the plain
// UI uses, so keyboard users do not have to relearn.

import { Box, Text, useInput } from "ink";
import { useState } from "react";

import {
  APPROVAL_LABELS,
  type ApprovalChoice,
  parseApprovalChoice,
  parseApprovalText,
  parseClarifyAnswer,
} from "./dialogs.ts";

/** The approval dialog: pick once/session/always/deny for a dangerous command. */
export function ApprovalDialog({
  command,
  description,
  onChoose,
}: {
  command: string;
  description: string;
  onChoose: (choice: ApprovalChoice) => void;
}) {
  const [selected, setSelected] = useState(0);
  useInput((input, key) => {
    if (key.leftArrow) setSelected((i) => Math.max(0, i - 1));
    else if (key.rightArrow) setSelected((i) => Math.min(APPROVAL_LABELS.length - 1, i + 1));
    else if (key.return) onChoose(parseApprovalChoice(selected));
    else {
      const lower = input.toLowerCase();
      if (["o", "s", "a", "d"].includes(lower)) onChoose(parseApprovalText(lower));
    }
  });
  return (
    <Box flexDirection="column" borderStyle="round" paddingX={1}>
      <Text color="yellow">This command needs your approval ({description}):</Text>
      <Text> {command}</Text>
      <Box marginTop={1}>
        {APPROVAL_LABELS.map((label, index) => (
          <Text key={label} color={index === selected ? "cyan" : undefined}>
            {index === selected ? "❯" : " "}[{label}]{" "}
          </Text>
        ))}
      </Box>
    </Box>
  );
}

/** The clarify dialog: a question with numbered choices or free text. */
export function ClarifyDialog({
  question,
  choices,
  onAnswer,
}: {
  question: string;
  choices: string[];
  onAnswer: (answer: string) => void;
}) {
  const [selected, setSelected] = useState(0);
  const [text, setText] = useState("");
  useInput((input, key) => {
    if (key.return) {
      onAnswer(text.trim() ? parseClarifyAnswer(text, choices) : parseClarifyAnswer(String(selected + 1), choices));
      return;
    }
    if (key.upArrow) setSelected((i) => Math.max(0, i - 1));
    else if (key.downArrow) setSelected((i) => Math.min(choices.length - 1, i + 1));
    else if (key.backspace || key.delete) setText((t) => t.slice(0, -1));
    else if (input && !key.ctrl && !key.meta) setText((t) => t + input);
  });
  return (
    <Box flexDirection="column" borderStyle="round" paddingX={1}>
      <Text color="yellow">{question}</Text>
      {choices.map((choice, index) => (
        <Text key={index} color={index === selected ? "cyan" : undefined}>
          {index === selected ? "❯" : " "} {index + 1}. {choice}
        </Text>
      ))}
      <Text> answer: {text}</Text>
    </Box>
  );
}
