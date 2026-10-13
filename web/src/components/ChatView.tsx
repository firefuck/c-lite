import { useEffect, useRef, useState } from "react";
import type { ClipboardEvent, DragEvent, FormEvent, KeyboardEvent } from "react";

import { askNotificationPermission } from "../state/browser.ts";
import { errorText } from "../state/dashboard.ts";
import { useDashboard, useDashboardState } from "../state/useDashboard.ts";
import { Transcript } from "./Transcript.tsx";

function filesOf(list: FileList | null | undefined): { file: Blob; name: string; type: string }[] {
  return [...(list ?? [])].map((file) => ({ file, name: file.name, type: file.type }));
}

export function ChatView({ active }: { active: boolean }) {
  const dashboard = useDashboard();
  const state = useDashboardState();
  const view = state.views.find((entry) => entry.id === state.activeId) ?? null;
  const busy = view?.transcript.busy ?? false;
  const [dragging, setDragging] = useState(false);
  const prompt = useRef<HTMLTextAreaElement>(null);
  const composer = useRef<HTMLFormElement>(null);

  useEffect(() => {
    if (active) prompt.current?.focus();
  }, [active, state.activeId]);

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const field = prompt.current;
    if (!field) return;
    const text = field.value;
    field.value = "";
    askNotificationPermission(); // a user gesture: the only moment a browser will ask
    dashboard.send(text).catch((error: unknown) => dashboard.notice(errorText(error), "error"));
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      composer.current?.requestSubmit();
    }
  };

  const onPaste = (event: ClipboardEvent<HTMLTextAreaElement>) => {
    const files = filesOf(event.clipboardData?.files);
    if (files.length) {
      event.preventDefault();
      dashboard.addAttachments(files);
    }
  };

  const onDragOver = (event: DragEvent) => {
    event.preventDefault(); // without this the browser just opens the file
    setDragging(true);
  };

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    dashboard.addAttachments(filesOf(event.dataTransfer?.files));
  };

  return (
    <section
      id="view-chat"
      className={`view${active ? " active" : ""}`}
      onDragEnter={onDragOver}
      onDragOver={onDragOver}
      onDragLeave={() => setDragging(false)}
      onDragEnd={() => setDragging(false)}
      onDrop={onDrop}
    >
      <Transcript items={view?.transcript.items ?? []} banner={state.banner} />
      <form id="composer" ref={composer} className={dragging ? "dragging" : undefined} onSubmit={submit}>
        <div id="attachments" aria-live="polite">
          {(view?.attachments ?? []).map((entry, index) => (
            <span className="chip" data-name={entry.name} key={`${index}:${entry.name}`}>
              {entry.image ? "image · " : "file · "}
              {entry.name}
              <span className="remove" role="button" data-remove={index} onClick={() => dashboard.removeAttachment(index)}>
                ×
              </span>
            </span>
          ))}
        </div>
        <textarea
          id="prompt"
          ref={prompt}
          rows={2}
          placeholder="Message, /help for commands, or drop a file here"
          autoComplete="off"
          onKeyDown={onKeyDown}
          onPaste={onPaste}
        />
        <button id="send" type="submit" hidden={busy}>
          Send
        </button>
        <button id="stop" type="button" hidden={!busy} onClick={() => dashboard.interrupt()}>
          Stop
        </button>
      </form>
    </section>
  );
}
