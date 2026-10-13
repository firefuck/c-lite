import { useEffect, useRef, useState, useCallback } from "react";
import { GatewayClient, WebSocketTransport } from "@clite/shared";
import type { EventEnvelope, SessionInfo } from "@clite/shared";

export interface GatewayState {
  client: GatewayClient | null;
  connected: boolean;
  connecting: boolean;
  error: string | null;
  activeSessionId: string | null;
  sessionInfo: SessionInfo | null;
}

export function useGateway(url?: string) {
  const [state, setState] = useState<GatewayState>({
    client: null,
    connected: false,
    connecting: true,
    error: null,
    activeSessionId: null,
    sessionInfo: null,
  });

  const clientRef = useRef<GatewayClient | null>(null);

  const connect = useCallback(async (targetUrl: string) => {
    setState((s) => ({ ...s, connecting: true, error: null }));
    try {
      const transport = await WebSocketTransport.connect(targetUrl);
      const client = new GatewayClient(transport);
      clientRef.current = client;

      client.onEvent((event: EventEnvelope) => {
        if (event.type === "session.info") {
          setState((s) => ({
            ...s,
            sessionInfo: event.payload as SessionInfo,
            activeSessionId: event.session_id,
          }));
        }
      });

      setState((s) => ({
        ...s,
        client,
        connected: true,
        connecting: false,
        error: null,
      }));
    } catch (err: any) {
      setState((s) => ({
        ...s,
        client: null,
        connected: false,
        connecting: false,
        error: err?.message || "Failed to connect",
      }));
    }
  }, []);

  return { ...state, connect };
}
