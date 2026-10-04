// A JSON-RPC 2.0 peer over any message transport.
//
// The same class serves the terminal UI (newline-delimited JSON over a child process's
// stdio) and the desktop app (one message per WebSocket frame). It knows the three kinds of
// traffic the protocol has:
//
//   request / response    client asks, server answers
//   event                 server notifies ("method": "event")
//   server request        server asks (id "srq-N"), client answers
//
// It holds no application logic. Types for a specific protocol are layered on top in
// gateway-client.ts.

export interface Transport {
  /** Send one serialised message. */
  send(text: string): void;
  /** Register the receiver for incoming messages. Called once. */
  onMessage(handler: (text: string) => void): void;
  /** Register the close handler. Called once. */
  onClose(handler: (reason: string) => void): void;
  close(): void;
}

export class RpcError extends Error {
  readonly code: number;
  readonly data: unknown;

  constructor(code: number, message: string, data?: unknown) {
    super(message);
    this.name = "RpcError";
    this.code = code;
    this.data = data;
  }
}

export const CONNECTION_CLOSED = -1;
export const REQUEST_TIMEOUT = -2;

interface Pending {
  resolve: (value: unknown) => void;
  reject: (error: RpcError) => void;
  timer: ReturnType<typeof setTimeout> | undefined;
}

export type EventHandler = (event: { type: string; session_id: string; payload: unknown; seq: number }) => void;
export type ServerRequestHandler = (params: unknown) => unknown | Promise<unknown>;

export interface ChannelOptions {
  /** Milliseconds to wait for a response. 0 (the default) waits forever. */
  requestTimeoutMs?: number;
}

export class JsonRpcChannel {
  private nextId = 1;
  private readonly pending = new Map<number, Pending>();
  private readonly eventHandlers = new Set<EventHandler>();
  private readonly requestHandlers = new Map<string, ServerRequestHandler>();
  private readonly closeHandlers = new Set<(reason: string) => void>();
  private closed = false;
  private readonly transport: Transport;
  private readonly options: ChannelOptions;

  constructor(transport: Transport, options: ChannelOptions = {}) {
    this.transport = transport;
    this.options = options;
    transport.onMessage((text) => this.receive(text));
    transport.onClose((reason) => this.handleClose(reason));
  }

  get isClosed(): boolean {
    return this.closed;
  }

  request(method: string, params: unknown = {}): Promise<unknown> {
    if (this.closed) return Promise.reject(new RpcError(CONNECTION_CLOSED, "connection closed"));
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timeout = this.options.requestTimeoutMs ?? 0;
      const timer =
        timeout > 0
          ? setTimeout(() => {
              this.pending.delete(id);
              reject(new RpcError(REQUEST_TIMEOUT, `${method} timed out after ${timeout} ms`));
            }, timeout)
          : undefined;
      this.pending.set(id, { resolve, reject, timer });
      this.transport.send(JSON.stringify({ jsonrpc: "2.0", id, method, params }));
    });
  }

  /** Subscribe to events. Returns the unsubscribe function. */
  onEvent(handler: EventHandler): () => void {
    this.eventHandlers.add(handler);
    return () => this.eventHandlers.delete(handler);
  }

  /** Answer a server request. One handler per method; a later call replaces the earlier one. */
  onServerRequest(method: string, handler: ServerRequestHandler): void {
    this.requestHandlers.set(method, handler);
  }

  onClose(handler: (reason: string) => void): () => void {
    this.closeHandlers.add(handler);
    return () => this.closeHandlers.delete(handler);
  }

  close(): void {
    this.transport.close();
    this.handleClose("closed by client");
  }

  private receive(text: string): void {
    let message: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(text);
      if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return;
      message = parsed as Record<string, unknown>;
    } catch {
      return; // a line that is not JSON is not protocol; ignore it rather than die
    }

    if (message["method"] === "event") {
      const event = message["params"] as Parameters<EventHandler>[0];
      for (const handler of this.eventHandlers) handler(event);
      return;
    }
    if (typeof message["method"] === "string") {
      void this.answer(message["id"], message["method"], message["params"]);
      return;
    }

    const id = message["id"];
    const waiting = typeof id === "number" ? this.pending.get(id) : undefined;
    if (!waiting || typeof id !== "number") return;
    this.pending.delete(id);
    if (waiting.timer) clearTimeout(waiting.timer);
    const error = message["error"] as { code?: number; message?: string; data?: unknown } | undefined;
    if (error) waiting.reject(new RpcError(error.code ?? 0, error.message ?? "error", error.data));
    else waiting.resolve(message["result"]);
  }

  private async answer(id: unknown, method: string, params: unknown): Promise<void> {
    if (id === undefined || id === null) return; // a notification we do not know: nothing to answer
    const handler = this.requestHandlers.get(method);
    let reply: Record<string, unknown>;
    try {
      if (!handler) throw new RpcError(-32601, `no handler for ${method}`);
      reply = { jsonrpc: "2.0", id, result: await handler(params) };
    } catch (error) {
      const code = error instanceof RpcError ? error.code : -32603;
      reply = { jsonrpc: "2.0", id, error: { code, message: error instanceof Error ? error.message : String(error) } };
    }
    if (!this.closed) this.transport.send(JSON.stringify(reply));
  }

  private handleClose(reason: string): void {
    if (this.closed) return;
    this.closed = true;
    for (const waiting of this.pending.values()) {
      if (waiting.timer) clearTimeout(waiting.timer);
      waiting.reject(new RpcError(CONNECTION_CLOSED, `connection closed: ${reason}`));
    }
    this.pending.clear();
    for (const handler of this.closeHandlers) handler(reason);
  }
}
