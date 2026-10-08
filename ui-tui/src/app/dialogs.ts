// Pure helpers for the approval and clarify dialogs, testable without a terminal.
//
// The Ink components (`Dialogs.tsx`) call these to turn keyboard input into an RPC result.
// `parseApprovalChoice` maps a selection index to the four approval choices; the list order
// matches what `plain.ts` shows: [once, session, always, deny].

export type ApprovalChoice = "once" | "session" | "always" | "deny";

export const APPROVAL_LABELS: ApprovalChoice[] = ["once", "session", "always", "deny"];

/** Map a 0-based selection index to an approval choice, defaulting to deny. */
export function parseApprovalChoice(index: number): ApprovalChoice {
  return APPROVAL_LABELS[index] ?? "deny";
}

/** Parse free-text shorthand the way `plain.ts` does, for keyboard users who type instead. */
export function parseApprovalText(input: string): ApprovalChoice {
  const c = input.trim().toLowerCase();
  if (c === "o" || c === "once") return "once";
  if (c === "s" || c === "session") return "session";
  if (c === "a" || c === "always") return "always";
  return "deny";
}

export interface ClarifyResult {
  answer: string;
}

/**
 * Resolve a clarify answer from either a numbered choice or free text.
 *
 * A number picks that choice (1-based, like `plain.ts`); anything else is taken as typed.
 */
export function parseClarifyAnswer(input: string, choices: string[]): string {
  const trimmed = input.trim();
  const num = Number(trimmed);
  if (trimmed !== "" && Number.isInteger(num) && num >= 1 && num <= choices.length) {
    return choices[num - 1]!;
  }
  return trimmed;
}
