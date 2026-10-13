// Skills, tools, plugins, hooks and profiles: what is installed, and little to change.

import { useEffect, useState } from "react";
import type { PluginsListResult } from "@clite/shared";

import { useDashboard, useDashboardState } from "../state/useDashboard.ts";
import { Actions, PanelError, Row, useAction, useLoad } from "./common.tsx";

export function SkillsPanel() {
  const dashboard = useDashboard();
  const { data, error } = useLoad(() => dashboard.request("skills.list", {}));
  return (
    <>
      <PanelError error={error} />
      {data ? (
        <>
          <h2>{`Skills (${data.skills.length})`}</h2>
          {data.skills.map((skill) => (
            <Row
              key={skill.name}
              name={`/${skill.name}`}
              desc={`${skill.description} · ${skill.category || "general"} · ${skill.tier}`}
            />
          ))}
        </>
      ) : null}
    </>
  );
}

export function ToolsPanel() {
  const dashboard = useDashboard();
  const { activeId } = useDashboardState();
  const { data, error } = useLoad(() => dashboard.request("tools.list", { session_id: activeId }), [activeId]);
  return (
    <>
      <h2>Toolsets</h2>
      <PanelError error={error} />
      {(data?.toolsets ?? []).map((set) => (
        <Row
          key={set.name}
          name={`${set.name}  (${set.enabled_tools.length}/${set.tools.length})`}
          desc={`${set.description} · ${set.tools.join(", ")}`}
        />
      ))}
    </>
  );
}

interface PluginPage {
  name: string;
  title: string;
  url: string;
}

/**
 * Pages plugins ship are frames, not markup: the sandbox drops allow-same-origin, so the frame
 * gets an origin of its own (and the page is served from a port of its own too). It cannot
 * read this document, this origin's storage, or the session token.
 */
function PluginFrames() {
  const dashboard = useDashboard();
  const [pages, setPages] = useState<PluginPage[]>([]);
  useEffect(() => {
    let current = true;
    fetch("/api/plugin-pages", { headers: { "X-Clite-Token": dashboard.sessionToken } })
      .then((response) => response.json() as Promise<{ plugins: PluginPage[] }>)
      .then(({ plugins }) => {
        if (current) setPages(plugins.filter((page) => page.url));
      })
      .catch(() => undefined); // no pages is not an error worth showing
    return () => {
      current = false;
    };
  }, [dashboard]);
  return (
    <>
      {pages.map((page) => (
        <section key={page.name}>
          <h2>{page.title}</h2>
          <iframe
            className="plugin-page"
            src={page.url}
            sandbox="allow-scripts allow-forms allow-popups"
            loading="lazy"
            referrerPolicy="no-referrer"
            title={`${page.name} dashboard page`}
          />
        </section>
      ))}
    </>
  );
}

export function PluginsPanel() {
  const dashboard = useDashboard();
  const run = useAction();
  const loaded = useLoad(() => dashboard.request("plugins.list", {}));
  const [changed, setChanged] = useState<PluginsListResult | null>(null);
  const data = changed ?? loaded.data;
  return (
    <>
      <h2>Plugins</h2>
      <PanelError error={loaded.error} />
      {(data?.plugins ?? []).map((plugin) => (
        <Row
          key={plugin.name}
          name={`${plugin.name} ${plugin.version}`}
          desc={`${plugin.status} · ${plugin.source} · ${plugin.error || plugin.description}`}
        >
          <Actions>
            <button
              type="button"
              onClick={() =>
                run(async () =>
                  setChanged(
                    await dashboard.request("plugins.set_enabled", {
                      name: plugin.name,
                      enabled: plugin.status !== "loaded",
                    }),
                  ),
                )
              }
            >
              {plugin.status === "loaded" ? "Disable" : "Enable"}
            </button>
          </Actions>
        </Row>
      ))}
      {/* After plugins.list: loading the plugins is what registers the pages they ship. */}
      {loaded.data ? <PluginFrames /> : null}
    </>
  );
}

export function HooksPanel() {
  const dashboard = useDashboard();
  const { data, error } = useLoad(() =>
    Promise.all([dashboard.request("hooks.status", {}), dashboard.request("mcp.status", {})]),
  );
  if (!data) return <PanelError error={error} />;
  const [hooks, mcp] = data;
  return (
    <>
      <h2>Shell hooks</h2>
      <p className="desc">
        {hooks.pending
          ? `${hooks.pending} hook(s) are waiting for approval. Approving one is a local act: run "clite hooks approve" on this machine.`
          : "Every configured hook is approved on this machine."}
      </p>
      {hooks.hooks.length ? (
        hooks.hooks.map((hook, index) => (
          <Row
            key={index}
            name={`${hook.event}${hook.matcher ? ` · ${hook.matcher}` : ""}`}
            desc={`${hook.command} · ${hook.approved ? "approved" : "waiting for approval"}${hook.fail_closed ? " · fail-closed" : ""}`}
          />
        ))
      ) : (
        <p className="empty">No shell hooks configured.</p>
      )}
      <h2>MCP servers</h2>
      {mcp.servers.length ? (
        mcp.servers.map((server) => (
          <Row
            key={server.name}
            name={server.name}
            desc={`${server.transport} · ${server.alive ? "connected" : "not connected"} · ${server.tools.length} tools · ${server.resources} resources · ${server.prompts} prompts`}
          />
        ))
      ) : (
        <p className="empty">{`${mcp.configured} configured; none connected in this session.`}</p>
      )}
    </>
  );
}

export function ProfilesPanel() {
  const dashboard = useDashboard();
  const { data, error } = useLoad(() => dashboard.request("profiles.list", {}));
  if (!data) return <PanelError error={error} />;
  const { current, sticky, profiles } = data;
  const describe = (name: string) => {
    if (name === current) return "this dashboard is running here";
    if (window.cliteDesktop) return `restart C-lite with --profile ${name}`;
    return `run: clite dashboard -p ${name}`;
  };
  return (
    <>
      <h2>Profiles</h2>
      <p className="empty">
        A profile is a separate home: its own config, keys, memory and sessions. One backend serves one profile, so
        switching means starting another one.
      </p>
      {profiles.map((profile) => (
        <div
          key={profile.name}
          className={`row${profile.name === current ? " current" : ""}`}
          data-profile={profile.name}
        >
          <div className="name">
            {profile.name}
            {profile.name === current ? <span className="badge">running</span> : null}
            {profile.name === sticky && profile.name !== current ? (
              <span className="badge">default for new shells</span>
            ) : null}
          </div>
          <div className="desc">{describe(profile.name)}</div>
        </div>
      ))}
    </>
  );
}
