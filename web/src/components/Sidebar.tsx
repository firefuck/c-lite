import React from "react";
import type { SessionInfo } from "@clite/shared";

export function Sidebar({
  sessionInfo,
  connected,
  onNewChat,
}: {
  sessionInfo: SessionInfo | null;
  connected: boolean;
  onNewChat: () => void;
}) {
  return (
    <aside id="sidebar">
      <div className="brand">C-lite</div>
      <button id="new-chat" type="button" onClick={onNewChat}>+ New chat</button>
      <div className="section-title">Open</div>
      <ul id="open-sessions" aria-label="Open conversations"></ul>
      <div className="section-title">Sessions</div>
      <ul id="sessions" aria-label="Sessions"></ul>
      <div id="status" aria-live="polite">
        <div id="status-connection" className={`pill ${connected ? "online" : "offline"}`}>
          {connected ? "online" : "connecting…"}
        </div>
        <div id="status-model">{sessionInfo?.model || ""}</div>
        <div id="status-profile" title="This backend serves one profile">
          {sessionInfo?.provider || ""}
        </div>
        <div id="status-context"></div>
      </div>
    </aside>
  );
}
