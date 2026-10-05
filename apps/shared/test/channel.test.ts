import assert from "node:assert/strict";
import { PassThrough } from "node:stream";
import { test } from "node:test";

import { CONNECTION_CLOSED, JsonRpcChannel, REQUEST_TIMEOUT, RpcError } from "../src/json-rpc-channel.ts";
import type { Transport } from "../src/json-rpc-channel.ts";
import { LineSplitter, LineTransport, WebSocketTransport } from "../src/transports.ts";
import type { WebSocketLike } from "../src/transports.ts";

/** An in-memory transport: `sent` records what the channel wrote; `deliver` plays the server. */
class FakeTransport implements Transport {
  sent: Record<string, unknown>[] = [];
  private messageHandler: (text: string) => void = () => {};
  private closeHandler: (reason: string) => void = () => {};
  closed = false;

  send(text: string): void {
    this.sent.push(JSON.parse(text));
  }
  onMessage(handler: (text: string) => void): void {
    this.messageHandler = handler;
  }
  onClose(handler: (reason: string) => void): void {
    this.closeHandler = handler;
  }
  close(): void {
    this.closed = true;
  }
  deliver(message: unknown): void {
    this.messageHandler(typeof message === "string" ? message : JSON.stringify(message));
  }
  drop(reason = "gone"): void {
    this.closeHandler(reason);
  }
}

const tick = () => new Promise((resolve) => setImmediate(resolve));

test("a request resolves with the matching response", async () => {
  const transport = new FakeTransport();
  const channel = new JsonRpcChannel(transport);
  const first = channel.request("ping");
  const second = channel.request("session.info", { session_id: "s1" });
  assert.deepEqual(transport.sent, [
    { jsonrpc: "2.0", id: 1, method: "ping", params: {} },
    { jsonrpc: "2.0", id: 2, method: "session.info", params: { session_id: "s1" } },
  ]);
  transport.deliver({ jsonrpc: "2.0", id: 2, result: { title: "second" } }); // answers may arrive out of order
  transport.deliver({ jsonrpc: "2.0", id: 1, result: { pong: true } });
  assert.deepEqual(await first, { pong: true });
  assert.deepEqual(await second, { title: "second" });
});

test("an error response rejects with code, message and data", async () => {
  const transport = new FakeTransport();
  const channel = new JsonRpcChannel(transport);
  const pending = channel.request("session.info", {});
  transport.deliver({ jsonrpc: "2.0", id: 1, error: { code: -32602, message: "invalid params", data: [{ field: "session_id" }] } });
  await assert.rejects(pending, (error: unknown) => {
    assert.ok(error instanceof RpcError);
    assert.equal(error.code, -32602);
    assert.deepEqual(error.data, [{ field: "session_id" }]);
    return true;
  });
});

test("events reach every subscriber until it unsubscribes", () => {
  const transport = new FakeTransport();
  const channel = new JsonRpcChannel(transport);
  const seen: string[] = [];
  const stop = channel.onEvent((event) => seen.push(`a:${event.type}`));
  channel.onEvent((event) => seen.push(`b:${event.type}`));
  transport.deliver({ jsonrpc: "2.0", method: "event", params: { type: "turn.start", session_id: "s", payload: {}, seq: 1 } });
  stop();
  transport.deliver({ jsonrpc: "2.0", method: "event", params: { type: "turn.complete", session_id: "s", payload: {}, seq: 2 } });
  assert.deepEqual(seen, ["a:turn.start", "b:turn.start", "b:turn.complete"]);
});

test("a server request is answered with the handler's result, sync or async", async () => {
  const transport = new FakeTransport();
  const channel = new JsonRpcChannel(transport);
  channel.onServerRequest("approval.request", (params) => ({ choice: (params as { command: string }).command === "ls" ? "once" : "deny" }));
  channel.onServerRequest("clarify.request", async () => ({ answer: "staging" }));
  transport.deliver({ jsonrpc: "2.0", id: "srq-1", method: "approval.request", params: { command: "rm -rf /" } });
  transport.deliver({ jsonrpc: "2.0", id: "srq-2", method: "clarify.request", params: {} });
  await tick();
  assert.deepEqual(transport.sent, [
    { jsonrpc: "2.0", id: "srq-1", result: { choice: "deny" } },
    { jsonrpc: "2.0", id: "srq-2", result: { answer: "staging" } },
  ]);
});

test("a server request without a handler, or whose handler throws, gets an error reply", async () => {
  const transport = new FakeTransport();
  const channel = new JsonRpcChannel(transport);
  channel.onServerRequest("clarify.request", () => {
    throw new Error("the dialog was closed");
  });
  transport.deliver({ jsonrpc: "2.0", id: "srq-1", method: "unknown.request", params: {} });
  transport.deliver({ jsonrpc: "2.0", id: "srq-2", method: "clarify.request", params: {} });
  await tick();
  assert.deepEqual(transport.sent[0], { jsonrpc: "2.0", id: "srq-1", error: { code: -32601, message: "no handler for unknown.request" } });
  assert.deepEqual(transport.sent[1], { jsonrpc: "2.0", id: "srq-2", error: { code: -32603, message: "the dialog was closed" } });
});

test("junk on the wire is ignored and the channel keeps working", async () => {
  const transport = new FakeTransport();
  const channel = new JsonRpcChannel(transport);
  const pending = channel.request("ping");
  for (const junk of ["not json", "[1, 2]", "null", '{"id": 99, "result": "nobody asked"}']) transport.deliver(junk);
  transport.deliver({ jsonrpc: "2.0", id: 1, result: "ok" });
  assert.equal(await pending, "ok");
});

test("closing rejects whatever is still pending, and later requests fail at once", async () => {
  const transport = new FakeTransport();
  const channel = new JsonRpcChannel(transport);
  const reasons: string[] = [];
  channel.onClose((reason) => reasons.push(reason));
  const pending = channel.request("prompt.submit", {});
  transport.drop("backend exited");
  await assert.rejects(pending, (error: unknown) => error instanceof RpcError && error.code === CONNECTION_CLOSED);
  await assert.rejects(channel.request("ping"), (error: unknown) => error instanceof RpcError && error.code === CONNECTION_CLOSED);
  transport.drop("again");
  assert.deepEqual(reasons, ["backend exited"]); // close is reported once
  assert.equal(channel.isClosed, true);
});

test("a request can time out", async () => {
  const channel = new JsonRpcChannel(new FakeTransport(), { requestTimeoutMs: 20 });
  await assert.rejects(channel.request("slow.method"), (error: unknown) => error instanceof RpcError && error.code === REQUEST_TIMEOUT);
});

test("LineSplitter reassembles lines split across chunks", () => {
  const splitter = new LineSplitter();
  assert.deepEqual(splitter.push('{"a":1}\n{"b"'), ['{"a":1}']);
  assert.deepEqual(splitter.push(':2}\r\n\n{"c":3}'), ['{"b":2}']);
  assert.deepEqual(splitter.flush(), ['{"c":3}']);
  assert.deepEqual(splitter.flush(), []);
});

test("LineTransport frames messages as lines in both directions", async () => {
  const fromServer = new PassThrough();
  const toServer = new PassThrough();
  const transport = new LineTransport(fromServer, toServer);
  const received: string[] = [];
  const closed: string[] = [];
  transport.onMessage((text) => received.push(text));
  transport.onClose((reason) => closed.push(reason));

  transport.send('{"id":1}');
  assert.equal(toServer.read().toString(), '{"id":1}\n');
  fromServer.write('{"id":1,"result":true}\n{"met');
  fromServer.write('hod":"event"}\n');
  fromServer.end();
  await tick();
  await tick();
  assert.deepEqual(received, ['{"id":1,"result":true}', '{"method":"event"}']);
  assert.deepEqual(closed, ["stream ended"]);
});

test("WebSocketTransport adapts a socket and reports why it could not connect", async () => {
  class FakeSocket implements WebSocketLike {
    listeners = new Map<string, ((event: never) => void)[]>();
    sent: string[] = [];
    send(data: string): void {
      this.sent.push(data);
    }
    close(): void {
      this.emit("close", { code: 1000, reason: "" });
    }
    addEventListener(type: string, listener: (event: never) => void): void {
      this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
    }
    emit(type: string, event: unknown): void {
      for (const listener of this.listeners.get(type) ?? []) listener(event as never);
    }
  }

  const socket = new FakeSocket();
  const connecting = WebSocketTransport.connect("ws://example.test", () => socket);
  socket.emit("open", {});
  const transport = await connecting;
  const received: string[] = [];
  const closed: string[] = [];
  transport.onMessage((text) => received.push(text));
  transport.onClose((reason) => closed.push(reason));
  transport.send("hello");
  socket.emit("message", { data: "world" });
  transport.close();
  assert.deepEqual([socket.sent, received, closed], [["hello"], ["world"], ["socket closed (1000)"]]);

  const refused = new FakeSocket();
  const failing = WebSocketTransport.connect("ws://example.test", () => refused);
  refused.emit("close", { code: 4401 });
  await assert.rejects(failing, /unauthorized/);
});
