import { useState } from "react";
import type { StoredSession } from "@clite/shared";

import { useDashboard } from "../state/useDashboard.ts";
import { Actions, PanelError, Row, plural, useAction, useLoad } from "./common.tsx";

/** Save a session's JSON through the browser's download machinery. */
function download(filename: string, content: string): void {
  const url = URL.createObjectURL(new Blob([content], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

export function SessionsPanel() {
  const dashboard = useDashboard();
  const run = useAction();
  const [query, setQuery] = useState("");
  const [archived, setArchived] = useState(false);
  const text = query.trim();
  const search = useLoad(() => (text ? dashboard.request("session.search", { query: text }) : Promise.resolve(null)), [
    text,
  ]);
  const listing = useLoad(
    () => (text ? Promise.resolve(null) : dashboard.request("session.list", { limit: 100, include_archived: archived })),
    [text, archived],
  );

  const after = async () => {
    await dashboard.refreshSessions();
    await listing.reload();
  };
  const open = (id: string) => dashboard.openSession({ resume: id });
  const rename = async (session: StoredSession) => {
    const title = await dashboard.askText("Rename session", "Title", session.title || "");
    if (title === null) return;
    await dashboard.request("session.rename", { stored_session_id: session.id, title });
    await after();
  };
  const remove = async (session: StoredSession) => {
    if (!(await dashboard.askConfirm("Delete this session?", session.title || session.id, "Delete"))) return;
    await dashboard.request("session.delete", { stored_session_id: session.id });
    await after();
  };
  const exportSession = async (session: StoredSession) => {
    const { filename, content } = await dashboard.request("session.export", { stored_session_id: session.id });
    download(filename, content);
  };

  let results = null;
  if (text && search.data) {
    const { hits } = search.data;
    results = (
      <>
        <h3>{plural(hits.length, "match", "matches")}</h3>
        {hits.length ? (
          hits.map((hit, index) => (
            <Row key={index} name={hit.title || hit.stored_session_id} desc={`${hit.role} · ${hit.source} · ${hit.snippet}`}>
              <Actions>
                <button type="button" onClick={() => run(() => open(hit.stored_session_id))}>
                  Open
                </button>
              </Actions>
            </Row>
          ))
        ) : (
          <p className="empty">Nothing matched.</p>
        )}
      </>
    );
  } else if (!text && listing.data) {
    const { sessions } = listing.data;
    results = (
      <>
        <h3>{plural(sessions.length, "session")}</h3>
        {sessions.length ? (
          sessions.map((session) => {
            const flags = [session.pinned && "pinned", session.archived && "archived"].filter(Boolean);
            return (
              <Row
                key={`${session.id}:${listing.version}`}
                name={session.title || "(untitled)"}
                desc={`${session.message_count} messages · ${session.source}${flags.length ? ` · ${flags.join(", ")}` : ""}`}
              >
                <Actions>
                  <button type="button" data-action="open" onClick={() => run(() => open(session.id))}>
                    Open
                  </button>
                  <button type="button" data-action="rename" onClick={() => run(() => rename(session))}>
                    Rename
                  </button>
                  <button
                    type="button"
                    data-action="pin"
                    onClick={() =>
                      run(async () => {
                        await dashboard.request("session.pin", { stored_session_id: session.id, pinned: !session.pinned });
                        await after();
                      })
                    }
                  >
                    {session.pinned ? "Unpin" : "Pin"}
                  </button>
                  <button
                    type="button"
                    data-action="archive"
                    onClick={() =>
                      run(async () => {
                        await dashboard.request("session.archive", {
                          stored_session_id: session.id,
                          archived: !session.archived,
                        });
                        await after();
                      })
                    }
                  >
                    {session.archived ? "Restore" : "Archive"}
                  </button>
                  <button type="button" data-action="export" onClick={() => run(() => exportSession(session))}>
                    Export
                  </button>
                  <button type="button" data-action="delete" className="danger" onClick={() => run(() => remove(session))}>
                    Delete
                  </button>
                </Actions>
              </Row>
            );
          })
        ) : (
          <p className="empty">No sessions yet.</p>
        )}
      </>
    );
  }

  return (
    <>
      <h2>Sessions</h2>
      <div className="filters">
        <input
          type="search"
          id="session-search"
          placeholder="Search every message…"
          autoComplete="off"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <label>
          <input
            type="checkbox"
            id="session-archived"
            checked={archived}
            onChange={(event) => setArchived(event.target.checked)}
          />
          include archived
        </label>
      </div>
      <PanelError error={search.error || listing.error} />
      <div id="session-results">{results}</div>
    </>
  );
}
