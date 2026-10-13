import React from "react";

export const TAB_LIST = [
  "chat", "sessions", "config", "credentials", "skills",
  "tools", "cron", "plugins", "memory", "logs", "hooks", "profiles"
] as const;

export type TabKey = typeof TAB_LIST[number];

export function Tabs({ activeTab, onTabSelect }: { activeTab: TabKey; onTabSelect: (tab: TabKey) => void }) {
  return (
    <nav id="tabs" role="tablist">
      {TAB_LIST.map((tab) => (
        <button
          key={tab}
          type="button"
          role="tab"
          data-tab={tab}
          className={activeTab === tab ? "active" : ""}
          onClick={() => onTabSelect(tab)}
        >
          {tab.charAt(0).toUpperCase() + tab.slice(1)}
        </button>
      ))}
    </nav>
  );
}
