// The terminal UI: a line-based interface over the JSON-RPC protocol.
//
// It uses only node:readline, so it runs anywhere Node does and can be driven by a test with
// plain streams. Compared with the classic Python CLI it adds one thing that needs two
// processes: you can type while the agent works. A line sent during a turn is handled by the
// server's busy policy (interrupt, queue or steer).
//
// A full-screen interface (panes, a live status bar, an inline diff viewer) is the planned
// replacement; it will reuse backend.ts, render.ts and the shared transcript reducer as they
// are. See docs/roadmap.

import { createInterface } from "node:readline";
import type { Interface } from "node:readline";
import type { Readable, Writable } from "node:stream";

import type { EventEnvelope, SessionCreateParams, SessionInfo } from "../../apps/shared/src/contracts.generated.ts";
import type { GatewayClient } from "../../apps/shared/src/gateway-client.ts";
import { RpcError } from "../../apps/shared/src/json-rpc-channel.ts";
import { formatBanner, formatToolLine, paint, parseApproval, parseChoice } from "./render.ts";

export interface PlainTuiOptions {
  client: GatewayClient;
  input: Readable;
  output: Writable;
  color?: boolean;
  version?: string;
  session?: SessionCreateParams;
}

type Question = { resolve: (answer: string) => void };

export class PlainTui {
  private readonly client: GatewayClient;
  private readonly output: Writable;
  private readonly color: boolean;
  private readonly version: string;
  private readonly sessionParams: SessionCreateParams;
  private readonly readline: Interface;
  private sessionId = "";
  private busy = false;
  private midLine = false;
  private streamed = false;
  private question: Question | null = null;
  private readonly toolPreviews = new Map<string, { name: string; preview: string }>();
  private finish: (code: number) => void = () => {};
  private closing = false;
  private sessionOpen: () => void = () => {};
  private chain: Promise<void>;

  constructor(options: PlainTuiOptions) {
    this.client = options.client;
    this.output = options.output;
    this.color = options.color ?? false;
    this.version = options.version ?? "";
    this.sessionParams = options.session ?? {};
    this.readline = createInterface({ input: options.input, crlfDelay: Infinity });
    // Listen from the start: input that arrives before the session is open (piped input,
    // a fast typist) is held in order and handled once it is.
    this.chain = new Promise((resolve) => {
      this.sessionOpen = resolve;
    });
    this.readline.on("line", (line) => {
      this.chain = this.chain.then(() => this.handleLine(line));
    });
    this.readline.on("close", () => {
      void this.chain.then(() => this.shutdown(0)); // Ctrl+D, or the input stream ended
    });
  }

  // ── output ───────────────────────────────────────────────────────────────────────────

  private write(text: string): void {
    this.output.write(text);
    this.midLine = !text.endsWith("\n");
  }

  private line(text = ""): void {
    if (this.midLine) this.output.write("\n");
    this.output.write(`${text}\n`);
    this.midLine = false;
  }

  private prompt(): void {
    if (!this.closing && !this.busy && !this.question) this.write(paint("❯ ", "green", this.color));
  }

  // ── events ───────────────────────────────────────────────────────────────────────────

  private handleEvent(event: EventEnvelope): void {
    if (event.session_id && event.session_id !== this.sessionId) return;
    switch (event.type) {
      case "turn.start":
        this.busy = true;
        this.streamed = false;
        break;
      case "message.delta":
        this.streamed = true;
        this.write(event.payload.text);
        break;
      case "message.complete":
        if (!this.streamed && event.payload.text) this.line(event.payload.text);
        else if (this.midLine) this.line();
        this.streamed = false;
        break;
      case "tool.start":
        this.toolPreviews.set(event.payload.call_id, { name: event.payload.name, preview: event.payload.preview });
        break;
      case "tool.complete": {
        const started = this.toolPreviews.get(event.payload.call_id);
        this.toolPreviews.delete(event.payload.call_id);
        this.line(
          formatToolLine(
            {
              kind: "tool", callId: event.payload.call_id, name: event.payload.name, preview: started?.preview ?? "",
              status: event.payload.failed ? "failed" : "ok", duration: event.payload.duration,
            },
            this.color,
          ),
        );
        break;
      }
      case "status.update":
        this.line(paint(`[${event.payload.kind}] ${event.payload.text}`, "yellow", this.color));
        break;
      case "subagent.update":
        this.line(paint(`  subagent ${event.payload.index + 1}: ${event.payload.event} ${event.payload.tool || event.payload.status}`.trimEnd(), "dim", this.color));
        break;
      case "error":
        this.line(paint(event.payload.message, "red", this.color));
        break;
      case "turn.complete":
        this.busy = false;
        if (this.midLine) this.line();
        if (event.payload.interrupted) this.line(paint("(interrupted)", "yellow", this.color));
        else if (event.payload.error) this.line(paint(event.payload.final_response || event.payload.error, "red", this.color));
        this.prompt();
        break;
      default:
        break;
    }
  }

  // ── questions from the agent ─────────────────────────────────────────────────────────

  private ask(promptText: string): Promise<string> {
    return new Promise((resolve) => {
      this.question = { resolve };
      this.write(promptText);
    });
  }

  private installServerRequests(): void {
    this.client.onServerRequest("approval.request", async (params) => {
      this.line(paint(`This command needs your approval (${params.description}):`, "yellow", this.color));
      this.line(`    ${params.command}`);
      return { choice: parseApproval(await this.ask("  [o]nce  [s]ession  [a]lways  [d]eny > ")) };
    });
    this.client.onServerRequest("clarify.request", async (params) => {
      this.line(paint(params.question, "yellow", this.color));
      params.choices.forEach((choice, index) => this.line(`  ${index + 1}. ${choice}`));
      return { answer: parseChoice(await this.ask("  answer > "), params.choices) };
    });
  }

  // ── input ────────────────────────────────────────────────────────────────────────────

  private async handleLine(raw: string): Promise<void> {
    this.midLine = false; // the user's Enter ended whatever line the cursor was on
    if (this.question) {
      const { resolve } = this.question;
      this.question = null;
      resolve(raw);
      return;
    }
    const text = raw.trim();
    if (!text) {
      this.prompt();
      return;
    }
    try {
      if (text.startsWith("/")) await this.runSlash(text);
      else await this.client.request("prompt.submit", { session_id: this.sessionId, text });
    } catch (error) {
      this.line(paint(error instanceof RpcError || error instanceof Error ? error.message : String(error), "red", this.color));
      this.prompt();
    }
  }

  private async runSlash(command: string): Promise<void> {
    const result = await this.client.request("slash.exec", { session_id: this.sessionId, command });
    if (result.text) this.line(result.text);
    if (result.action === "quit") {
      await this.shutdown(0);
      return;
    }
    if (result.action === "submit") return; // a turn was started; its events do the rest
    this.prompt();
  }

  /** Ctrl+C: stop the running turn, or leave when nothing is running. */
  async handleInterrupt(): Promise<void> {
    if (this.question) {
      const { resolve } = this.question;
      this.question = null;
      resolve(""); // an empty answer denies an approval and skips a question
      return;
    }
    if (this.busy) {
      this.line(paint("Interrupting…", "yellow", this.color));
      await this.client.request("session.interrupt", { session_id: this.sessionId }).catch(() => {});
      return;
    }
    await this.shutdown(130);
  }

  private async shutdown(code: number): Promise<void> {
    if (this.closing) return;
    this.closing = true;
    this.readline.close();
    let stored = "";
    try {
      stored = (await this.client.request("session.info", { session_id: this.sessionId })).stored_session_id;
      await this.client.request("session.close", { session_id: this.sessionId });
    } catch {
      // the backend may already be gone
    }
    if (stored) this.line(paint(`Resume this session with: clite chat --resume ${stored}`, "dim", this.color));
    this.finish(code);
  }

  // ── main ─────────────────────────────────────────────────────────────────────────────

  /** Runs until the user quits. Resolves with the process exit code. */
  async run(): Promise<number> {
    const done = new Promise<number>((resolve) => {
      this.finish = resolve;
    });
    this.client.onEvent((event) => this.handleEvent(event));
    this.installServerRequests();
    this.client.channel.onClose((reason) => {
      if (!this.closing) {
        this.line(paint(`The backend stopped: ${reason}`, "red", this.color));
        this.closing = true;
        this.readline.close();
        this.finish(1);
      }
    });

    let info: SessionInfo;
    try {
      info = await this.client.request("session.create", this.sessionParams);
    } catch (error) {
      this.line(paint(error instanceof Error ? error.message : String(error), "red", this.color));
      return 1;
    }
    this.sessionId = info.session_id;
    this.line(formatBanner(info, this.version, this.color));
    this.prompt();
    this.sessionOpen(); // lines are now handled one at a time, in the order they arrived
    return done;
  }
}
