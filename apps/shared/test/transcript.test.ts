import assert from "node:assert/strict";
import { test } from "node:test";

import type { EventEnvelope } from "../src/contracts.generated.ts";
import { EVENT_TYPES, METHOD_NAMES, PROTOCOL_VERSION, SERVER_REQUEST_NAMES } from "../src/contracts.generated.ts";
import { GatewayClient } from "../src/gateway-client.ts";
import type { Transport } from "../src/json-rpc-channel.ts";
import { addUserMessage, emptyTranscript, fromHistory, reduce } from "../src/transcript.ts";
import type { TranscriptState } from "../src/transcript.ts";

let seq = 0;
function event<T extends EventEnvelope["type"]>(type: T, payload: Extract<EventEnvelope, { type: T }>["payload"]): EventEnvelope {
  return { type, session_id: "s1", payload, seq: ++seq } as EventEnvelope;
}

const usage = { input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0, reasoning_tokens: 0, prompt_tokens: 0 };
const turnComplete = (overrides: Partial<Extract<EventEnvelope, { type: "turn.complete" }>["payload"]> = {}) =>
  event("turn.complete", {
    turn_id: "t1", final_response: "", completed: true, interrupted: false, error: null, exit_reason: "completed",
    api_calls: 1, duration: 0.1, usage, ...overrides,
  });

function play(events: EventEnvelope[], start: TranscriptState = emptyTranscript): TranscriptState {
  return events.reduce(reduce, start);
}

test("a streamed answer becomes one assistant item", () => {
  const state = play(
    [
      event("turn.start", { turn_id: "t1", text: "hi" }),
      event("message.delta", { text: "Hel" }),
      event("message.delta", { text: "lo" }),
      event("message.complete", { role: "assistant", text: "Hello", tool_calls: [] }),
      turnComplete({ final_response: "Hello" }),
    ],
    addUserMessage(emptyTranscript, "hi"),
  );
  assert.deepEqual(state, {
    busy: false,
    items: [
      { kind: "user", text: "hi" },
      { kind: "assistant", text: "Hello", streaming: false },
    ],
  });
});

test("busy follows turn.start and turn.complete", () => {
  const started = reduce(emptyTranscript, event("turn.start", { turn_id: "t1", text: "x" }));
  assert.equal(started.busy, true);
  assert.equal(reduce(started, turnComplete()).busy, false);
});

test("an unstreamed answer is taken from message.complete", () => {
  const state = play([event("message.complete", { role: "assistant", text: "All at once.", tool_calls: [] })]);
  assert.deepEqual(state.items, [{ kind: "assistant", text: "All at once.", streaming: false }]);
  // A tool-call message with no text adds nothing.
  assert.equal(play([event("message.complete", { role: "assistant", text: "", tool_calls: ["terminal"] })]).items.length, 0);
});

test("tools run between pieces of assistant text and settle by call id", () => {
  const state = play([
    event("message.delta", { text: "Let me check." }),
    event("message.complete", { role: "assistant", text: "Let me check.", tool_calls: ["read_file", "terminal"] }),
    event("tool.start", { call_id: "c1", name: "read_file", args: { path: "a.txt" }, preview: "a.txt" }),
    event("tool.start", { call_id: "c2", name: "terminal", args: { command: "false" }, preview: "false" }),
    event("tool.complete", { call_id: "c2", name: "terminal", duration: 0.2, failed: true, result_preview: "" }),
    event("tool.complete", { call_id: "c1", name: "read_file", duration: 0.05, failed: false, result_preview: "" }),
    event("message.delta", { text: "Done." }),
  ]);
  assert.deepEqual(state.items, [
    { kind: "assistant", text: "Let me check.", streaming: false },
    { kind: "tool", callId: "c1", name: "read_file", preview: "a.txt", status: "ok", duration: 0.05 },
    { kind: "tool", callId: "c2", name: "terminal", preview: "false", status: "failed", duration: 0.2 },
    { kind: "assistant", text: "Done.", streaming: true },
  ]);
});

test("reasoning, status, subagent and error events become their own items", () => {
  const state = play([
    event("reasoning.delta", { text: "think" }),
    event("reasoning.delta", { text: "ing" }),
    event("status.update", { kind: "retry", text: "retrying in 2s" }),
    event("subagent.update", { event: "tool", index: 1, goal: "g", tool: "search_files", status: "" }),
    event("error", { message: "backend error", code: 0 }),
  ]);
  assert.deepEqual(state.items, [
    { kind: "reasoning", text: "thinking" },
    { kind: "notice", level: "info", text: "[retry] retrying in 2s" },
    { kind: "notice", level: "info", text: "subagent 2: tool search_files" },
    { kind: "notice", level: "error", text: "backend error" },
  ]);
});

test("an interrupted or failed turn ends with a notice and no dangling stream", () => {
  const interrupted = play([event("message.delta", { text: "partial" }), turnComplete({ completed: false, interrupted: true })]);
  assert.deepEqual(interrupted.items, [
    { kind: "assistant", text: "partial", streaming: false },
    { kind: "notice", level: "info", text: "(interrupted)" },
  ]);
  const failed = play([turnComplete({ completed: false, error: "rate_limit", final_response: "The model call failed: rate limit" })]);
  assert.deepEqual(failed.items, [{ kind: "notice", level: "error", text: "The model call failed: rate limit" }]);
});

test("reduce never mutates its input", () => {
  const before = play([event("message.delta", { text: "a" })]);
  const snapshot = JSON.stringify(before);
  reduce(before, event("message.delta", { text: "b" }));
  reduce(before, turnComplete());
  assert.equal(JSON.stringify(before), snapshot);
});

test("stored history maps to items", () => {
  const state = fromHistory([
    { role: "user", text: "list files", tool_name: "", tool_calls: [], is_summary: false, timestamp: 1 },
    { role: "assistant", text: "", tool_name: "", tool_calls: ["terminal"], is_summary: false, timestamp: 2 },
    { role: "tool", text: "{}", tool_name: "terminal", tool_calls: [], is_summary: false, timestamp: 3 },
    { role: "assistant", text: "One file.", tool_name: "", tool_calls: [], is_summary: false, timestamp: 4 },
  ]);
  assert.deepEqual(state.items.map((item) => item.kind), ["user", "tool", "assistant"]);
});

test("the generated contracts expose the protocol's names", () => {
  assert.equal(PROTOCOL_VERSION, 1);
  assert.ok(METHOD_NAMES.includes("prompt.submit") && METHOD_NAMES.includes("session.create"));
  assert.ok(EVENT_TYPES.includes("turn.complete") && EVENT_TYPES.includes("gateway.ready"));
  assert.deepEqual([...SERVER_REQUEST_NAMES], ["approval.request", "clarify.request"]);
});

test("GatewayClient types requests, filters events and waits for one", async () => {
  let deliver: (text: string) => void = () => {};
  const sent: string[] = [];
  const transport: Transport = {
    send: (text) => sent.push(text),
    onMessage: (handler) => {
      deliver = handler;
    },
    onClose: () => {},
    close: () => {},
  };
  const client = new GatewayClient(transport);
  const info = client.request("session.info", { session_id: "s1" });
  deliver(JSON.stringify({ jsonrpc: "2.0", id: 1, result: { session_id: "s1", model: "mock-1" } }));
  assert.equal((await info).model, "mock-1");

  const deltas: string[] = [];
  client.on("message.delta", (payload, sessionId) => deltas.push(`${sessionId}:${payload.text}`));
  const done = client.waitFor("turn.complete", "s1");
  const send = (type: string, sessionId: string, payload: unknown) =>
    deliver(JSON.stringify({ jsonrpc: "2.0", method: "event", params: { type, session_id: sessionId, payload, seq: 1 } }));
  send("message.delta", "s1", { text: "hi" });
  send("turn.complete", "other-session", { final_response: "not mine" });
  send("turn.complete", "s1", { final_response: "mine" });
  assert.equal((await done).final_response, "mine");
  assert.deepEqual(deltas, ["s1:hi"]);

  client.onServerRequest("approval.request", (params) => ({ choice: params.command.startsWith("rm") ? "deny" : "once" }));
  deliver(JSON.stringify({ jsonrpc: "2.0", id: "srq-1", method: "approval.request", params: { session_id: "s1", command: "rm -rf x", description: "d" } }));
  await new Promise((resolve) => setImmediate(resolve));
  assert.deepEqual(JSON.parse(sent[sent.length - 1] ?? "{}"), { jsonrpc: "2.0", id: "srq-1", result: { choice: "deny" } });
});
