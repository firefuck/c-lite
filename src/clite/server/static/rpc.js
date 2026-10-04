// JSON-RPC 2.0 over a WebSocket: requests, events, and server requests.
//
// This file has no dependencies and no DOM access, so the same client works in the
// dashboard, in the desktop app's renderer, and under a test runner.

export class RpcError extends Error {
  constructor(code, message, data) {
    super(message);
    this.name = "RpcError";
    this.code = code;
    this.data = data;
  }
}

export class RpcClient {
  constructor(url, { WebSocketImpl = globalThis.WebSocket } = {}) {
    this.url = url;
    this.WebSocketImpl = WebSocketImpl;
    this.nextId = 1;
    this.pending = new Map(); // id -> {resolve, reject}
    this.eventHandlers = new Set();
    this.requestHandlers = new Map(); // server request method -> async handler(params)
    this.onClose = () => {};
    this.socket = null;
  }

  connect() {
    return new Promise((resolve, reject) => {
      const socket = new this.WebSocketImpl(this.url);
      this.socket = socket;
      let opened = false;
      socket.onopen = () => {
        opened = true;
        resolve();
      };
      socket.onmessage = (message) => this.receive(String(message.data));
      socket.onerror = () => {
        if (!opened) reject(new Error("could not connect"));
      };
      socket.onclose = (event) => {
        for (const { reject: fail } of this.pending.values()) fail(new RpcError(-1, "connection closed"));
        this.pending.clear();
        if (!opened) reject(new Error(event.code === 4401 ? "unauthorized" : "connection closed"));
        this.onClose(event);
      };
    });
  }

  close() {
    if (this.socket) this.socket.close();
  }

  request(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.pending.set(id, { resolve, reject });
      this.socket.send(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
    });
  }

  onEvent(handler) {
    this.eventHandlers.add(handler);
    return () => this.eventHandlers.delete(handler);
  }

  onServerRequest(method, handler) {
    this.requestHandlers.set(method, handler);
  }

  receive(text) {
    let message;
    try {
      message = JSON.parse(text);
    } catch {
      return; // not ours to fix; the server only sends JSON
    }
    if (message.method === "event") {
      for (const handler of this.eventHandlers) handler(message.params);
      return;
    }
    if (message.method !== undefined) {
      this.answer(message);
      return;
    }
    const waiting = this.pending.get(message.id);
    if (!waiting) return;
    this.pending.delete(message.id);
    if (message.error) waiting.reject(new RpcError(message.error.code, message.error.message, message.error.data));
    else waiting.resolve(message.result);
  }

  async answer(message) {
    const handler = this.requestHandlers.get(message.method);
    let reply;
    try {
      if (!handler) throw new Error(`no handler for ${message.method}`);
      reply = { jsonrpc: "2.0", id: message.id, result: await handler(message.params) };
    } catch (error) {
      reply = { jsonrpc: "2.0", id: message.id, error: { code: -32603, message: String(error.message || error) } };
    }
    this.socket.send(JSON.stringify(reply));
  }
}
