// Formatting, as pure functions: transcript items and status lines to strings.
// No I/O here, so every line the user sees can be asserted in a test.

import type { SessionInfo } from "../../apps/shared/src/contracts.generated.ts";
import type { TranscriptItem } from "../../apps/shared/src/transcript.ts";

const CODES = { dim: "2", red: "31", green: "32", yellow: "33", cyan: "36", bold: "1" } as const;
export type Style = keyof typeof CODES;

export function paint(text: string, style: Style, color: boolean): string {
  return color ? `\u001b[${CODES[style]}m${text}\u001b[0m` : text;
}

export function shouldUseColor(stream: { isTTY?: boolean }, env: NodeJS.ProcessEnv = process.env): boolean {
  return Boolean(stream.isTTY) && !("NO_COLOR" in env) && env["TERM"] !== "dumb";
}

export function formatToolLine(item: Extract<TranscriptItem, { kind: "tool" }>, color: boolean): string {
  const mark = item.status === "failed" ? "✗" : item.status === "ok" ? "✓" : "…";
  const seconds = item.duration === null ? "" : `  (${item.duration.toFixed(1)}s)`;
  const line = `┊ ${mark} ${item.name} ${item.preview}`.trimEnd() + seconds;
  return paint(line, item.status === "failed" ? "red" : "dim", color);
}

export function formatItem(item: TranscriptItem, color: boolean): string {
  switch (item.kind) {
    case "user":
      return paint(`❯ ${item.text}`, "green", color);
    case "assistant":
      return item.text;
    case "reasoning":
      return paint(item.text, "dim", color);
    case "tool":
      return formatToolLine(item, color);
    case "notice":
      return paint(item.text, item.level === "error" ? "red" : "yellow", color);
  }
}

export function formatBanner(info: SessionInfo, version: string, color: boolean): string {
  return [
    paint(`C-lite ${version}`, "cyan", color),
    paint(`${info.model} via ${info.provider} · ${info.tools.length} tools · session ${info.stored_session_id}`, "dim", color),
    paint(info.cwd, "dim", color),
    paint("Type a message, /help for commands. Ctrl+C interrupts a running turn; Ctrl+D exits.", "dim", color),
  ].join("\n");
}

export function formatStatus(info: SessionInfo): string {
  const context = info.context.context_length ? ` · context ${info.context.usage_percent}%` : "";
  return `${info.model} · ${info.message_count} messages${context}`;
}

const APPROVAL_ANSWERS: Record<string, "once" | "session" | "always" | "deny"> = {
  o: "once", once: "once", y: "once", yes: "once",
  s: "session", session: "session",
  a: "always", always: "always",
  d: "deny", deny: "deny", n: "deny", no: "deny", "": "deny",
};

/** What the user typed at an approval prompt, as a protocol choice. Anything unclear is a no. */
export function parseApproval(answer: string): "once" | "session" | "always" | "deny" {
  return APPROVAL_ANSWERS[answer.trim().toLowerCase()] ?? "deny";
}

/** A clarify answer: a number picks that choice, anything else is taken as typed. */
export function parseChoice(answer: string, choices: string[]): string {
  const trimmed = answer.trim();
  const index = Number.parseInt(trimmed, 10);
  if (/^\d+$/.test(trimmed) && index >= 1 && index <= choices.length) return choices[index - 1] ?? trimmed;
  return trimmed;
}
