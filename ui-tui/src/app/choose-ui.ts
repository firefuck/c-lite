// The choice between the full-screen Ink UI and the line-based plain UI, as a pure function.
//
// `entry.ts` calls this and then runs one of the two. The rule is simple and tested here
// without a terminal: Ink only when both stdin and stdout are a TTY and the user did not ask
// for `--plain`. Piped input (a script, `clite tui | less`) always uses the plain surface,
// which is the one that reads line by line. If `ink` fails to load at runtime, `entry.ts`
// falls back to plain too, but that is a runtime decision, not this function's.

export type UiKind = "ink" | "plain";

export interface ChooseUiOptions {
  stdinIsTTY: boolean;
  stdoutIsTTY: boolean;
  plain: boolean;
}

/** `"ink"` only for a real terminal without `--plain`; `"plain"` otherwise. */
export function chooseUi(options: ChooseUiOptions): UiKind {
  if (options.plain) return "plain";
  if (!options.stdinIsTTY || !options.stdoutIsTTY) return "plain";
  return "ink";
}
