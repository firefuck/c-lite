import assert from "node:assert/strict";
import { test } from "node:test";

import type { SessionInfo } from "../../apps/shared/src/contracts.generated.ts";
import {
  formatBanner, formatItem, formatStatus, formatToolLine, MarkdownStream, MarkdownStyle, paint, parseApproval,
  parseChoice, renderDiff, renderMarkdown, shouldUseColor,
} from "../src/render.ts";

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

// ── Markdown and diff: the same rules as the Python renderer ──────────────────────────────

const COLOR = MarkdownStyle.fromCodes({
  heading: "1", code: "36", fence: "2", marker: "33", quote: "36", rule: "2",
  link: "34", diff_file: "1", diff_hunk: "36", diff_add: "32", diff_del: "31", diff_context: "2",
});
const PLAIN = MarkdownStyle.none();
const WIDTH = 80;

const strip = (text: string): string => text.replace(/\u001b\[[0-9;]*m/g, "");

function streamIn(text: string, sizes: number[], style: MarkdownStyle = PLAIN): string {
  const out = new MarkdownStream({ style, width: WIDTH });
  const parts: string[] = [];
  let index = 0;
  for (const size of sizes) {
    parts.push(out.feed(text.slice(index, index + size)));
    index += size;
  }
  if (index < text.length) parts.push(out.feed(text.slice(index)));
  parts.push(out.close());
  return parts.join("");
}

test("a stream in random fragments matches the whole text", () => {
  const text =
    "# Title\n\n" +
    "Some **bold** prose and a `snippet`.\n\n" +
    "- first\n- second\n\n" +
    "| A | B |\n| --- | --- |\n| 1 | 2 |\n| wider | values |\n\n" +
    "```py\n# not a heading\nprint('x')\n```\n\n" +
    "Closing prose.\n";
  const whole = renderMarkdown(text);
  for (let seed = 0; seed < 25; seed++) {
    let state = seed * 2654435761 + 1;
    const sizes: number[] = [];
    while (sizes.reduce((a, b) => a + b, 0) < text.length) {
      state = (state * 1103515245 + 12345) % 2147483648;
      sizes.push(1 + (state % 7));
    }
    assert.equal(streamIn(text, sizes), whole, `fragments from seed ${seed}`);
  }
});

test("the live view shows an unfinished line while it is typed", () => {
  const out = new MarkdownStream({ style: PLAIN, width: WIDTH });
  let seen = "";
  for (const fragment of ["slee", "ping ", "z z", "z\n"]) {
    out.feed(fragment);
    const view = out.view();
    assert.ok(view.startsWith(seen), `view went backwards: ${JSON.stringify([seen, view])}`);
    seen = view;
  }
  assert.equal(out.view(), "sleeping z zz\n");
});

test("the live view waits at the first Markdown character", () => {
  const out = new MarkdownStream({ style: PLAIN, width: WIDTH });
  out.feed("a plain word, then **bold half");
  assert.equal(out.view(), "a plain word, then ");
  out.feed(" done**\n");
  assert.equal(out.view(), "a plain word, then bold half done\n");
});

test("a code block is never rendered as Markdown", () => {
  const out = renderMarkdown("```\n# heading\n**bold** and `code`\n```\n");
  assert.ok(out.includes("# heading"));
  assert.ok(out.includes("**bold** and `code`"));
  assert.ok(!out.includes("\u001b[1m"));
});

test("a table wider than the terminal is cut to the width", () => {
  const table = "| left column | right column |\n| --- | --- |\n| a long value here | another long value here |\n";
  for (const line of renderMarkdown(table, { width: 30 }).replace(/\n$/, "").split("\n")) {
    assert.ok(line.length <= 30, `line too long: ${JSON.stringify(line)}`);
  }
  const out = renderMarkdown(table, { width: 30 });
  assert.ok(out.includes("left column"));
  assert.ok(!out.includes("another long value here"));
  assert.ok(out.includes("…"));
});

test("without colour the output is plain and readable", () => {
  assert.equal(PLAIN.isPlain(), true);
  const coloured = renderMarkdown("## Title\n- item with `code`\n", { style: COLOR });
  const plain = renderMarkdown("## Title\n- item with `code`\n");
  assert.ok(!plain.includes("\u001b"));
  assert.equal(strip(coloured), plain);
  assert.ok(plain.includes("Title") && plain.includes("item with code"));
});

test("a unified diff is coloured by line role", () => {
  const diff = "--- a/file.txt\n+++ b/file.txt\n@@ -1,3 +1,3 @@\n context line\n-removed line\n+added line\n";
  const out = renderDiff(diff, { style: COLOR });
  assert.ok(out.includes("\u001b[32m+added line\u001b[0m"));
  assert.ok(out.includes("\u001b[31m-removed line\u001b[0m"));
  assert.ok(out.includes("a/file.txt → b/file.txt"));
});

test("a diff without colour is plain readable text", () => {
  const diff = "--- a/file.txt\n+++ b/file.txt\n@@ -1,3 +1,3 @@\n context line\n-removed line\n+added line\n";
  const out = renderDiff(diff);
  assert.ok(!out.includes("\u001b"));
  assert.ok(out.includes("-removed line") && out.includes("+added line"));
});

test("a long diff is capped and says how much was left out", () => {
  let body = "";
  for (let i = 0; i < 200; i++) body += `+line ${i}\n`;
  const diff = "--- a/x\n+++ b/x\n@@ -1 +1 @@\n" + body;
  const out = renderDiff(diff, { maxLines: 20 });
  assert.ok(out.split("\n").length <= 22);
  assert.ok(out.includes("omitted") && out.includes("line(s)"));
});

test("a diff of nothing is empty", () => {
  assert.equal(renderDiff(""), "");
  assert.equal(renderDiff("   \n"), "");
});

test("the tui paints an assistant answer as Markdown", () => {
  const out = formatItem({ kind: "assistant", text: "## Title\nplain\n", streaming: false }, false);
  assert.equal(out, "Title\nplain\n");
  const coloured = formatItem({ kind: "assistant", text: "## Title\n", streaming: false }, true);
  assert.ok(coloured.includes("\u001b[1m"));
});
