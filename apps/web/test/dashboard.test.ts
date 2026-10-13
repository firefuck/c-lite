// The dashboard's state, driven against a scripted server: no browser, no React.

import assert from "node:assert/strict";
import { test } from "node:test";

import type { Transport } from "@clite/shared";
import type { Platform } from "../src/state/dashboard.ts";
import { Dashboard } from "../src/state/dashboard.ts";

type Handler = (params: Record<string, unknown>) => unknown;

/** A server on the other end of a transport: answers requests from `handlers`, sends events
 *  and server requests on demand, and records every request it saw. */
class FakeServer implements Transport {
  readonly requests: { method: string; params: Record<string, unknown> }[] = [];
  readonly answers: Record<string, unknown>[] = [];
  private receive: (text: string) => void = () => {};
  private closed: (reason: string) => void = () => {};
  private readonly handlers: Record<string, Handler>;

  constructor(handlers: Record<string, Handler>) {
    this.handlers = handlers;
  }

  send(text: string): void {
    const message = JSON.parse(text) as Record<string, unknown>;
    if (typeof message.method !== "string") {
      this.answers.push(message); // the client answering a server request
      return;
    }
    const method = message.method;
    const params = (message.params ?? {}) as Record<string, unknown>;
    this.requests.push({ method, params });
    const handler = this.handlers[method];
    queueMicrotask(() => {
      const reply = handler
        ? { jsonrpc: "2.0", id: message.id, result: handler(params) }
        : { jsonrpc: "2.0", id: message.id, error: { code: -32601, message: `no ${method}` } };
      this.receive(JSON.stringify(reply));
    });
  }

  onMessage(handler: (text: string) => void): void {
    this.receive = handler;
  }

  onClose(handler: (reason: string) => void): void {
    this.closed = handler;
  }

  close(): void {
    this.closed("closed");
  }

  event(type: string, sessionId: string, payload: unknown, seq: number): void {
    this.receive(
      JSON.stringify({ jsonrpc: "2.0", method: "event", params: { type, session_id: sessionId, payload, seq } }),
    );
  }

  ask(id: string, method: string, params: unknown): void {
    this.receive(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
  }

  /** The connection drops, as a sleeping laptop would see it. */
  drop(): void {
    this.closed("socket closed (1006)");
  }
}

let sessions = 0;

function info(id: string, extra: Record<string, unknown> = {}) {
  return {
    session_id: id,
    stored_session_id: `stored-${id}`,
    title: "",
    platform: "desktop",
    model: "mock-1",
    provider: "mock",
    cwd: "/",
    busy: false,
    yolo: false,
    message_count: 0,
    tools: [],
    toolsets: [],
    reasoning_effort: "",
    context: { context_length: 0, usage_percent: 0 },
    ...extra,
  };
}

function handlers(extra: Record<string, Handler> = {}): Record<string, Handler> {
  return {
    "system.info": () => ({ profile: "default", configured: true, notifications: true }),
    "session.create": () => info(`s${++sessions}`),
    "session.list": () => ({ sessions: [] }),
    "session.info": (params) => info(String(params.session_id)),
    "session.history": () => ({ messages: [] }),
    "prompt.submit": () => ({ accepted: true }),
    ...extra,
  };
}

interface Harness {
  dashboard: Dashboard;
  servers: FakeServer[];
  urls: string[];
  stored: Map<string, string>;
  address: { hash: string; search: string; pathname: string; replaced: string[] };
  /** Pending `later` callbacks; `tick()` runs them. */
  tick: () => Promise<void>;
  refuse: { next: string | null };
}

function harness(serverHandlers: Record<string, Handler> = handlers(), hash = "#token=secret"): Harness {
  const servers: FakeServer[] = [];
  const urls: string[] = [];
  const stored = new Map<string, string>();
  const timers: (() => void)[] = [];
  const refuse = { next: null as string | null };
  const address = { hash, search: "", pathname: "/", replaced: [] as string[] };
  const platform: Platform = {
    address: { ...address, replace: (path) => address.replaced.push(path) },
    storage: {
      getItem: (key) => stored.get(key) ?? null,
      setItem: (key, value) => void stored.set(key, value),
      removeItem: (key) => void stored.delete(key),
    },
    socketUrl: (token) => `ws://dashboard/api/ws?token=${token}`,
    openTransport: async (url) => {
      urls.push(url);
      if (refuse.next) {
        const reason = refuse.next;
        refuse.next = null;
        throw new Error(reason);
      }
      const server = new FakeServer(serverHandlers);
      servers.push(server);
      return server;
    },
    notify: () => {},
    pathForFile: async () => "",
    base64: async (file) => Buffer.from(await file.arrayBuffer()).toString("base64"),
    later: (callback) => void timers.push(callback),
  };
  const tick = async () => {
    for (const callback of timers.splice(0)) callback();
    await settle();
  };
  return { dashboard: new Dashboard(platform), servers, urls, stored, address, tick, refuse };
}

/** Let queued microtasks (fake replies) run. */
async function settle(): Promise<void> {
  for (let round = 0; round < 20; round++) await new Promise((resolve) => setImmediate(resolve));
}

test("the token is taken from the link, kept out of the address bar, and used to connect", async () => {
  const { dashboard, urls, stored, address } = harness();
  await dashboard.start();
  assert.deepEqual(urls, ["ws://dashboard/api/ws?token=secret"]);
  assert.equal(stored.get("clite-token"), "secret");
  assert.deepEqual(address.replaced, ["/"]);
  const state = dashboard.getState();
  assert.equal(state.connection.label, "connected");
  assert.equal(state.profile, "profile: default");
  assert.equal(state.views.length, 1);
  assert.equal(state.activeId, state.views[0]?.id);
});

test("without a token in the link or in storage, the dashboard asks for one first", async () => {
  const { dashboard, urls } = harness(handlers(), "");
  const started = dashboard.start();
  await settle();
  const question = dashboard.getState().dialogs[0];
  assert.equal(question?.kind, "token");
  if (question?.kind === "token") question.answer("typed");
  await started;
  assert.deepEqual(urls, ["ws://dashboard/api/ws?token=typed"]);
});

test("each event lands in the transcript of its own session only", async () => {
  const { dashboard, servers } = harness();
  await dashboard.start();
  await dashboard.openSession({});
  const [first, second] = dashboard.getState().views.map((view) => view.id);
  const server = servers[0]!;
  server.event("message.delta", first!, { text: "for the first" }, 1);
  server.event("message.delta", second!, { text: "for the second" }, 2);
  server.event("message.delta", "never-opened", { text: "nobody's" }, 3);
  const views = dashboard.getState().views;
  assert.deepEqual(
    views.map((view) => view.transcript.items.map((item) => ("text" in item ? item.text : ""))),
    [["for the first"], ["for the second"]],
  );
  assert.deepEqual(
    views.map((view) => view.lastSeq),
    [1, 2],
  );
});

test("an approval question waits in a dialog and its answer goes back to the server", async () => {
  const { dashboard, servers } = harness();
  await dashboard.start();
  const sessionId = dashboard.getState().activeId!;
  servers[0]!.ask("srq-1", "approval.request", {
    session_id: sessionId,
    command: "rm -rf build",
    description: "recursive delete",
    pattern_keys: [],
  });
  await settle();
  const question = dashboard.getState().dialogs[0];
  assert.equal(question?.kind, "approval");
  if (question?.kind === "approval") question.answer("once");
  await settle();
  assert.deepEqual(servers[0]!.answers, [{ jsonrpc: "2.0", id: "srq-1", result: { choice: "once" } }]);
  assert.equal(dashboard.getState().dialogs.length, 0);
});

test("a second question waits until the first is answered instead of replacing it", async () => {
  const { dashboard } = harness();
  const first = dashboard.askConfirm("First?", "", "Yes");
  const second = dashboard.askText("Second?", "", "");
  assert.deepEqual(
    dashboard.getState().dialogs.map((dialog) => dialog.kind),
    ["confirm", "text"],
  );
  const shown = dashboard.getState().dialogs[0];
  if (shown?.kind === "confirm") shown.answer(true);
  assert.equal(await first, true);
  assert.equal(dashboard.getState().dialogs[0]?.kind, "text");
  const next = dashboard.getState().dialogs[0];
  if (next?.kind === "text") next.answer("typed");
  assert.equal(await second, "typed");
});

test("after the socket drops, the dashboard reconnects and replays what it missed", async () => {
  const serverHandlers = handlers({
    "session.attach": (params) => ({
      session: info(String(params.session_id)),
      complete: true,
      last_seq: 5,
      events: [{ type: "message.delta", session_id: params.session_id, payload: { text: "while away" }, seq: 5 }],
    }),
  });
  const { dashboard, servers, tick } = harness(serverHandlers);
  await dashboard.start();
  servers[0]!.drop();
  assert.equal(dashboard.getState().connection.label, "reconnecting…");
  await tick();
  assert.equal(dashboard.getState().connection.label, "connected");
  const attach = servers[1]!.requests.find((request) => request.method === "session.attach");
  assert.deepEqual(attach?.params, { session_id: dashboard.getState().activeId, last_seq: 0 });
  const view = dashboard.getState().views[0]!;
  assert.equal(view.lastSeq, 5);
  assert.deepEqual(view.transcript.items, [{ kind: "assistant", text: "while away", streaming: true }]);
});

test("a token refused on reconnect is forgotten instead of retried", async () => {
  const { dashboard, servers, stored, tick, refuse, urls } = harness();
  await dashboard.start();
  refuse.next = "unauthorized";
  servers[0]!.drop();
  await tick();
  assert.equal(dashboard.getState().connection.label, "unauthorized");
  assert.equal(stored.has("clite-token"), false);
  await tick();
  assert.equal(urls.length, 2); // no further attempts
});

test("a dropped file is uploaded and its path is spelled out; an image rides as an attachment", async () => {
  const saved: Record<string, unknown>[] = [];
  const { dashboard, servers } = harness(
    handlers({
      "attachment.save": (params) => {
        saved.push(params);
        return { path: `/cache/${String(params.name)}`, name: params.name, bytes: 1, image: false };
      },
    }),
  );
  await dashboard.start();
  dashboard.addAttachments([
    { file: new Blob(["notes"]), name: "notes.txt", type: "text/plain" },
    { file: new Blob(["png"]), name: "shot.png", type: "image/png" },
  ]);
  assert.equal(dashboard.activeView()?.attachments.length, 2);
  await dashboard.send("read these");
  assert.equal(dashboard.activeView()?.attachments.length, 0);
  assert.deepEqual(
    saved.map((entry) => [entry.name, entry.data]),
    [
      ["notes.txt", Buffer.from("notes").toString("base64")],
      ["shot.png", Buffer.from("png").toString("base64")],
    ],
  );
  const submit = servers[0]!.requests.find((request) => request.method === "prompt.submit");
  assert.deepEqual(submit?.params, {
    session_id: dashboard.getState().activeId,
    text: "read these\n\n[attached: /cache/notes.txt]",
    attachments: ["/cache/shot.png"],
  });
});

test("a slash command runs through slash.exec and its answer is a notice", async () => {
  const { dashboard, servers } = harness(
    handlers({ "slash.exec": () => ({ text: "mock-1 via mock", action: null, turn_id: "", data: {} }) }),
  );
  await dashboard.start();
  await dashboard.send("/status");
  assert.ok(servers[0]!.requests.some((request) => request.method === "slash.exec"));
  assert.ok(!servers[0]!.requests.some((request) => request.method === "prompt.submit"));
  assert.deepEqual(dashboard.activeView()?.transcript.items, [
    { kind: "notice", level: "info", text: "mock-1 via mock" },
  ]);
});

test("closing the conversation on screen shows the newest other one, or opens a fresh one", async () => {
  const { dashboard } = harness(handlers({ "session.close": () => ({ ok: true }) }));
  await dashboard.start();
  await dashboard.openSession({});
  const [first, second] = dashboard.getState().views.map((view) => view.id);
  await dashboard.closeSession(second!);
  assert.equal(dashboard.getState().activeId, first);
  await dashboard.closeSession(first!);
  const state = dashboard.getState();
  assert.equal(state.views.length, 1);
  assert.notEqual(state.activeId, first);
});
