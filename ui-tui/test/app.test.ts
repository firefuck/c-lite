// Tests for the full-screen TUI's pure pieces: the plain/Ink chooser and that the Ink
// transcript path uses the same reducer as the line-based UI.
//
// The Ink components themselves (.tsx) are exercised end to end through the bundle; here we
// test the logic that has to stay in step with `plain.ts` without a real terminal.

import assert from "node:assert/strict";
import { test } from "node:test";

import { chooseUi } from "../src/app/choose-ui.ts";
import { createTuiSessionParams } from "../src/app/session-params.ts";
import { fitStatusLine, formatStatus, wrapTranscriptText } from "../src/app/status-bar.ts";
import { parseApprovalChoice, parseApprovalText, parseClarifyAnswer } from "../src/app/dialogs.ts";
import { getSlashCandidates, handleTabCompletion } from "../src/app/completion.ts";
import { formatModelItem, formatSessionItem, resumeSession, switchModel } from "../src/app/pickers.ts";
import { markdownRoleCodes, markdownStyle } from "../src/render.ts";
import type { CommandEntry, ModelEntry, StoredSession } from "../../apps/shared/src/contracts.generated.ts";
import { reduce, emptyTranscript, addUserMessage } from "../../apps/shared/src/transcript.ts";

test("the Ink TUI creates a valid session.create payload", () => {
  const params = createTuiSessionParams({ cwd: "/tmp/work", model: "mock-1", provider: "mock", yolo: false });

  assert.deepEqual(params, {
    cwd: "/tmp/work",
    model: "mock-1",
    provider: "mock",
    yolo: false,
    platform: "tui",
  });
  assert.equal("source" in params, false);
});

test("a piped (non-TTY) input always uses the plain UI", () => {
  assert.equal(chooseUi({ stdinIsTTY: false, stdoutIsTTY: true, plain: false }), "plain");
  assert.equal(chooseUi({ stdinIsTTY: false, stdoutIsTTY: false, plain: false }), "plain");
});

test("an explicit --plain flag uses the plain UI even on a TTY", () => {
  assert.equal(chooseUi({ stdinIsTTY: true, stdoutIsTTY: true, plain: true }), "plain");
});

test("a real terminal without --plain uses the Ink UI", () => {
  assert.equal(chooseUi({ stdinIsTTY: true, stdoutIsTTY: true, plain: false }), "ink");
});

test("a non-TTY stdout on an otherwise interactive terminal falls back to plain", () => {
  assert.equal(chooseUi({ stdinIsTTY: true, stdoutIsTTY: false, plain: false }), "plain");
});

test("the Ink transcript uses the same reducer as the plain UI", () => {
  // The same sequence of events must produce the same items whether the surface is Ink or
  // plain. This is the property that keeps the two modes from disagreeing.
  const events = [
    { type: "turn.start", payload: {}, session_id: "s" },
    { type: "message.delta", payload: { text: "Hello " }, session_id: "s" },
    { type: "message.delta", payload: { text: "world" }, session_id: "s" },
    { type: "message.complete", payload: { role: "assistant", text: "Hello world", tool_calls: [] }, session_id: "s" },
    { type: "turn.complete", payload: { interrupted: false, error: null, final_response: null }, session_id: "s" },
  ] as const;

  let state = addUserMessage(emptyTranscript, "hi");
  for (const event of events) state = reduce(state, event as any);

  assert.equal(state.busy, false);
  assert.equal(state.items.length, 2);
  const userItem = state.items[0];
  const assistantItem = state.items[1];
  assert.ok(userItem, "user item exists");
  assert.ok(assistantItem, "assistant item exists");
  assert.equal(userItem!.kind, "user");
  assert.equal(assistantItem!.kind, "assistant");
  if (assistantItem!.kind === "assistant") {
    assert.equal(assistantItem.text, "Hello world");
    assert.equal(assistantItem.streaming, false);
  }
});

// ── status bar ──────────────────────────────────────────────────────────────────────────

test("the status bar renders model, cwd, context, and busy from state", () => {
  const line = formatStatus({ model: "mock-1", provider: "mock", cwd: "/tmp/work", busy: false, usagePercent: 42.5 });
  assert.match(line, /mock-1/);
  assert.match(line, /\/tmp\/work/);
  assert.match(line, /ctx 43%/);
  assert.ok(!line.includes("busy"));
});

test("the status bar shows busy when a turn is running", () => {
  const line = formatStatus({ model: "mock-1", provider: "mock", cwd: "/tmp", busy: true, usagePercent: 0 });
  assert.ok(line.includes("busy"));
});

test("the status bar presents live session, context, tool activity, and token usage", () => {
  const line = formatStatus({
    model: "claude-sonnet",
    provider: "anthropic",
    cwd: "/work/clite",
    busy: true,
    usagePercent: 37.5,
    contextUsed: 48_000,
    contextTotal: 128_000,
    sessionId: "stored-session-abcdef",
    title: "Refine terminal dashboard",
    activity: "tool read_file",
    inputTokens: 12_345,
    outputTokens: 678,
  });

  assert.match(line, /claude-sonnet @ anthropic/);
  assert.match(line, /48,000\/128,000 38%/);
  assert.match(line, /Refine terminal dashboard/);
  assert.match(line, /tool read_file/);
  assert.match(line, /12,345 in\/678 out/);
});

test("the status bar keeps activity, model, and context visible on narrow terminals", () => {
  const state = {
    model: "claude-sonnet",
    provider: "anthropic",
    cwd: "/work/clite",
    busy: true,
    usagePercent: 37.5,
    contextUsed: 48_000,
    contextTotal: 128_000,
    activity: "tool read_file",
  };

  const line = formatStatus(state, 55);
  assert.ok(line.length <= 55);
  assert.match(line, /tool read_file/);
  assert.match(line, /claude-sonnet/);
  assert.match(line, /48k\/128k/);
});

test("the status bar shortens the home directory to a tilde", () => {
  const home = process.env["HOME"] ?? "/home/user";
  const line = formatStatus({ model: "m", provider: "p", cwd: `${home}/projects/clite`, busy: false, usagePercent: 0 });
  assert.ok(line.includes("~/projects/clite"));
  assert.ok(!line.includes(home));
});

// ── dialogs ─────────────────────────────────────────────────────────────────────────────

test("the approval dialog maps a selection index to the right choice", () => {
  assert.equal(parseApprovalChoice(0), "once");
  assert.equal(parseApprovalChoice(1), "session");
  assert.equal(parseApprovalChoice(2), "always");
  assert.equal(parseApprovalChoice(3), "deny");
  assert.equal(parseApprovalChoice(99), "deny"); // out of range defaults to deny
});

test("the approval dialog accepts keyboard shorthand like the plain UI", () => {
  assert.equal(parseApprovalText("o"), "once");
  assert.equal(parseApprovalText("s"), "session");
  assert.equal(parseApprovalText("a"), "always");
  assert.equal(parseApprovalText("d"), "deny");
  assert.equal(parseApprovalText("nonsense"), "deny");
});

test("the clarify dialog picks a numbered choice and passes free text through", () => {
  const choices = ["staging", "production"];
  assert.equal(parseClarifyAnswer("2", choices), "production");
  assert.equal(parseClarifyAnswer("1", choices), "staging");
  assert.equal(parseClarifyAnswer("3", choices), "3"); // out of range: taken as text
  assert.equal(parseClarifyAnswer("a custom reply", choices), "a custom reply");
});

// ── slash command completion ─────────────────────────────────────────────────────────────

const mockCatalog: CommandEntry[] = [
  { name: "help", description: "Show help", category: "core", aliases: ["h", "?"], args_hint: "", subcommands: [], kind: "builtin" },
  { name: "clear", description: "Clear screen", category: "core", aliases: [], args_hint: "", subcommands: [], kind: "builtin" },
  { name: "history", description: "Show history", category: "core", aliases: [], args_hint: "", subcommands: [], kind: "builtin" },
  { name: "help", description: "Duplicate help", category: "core", aliases: [], args_hint: "", subcommands: [], kind: "builtin" },
  { name: "model", description: "Model picker", category: "core", aliases: ["m"], args_hint: "", subcommands: ["list", "set"], kind: "builtin" },
];

test("a slash prefix produces candidates from commands.catalog, sorted, without duplicates", () => {
  // Bare "/" lists all unique commands sorted alphabetically
  const all = getSlashCandidates(mockCatalog, "/");
  assert.deepEqual(all.map((c) => c.name), ["clear", "help", "history", "model"]);

  // "/h" matches "help" and "history"
  const h = getSlashCandidates(mockCatalog, "/h");
  assert.deepEqual(h.map((c) => c.name), ["help", "history"]);

  // Matching via alias (e.g. "/?" matches help via alias)
  const q = getSlashCandidates(mockCatalog, "/?");
  assert.deepEqual(q.map((c) => c.name), ["help"]);

  // Non-slash inputs produce no candidates
  assert.deepEqual(getSlashCandidates(mockCatalog, "hello"), []);
});

test("Tab on a single candidate completes the text", () => {
  const result = handleTabCompletion("/cl", mockCatalog);
  assert.equal(result.text, "/clear ");
  assert.equal(result.menuOpen, false);
  assert.equal(result.candidates.length, 1);
});

test("Tab on multiple candidates opens the menu and preserves text", () => {
  const result = handleTabCompletion("/h", mockCatalog);
  assert.equal(result.text, "/h");
  assert.equal(result.menuOpen, true);
  assert.equal(result.candidates.length, 2);
  assert.deepEqual(result.candidates.map((c) => c.name), ["help", "history"]);
});

test("Tab with no matches keeps text and leaves menu closed", () => {
  const result = handleTabCompletion("/xyz", mockCatalog);
  assert.equal(result.text, "/xyz");
  assert.equal(result.menuOpen, false);
  assert.equal(result.candidates.length, 0);
});

test("Tab on subcommand arguments completes when a single candidate matches", () => {
  const result = handleTabCompletion("/model s", mockCatalog);
  assert.equal(result.text, "/model set ");
  assert.equal(result.menuOpen, false);
});

// ── session and model pickers ────────────────────────────────────────────────────────────

test("the session picker formats stored sessions with title, model, and activity", () => {
  const sampleSession: StoredSession = {
    id: "session-12345678",
    title: "Fix bug in parser",
    source: "cli",
    model: "claude-3-7-sonnet",
    message_count: 5,
    started_at: Date.now() - 3600000,
    last_activity_at: Date.now() - 60000,
    estimated_cost_usd: 0,
    archived: false,
    pinned: false,
  };

  const rendered = formatSessionItem(sampleSession, true);
  assert.ok(rendered.includes("Fix bug in parser"));
  assert.ok(rendered.includes("claude-3-7-sonnet"));
  assert.ok(rendered.startsWith("❯ "));
});

test("selecting a session triggers resume via session.create", async () => {
  const sampleSession: StoredSession = {
    id: "sess-abc-999",
    title: "Project setup",
    source: "cli",
    model: "mock-model",
    message_count: 2,
    started_at: 1000,
    last_activity_at: 2000,
    estimated_cost_usd: 0,
    archived: false,
    pinned: false,
  };

  let calledMethod = "";
  let calledParams: Record<string, unknown> = {};

  const fakeClient = {
    async request(method: string, params: Record<string, unknown>) {
      calledMethod = method;
      calledParams = params;
      return { session_id: "resumed-sess-abc-999" };
    },
  };

  const res = await resumeSession(fakeClient, sampleSession);
  assert.equal(calledMethod, "session.create");
  assert.equal(calledParams["resume"], "sess-abc-999");
  assert.equal(res.session_id, "resumed-sess-abc-999");
});

test("the model picker formats model entries with id and current indicator", () => {
  const sampleModel: ModelEntry = {
    id: "gpt-4o",
    context_length: 128000,
  };

  const renderedCurrent = formatModelItem(sampleModel, "gpt-4o", true);
  assert.ok(renderedCurrent.includes("gpt-4o"));
  assert.ok(renderedCurrent.includes("(current)"));
  assert.ok(renderedCurrent.startsWith("❯ "));

  const renderedOther = formatModelItem(sampleModel, "claude-3-5", false);
  assert.ok(!renderedOther.includes("(current)"));
  assert.ok(renderedOther.startsWith("  "));
});

test("selecting a model triggers model.set for active session", async () => {
  const sampleModel: ModelEntry = {
    id: "deepseek-r1",
    context_length: 64000,
  };

  let calledMethod = "";
  let calledParams: Record<string, unknown> = {};

  const fakeClient = {
    async request(method: string, params: Record<string, unknown>) {
      calledMethod = method;
      calledParams = params;
      return { success: true, message: "ok", model: "deepseek-r1", provider: "mock" };
    },
  };

  const res = await switchModel(fakeClient, "active-session-1", sampleModel);
  assert.equal(calledMethod, "model.set");
  assert.equal(calledParams["session_id"], "active-session-1");
  assert.equal(calledParams["model"], "deepseek-r1");
  assert.equal(res.success, true);
});

// ── skin themes and terminal resize ──────────────────────────────────────────────────────

test("markdownRoleCodes maps skin role names to ANSI codes matching Python presentation rules", () => {
  const sampleSkin: Record<string, string> = {
    md_heading: "bright_yellow",
    md_code: "bright_cyan",
    md_table: "cyan",
    diff_add: "bright_green",
    diff_del: "bright_red",
    md_quote: "magenta",
  };

  const codes = markdownRoleCodes(sampleSkin);
  assert.equal(codes["heading"], "93");
  assert.equal(codes["code"], "96");
  assert.equal(codes["table"], "36");
  assert.equal(codes["diff_add"], "92");
  assert.equal(codes["diff_del"], "91");
  assert.equal(codes["quote"], "35");
  // Roles not in the skin are omitted
  assert.equal(codes["link"], undefined);
});

test("markdownStyle uses custom skin codes when provided", () => {
  const customSkin: Record<string, string> = {
    md_heading: "yellow",
    md_code: "magenta",
  };

  const style = markdownStyle(true, customSkin);
  // Color on uses codes from the skin
  assert.equal(style.paint("heading", "Header"), "\u001b[33mHeader\u001b[0m");
  assert.equal(style.paint("code", "const x"), "\u001b[35mconst x\u001b[0m");

  const styleNoColor = markdownStyle(false, customSkin);
  // Color off returns none style even with skin
  assert.equal(styleNoColor.paint("heading", "Header"), "Header");
  assert.equal(styleNoColor.paint("code", "const x"), "const x");
  assert.equal(styleNoColor.isPlain(), true);
});

test("when terminal width changes, transcript wraps and status bar stays on one line", () => {
  // Test transcript wrapping
  const longText = "The quick brown fox jumps over the lazy dog";
  const wrappedWide = wrapTranscriptText(longText, 80);
  assert.equal(wrappedWide.length, 1);
  assert.equal(wrappedWide[0], longText);

  const wrappedNarrow = wrapTranscriptText(longText, 15);
  assert.ok(wrappedNarrow.length > 1);
  assert.ok(wrappedNarrow.every((line) => line.length <= 15));

  // Test status bar strictly fitting one line
  const longStatus = "gpt-4o · /home/very/long/deeply/nested/path/to/project/repo · ctx 85% · busy";
  const statusFitWide = fitStatusLine(longStatus, 100);
  assert.equal(statusFitWide, longStatus);

  const statusFitNarrow = fitStatusLine(longStatus, 25);
  assert.ok(statusFitNarrow.length <= 25);
  assert.ok(statusFitNarrow.endsWith("…"));
  assert.ok(!statusFitNarrow.includes("\n"));
});



