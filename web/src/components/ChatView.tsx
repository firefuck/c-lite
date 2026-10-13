import React, { useState, useEffect, useRef } from "react";
import type { GatewayClient, TranscriptState, TranscriptItem } from "@clite/shared";
import { emptyTranscript, reduce, addUserMessage } from "@clite/shared";

export function ChatView({ client, sessionId }: { client: GatewayClient | null; sessionId: string | null }) {
  const [transcript, setTranscript] = useState<TranscriptState>(emptyTranscript);
  const [input, setInput] = useState("");
  const transcriptRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!client) return;
    const unsub = client.onEvent((event) => {
      if (!sessionId || event.session_id === sessionId) {
        setTranscript((curr) => reduce(curr, event));
      }
    });
    return () => unsub();
  }, [client, sessionId]);

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || !client || !sessionId) return;
    const text = input;
    setInput("");
    setTranscript((curr) => addUserMessage(curr, text));
    try {
      await client.request("prompt.submit", {
        session_id: sessionId,
        text,
      });
    } catch (err) {
      console.error("Failed to submit prompt:", err);
    }
  };

  return (
    <section id="view-chat" className="view active" style={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <div id="transcript" ref={transcriptRef} aria-live="polite" style={{ flex: 1, overflowY: "auto", padding: "1rem" }}>
        {transcript.items.map((item, idx) => (
          <div key={idx} className={`message ${item.kind}`} style={{ marginBottom: "0.75rem" }}>
            <strong>{item.kind}: </strong>
            {"text" in item ? item.text : JSON.stringify(item)}
          </div>
        ))}
        {transcript.busy && <div className="busy-indicator">Thinking…</div>}
      </div>

      <form id="composer" onSubmit={handleSend} style={{ display: "flex", padding: "1rem", gap: "0.5rem", borderTop: "1px solid #ccc" }}>
        <textarea
          id="prompt"
          rows={2}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Message, /help for commands, or drop a file here"
          style={{ flex: 1, resize: "none" }}
        />
        <button id="send" type="submit">Send</button>
      </form>
    </section>
  );
}
