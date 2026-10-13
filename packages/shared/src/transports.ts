// Transports for JsonRpcChannel.

import type { Readable, Writable } from "node:stream";

import type { Transport } from "./json-rpc-channel.ts";

/** Splits a byte stream into lines. Handles a line arriving in several chunks. */
export class LineSplitter {
  private buffer = "";

  push(chunk: string): string[] {
    this.buffer += chunk;
    const lines = this.buffer.split("\n");
    this.buffer = lines.pop() ?? "";
    return lines.map((line) => line.replace(/\r$/, "")).filter((line) => line.length > 0);
  }

  /** Whatever is left when the stream ends without a final newline. */
  flush(): string[] {
    const rest = this.buffer.trim();
    this.buffer = "";
    return rest ? [rest] : [];
  }
}

/** Newline-delimited JSON over a pair of streams (a child process's stdout and stdin). */
export class LineTransport implements Transport {
  private readonly splitter = new LineSplitter();
  private messageHandler: (text: string) => void = () => {};
  private closeHandler: (reason: string) => void = () => {};
  private readonly output: Writable;

  constructor(input: Readable, output: Writable) {
    this.output = output;
    input.setEncoding("utf8");
    input.on("data", (chunk: string) => {
      for (const line of this.splitter.push(chunk)) this.messageHandler(line);
    });
    input.on("end", () => {
      for (const line of this.splitter.flush()) this.messageHandler(line);
      this.closeHandler("stream ended");
    });
    input.on("error", (error: Error) => this.closeHandler(error.message));
    output.on("error", (error: Error) => this.closeHandler(error.message));
  }

  send(text: string): void {
    this.output.write(`${text}\n`);
  }

  onMessage(handler: (text: string) => void): void {
    this.messageHandler = handler;
  }

  onClose(handler: (reason: string) => void): void {
    this.closeHandler = handler;
  }

  close(): void {
    this.output.end();
  }
}

/** The subset of the WebSocket API this transport uses (browser, Node 22+, or the `ws` package). */
export interface WebSocketLike {
  send(data: string): void;
  close(): void;
  addEventListener(type: "message", listener: (event: { data: unknown }) => void): void;
  addEventListener(type: "close", listener: (event: { code?: number; reason?: string }) => void): void;
  addEventListener(type: "open" | "error", listener: (event: unknown) => void): void;
}

export class WebSocketTransport implements Transport {
  private readonly socket: WebSocketLike;

  constructor(socket: WebSocketLike) {
    this.socket = socket;
  }

  /** Open a socket and resolve once it is connected. */
  static connect(url: string, create: (url: string) => WebSocketLike = (target) => new WebSocket(target)): Promise<WebSocketTransport> {
    return new Promise((resolve, reject) => {
      const socket = create(url);
      let settled = false;
      socket.addEventListener("open", () => {
        settled = true;
        resolve(new WebSocketTransport(socket));
      });
      socket.addEventListener("close", (event) => {
        if (!settled) reject(new Error(event.code === 4401 ? "unauthorized" : "could not connect"));
      });
      socket.addEventListener("error", () => {
        if (!settled) reject(new Error("could not connect"));
      });
    });
  }

  send(text: string): void {
    this.socket.send(text);
  }

  onMessage(handler: (text: string) => void): void {
    this.socket.addEventListener("message", (event) => handler(String(event.data)));
  }

  onClose(handler: (reason: string) => void): void {
    this.socket.addEventListener("close", (event) => handler(event.reason || `socket closed (${event.code ?? "?"})`));
  }

  close(): void {
    this.socket.close();
  }
}
