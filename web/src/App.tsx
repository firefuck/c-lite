import React, { useState, useEffect } from "react";
import { useGateway } from "./hooks/useGateway.ts";
import { Sidebar } from "./components/Sidebar.tsx";
import { Tabs, type TabKey } from "./components/Tabs.tsx";
import { ChatView } from "./components/ChatView.tsx";
import { ManagementView } from "./panels/Panels.tsx";

export function App() {
  const [activeTab, setActiveTab] = useState<TabKey>("chat");
  const { client, connected, activeSessionId, sessionInfo, connect } = useGateway();

  useEffect(() => {
    // Ambil token dari fragment hash #token=xxx
    const hash = window.location.hash.slice(1);
    const params = new URLSearchParams(hash);
    const token = params.get("token") || "";

    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = window.location.host;
    const wsUrl = `${proto}//${host}/api/ws${token ? `?token=${encodeURIComponent(token)}` : ""}`;
    connect(wsUrl);
  }, [connect]);

  const handleNewChat = async () => {
    if (!client) return;
    try {
      await client.request("session.create", {});
    } catch (err) {
      console.error("Create session failed:", err);
    }
  };

  return (
    <div id="app" style={{ display: "flex", height: "100vh" }}>
      <Sidebar
        sessionInfo={sessionInfo}
        connected={connected}
        onNewChat={handleNewChat}
      />
      <main style={{ flex: 1, display: "flex", flexDirection: "column" }}>
        <Tabs activeTab={activeTab} onTabSelect={setActiveTab} />
        {activeTab === "chat" ? (
          <ChatView client={client} sessionId={activeSessionId} />
        ) : (
          <ManagementView tab={activeTab} client={client} />
        )}
      </main>
    </div>
  );
}
