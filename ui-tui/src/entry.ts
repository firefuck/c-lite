// `clite tui`: start the backend, then run the terminal UI on this process's terminal.
//
// A real terminal runs the full-screen Ink UI; piped input or `--plain` runs the line-based
// UI. If Ink cannot be loaded (its bundle is missing, or the terminal is too limited), the
// line-based UI runs instead, with a note on stderr.

import { parseArgs } from "node:util";

import { spawnBackend } from "./backend.ts";
import { chooseUi } from "./app/choose-ui.ts";
import { runInkTui } from "./ink-tui.ts";
import { PlainTui } from "./plain.ts";
import { shouldUseColor } from "./render.ts";

const HELP = `Usage: clite tui [options]

  -r, --resume <session>   resume a session by id, id prefix or title
  -m, --model <model>      model for this run
      --provider <name>    provider for this run
      --cwd <dir>          working directory for the agent
      --yolo               skip command approval prompts
  -p, --profile <name>     run in another profile
      --plain              line-based UI (for pipes and non-TTY; default when not a terminal)
  -h, --help               show this help
`;

async function main(): Promise<number> {
  const { values } = parseArgs({
    options: {
      resume: { type: "string", short: "r" },
      model: { type: "string", short: "m" },
      provider: { type: "string" },
      cwd: { type: "string" },
      yolo: { type: "boolean", default: false },
      profile: { type: "string", short: "p" },
      plain: { type: "boolean", default: false },
      help: { type: "boolean", short: "h", default: false },
    },
  });
  if (values.help) {
    process.stdout.write(HELP);
    return 0;
  }

  const backend = spawnBackend({ args: values.profile ? ["-p", values.profile] : [] });
  let ready;
  try {
    ready = await backend.ready;
  } catch (error) {
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}\n`);
    return 1;
  }

  const session = {
    resume: values.resume ?? null,
    model: values.model ?? null,
    provider: values.provider ?? null,
    cwd: values.cwd ?? process.cwd(),
    yolo: values.yolo,
  };

  const ui = chooseUi({
    stdinIsTTY: process.stdin.isTTY === true,
    stdoutIsTTY: process.stdout.isTTY === true,
    plain: values.plain,
  });

  if (ui === "ink") {
    try {
      const code = await runInkTui({ backend, version: ready.version, session });
      await backend.stop();
      return code;
    } catch (error) {
      // Ink could not run (missing bundle, unsupported terminal): fall back to the plain UI.
      process.stderr.write(`The full-screen UI could not start (${error instanceof Error ? error.message : String(error)}). Falling back to --plain.\n`);
    }
  }

  const tui = new PlainTui({
    client: backend.client,
    input: process.stdin,
    output: process.stdout,
    color: shouldUseColor(process.stdout),
    version: ready.version,
    session,
  });
  process.on("SIGINT", () => void tui.handleInterrupt());
  const code = await tui.run();
  await backend.stop();
  return code;
}

main().then(
  (code) => process.exit(code),
  (error) => {
    process.stderr.write(`${error instanceof Error ? (error.stack ?? error.message) : String(error)}\n`);
    process.exit(1);
  },
);
