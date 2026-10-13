import type { ComponentType } from "react";
import { useEffect, useState } from "react";

import { ChatView } from "./components/ChatView.tsx";
import { Sidebar } from "./components/Sidebar.tsx";
import { DialogHost } from "./dialogs/DialogHost.tsx";
import { HooksPanel, PluginsPanel, ProfilesPanel, SkillsPanel, ToolsPanel } from "./panels/InfoPanels.tsx";
import { SessionsPanel } from "./panels/SessionsPanel.tsx";
import { ConfigPanel, CredentialsPanel } from "./panels/SettingsPanels.tsx";
import { CronPanel, LogsPanel, MemoryPanel } from "./panels/WorkPanels.tsx";
import { useDashboard, useDashboardState } from "./state/useDashboard.ts";

/** Every tab after "Chat", in the order the tab bar shows them. */
const PANELS: [string, string, ComponentType][] = [
  ["sessions", "Sessions", SessionsPanel],
  ["config", "Config", ConfigPanel],
  ["credentials", "Credentials", CredentialsPanel],
  ["skills", "Skills", SkillsPanel],
  ["tools", "Tools", ToolsPanel],
  ["cron", "Cron", CronPanel],
  ["plugins", "Plugins", PluginsPanel],
  ["memory", "Memory", MemoryPanel],
  ["logs", "Logs", LogsPanel],
  ["hooks", "Hooks & MCP", HooksPanel],
  ["profiles", "Profiles", ProfilesPanel],
];

export function App() {
  const dashboard = useDashboard();
  const state = useDashboardState();
  const [tab, setTab] = useState("chat");
  // Opening a tab loads it afresh, so a panel never shows what was true when it was last open.
  const [visit, setVisit] = useState(0);
  const select = (name: string) => {
    setTab(name);
    setVisit((value) => value + 1);
  };
  const online = state.connection.online;

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const busy = dashboard.activeView()?.transcript.busy;
      if (event.key === "Escape" && busy && !dashboard.getState().dialogs.length) dashboard.interrupt();
    };
    const onUnload = () => dashboard.stop();
    document.addEventListener("keydown", onKeyDown);
    window.addEventListener("beforeunload", onUnload);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("beforeunload", onUnload);
    };
  }, [dashboard]);

  return (
    <>
      <div id="app">
        <Sidebar />
        <main>
          <div id="tabs" role="tablist">
            {[["chat", "Chat"] as const, ...PANELS.map(([name, label]) => [name, label] as const)].map(
              ([name, label]) => (
                <button
                  key={name}
                  type="button"
                  role="tab"
                  data-tab={name}
                  className={tab === name ? "active" : undefined}
                  onClick={() => select(name)}
                >
                  {label}
                </button>
              ),
            )}
          </div>
          <ChatView active={tab === "chat"} />
          {PANELS.map(([name, , Panel]) => (
            <section key={name} id={`view-${name}`} className={`view${tab === name ? " active" : ""}`}>
              <div className="panel" id={`panel-${name}`}>
                {tab === name && online ? <Panel key={visit} /> : null}
              </div>
            </section>
          ))}
        </main>
      </div>
      <DialogHost />
    </>
  );
}
