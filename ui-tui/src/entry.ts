// `clite tui`: start the backend, then run the terminal UI on this process's terminal.

import { parseArgs } from "node:util";

import { spawnBackend } from "./backend.ts";
import { PlainTui } from "./plain.ts";
import { shouldUseColor } from "./render.ts";

const HELP = `Usage: clite tui [options]

  -r, --resume <session>   resume a session by id, id prefix or title
  -m, --model <model>      model for this run
      --provider <name>    provider for this run
      --cwd <dir>          working directory for the agent
      --yolo               skip command approval prompts
  -p, --profile <name>     run in another profile
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

  const tui = new PlainTui({
    client: backend.client,
    input: process.stdin,
    output: process.stdout,
    color: shouldUseColor(process.stdout),
    version: ready.version,
    session: {
      resume: values.resume ?? null,
      model: values.model ?? null,
      provider: values.provider ?? null,
      cwd: values.cwd ?? process.cwd(),
      yolo: values.yolo,
    },
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
