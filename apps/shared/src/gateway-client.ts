// The typed protocol client: JsonRpcChannel plus the generated contracts.
//
// `client.request("session.create", {...})` is checked against the Python contracts at
// compile time: a wrong method name, a missing parameter or a misspelt result field is a
// type error here, long before it is a runtime error there.

import type { EventEnvelope, EventType, Events, MethodName, Methods, ServerRequestName, ServerRequests } from "./contracts.generated.ts";
import { JsonRpcChannel } from "./json-rpc-channel.ts";
import type { ChannelOptions, Transport } from "./json-rpc-channel.ts";

type MaybePromise<T> = T | Promise<T>;

export class GatewayClient {
  readonly channel: JsonRpcChannel;

  constructor(transport: Transport, options: ChannelOptions = {}) {
    this.channel = new JsonRpcChannel(transport, options);
  }

  request<M extends MethodName>(method: M, params: Methods[M]["params"]): Promise<Methods[M]["result"]> {
    return this.channel.request(method, params) as Promise<Methods[M]["result"]>;
  }

  /** Every event, as a discriminated union on `type`. */
  onEvent(handler: (event: EventEnvelope) => void): () => void {
    return this.channel.onEvent((event) => handler(event as EventEnvelope));
  }

  /** Events of one type. */
  on<T extends EventType>(type: T, handler: (payload: Events[T], sessionId: string) => void): () => void {
    return this.channel.onEvent((event) => {
      if (event.type === type) handler(event.payload as Events[T], event.session_id);
    });
  }

  onServerRequest<R extends ServerRequestName>(
    name: R,
    handler: (params: ServerRequests[R]["params"]) => MaybePromise<ServerRequests[R]["result"]>,
  ): void {
    this.channel.onServerRequest(name, (params) => handler(params as ServerRequests[R]["params"]));
  }

  /** Resolves with the next event of `type` for `sessionId` (or any session when omitted). */
  waitFor<T extends EventType>(type: T, sessionId?: string): Promise<Events[T]> {
    return new Promise((resolve, reject) => {
      const stopEvents = this.on(type, (payload, from) => {
        if (sessionId !== undefined && from !== sessionId) return;
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

  close(): void {
    this.channel.close();
  }
}
