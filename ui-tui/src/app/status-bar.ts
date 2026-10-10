// The status bar text as a pure function, so it can be tested without a terminal.
//
// The Ink component (`StatusBar.tsx`) calls this and wraps the line in `<Text>`. The state
// comes from `session.info` (RPC) and the `session.info`/`turn.start`/`turn.complete` events.

export interface StatusBarState {
  model: string;
  provider: string;
  cwd: string;
  busy: boolean;
  usagePercent: number;
  contextUsed?: number;
  contextTotal?: number;
  sessionId?: string;
  title?: string;
  activity?: string;
  inputTokens?: number;
  outputTokens?: number;
}

const separator = " · ";

function tokenCount(value: number): string {
  return Math.max(0, Math.round(value)).toLocaleString("en-US");
}

function compactTokenCount(value: number): string {
  const rounded = Math.max(0, Math.round(value));
  if (rounded >= 1_000_000) return `${Math.round(rounded / 100_000) / 10}m`;
  if (rounded >= 1_000) return `${Math.round(rounded / 100) / 10}k`;
  return String(rounded);
}

function contextLabel(state: StatusBarState, compact = false): string {
  const count = compact ? compactTokenCount : tokenCount;
  const used = state.contextUsed ?? 0;
  const total = state.contextTotal ?? 0;
  if (total > 0) {
    return `ctx ${count(used)}/${count(total)} ${Math.round(state.usagePercent)}%`;
  }
  return state.usagePercent > 0 ? `ctx ${Math.round(state.usagePercent)}%` : "ctx —";
}

function sessionLabel(state: StatusBarState): string {
  const id = state.sessionId ? `#${state.sessionId.slice(-8)}` : "";
  return [state.title, id].filter(Boolean).join(" ");
}

function joined(parts: string[]): string {
  return parts.filter(Boolean).join(separator);
}

/**
 * Render a compact, data-first live dashboard line from facts already supplied by RPC events.
 *
 * At ordinary widths it includes activity, model/provider, exact context usage, last turn
 * tokens, session title/id, and cwd. At narrow widths it sheds the least immediate details
 * first, retaining activity, model, and context before a final one-row ellipsis fallback.
 */
export function formatStatus(state: StatusBarState, width?: number): string {
  const activity = state.activity || (state.busy ? "busy" : "idle");
  const model = state.model || "(no model)";
  const modelWithProvider = state.provider ? `${model} @ ${state.provider}` : model;
  const context = contextLabel(state);
  const contextCompact = contextLabel(state, true);
  const inputTokens = state.inputTokens ?? 0;
  const outputTokens = state.outputTokens ?? 0;
  const tokens = inputTokens || outputTokens
    ? `${tokenCount(inputTokens)} in/${tokenCount(outputTokens)} out`
    : "";
  const session = sessionLabel(state);
  const cwd = state.cwd ? state.cwd.replace(process.env["HOME"] ?? "", "~") : "";
  const full = joined([`● ${activity}`, modelWithProvider, context, tokens, session, cwd]);
  if (!width || width <= 0 || full.length <= width) return full;

  const useful = joined([`● ${activity}`, modelWithProvider, context, tokens]);
  if (useful.length <= width) return useful;

  const narrow = [`● ${activity}`, model, contextCompact].filter(Boolean).join(" | ");
  if (narrow.length <= width) return narrow;

  return fitStatusLine(narrow, width);
}

/**
 * Ensure the status line fits strictly on a single line of `width` columns.
 *
 * If terminal width is provided and the line exceeds it, truncates cleanly
 * with an ellipsis so it never wraps to a second row.
 */
export function fitStatusLine(line: string, width?: number): string {
  if (!width || width <= 0 || line.length <= width) {
    return line;
  }
  return line.slice(0, Math.max(0, width - 1)) + "…";
}

/**
 * Re-wrap transcript text according to the terminal width.
 */
export function wrapTranscriptText(text: string, width: number): string[] {
  if (width <= 0) return [text];
  const out: string[] = [];
  for (const line of text.split("\n")) {
    if (line.length <= width) {
      out.push(line);
    } else {
      for (let i = 0; i < line.length; i += width) {
        out.push(line.slice(i, i + width));
      }
    }
  }
  return out;
}

