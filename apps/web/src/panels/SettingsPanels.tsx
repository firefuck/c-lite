// Configuration and credentials: the two panels that write to the user's home.

import type { ConfigEntry, CredentialEntry } from "@clite/shared";
import { useRef } from "react";

import { useDashboard } from "../state/useDashboard.ts";
import { Actions, PanelError, useAction, useLoad } from "./common.tsx";

function parseValue(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text; // a plain string is a value too
  }
}

function ConfigRow({ entry, onSave }: { entry: ConfigEntry; onSave: (entry: ConfigEntry, text: string) => void }) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <div className={`row${entry.sensitive ? " sensitive" : ""}`} data-key={entry.key}>
      <div className="name">
        {entry.key}
        {entry.sensitive ? <span className="badge">needs confirmation</span> : null}
      </div>
      <div className="desc">{`default: ${JSON.stringify(entry.default)}`}</div>
      <Actions>
        <input type="text" id={`config-${entry.key}`} defaultValue={JSON.stringify(entry.value)} ref={input} />
        <button type="button" data-action="save" onClick={() => onSave(entry, input.current?.value ?? "")}>
          Save
        </button>
      </Actions>
    </div>
  );
}

export function ConfigPanel() {
  const dashboard = useDashboard();
  const run = useAction();
  const { data, error, reload, version } = useLoad(() => dashboard.request("config.list", {}));

  const save = (entry: ConfigEntry, text: string) =>
    run(async () => {
      const value = parseValue(text);
      if (entry.sensitive) {
        const ok = await dashboard.askConfirm(
          "Change a security setting?",
          `${entry.key} changes what the agent may do without asking. Set it to ${JSON.stringify(value)}?`,
          "Change it",
        );
        if (!ok) return;
      }
      await dashboard.request("config.set", { key: entry.key, value, confirm: entry.sensitive });
      if (entry.key.startsWith("dashboard.")) await dashboard.reloadPreferences();
      await reload();
    });

  const groups = new Map<string, ConfigEntry[]>();
  for (const entry of data?.entries ?? []) {
    groups.set(entry.group, [...(groups.get(entry.group) ?? []), entry]);
  }
  return (
    <>
      <PanelError error={error} />
      {data ? (
        <>
          <h2>{`Configuration (${data.entries.length} settings)`}</h2>
          {[...groups].map(([group, entries]) => (
            <section className="config-group" key={group}>
              <h3>{group}</h3>
              {entries.map((entry) => (
                // Keyed by the load, so every row is rebuilt from the server's answer.
                <ConfigRow key={`${entry.key}:${version}`} entry={entry} onSave={save} />
              ))}
            </section>
          ))}
        </>
      ) : null}
    </>
  );
}

function CredentialRow({
  credential,
  onSave,
  onDelete,
}: {
  credential: CredentialEntry;
  onSave: (credential: CredentialEntry, value: string) => void;
  onDelete: (credential: CredentialEntry) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <div className={`row${credential.filled ? " filled" : ""}`} data-name={credential.name}>
      <div className="name">{credential.name}</div>
      <div className="desc">{credential.filled ? `set (from ${credential.source})` : "not set"}</div>
      <Actions>
        <input
          type="password"
          id={`credential-${credential.name}`}
          autoComplete="off"
          placeholder={credential.filled ? "(set — type to replace)" : "not set"}
          ref={input}
        />
        <button type="button" data-action="save" onClick={() => onSave(credential, input.current?.value ?? "")}>
          Save
        </button>
        {credential.filled ? (
          <button type="button" data-action="delete" className="danger" onClick={() => onDelete(credential)}>
            Delete
          </button>
        ) : null}
      </Actions>
    </div>
  );
}

export function CredentialsPanel() {
  const dashboard = useDashboard();
  const run = useAction();
  const { data, error, reload, version } = useLoad(() => dashboard.request("credentials.list", {}));

  const save = (credential: CredentialEntry, value: string) =>
    run(async () => {
      if (!value) return;
      await dashboard.request("credentials.set", { name: credential.name, value });
      await reload(); // rebuilds the rows, so the value never stays in the page
    });
  const remove = (credential: CredentialEntry) =>
    run(async () => {
      if (!(await dashboard.askConfirm("Delete this credential?", credential.name, "Delete"))) return;
      await dashboard.request("credentials.delete", { name: credential.name });
      await reload();
    });

  const credentials = data?.credentials ?? [];
  return (
    <>
      <PanelError error={error} />
      {data ? (
        <>
          <h2>{`Credentials (${credentials.filter((entry) => entry.filled).length}/${credentials.length} set)`}</h2>
          <p className="desc">Values live in .env on this machine and are never sent back to this page.</p>
          {credentials.map((credential) => (
            <CredentialRow
              key={`${credential.name}:${version}`}
              credential={credential}
              onSave={save}
              onDelete={remove}
            />
          ))}
        </>
      ) : null}
    </>
  );
}
