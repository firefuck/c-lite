import { useEffect } from "react";
import type { MouseEvent } from "react";

import { errorText } from "../state/dashboard.ts";
import { useDashboard, useDashboardState } from "../state/useDashboard.ts";

export function Sidebar() {
  const dashboard = useDashboard();
  const state = useDashboardState();
  const active = state.views.find((view) => view.id === state.activeId) ?? null;
  const info = active?.info ?? null;
  const report = (error: unknown) => dashboard.notice(errorText(error), "error");

  useEffect(() => {
    document.title = info?.title ? `${info.title} · C-lite` : "C-lite";
  }, [info?.title]);

  const close = (event: MouseEvent, sessionId: string) => {
    event.stopPropagation();
    dashboard.closeSession(sessionId).catch(report);
  };

  return (
    <aside id="sidebar">
      <div className="brand">C-lite</div>
      <button id="new-chat" type="button" onClick={() => dashboard.openSession({}).catch(report)}>
        + New chat
      </button>

      <div className="section-title">Open</div>
      <ul id="open-sessions" aria-label="Open conversations">
        {state.views.map((view) => {
          const busy = view.transcript.busy;
          return (
            <li key={view.id}>
              <button
                type="button"
                data-open={view.id}
                className={`${view.id === state.activeId ? "current" : ""}${busy ? " busy" : ""}`}
                onClick={() => dashboard.activate(view.id)}
              >
                <span className="dot" />
                {view.info.title || "(new chat)"}
                {busy ? <span className="meta">working</span> : null}
                {state.views.length > 1 ? (
                  <span className="close" role="button" data-close={view.id} onClick={(event) => close(event, view.id)}>
                    ×
                  </span>
                ) : null}
              </button>
            </li>
          );
        })}
      </ul>

      <div className="section-title">Sessions</div>
      <ul id="sessions" aria-label="Sessions">
        {state.stored.map((session) => (
          <li key={session.id}>
            <button
              type="button"
              data-id={session.id}
              className={session.id === info?.stored_session_id ? "current" : ""}
              onClick={() => dashboard.openSession({ resume: session.id }).catch(report)}
            >
              {session.title || "(untitled)"}
              <span className="meta">{`${session.message_count} messages · ${session.source}`}</span>
            </button>
          </li>
        ))}
      </ul>

      <div id="status" aria-live="polite">
        <div id="status-connection" className={`pill ${state.connection.online ? "online" : "offline"}`}>
          {state.connection.label}
        </div>
        <div id="status-model">{info ? `${info.model} · ${info.provider}` : ""}</div>
        <div id="status-profile" title="This backend serves one profile">
          {state.profile}
        </div>
        <div id="status-context">
          {info?.context.context_length
            ? `context ${info.context.usage_percent}% · ${info.message_count} messages`
            : ""}
        </div>
      </div>
    </aside>
  );
}
