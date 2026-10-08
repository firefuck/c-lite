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
}

/** One line: `model · cwd · context N% · busy`. */
export function formatStatus(state: StatusBarState): string {
  const parts: string[] = [];
  parts.push(state.model || "(no model)");
  if (state.cwd) {
    const short = state.cwd.replace(process.env["HOME"] ?? "", "~");
    parts.push(short);
  }
  if (state.usagePercent > 0) parts.push(`ctx ${Math.round(state.usagePercent)}%`);
  if (state.busy) parts.push("busy");
  return parts.join(" · ");
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

