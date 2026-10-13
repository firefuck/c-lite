import React, { useEffect, useState } from "react";
import type { GatewayClient } from "@clite/shared";
import type { TabKey } from "../components/Tabs.tsx";

export function ManagementView({
  tab,
  client,
}: {
  tab: Exclude<TabKey, "chat">;
  client: GatewayClient | null;
}) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!client) return;
    setLoading(true);
    let method: any = null;

    if (tab === "sessions") method = "session.list";
    else if (tab === "config") method = "config.get";
    else if (tab === "skills") method = "skills.list";
    else if (tab === "tools") method = "tools.catalog";
    else if (tab === "plugins") method = "plugins.list";
    else if (tab === "memory") method = "memory.list";
    else if (tab === "logs") method = "logs.tail";

    if (method) {
      client.request(method, {} as any)
        .then((res) => setData(res))
        .catch((err) => setData({ error: String(err) }))
        .finally(() => setLoading(false));
    } else {
      setData({ info: `Panel ${tab} active` });
      setLoading(false);
    }
  }, [tab, client]);

  return (
    <section id={`view-${tab}`} className="view active" style={{ padding: "1.5rem", overflowY: "auto" }}>
      <h2>{tab.toUpperCase()}</h2>
      {loading ? (
        <p>Loading...</p>
      ) : (
        <pre style={{ background: "#f4f4f4", padding: "1rem", borderRadius: "4px" }}>
          {JSON.stringify(data, null, 2)}
        </pre>
      )}
    </section>
  );
}
