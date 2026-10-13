// The one <dialog> on the page. It shows the first queued question and stays open while the
// queue is not empty, so a question that arrives while another is open waits its turn instead
// of replacing it.

import type { ReactNode, SyntheticEvent } from "react";
import { useEffect, useRef, useState } from "react";

import { errorText } from "../state/dashboard.ts";
import type { DialogSpec } from "../state/dialogs.ts";
import { dismissal } from "../state/dialogs.ts";
import { useDashboardState } from "../state/useDashboard.ts";

const ids = new WeakMap<DialogSpec, number>();
let nextId = 0;

function idOf(spec: DialogSpec): number {
  let id = ids.get(spec);
  if (id === undefined) {
    id = nextId++;
    ids.set(spec, id);
  }
  return id;
}

export function DialogHost() {
  const { dialogs } = useDashboardState();
  const spec = dialogs[0] ?? null;
  const element = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = element.current;
    if (!dialog) return;
    if (spec && !dialog.open) dialog.showModal();
    if (!spec && dialog.open) dialog.close();
  }, [spec]);

  const onCancel = (event: SyntheticEvent) => {
    // Escape: the queue decides what closing means, and whether the dialog may close at all.
    event.preventDefault();
    if (spec) dismissal(spec)?.();
  };

  return (
    <dialog id="dialog" ref={element} onCancel={onCancel}>
      <div id="dialog-body">{spec ? <Body key={idOf(spec)} spec={spec} /> : null}</div>
    </dialog>
  );
}

function Buttons({ children }: { children: ReactNode }) {
  return <div className="buttons">{children}</div>;
}

function Body({ spec }: { spec: DialogSpec }) {
  switch (spec.kind) {
    case "token":
      return <TokenDialog spec={spec} />;
    case "approval":
      return <ApprovalDialog spec={spec} />;
    case "clarify":
      return <ClarifyDialog spec={spec} />;
    case "setup":
      return <SetupDialog spec={spec} />;
    case "text":
      return <TextDialog spec={spec} />;
    case "confirm":
      return <ConfirmDialog spec={spec} />;
    case "cron":
      return <CronDialog spec={spec} />;
    case "output":
      return <OutputDialog spec={spec} />;
  }
}

type Spec<K extends DialogSpec["kind"]> = Extract<DialogSpec, { kind: K }>;

function TokenDialog({ spec }: { spec: Spec<"token"> }) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <h2>Session token</h2>
      <p>Open the link printed by `clite dashboard`, or paste the token here.</p>
      <input id="token-input" type="password" autoComplete="off" ref={input} />
      <Buttons>
        <button className="primary" type="button" onClick={() => spec.answer(input.current?.value.trim() ?? "")}>
          Connect
        </button>
      </Buttons>
    </>
  );
}

function ApprovalDialog({ spec }: { spec: Spec<"approval"> }) {
  const choices = [
    ["deny", "Deny"],
    ["once", "Once"],
    ["session", "This session"],
    ["always", "Always"],
  ] as const;
  return (
    <>
      <h2>Approve this command?</h2>
      <p>{spec.params.description}</p>
      <code id="approval-command">{spec.params.command}</code>
      <Buttons>
        {choices.map(([choice, label]) => (
          <button
            key={choice}
            type="button"
            className={choice === "deny" ? "danger" : undefined}
            data-choice={choice}
            onClick={() => spec.answer(choice)}
          >
            {label}
          </button>
        ))}
      </Buttons>
    </>
  );
}

function ClarifyDialog({ spec }: { spec: Spec<"clarify"> }) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <h2>{spec.params.question}</h2>
      <Buttons>
        {spec.params.choices.map((choice) => (
          <button key={choice} type="button" onClick={() => spec.answer(choice)}>
            {choice}
          </button>
        ))}
      </Buttons>
      <input id="clarify-input" type="text" placeholder="Your answer" ref={input} />
      <Buttons>
        <button className="primary" type="button" onClick={() => spec.answer(input.current?.value ?? "")}>
          Answer
        </button>
      </Buttons>
    </>
  );
}

/** A form whose submit may fail: the error shows in the dialog and the dialog stays open. */
function useSubmit(run: () => Promise<void>, done: () => void): [string, () => void] {
  const [problem, setProblem] = useState("");
  const submit = () => {
    run().then(done, (error: unknown) => setProblem(errorText(error)));
  };
  return [problem, submit];
}

function SetupDialog({ spec }: { spec: Spec<"setup"> }) {
  const provider = useRef<HTMLSelectElement>(null);
  const apiKey = useRef<HTMLInputElement>(null);
  const model = useRef<HTMLInputElement>(null);
  const baseUrl = useRef<HTMLInputElement>(null);
  const [problem, save] = useSubmit(
    () =>
      spec.submit({
        provider: provider.current?.value ?? "",
        apiKey: apiKey.current?.value ?? "",
        model: model.current?.value ?? "",
        baseUrl: baseUrl.current?.value ?? "",
      }),
    spec.answer,
  );
  return (
    <>
      <h2>Set up a model</h2>
      <label htmlFor="setup-provider">Provider</label>
      <select id="setup-provider" ref={provider}>
        {spec.providers.map((entry) => (
          <option key={entry.name} value={entry.name}>{`${entry.display_name} — ${entry.description}`}</option>
        ))}
      </select>
      <label htmlFor="setup-key">API key (stored in .env on this machine)</label>
      <input id="setup-key" type="password" autoComplete="off" ref={apiKey} />
      <label htmlFor="setup-model">Model</label>
      <input id="setup-model" type="text" placeholder="model id" ref={model} />
      <label htmlFor="setup-url">Base URL</label>
      <input id="setup-url" type="text" placeholder="http://localhost:8000/v1 (custom endpoints only)" ref={baseUrl} />
      <p className="message error">{problem}</p>
      <Buttons>
        <button className="primary" type="button" onClick={save}>
          Save
        </button>
      </Buttons>
    </>
  );
}

function TextDialog({ spec }: { spec: Spec<"text"> }) {
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    input.current?.focus();
    input.current?.select();
  }, []);
  return (
    <>
      <h2>{spec.title}</h2>
      <label htmlFor="ask-text">{spec.label}</label>
      <input type="text" id="ask-text" defaultValue={spec.initial} ref={input} />
      <Buttons>
        <button type="button" onClick={() => spec.answer(null)}>
          Cancel
        </button>
        <button className="primary" type="button" onClick={() => spec.answer(input.current?.value ?? "")}>
          Save
        </button>
      </Buttons>
    </>
  );
}

function ConfirmDialog({ spec }: { spec: Spec<"confirm"> }) {
  return (
    <>
      <h2>{spec.title}</h2>
      <p>{spec.body}</p>
      <Buttons>
        <button type="button" onClick={() => spec.answer(false)}>
          Cancel
        </button>
        <button className="danger" type="button" data-confirm="yes" onClick={() => spec.answer(true)}>
          {spec.confirmLabel}
        </button>
      </Buttons>
    </>
  );
}

function CronDialog({ spec }: { spec: Spec<"cron"> }) {
  const prompt = useRef<HTMLInputElement>(null);
  const schedule = useRef<HTMLInputElement>(null);
  const name = useRef<HTMLInputElement>(null);
  useEffect(() => prompt.current?.focus(), []);
  const [problem, create] = useSubmit(
    () =>
      spec.submit({
        prompt: prompt.current?.value ?? "",
        schedule: schedule.current?.value ?? "",
        name: name.current?.value ?? "",
      }),
    spec.answer,
  );
  return (
    <>
      <h2>Schedule a job</h2>
      <label htmlFor="cron-prompt">Prompt</label>
      <input
        type="text"
        id="cron-prompt"
        placeholder="what to ask, e.g. summarise my open pull requests"
        ref={prompt}
      />
      <label htmlFor="cron-schedule">Schedule</label>
      <input type="text" id="cron-schedule" placeholder="when, e.g. every morning at 9" ref={schedule} />
      <label htmlFor="cron-name">Name</label>
      <input type="text" id="cron-name" placeholder="name (optional)" ref={name} />
      <p className="message error">{problem}</p>
      <Buttons>
        <button type="button" onClick={() => spec.answer()}>
          Cancel
        </button>
        <button className="primary" type="button" data-action="create" onClick={create}>
          Create
        </button>
      </Buttons>
    </>
  );
}

function OutputDialog({ spec }: { spec: Spec<"output"> }) {
  return (
    <>
      <h2>{spec.title}</h2>
      {spec.content ? <pre id="cron-output">{spec.content}</pre> : <p className="empty">No output saved yet.</p>}
      {spec.path ? <div className="desc">{spec.path}</div> : null}
      <Buttons>
        <button type="button" onClick={() => spec.answer()}>
          Close
        </button>
      </Buttons>
    </>
  );
}
