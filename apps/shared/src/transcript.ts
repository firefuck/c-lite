// The transcript as a pure function of events.
//
// Every front-end shows the same thing: user messages, streamed assistant text, tool calls
// with their outcome, and notices. Keeping that logic here, as a reducer with no I/O, means
// the terminal UI and the desktop renderer cannot disagree about it, and it is tested once.

import type { EventEnvelope, TranscriptMessage } from "./contracts.generated.ts";

export type TranscriptItem =
  | { kind: "user"; text: string }
  | { kind: "assistant"; text: string; streaming: boolean }
  | { kind: "reasoning"; text: string }
  | { kind: "tool"; callId: string; name: string; preview: string; status: "running" | "ok" | "failed"; duration: number | null }
  | { kind: "notice"; level: "info" | "error"; text: string };

export interface TranscriptState {
  items: TranscriptItem[];
  busy: boolean;
}

export const emptyTranscript: TranscriptState = { items: [], busy: false };

/** The stored history (from `session.history`) as transcript items. */
export function fromHistory(messages: TranscriptMessage[]): TranscriptState {
  const items: TranscriptItem[] = [];
  for (const message of messages) {
    if (message.role === "tool") {
      items.push({ kind: "tool", callId: "", name: message.tool_name, preview: "", status: "ok", duration: null });
    } else if (message.role === "user" && message.text) {
      items.push({ kind: "user", text: message.text });
    } else if (message.role === "assistant" && message.text) {
      items.push({ kind: "assistant", text: message.text, streaming: false });
    }
  }
  return { items, busy: false };
}

export function addUserMessage(state: TranscriptState, text: string): TranscriptState {
  return { ...state, items: [...state.items, { kind: "user", text }] };
}

function replaceLast(items: TranscriptItem[], item: TranscriptItem): TranscriptItem[] {
  return [...items.slice(0, -1), item];
}

/** Apply one event. Never mutates `state`. Unknown events leave it unchanged. */
export function reduce(state: TranscriptState, event: EventEnvelope): TranscriptState {
  const { items } = state;
  const last = items[items.length - 1];
  switch (event.type) {
    case "turn.start":
      return { ...state, busy: true };

    case "message.delta":
      if (last?.kind === "assistant" && last.streaming) {
        return { ...state, items: replaceLast(items, { ...last, text: last.text + event.payload.text }) };
      }
      return { ...state, items: [...items, { kind: "assistant", text: event.payload.text, streaming: true }] };

    case "reasoning.delta":
      if (last?.kind === "reasoning") {
        return { ...state, items: replaceLast(items, { ...last, text: last.text + event.payload.text }) };
      }
      return { ...state, items: [...items, { kind: "reasoning", text: event.payload.text }] };

    case "message.complete":
      if (last?.kind === "assistant" && last.streaming) {
        return { ...state, items: replaceLast(items, { ...last, streaming: false }) };
      }
      // Nothing was streamed (streaming off, or a provider that does not stream).
      return event.payload.text
        ? { ...state, items: [...items, { kind: "assistant", text: event.payload.text, streaming: false }] }
        : state;

    case "tool.start":
      return {
        ...state,
        items: [
          ...items,
          { kind: "tool", callId: event.payload.call_id, name: event.payload.name, preview: event.payload.preview, status: "running", duration: null },
        ],
      };

    case "tool.complete":
      return {
        ...state,
        items: items.map((item) =>
          item.kind === "tool" && item.callId === event.payload.call_id
            ? { ...item, status: event.payload.failed ? "failed" : "ok", duration: event.payload.duration }
            : item,
        ),
      };

    case "status.update":
      return { ...state, items: [...items, { kind: "notice", level: "info", text: `[${event.payload.kind}] ${event.payload.text}` }] };

    case "subagent.update":
      return {
        ...state,
        items: [
          ...items,
          {
            kind: "notice",
            level: "info",
            text: `subagent ${event.payload.index + 1}: ${event.payload.event} ${event.payload.tool || event.payload.status}`.trim(),
          },
        ],
      };

    case "error":
      return { ...state, items: [...items, { kind: "notice", level: "error", text: event.payload.message }] };

    case "turn.complete": {
      const settled = items.map((item) => (item.kind === "assistant" && item.streaming ? { ...item, streaming: false } : item));
      if (event.payload.interrupted) settled.push({ kind: "notice", level: "info", text: "(interrupted)" });
      else if (event.payload.error) settled.push({ kind: "notice", level: "error", text: event.payload.final_response || event.payload.error });
      return { items: settled, busy: false };
    }

    default:
      return state;
  }
}
