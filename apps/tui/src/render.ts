// Formatting, as pure functions: transcript items and status lines to strings.
// No I/O here, so every line the user sees can be asserted in a test.

import type { SessionInfo, TranscriptItem } from "@clite/shared";

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
      // An answer is Markdown; the same pure rules as the classic CLI render it.
      return renderMarkdown(item.text, { style: markdownStyle(color) });
    case "reasoning":
      return paint(item.text, "dim", color);
    case "tool":
      return formatToolLine(item, color);
    case "notice":
      return paint(item.text, item.level === "error" ? "red" : "yellow", color);
  }
}

export const MARKDOWN_ROLE_KEYS: Record<string, string> = {
  heading: "md_heading",
  code: "md_code",
  fence: "md_fence",
  table: "md_table",
  marker: "md_marker",
  quote: "md_quote",
  rule: "md_rule",
  link: "md_link",
  diff_add: "diff_add",
  diff_del: "diff_del",
  diff_hunk: "diff_hunk",
  diff_file: "diff_file",
  diff_context: "diff_context",
};

export const COLOR_CODES: Record<string, string> = {
  black: "30",
  red: "31",
  green: "32",
  yellow: "33",
  blue: "34",
  magenta: "35",
  cyan: "36",
  white: "37",
  gray: "90",
  bright_red: "91",
  bright_green: "92",
  bright_yellow: "93",
  bright_blue: "94",
  bright_magenta: "95",
  bright_cyan: "96",
  bold: "1",
  dim: "2",
};

/**
 * Turn a skin (role name -> colour name) into a renderer role map (role -> ANSI code).
 *
 * TypeScript equivalent of Python's `runtime.presentation.markdown_role_codes`.
 * Pure: the same skin always yields the same codes, matching CLI behaviour exactly.
 */
export function markdownRoleCodes(skin: Record<string, string>): Record<string, string> {
  const codes: Record<string, string> = {};
  for (const [role, key] of Object.entries(MARKDOWN_ROLE_KEYS)) {
    const colorName = skin[key] ?? "";
    const code = COLOR_CODES[colorName] ?? "";
    if (code) {
      codes[role] = code;
    }
  }
  return codes;
}

/** The Markdown role map the TUI uses: custom skin or default shared colours, or nothing when colour is off. */
export function markdownStyle(color: boolean, skin?: Record<string, string>): MarkdownStyle {
  if (!color) return MarkdownStyle.none();
  if (skin && Object.keys(skin).length > 0) {
    return MarkdownStyle.fromCodes(markdownRoleCodes(skin));
  }
  return MarkdownStyle.fromCodes({
    heading: CODES.bold, code: CODES.cyan, fence: CODES.dim, table: CODES.cyan, marker: CODES.yellow,
    quote: CODES.cyan, rule: CODES.dim, link: CODES.cyan,
    diff_add: CODES.green, diff_del: CODES.red, diff_hunk: CODES.cyan, diff_file: CODES.bold,
    diff_context: CODES.dim,
  });
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

// ── Markdown and diff ─────────────────────────────────────────────────────────────────────
// The same rules as the Python renderer in src/clite/cli/markdown.py: a line that is complete
// is rendered, a line still being typed is held, and a fenced block is never read as Markdown.
// Nothing here chooses a colour — a MarkdownStyle maps a semantic role to an escape the caller
// built from the active skin, and an empty style means plain text.

export type MarkdownRole =
  | "heading" | "code" | "fence" | "table" | "marker" | "quote" | "rule" | "link"
  | "diff_add" | "diff_del" | "diff_hunk" | "diff_file" | "diff_context";

export class MarkdownStyle {
  private readonly codes: Readonly<Record<string, string>>;

  private constructor(codes: Record<string, string>) {
    this.codes = codes;
  }

  static none(): MarkdownStyle {
    return new MarkdownStyle({});
  }

  static fromCodes(codes: Record<string, string>): MarkdownStyle {
    const kept: Record<string, string> = {};
    for (const [role, code] of Object.entries(codes)) if (code) kept[role] = code;
    return new MarkdownStyle(kept);
  }

  isPlain(): boolean {
    return Object.keys(this.codes).length === 0;
  }

  paint(role: MarkdownRole, text: string): string {
    const code = this.codes[role];
    return code ? `\u001b[${code}m${text}\u001b[0m` : text;
  }
}

const RULE = "─";
const DEFAULT_WIDTH = 80;
const RULE_WIDTH = 40;

const LINK = /\[([^\]]+)\]\([^)]*\)/g;
const INLINE_CODE = /`([^`]+)`/g;
const BOLD = /\*\*([^*]+)\*\*|__([^_]+)__/g;
const ITALIC = /(?<!\*)\*([^*]+)\*(?!\*)|(?<!_)_([^_]+)_(?!_)/g;
const HEADING = /^(#{1,6})\s+(.*)$/;
const BULLET = /^(\s*)[-*+]\s+(.*)$/;
const ORDERED = /^(\s*)(\d+)[.)]\s+(.*)$/;
const QUOTE = /^>\s?(.*)$/;
const FENCE = /^\s*(```+|~~~+)/;
const TABLE_DIVIDER_CELL = /^\s*:?-{3,}:?\s*$/;

/** Characters Markdown may give meaning to: an unfinished line shows only up to the first. */
const MEANINGFUL = new Set("*_`[]()#>~|<&\\".split(""));

/** The prefix of an unfinished line that renders exactly as it is typed. Past the first
 *  meaningful character the raw text may differ from the finished render, and a stream that
 *  cannot rewrite a line would print it twice, so that part waits for the line to settle. */
function plainHead(line: string): string {
  for (let index = 0; index < line.length; index += 1) {
    if (MEANINGFUL.has(line[index] as string)) return line.slice(0, index);
  }
  return line;
}

function inline(text: string, style: MarkdownStyle): string {
  let out = text.replace(LINK, "$1");
  out = out.replace(INLINE_CODE, (_m, body: string) => style.paint("code", body));
  out = out.replace(BOLD, (_m, a: string, b: string) => style.paint("heading", a || b || ""));
  out = out.replace(ITALIC, (_m, a: string, b: string) => style.paint("quote", a || b || ""));
  return out;
}

function splitRow(row: string): string[] {
  let text = row.trim();
  if (text.startsWith("|")) text = text.slice(1);
  if (text.endsWith("|")) text = text.slice(0, -1);
  return text.split("|").map((cell) => cell.trim());
}

function isDivider(row: string): boolean {
  const cells = splitRow(row);
  return cells.length > 1 && cells.every((cell) => TABLE_DIVIDER_CELL.test(cell));
}

function couldOpenTable(line: string): boolean {
  const text = line.trim();
  return text.includes("|") && splitRow(text).length > 1;
}

/** How many trailing lines a stream must hold back because their meaning may still change. */
function unsettledTail(lines: string[]): number {
  if (lines.length === 0) return 0;
  if (!couldOpenTable(lines[lines.length - 1]!)) return 0;
  let start = lines.length;
  while (start > 0 && couldOpenTable(lines[start - 1]!)) start -= 1;
  return lines.length - start;
}

function visibleLen(text: string): number {
  return text.replace(/\u001b\[[0-9;]*m/g, "").length;
}

function cut(text: string, limit: number): string {
  if (visibleLen(text) <= limit) return text;
  if (limit <= 1) return "…".slice(0, limit);
  return text.slice(0, limit - 1) + "…";
}

function padRight(text: string, width: number): string {
  return text + " ".repeat(Math.max(0, width - text.length));
}

function renderTable(rows: string[][], style: MarkdownStyle, width: number): string[] {
  const columns = Math.max(...rows.map((row) => row.length));
  const grid = rows.map((row) => [...row, ...Array<string>(columns - row.length).fill("")]);
  const widths = Array.from({ length: columns }, (_v, c) => Math.max(1, ...grid.map((row) => row[c]!.length)));
  const gap = "  ";
  const available = width - gap.length * (columns - 1);
  const order = widths.map((_w, c) => c).sort((a, b) => widths[b]! - widths[a]!);
  for (const column of order) {
    if (widths.reduce((a, b) => a + b, 0) <= available) break;
    const overflow = widths.reduce((a, b) => a + b, 0) - available;
    widths[column] = Math.max(1, widths[column]! - overflow);
  }
  return grid.map((row) => {
    const cells = row.map((cell, c) => padRight(cut(cell, widths[c]!), widths[c]!));
    return style.paint("table", cells.join(gap).replace(/\s+$/, ""));
  });
}

function renderLine(line: string, style: MarkdownStyle, width: number): string {
  if (!line) return "";
  const heading = HEADING.exec(line);
  if (heading) return style.paint("heading", inline(heading[2]!, style));
  const quote = QUOTE.exec(line);
  if (quote) return style.paint("quote", "│ " + inline(quote[1]!, style));
  if (["---", "***", "___"].includes(line.trim())) return style.paint("rule", RULE.repeat(Math.min(width, RULE_WIDTH)));
  const ordered = ORDERED.exec(line);
  if (ordered) return `${ordered[1]}  ${style.paint("marker", ordered[2]! + ".")} ${inline(ordered[3]!, style)}`;
  const bullet = BULLET.exec(line);
  if (bullet) return `${bullet[1]}  ${style.paint("marker", "•")} ${inline(bullet[2]!, style)}`;
  return inline(line, style);
}

function renderBlocks(lines: string[], style: MarkdownStyle, width: number): string[] {
  const out: string[] = [];
  let index = 0;
  while (index < lines.length) {
    const line = lines[index]!;
    if (line.includes("|") && index + 1 < lines.length && isDivider(lines[index + 1]!)) {
      const rows = [splitRow(line)];
      index += 2;
      while (index < lines.length && lines[index]!.includes("|") && lines[index]!.trim()) {
        if (!isDivider(lines[index]!)) rows.push(splitRow(lines[index]!));
        index += 1;
      }
      out.push(...renderTable(rows, style, width));
      continue;
    }
    out.push(renderLine(line, style, width));
    index += 1;
  }
  return out;
}

function renderFenceLine(line: string, style: MarkdownStyle): string {
  return style.paint("code", line);
}

export interface MarkdownOptions {
  style?: MarkdownStyle;
  width?: number;
}

/** Render a whole Markdown document. Equivalent to one stream fed the text and then closed. */
export function renderMarkdown(text: string, options: MarkdownOptions = {}): string {
  const stream = new MarkdownStream(options);
  return stream.feed(text) + stream.close();
}

/** Stage a Markdown answer as it streams: hold the unfinished line, render the rest. */
export class MarkdownStream {
  private readonly style: MarkdownStyle;
  private readonly width: number;
  private held = "";
  private decided: string[] = [];
  private inFence = false;
  private fenceBuffer: string[] = [];
  private emitted = "";

  constructor(options: MarkdownOptions = {}) {
    this.style = options.style ?? MarkdownStyle.none();
    this.width = options.width ?? DEFAULT_WIDTH;
  }

  /** The whole answer as it should look right now, unfinished line included. A live surface
   *  can track this and print each new suffix, so an answer shows while it is being typed. */
  view(): string {
    return this.emitted + this.pendingRaw();
  }

  private pendingRaw(): string {
    let lines = this.decided;
    if (!this.inFence) lines = lines.slice(0, lines.length - unsettledTail(lines));
    const parts = this.held ? [...lines, plainHead(this.held)] : lines;
    return parts.join("\n");
  }

  /** Take a piece of the answer and return the text that is now safe to show. */
  feed(chunk: string): string {
    this.held += chunk;
    if (!this.held.includes("\n")) return "";
    const parts = this.held.split("\n");
    this.held = parts.pop() ?? "";
    this.decided.push(...parts);
    const out = this.render(false, false);
    this.emitted += out;
    return out;
  }

  /** Flush whatever is still held: the answer has ended. */
  close(): string {
    const held = this.held;
    this.held = "";
    if (held) this.decided.push(held);
    let out = this.render(true, true);
    if (held && !this.inFence && out.endsWith("\n")) out = out.slice(0, -1);
    this.emitted += out;
    return out;
  }

  private flushFence(): string {
    const rendered = this.fenceBuffer.map((line) => renderFenceLine(line, this.style) + "\n").join("");
    this.fenceBuffer = [];
    return rendered;
  }

  private render(settle: boolean, closed: boolean): string {
    let lines = this.decided;
    if (!settle && !this.inFence) lines = lines.slice(0, lines.length - unsettledTail(lines));
    const out: string[] = [];
    let index = 0;
    while (index < lines.length) {
      const line = lines[index]!;
      if (this.inFence) {
        if (FENCE.test(line)) {
          this.inFence = false;
          out.push(this.flushFence());
        } else {
          this.fenceBuffer.push(line);
        }
        index += 1;
        continue;
      }
      if (FENCE.test(line)) {
        this.inFence = true;
        index += 1;
        continue;
      }
      const run: string[] = [];
      while (index < lines.length && !FENCE.test(lines[index]!)) {
        run.push(lines[index]!);
        index += 1;
      }
      out.push(...renderBlocks(run, this.style, this.width).map((line) => line + "\n"));
    }
    if (closed && this.inFence && this.fenceBuffer.length > 0) {
      this.inFence = false;
      out.push(this.flushFence());
    }
    this.decided = this.decided.slice(lines.length);
    return out.join("");
  }
}

const DIFF_ROLES: Record<string, MarkdownRole> = {
  "-": "diff_del", "+": "diff_add", "@": "diff_hunk", " ": "diff_context",
};

export interface DiffOptions {
  style?: MarkdownStyle;
  maxLines?: number;
}

/** Render a unified diff with one colour per line kind, capped at ``maxLines``. */
export function renderDiff(diff: string, options: DiffOptions = {}): string {
  const style = options.style ?? MarkdownStyle.none();
  if (!diff.trim()) return "";
  const lines = diff.replace(/\n+$/, "").split("\n");
  const body: string[] = [];
  let fromFile = "";
  for (const raw of lines) {
    if (raw.startsWith("--- ")) {
      fromFile = raw.slice(4).trim();
      continue;
    }
    if (raw.startsWith("+++ ")) {
      const toFile = raw.slice(4).trim();
      body.push(style.paint("diff_file", `${fromFile || "a/?"} → ${toFile || "b/?"}`));
      continue;
    }
    const role = DIFF_ROLES[raw.slice(0, 1)];
    body.push(role ? style.paint(role, raw) : raw);
  }
  let omitted = 0;
  if (options.maxLines !== undefined && body.length > options.maxLines) {
    omitted = body.length - options.maxLines;
    body.length = options.maxLines;
  }
  if (omitted) body.push(style.paint("diff_hunk", `… omitted ${omitted} diff line(s)`));
  return body.join("\n") + "\n";
}
