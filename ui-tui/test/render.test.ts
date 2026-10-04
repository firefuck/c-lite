import assert from "node:assert/strict";
import { test } from "node:test";

import type { SessionInfo } from "../../apps/shared/src/contracts.generated.ts";
import { formatBanner, formatItem, formatStatus, formatToolLine, paint, parseApproval, parseChoice, shouldUseColor } from "../src/render.ts";

const info: SessionInfo = {
  session_id: "rt1", stored_session_id: "20261004_120000_abcd1234", title: "", platform: "tui", model: "mock-1", provider: "mock",
  cwd: "/work/project", busy: false, yolo: false, message_count: 4, tools: ["terminal", "read_file"], toolsets: ["clite-cli"],
  reasoning_effort: "",
  context: { engine: "compressor", context_length: 32000, threshold_tokens: 24000, last_prompt_tokens: 3200, compression_count: 0,
             usage_percent: 10, messages: 4, model: "mock-1", provider: "mock" },
};

test("paint adds colour only when asked", () => {
  assert.equal(paint("x", "red", false), "x");
  assert.equal(paint("x", "red", true), "\u001b[31mx\u001b[0m");
});

test("colour needs a terminal and respects NO_COLOR", () => {
  assert.equal(shouldUseColor({ isTTY: true }, {}), true);
  assert.equal(shouldUseColor({ isTTY: false }, {}), false);
  assert.equal(shouldUseColor({ isTTY: true }, { NO_COLOR: "1" }), false);
  assert.equal(shouldUseColor({ isTTY: true }, { TERM: "dumb" }), false);
});

test("tool lines show the outcome and the time", () => {
  const base = { kind: "tool" as const, callId: "c1", name: "terminal", preview: "npm test" };
  assert.equal(formatToolLine({ ...base, status: "ok", duration: 1.234 }, false), "┊ ✓ terminal npm test  (1.2s)");
  assert.equal(formatToolLine({ ...base, status: "failed", duration: 0.05 }, false), "┊ ✗ terminal npm test  (0.1s)");
  assert.equal(formatToolLine({ ...base, preview: "", status: "running", duration: null }, false), "┊ … terminal");
  assert.ok(formatToolLine({ ...base, status: "failed", duration: 0 }, true).startsWith("\u001b[31m"));
});

test("each transcript item has a rendering", () => {
  assert.equal(formatItem({ kind: "user", text: "hi" }, false), "❯ hi");
  assert.equal(formatItem({ kind: "assistant", text: "Hello.", streaming: false }, true), "Hello.");
  assert.equal(formatItem({ kind: "notice", level: "error", text: "boom" }, false), "boom");
  assert.equal(formatItem({ kind: "reasoning", text: "hmm" }, false), "hmm");
});

test("banner and status summarise the session", () => {
  const banner = formatBanner(info, "0.1.0", false);
  assert.match(banner, /^C-lite 0\.1\.0\nmock-1 via mock · 2 tools · session 20261004_120000_abcd1234\n\/work\/project\n/);
  assert.equal(formatStatus(info), "mock-1 · 4 messages · context 10%");
});

test("approval answers: anything unclear is a no", () => {
  assert.equal(parseApproval("o"), "once");
  assert.equal(parseApproval(" Yes "), "once");
  assert.equal(parseApproval("s"), "session");
  assert.equal(parseApproval("ALWAYS"), "always");
  assert.equal(parseApproval("d"), "deny");
  assert.equal(parseApproval(""), "deny");
  assert.equal(parseApproval("maybe later"), "deny");
});

test("clarify answers: a number picks a choice, text is kept", () => {
  const choices = ["staging", "production"];
  assert.equal(parseChoice("2", choices), "production");
  assert.equal(parseChoice(" 1 ", choices), "staging");
  assert.equal(parseChoice("3", choices), "3");
  assert.equal(parseChoice("the canary cluster", choices), "the canary cluster");
});
