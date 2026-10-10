// The root Ink component for the full-screen TUI.
//
// C-lite keeps this deliberately small: a scrollable transcript (from the shared reducer) and
// a single-line composer below it. The transcript uses the same `reduce()` as the plain UI, so
// the two surfaces cannot disagree. Conversation logic stays in the backend; this component
// only sends `prompt.submit` and renders events. Dialogs, completion and pickers arrive in
// later tasks (F3-T11, F3-T12, F3-T13).

import { Box, Text, useApp, useInput, useStdout } from "ink";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import type { CatalogResult, CommandEntry, EventEnvelope, ModelEntry, ModelListResult, PromptSubmitResult, SessionInfo, SessionListResult, StoredSession } from "../../../apps/shared/src/contracts.generated.ts";
import type { GatewayClient } from "../../../apps/shared/src/gateway-client.ts";
import { addUserMessage, emptyTranscript, reduce, type TranscriptItem, type TranscriptState } from "../../../apps/shared/src/transcript.ts";
import { formatItem } from "../render.ts";
import { CompletionMenu } from "./CompletionMenu.tsx";
import { ApprovalDialog, ClarifyDialog } from "./Dialogs.tsx";
import { ModelPicker, SessionPicker } from "./Pickers.tsx";
import { StatusBar, type StatusBarState } from "./StatusBar.tsx";
import { applySlashCompletion, getSlashCandidates, handleTabCompletion } from "./completion.ts";
import type { ApprovalChoice } from "./dialogs.ts";
import { resumeSession, switchModel } from "./pickers.ts";

export interface AppProps {
  client: GatewayClient;
  session: SessionInfo;
}

/** A wrapper around the shared reducer that also accepts an optimistic user message. */
type Action = { kind: "event"; event: EventEnvelope } | { kind: "user"; text: string };

function appReducer(state: TranscriptState, action: Action): TranscriptState {
  if (action.kind === "user") return addUserMessage(state, action.text);
  return reduce(state, action.event);
}

/** A transcript line, rendered from a `TranscriptItem` the same way `plain.ts` renders it. */
function TranscriptLine({ item, color }: { item: TranscriptItem; color: boolean }) {
  return <Text>{formatItem(item, color)}</Text>;
}

/** The transcript: a top-aligned column of rendered items. */
function Transcript({ state, color }: { state: TranscriptState; color: boolean }) {
  return (
    <Box flexDirection="column" flexGrow={1} overflow="hidden" paddingBottom={1}>
      {state.items.map((item, index) => (
        <TranscriptLine key={index} item={item} color={color} />
      ))}
      {state.busy && <Text dimColor>…</Text>}
    </Box>
  );
}

/** The composer: one line of input with slash completion. Enter sends, Ctrl+C interrupts, Ctrl+D quits. */
function Composer({ onSubmit, onInterrupt, onQuit, prompt, catalog }: {
  onSubmit: (text: string) => void;
  onInterrupt: () => void;
  onQuit: () => void;
  prompt: string;
  catalog: CommandEntry[];
}) {
  const [value, setValue] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState(0);

  const candidates = useMemo(() => {
    if (!value.startsWith("/")) return [];
    return getSlashCandidates(catalog, value);
  }, [catalog, value]);

  useInput((input, key) => {
    if (key.ctrl && input === "d") { onQuit(); return; }
    if (key.ctrl && input === "c") { onInterrupt(); return; }

    if (key.escape) {
      if (menuOpen) {
        setMenuOpen(false);
        return;
      }
    }

    if (key.tab) {
      const res = handleTabCompletion(value, catalog);
      setValue(res.text);
      setMenuOpen(res.menuOpen);
      setSelectedIndex(0);
      return;
    }

    if (menuOpen && candidates.length > 0) {
      if (key.upArrow) {
        setSelectedIndex((i) => (i > 0 ? i - 1 : candidates.length - 1));
        return;
      }
      if (key.downArrow) {
        setSelectedIndex((i) => (i < candidates.length - 1 ? i + 1 : 0));
        return;
      }
      if (key.return) {
        const picked = candidates[selectedIndex];
        if (picked) {
          setValue(applySlashCompletion(value, picked));
          setMenuOpen(false);
          return;
        }
      }
    }

    if (key.return) {
      onSubmit(value);
      setValue("");
      setMenuOpen(false);
      return;
    }

    if (key.backspace || key.delete) {
      const next = value.slice(0, -1);
      setValue(next);
      if (!next.startsWith("/")) setMenuOpen(false);
      return;
    }

    if (input && !key.ctrl && !key.meta) {
      const next = value + input;
      setValue(next);
      if (next.startsWith("/")) {
        const nextCandidates = getSlashCandidates(catalog, next);
        if (nextCandidates.length > 0) {
          setSelectedIndex(0);
        } else {
          setMenuOpen(false);
        }
      }
    }
  });

  return (
    <Box flexDirection="column">
      {menuOpen && candidates.length > 0 && (
        <CompletionMenu candidates={candidates} selectedIndex={selectedIndex} />
      )}
      <Box>
        <Text color="green">{prompt} </Text>
        <Text>{value}</Text>
      </Box>
    </Box>
  );
}

/** The full-screen app: transcript on top, composer at the bottom. */
export function App({ client, session }: AppProps) {
  const { exit } = useApp();
  const { stdout } = useStdout();
  const sessionId = session.session_id;
  const color = stdout.isTTY && !process.env["NO_COLOR"];
  const [state, dispatch] = useReducer(appReducer, emptyTranscript);
  const prompt = "❯";
  const turnId = useRef<string | null>(null);
  // Session creation returns the initial state before event subscriptions are registered.
  // Seed it here so the first Ink frame shows the configured model rather than `(no model)`.
  const [status, setStatus] = useState<StatusBarState>({
    model: session.model,
    provider: session.provider,
    cwd: session.cwd,
    busy: session.busy,
    usagePercent: session.context?.usage_percent ?? 0,
    contextUsed: session.context?.last_prompt_tokens ?? 0,
    contextTotal: session.context?.context_length ?? 0,
    sessionId: session.stored_session_id || session.session_id,
    title: session.title,
    activity: session.busy ? "busy" : "idle",
  });

  // The backend sends `approval.request` and `clarify.request` as server requests; each
  // resolves when the user picks from the dialog. Until then, the composer is hidden.
  type ApprovalReq = { kind: "approval"; command: string; description: string; resolve: (choice: ApprovalChoice) => void };
  type ClarifyReq = { kind: "clarify"; question: string; choices: string[]; resolve: (answer: string) => void };
  type PendingReq = ApprovalReq | ClarifyReq;
  const [pending, setPending] = useState<PendingReq | null>(null);
  const [catalog, setCatalog] = useState<CommandEntry[]>([]);

  type ActivePicker =
    | { kind: "session"; sessions: StoredSession[] }
    | { kind: "model"; models: ModelEntry[]; current: string };
  const [picker, setPicker] = useState<ActivePicker | null>(null);

  useEffect(() => {
    client.request("commands.catalog", { session_id: sessionId })
      .then((res) => {
        const cat = res as CatalogResult;
        if (cat?.commands) setCatalog(cat.commands);
      })
      .catch(() => {});
  }, [client, sessionId]);

  useEffect(() => {
    client.onServerRequest("approval.request", (params) => new Promise((resolve) => {
      setPending({ kind: "approval", command: params.command, description: params.description,
        resolve: (choice) => resolve({ choice }) });
    }));
    client.onServerRequest("clarify.request", (params) => new Promise((resolve) => {
      setPending({ kind: "clarify", question: params.question, choices: params.choices ?? [],
        resolve: (answer) => resolve({ answer }) });
    }));
  }, [client]);

  const closeDialog = useCallback(() => setPending(null), []);

  // Forward every event from the backend into the shared reducer, and keep the status bar
  // in step: `session.info` carries model/cwd/context, `turn.start`/`turn.complete` toggle busy.
  useEffect(() => client.onEvent((event: EventEnvelope) => {
    dispatch({ kind: "event", event });
    if (event.type === "session.info") {
      const info = event.payload as SessionInfo;
      setStatus((s) => ({
        ...s,
        model: info.model || s.model,
        provider: info.provider || s.provider,
        cwd: info.cwd || s.cwd,
        busy: info.busy,
        usagePercent: info.context?.usage_percent ?? s.usagePercent,
        contextUsed: info.context?.last_prompt_tokens ?? s.contextUsed,
        contextTotal: info.context?.context_length ?? s.contextTotal,
        sessionId: info.stored_session_id || info.session_id || s.sessionId,
        title: info.title || s.title,
        activity: info.busy ? "busy" : "idle",
      }));
    } else if (event.type === "turn.start") {
      setStatus((s) => ({ ...s, busy: true, activity: "thinking" }));
    } else if (event.type === "turn.step") {
      setStatus((s) => ({ ...s, busy: true, activity: `thinking #${event.payload.iteration}` }));
    } else if (event.type === "tool.start") {
      setStatus((s) => ({ ...s, busy: true, activity: `tool ${event.payload.name}` }));
    } else if (event.type === "tool.complete") {
      setStatus((s) => ({ ...s, busy: true, activity: "thinking" }));
    } else if (event.type === "turn.complete") {
      setStatus((s) => ({
        ...s,
        busy: false,
        activity: "idle",
        inputTokens: event.payload.usage.input_tokens,
        outputTokens: event.payload.usage.output_tokens,
      }));
    }
  }), [client]);

  const submit = useCallback(async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed) return;

    if (trimmed === "/model" || trimmed === "/models") {
      try {
        const res = (await client.request("model.list", {})) as ModelListResult;
        setPicker({ kind: "model", models: res.models || [], current: res.current || status.model });
        return;
      } catch {
        // Fall back to prompt.submit
      }
    }

    if (trimmed === "/session" || trimmed === "/resume" || trimmed === "/sessions") {
      try {
        const res = (await client.request("session.list", {})) as SessionListResult;
        setPicker({ kind: "session", sessions: res.sessions || [] });
        return;
      } catch {
        // Fall back to prompt.submit
      }
    }

    dispatch({ kind: "user", text });  // optimistic: show the user's line at once
    try {
      const result = await client.request("prompt.submit", { session_id: sessionId, text });
      turnId.current = (result as PromptSubmitResult).turn_id;
    } catch (error) {
      dispatch({ kind: "event", event: { type: "error", payload: { message: String(error) }, session_id: sessionId } as EventEnvelope });
    }
  }, [client, sessionId, status.model]);

  const interrupt = useCallback(async () => {
    await client.request("session.interrupt", { session_id: sessionId }).catch(() => {});
  }, [client, sessionId]);

  const quit = useCallback(async () => {
    await client.request("session.close", { session_id: sessionId }).catch(() => {});
    exit();
  }, [client, sessionId, exit]);

  return (
    <Box flexDirection="column" height="100%">
      <Transcript state={state} color={color} />
      {pending?.kind === "approval" && (
        <ApprovalDialog
          command={pending.command}
          description={pending.description}
          onChoose={(choice) => { pending.resolve(choice); closeDialog(); }}
        />
      )}
      {pending?.kind === "clarify" && (
        <ClarifyDialog
          question={pending.question}
          choices={pending.choices}
          onAnswer={(answer) => { pending.resolve(answer); closeDialog(); }}
        />
      )}
      {picker?.kind === "session" && (
        <SessionPicker
          sessions={picker.sessions}
          onSelect={async (sess) => {
            setPicker(null);
            await resumeSession(client, sess).catch(() => {});
          }}
          onClose={() => setPicker(null)}
        />
      )}
      {picker?.kind === "model" && (
        <ModelPicker
          models={picker.models}
          current={picker.current}
          onSelect={async (mod) => {
            setPicker(null);
            await switchModel(client, sessionId, mod).catch(() => {});
            setStatus((s) => ({ ...s, model: mod.id }));
          }}
          onClose={() => setPicker(null)}
        />
      )}
      {!pending && !picker && <Composer onSubmit={submit} onInterrupt={interrupt} onQuit={quit} prompt={prompt} catalog={catalog} />}
      <StatusBar state={status} />
    </Box>
  );
}
