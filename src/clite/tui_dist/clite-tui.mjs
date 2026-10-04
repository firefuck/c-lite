#!/usr/bin/env node

// src/entry.ts
import { parseArgs } from "node:util";

// src/backend.ts
import { spawn } from "node:child_process";

// ../apps/shared/src/json-rpc-channel.ts
var RpcError = class extends Error {
  code;
  data;
  constructor(code, message, data) {
    super(message);
    this.name = "RpcError";
    this.code = code;
    this.data = data;
  }
};
var CONNECTION_CLOSED = -1;
var REQUEST_TIMEOUT = -2;
var JsonRpcChannel = class {
  nextId = 1;
  pending = /* @__PURE__ */ new Map();
  eventHandlers = /* @__PURE__ */ new Set();
  requestHandlers = /* @__PURE__ */ new Map();
  closeHandlers = /* @__PURE__ */ new Set();
  closed = false;
  transport;
  options;
  constructor(transport, options = {}) {
    this.transport = transport;
    this.options = options;
    transport.onMessage((text) => this.receive(text));
    transport.onClose((reason) => this.handleClose(reason));
  }
  get isClosed() {
    return this.closed;
  }
  request(method, params = {}) {
    if (this.closed) return Promise.reject(new RpcError(CONNECTION_CLOSED, "connection closed"));
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timeout = this.options.requestTimeoutMs ?? 0;
      const timer = timeout > 0 ? setTimeout(() => {
        this.pending.delete(id);
        reject(new RpcError(REQUEST_TIMEOUT, `${method} timed out after ${timeout} ms`));
      }, timeout) : void 0;
      this.pending.set(id, { resolve, reject, timer });
      this.transport.send(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
    });
  }
  /** Subscribe to events. Returns the unsubscribe function. */
  onEvent(handler) {
    this.eventHandlers.add(handler);
    return () => this.eventHandlers.delete(handler);
  }
  /** Answer a server request. One handler per method; a later call replaces the earlier one. */
  onServerRequest(method, handler) {
    this.requestHandlers.set(method, handler);
  }
  onClose(handler) {
    this.closeHandlers.add(handler);
    return () => this.closeHandlers.delete(handler);
  }
  close() {
    this.transport.close();
    this.handleClose("closed by client");
  }
  receive(text) {
    let message;
    try {
      const parsed = JSON.parse(text);
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return;
      message = parsed;
    } catch {
      return;
    }
    if (message["method"] === "event") {
      const event = message["params"];
      for (const handler of this.eventHandlers) handler(event);
      return;
    }
    if (typeof message["method"] === "string") {
      void this.answer(message["id"], message["method"], message["params"]);
      return;
    }
    const id = message["id"];
    const waiting = typeof id === "number" ? this.pending.get(id) : void 0;
    if (!waiting || typeof id !== "number") return;
    this.pending.delete(id);
    if (waiting.timer) clearTimeout(waiting.timer);
    const error = message["error"];
    if (error) waiting.reject(new RpcError(error.code ?? 0, error.message ?? "error", error.data));
    else waiting.resolve(message["result"]);
  }
  async answer(id, method, params) {
    if (id === void 0 || id === null) return;
    const handler = this.requestHandlers.get(method);
    let reply;
    try {
      if (!handler) throw new RpcError(-32601, `no handler for ${method}`);
      reply = { jsonrpc: "2.0", id, result: await handler(params) };
    } catch (error) {
      const code = error instanceof RpcError ? error.code : -32603;
      reply = { jsonrpc: "2.0", id, error: { code, message: error instanceof Error ? error.message : String(error) } };
    }
    if (!this.closed) this.transport.send(JSON.stringify(reply));
  }
  handleClose(reason) {
    if (this.closed) return;
    this.closed = true;
    for (const waiting of this.pending.values()) {
      if (waiting.timer) clearTimeout(waiting.timer);
      waiting.reject(new RpcError(CONNECTION_CLOSED, `connection closed: ${reason}`));
    }
    this.pending.clear();
    for (const handler of this.closeHandlers) handler(reason);
  }
};

// ../apps/shared/src/gateway-client.ts
var GatewayClient = class {
  channel;
  constructor(transport, options = {}) {
    this.channel = new JsonRpcChannel(transport, options);
  }
  request(method, params) {
    return this.channel.request(method, params);
  }
  /** Every event, as a discriminated union on `type`. */
  onEvent(handler) {
    return this.channel.onEvent((event) => handler(event));
  }
  /** Events of one type. */
  on(type, handler) {
    return this.channel.onEvent((event) => {
      if (event.type === type) handler(event.payload, event.session_id);
    });
  }
  onServerRequest(name, handler) {
    this.channel.onServerRequest(name, (params) => handler(params));
  }
  /** Resolves with the next event of `type` for `sessionId` (or any session when omitted). */
  waitFor(type, sessionId) {
    return new Promise((resolve, reject) => {
      const stopEvents = this.on(type, (payload, from) => {
        if (sessionId !== void 0 && from !== sessionId) return;
        stopEvents();
        stopClose();
        resolve(payload);
      });
      const stopClose = this.channel.onClose((reason) => {
        stopEvents();
        reject(new Error(`connection closed while waiting for ${type}: ${reason}`));
      });
    });
  }
  close() {
    this.channel.close();
  }
};

// ../apps/shared/src/transports.ts
var LineSplitter = class {
  buffer = "";
  push(chunk) {
    this.buffer += chunk;
    const lines = this.buffer.split("\n");
    this.buffer = lines.pop() ?? "";
    return lines.map((line) => line.replace(/\r$/, "")).filter((line) => line.length > 0);
  }
  /** Whatever is left when the stream ends without a final newline. */
  flush() {
    const rest = this.buffer.trim();
    this.buffer = "";
    return rest ? [rest] : [];
  }
};
var LineTransport = class {
  splitter = new LineSplitter();
  messageHandler = () => {
  };
  closeHandler = () => {
  };
  output;
  constructor(input, output) {
    this.output = output;
    input.setEncoding("utf8");
    input.on("data", (chunk) => {
      for (const line of this.splitter.push(chunk)) this.messageHandler(line);
    });
    input.on("end", () => {
      for (const line of this.splitter.flush()) this.messageHandler(line);
      this.closeHandler("stream ended");
    });
    input.on("error", (error) => this.closeHandler(error.message));
    output.on("error", (error) => this.closeHandler(error.message));
  }
  send(text) {
    this.output.write(`${text}
`);
  }
  onMessage(handler) {
    this.messageHandler = handler;
  }
  onClose(handler) {
    this.closeHandler = handler;
  }
  close() {
    this.output.end();
  }
};

// src/backend.ts
var STDERR_LINES = 40;
function resolvePython(env = process.env) {
  return env["CLITE_PYTHON"] || (process.platform === "win32" ? "python" : "python3");
}
function spawnBackend(options = {}) {
  const env = { ...process.env, ...options.env, CLITE_RPC_PLATFORM: "tui", PYTHONUNBUFFERED: "1" };
  const child = spawn(options.python ?? resolvePython(env), ["-m", "clite.rpc.entry", ...options.args ?? []], {
    cwd: options.cwd,
    env,
    stdio: ["pipe", "pipe", "pipe"]
  });
  const stderr = [];
  child.stderr.setEncoding("utf8");
  child.stderr.on("data", (chunk) => {
    stderr.push(...chunk.split("\n").filter(Boolean));
    stderr.splice(0, Math.max(0, stderr.length - STDERR_LINES));
  });
  const client = new GatewayClient(new LineTransport(child.stdout, child.stdin));
  const exited = new Promise((resolve) => child.on("exit", (code) => resolve(code)));
  const ready = new Promise((resolve, reject) => {
    const stop = client.on("gateway.ready", (payload) => {
      stop();
      resolve(payload);
    });
    child.on("error", (error) => reject(new Error(`could not start the backend (${error.message}). Is Python installed?`)));
    void exited.then((code) => reject(new Error(`the backend exited with code ${code} before it was ready.
${stderr.join("\n")}`)));
  });
  ready.catch(() => {
  });
  return {
    client,
    process: child,
    ready,
    stderrTail: () => stderr.join("\n"),
    stop: async () => {
      client.close();
      const timer = setTimeout(() => child.kill(), 3e3);
      const code = await exited;
      clearTimeout(timer);
      return code;
    }
  };
}

// src/plain.ts
import { createInterface } from "node:readline";

// src/render.ts
var CODES = { dim: "2", red: "31", green: "32", yellow: "33", cyan: "36", bold: "1" };
function paint(text, style, color) {
  return color ? `\x1B[${CODES[style]}m${text}\x1B[0m` : text;
}
function shouldUseColor(stream, env = process.env) {
  return Boolean(stream.isTTY) && !("NO_COLOR" in env) && env["TERM"] !== "dumb";
}
function formatToolLine(item, color) {
  const mark = item.status === "failed" ? "\u2717" : item.status === "ok" ? "\u2713" : "\u2026";
  const seconds = item.duration === null ? "" : `  (${item.duration.toFixed(1)}s)`;
  const line = `\u250A ${mark} ${item.name} ${item.preview}`.trimEnd() + seconds;
  return paint(line, item.status === "failed" ? "red" : "dim", color);
}
function formatBanner(info, version, color) {
  return [
    paint(`C-lite ${version}`, "cyan", color),
    paint(`${info.model} via ${info.provider} \xB7 ${info.tools.length} tools \xB7 session ${info.stored_session_id}`, "dim", color),
    paint(info.cwd, "dim", color),
    paint("Type a message, /help for commands. Ctrl+C interrupts a running turn; Ctrl+D exits.", "dim", color)
  ].join("\n");
}
var APPROVAL_ANSWERS = {
  o: "once",
  once: "once",
  y: "once",
  yes: "once",
  s: "session",
  session: "session",
  a: "always",
  always: "always",
  d: "deny",
  deny: "deny",
  n: "deny",
  no: "deny",
  "": "deny"
};
function parseApproval(answer) {
  return APPROVAL_ANSWERS[answer.trim().toLowerCase()] ?? "deny";
}
function parseChoice(answer, choices) {
  const trimmed = answer.trim();
  const index = Number.parseInt(trimmed, 10);
  if (/^\d+$/.test(trimmed) && index >= 1 && index <= choices.length) return choices[index - 1] ?? trimmed;
  return trimmed;
}

// src/plain.ts
var PlainTui = class {
  client;
  output;
  color;
  version;
  sessionParams;
  readline;
  sessionId = "";
  busy = false;
  midLine = false;
  streamed = false;
  question = null;
  toolPreviews = /* @__PURE__ */ new Map();
  finish = () => {
  };
  closing = false;
  sessionOpen = () => {
  };
  chain;
  constructor(options) {
    this.client = options.client;
    this.output = options.output;
    this.color = options.color ?? false;
    this.version = options.version ?? "";
    this.sessionParams = options.session ?? {};
    this.readline = createInterface({ input: options.input, crlfDelay: Infinity });
    this.chain = new Promise((resolve) => {
      this.sessionOpen = resolve;
    });
    this.readline.on("line", (line) => {
      this.chain = this.chain.then(() => this.handleLine(line));
    });
    this.readline.on("close", () => {
      void this.chain.then(() => this.shutdown(0));
    });
  }
  // ── output ───────────────────────────────────────────────────────────────────────────
  write(text) {
    this.output.write(text);
    this.midLine = !text.endsWith("\n");
  }
  line(text = "") {
    if (this.midLine) this.output.write("\n");
    this.output.write(`${text}
`);
    this.midLine = false;
  }
  prompt() {
    if (!this.closing && !this.busy && !this.question) this.write(paint("\u276F ", "green", this.color));
  }
  // ── events ───────────────────────────────────────────────────────────────────────────
  handleEvent(event) {
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
              kind: "tool",
              callId: event.payload.call_id,
              name: event.payload.name,
              preview: started?.preview ?? "",
              status: event.payload.failed ? "failed" : "ok",
              duration: event.payload.duration
            },
            this.color
          )
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
  ask(promptText) {
    return new Promise((resolve) => {
      this.question = { resolve };
      this.write(promptText);
    });
  }
  installServerRequests() {
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
  async handleLine(raw) {
    this.midLine = false;
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
  async runSlash(command) {
    const result = await this.client.request("slash.exec", { session_id: this.sessionId, command });
    if (result.text) this.line(result.text);
    if (result.action === "quit") {
      await this.shutdown(0);
      return;
    }
    if (result.action === "submit") return;
    this.prompt();
  }
  /** Ctrl+C: stop the running turn, or leave when nothing is running. */
  async handleInterrupt() {
    if (this.question) {
      const { resolve } = this.question;
      this.question = null;
      resolve("");
      return;
    }
    if (this.busy) {
      this.line(paint("Interrupting\u2026", "yellow", this.color));
      await this.client.request("session.interrupt", { session_id: this.sessionId }).catch(() => {
      });
      return;
    }
    await this.shutdown(130);
  }
  async shutdown(code) {
    if (this.closing) return;
    this.closing = true;
    this.readline.close();
    let stored = "";
    try {
      stored = (await this.client.request("session.info", { session_id: this.sessionId })).stored_session_id;
      await this.client.request("session.close", { session_id: this.sessionId });
    } catch {
    }
    if (stored) this.line(paint(`Resume this session with: clite chat --resume ${stored}`, "dim", this.color));
    this.finish(code);
  }
  // ── main ─────────────────────────────────────────────────────────────────────────────
  /** Runs until the user quits. Resolves with the process exit code. */
  async run() {
    const done = new Promise((resolve) => {
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
    let info;
    try {
      info = await this.client.request("session.create", this.sessionParams);
    } catch (error) {
      this.line(paint(error instanceof Error ? error.message : String(error), "red", this.color));
      return 1;
    }
    this.sessionId = info.session_id;
    this.line(formatBanner(info, this.version, this.color));
    this.prompt();
    this.sessionOpen();
    return done;
  }
};

// src/entry.ts
var HELP = `Usage: clite tui [options]

  -r, --resume <session>   resume a session by id, id prefix or title
  -m, --model <model>      model for this run
      --provider <name>    provider for this run
      --cwd <dir>          working directory for the agent
      --yolo               skip command approval prompts
  -p, --profile <name>     run in another profile
  -h, --help               show this help
`;
async function main() {
  const { values } = parseArgs({
    options: {
      resume: { type: "string", short: "r" },
      model: { type: "string", short: "m" },
      provider: { type: "string" },
      cwd: { type: "string" },
      yolo: { type: "boolean", default: false },
      profile: { type: "string", short: "p" },
      help: { type: "boolean", short: "h", default: false }
    }
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
    process.stderr.write(`${error instanceof Error ? error.message : String(error)}
`);
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
      yolo: values.yolo
    }
  });
  process.on("SIGINT", () => void tui.handleInterrupt());
  const code = await tui.run();
  await backend.stop();
  return code;
}
main().then(
  (code) => process.exit(code),
  (error) => {
    process.stderr.write(`${error instanceof Error ? error.stack ?? error.message : String(error)}
`);
    process.exit(1);
  }
);
