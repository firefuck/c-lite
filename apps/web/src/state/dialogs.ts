// What the dashboard asks the user, as data. The controller queues a question and awaits its
// answer; DialogHost draws the first one in the queue. Keeping the questions free of the DOM
// lets the controller run (and be tested) without a page.

import type { ApprovalRequestParams, ClarifyRequestParams, ProviderEntry } from "@clite/shared";

export type ApprovalChoice = "once" | "session" | "always" | "deny";

export interface SetupValues {
  provider: string;
  apiKey: string;
  model: string;
  baseUrl: string;
}

export interface CronValues {
  prompt: string;
  schedule: string;
  name: string;
}

/** Every question, with the function that answers it. ``submit`` functions throw to keep the
 *  dialog open and show the error; the dialog closes when they resolve. */
export type DialogSpec =
  | { kind: "token"; answer: (token: string) => void }
  | { kind: "approval"; params: ApprovalRequestParams; answer: (choice: ApprovalChoice) => void }
  | { kind: "clarify"; params: ClarifyRequestParams; answer: (text: string) => void }
  | { kind: "setup"; providers: ProviderEntry[]; submit: (values: SetupValues) => Promise<void>; answer: () => void }
  | { kind: "text"; title: string; label: string; initial: string; answer: (text: string | null) => void }
  | { kind: "confirm"; title: string; body: string; confirmLabel: string; answer: (ok: boolean) => void }
  | { kind: "cron"; submit: (values: CronValues) => Promise<void>; answer: () => void }
  | { kind: "output"; title: string; content: string; path: string; answer: () => void };

/** What closing a dialog without choosing (Escape) means. ``undefined``: it cannot be dismissed. */
export function dismissal(spec: DialogSpec): (() => void) | undefined {
  switch (spec.kind) {
    case "approval":
      return () => spec.answer("deny"); // silence is a no
    case "clarify":
      return () => spec.answer("");
    case "text":
      return () => spec.answer(null);
    case "confirm":
      return () => spec.answer(false);
    case "cron":
    case "output":
      return () => spec.answer();
    case "token":
    case "setup":
      return undefined; // nothing works until these are answered
  }
}
