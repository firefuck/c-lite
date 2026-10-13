// The dashboard's state and everything that changes it, with no DOM.
//
// One connection serves several open conversations at once: every event carries its
// `session_id`, so each view keeps its own transcript. React components read a snapshot through
// `subscribe`/`getState` and call the methods here; nothing in this file knows about React.

import type {
  EventEnvelope,
  MethodName,
  Methods,
  SessionCreateParams,
  SessionInfo,
  StoredSession,
  TranscriptState,
  Transport,
} from "@clite/shared";
import { emptyTranscript, fromHistory, GatewayClient, reduce } from "@clite/shared";

import type { ApprovalChoice, CronValues, DialogSpec, SetupValues } from "./dialogs.ts";
import type { AddressBar, TokenStorage } from "./token.ts";
import { forgetToken, storeToken, takeToken } from "./token.ts";

/** A file dropped or pasted into the composer, not sent yet. */
export interface Attachment {
  file: Blob;
  name: string;
  mime: string;
  image: boolean;
}

export interface View {
  id: string;
  info: SessionInfo;
  transcript: TranscriptState;
  /** The newest event applied. A reconnect sends it back so the server replays what was missed. */
  lastSeq: number;
  attachments: Attachment[];
}

export interface DashboardState {
  connection: { online: boolean; label: string };
  profile: string;
  views: View[]; // in the order they were opened
  activeId: string | null;
  stored: StoredSession[];
  /** The first one is on screen; the rest wait their turn. */
  dialogs: DialogSpec[];
  /** Shown in the transcript when no conversation is open (a failed connection, say). */
  banner: string;
  notifications: boolean;
}

/** What the page provides. Tests pass a fake; the browser build passes `browserPlatform()`. */
export interface Platform {
  address: AddressBar;
  storage: TokenStorage;
  /** The WebSocket URL for a token: same host as the page. */
  socketUrl(token: string): string;
  openTransport(url: string): Promise<Transport>;
  /** Show a desktop notification if the user is not looking at the page. */
  notify(title: string, body: string, onClick: () => void): void;
  /** The real path of a dropped file, when the desktop app can tell; "" in a browser. */
  pathForFile(file: Blob): Promise<string>;
  base64(file: Blob): Promise<string>;
  /** Run `callback` after `ms` milliseconds. */
  later(callback: () => void, ms: number): void;
}

const MAX_RECONNECT_DELAY_MS = 10_000;

export class Dashboard {
  private state: DashboardState = {
    connection: { online: false, label: "connecting…" },
    profile: "",
    views: [],
    activeId: null,
    stored: [],
    dialogs: [],
    banner: "",
    notifications: true,
  };
  private readonly listeners = new Set<() => void>();
  private client: GatewayClient | null = null;
  private token = "";
  private closing = false;
  private reconnecting = false;
  private reconnectDelay = 500;
  private readonly platform: Platform;

  constructor(platform: Platform) {
    this.platform = platform;
  }

  // ── reading the state ─────────────────────────────────────────────────────────────────

  getState = (): DashboardState => this.state;

  subscribe = (listener: () => void): (() => void) => {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  };

  activeView(): View | null {
    return this.state.views.find((view) => view.id === this.state.activeId) ?? null;
  }

  private viewOf(sessionId: string): View | null {
    return this.state.views.find((view) => view.id === sessionId) ?? null;
  }

  private update(change: Partial<DashboardState>): void {
    this.state = { ...this.state, ...change };
    for (const listener of this.listeners) listener();
  }

  private updateView(sessionId: string, change: (view: View) => View): void {
    this.update({ views: this.state.views.map((view) => (view.id === sessionId ? change(view) : view)) });
  }

  /** A typed request on the current connection. */
  request<M extends MethodName>(method: M, params: Methods[M]["params"]): Promise<Methods[M]["result"]> {
    if (!this.client) return Promise.reject(new Error("not connected"));
    return this.client.request(method, params);
  }

  /** The token this page connected with, for the few REST routes (plugin pages). */
  get sessionToken(): string {
    return this.token;
  }

  // ── dialogs ───────────────────────────────────────────────────────────────────────────

  /** Queue a question; resolves with its answer once the user (or a dismissal) gives one. */
  ask<T>(build: (answer: (value: T) => void) => DialogSpec): Promise<T> {
    return new Promise((resolve) => {
      const spec = build((value) => {
        this.update({ dialogs: this.state.dialogs.filter((entry) => entry !== spec) });
        resolve(value);
      });
      this.update({ dialogs: [...this.state.dialogs, spec] });
    });
  }

  askText(title: string, label: string, initial: string): Promise<string | null> {
    return this.ask<string | null>((answer) => ({ kind: "text", title, label, initial, answer }));
  }

  askConfirm(title: string, body: string, confirmLabel: string): Promise<boolean> {
    return this.ask<boolean>((answer) => ({ kind: "confirm", title, body, confirmLabel, answer }));
  }

  showOutput(title: string, content: string, path: string): Promise<void> {
    return this.ask<void>((answer) => ({ kind: "output", title, content, path, answer }));
  }

  askCron(submit: (values: CronValues) => Promise<void>): Promise<void> {
    return this.ask<void>((answer) => ({ kind: "cron", submit, answer }));
  }

  // ── connection ────────────────────────────────────────────────────────────────────────

  async start(): Promise<void> {
    this.token = takeToken(this.platform.address, this.platform.storage);
    if (!this.token) {
      this.token = await this.ask<string>((answer) => ({ kind: "token", answer }));
      storeToken(this.platform.storage, this.token);
    }
    try {
      await this.open();
    } catch (error) {
      forgetToken(this.platform.storage);
      const message = errorText(error);
      this.update({
        connection: { online: false, label: message },
        banner: `Could not connect: ${message}. Reload the page with the link printed by \`clite dashboard\`.`,
      });
      return;
    }
    const system = await this.request("system.info", {});
    this.update({ profile: system.profile ? `profile: ${system.profile}` : "" });
    if (!system.configured) await this.runSetup();
    this.update({ notifications: system.notifications !== false });
    await this.openSession({});
    await this.refreshSessions();
  }

  /** The page is going away on purpose: a reconnect now would only fight the unload. */
  stop(): void {
    this.closing = true;
  }

  private async open(): Promise<void> {
    const transport = await this.platform.openTransport(this.platform.socketUrl(this.token));
    const client = new GatewayClient(transport);
    client.onEvent((event) => this.handleEvent(event));
    client.onServerRequest("approval.request", (params) => {
      this.notify("Approval needed", params.description || params.command, this.viewOf(params.session_id));
      return this.ask<ApprovalChoice>((answer) => ({ kind: "approval", params, answer })).then((choice) => ({
        choice,
      }));
    });
    client.onServerRequest("clarify.request", (params) =>
      this.ask<string>((answer) => ({ kind: "clarify", params, answer })).then((text) => ({ answer: text })),
    );
    client.channel.onClose(() => {
      if (this.client === client) this.connectionLost();
    });
    this.client = client;
    this.update({ connection: { online: true, label: "connected" }, banner: "" });
  }

  private connectionLost(): void {
    this.client = null;
    if (this.closing) return;
    this.update({ connection: { online: false, label: "reconnecting…" } });
    this.scheduleReconnect();
  }

  private scheduleReconnect(): void {
    if (this.reconnecting) return;
    this.reconnecting = true;
    this.platform.later(() => void this.reconnect(), this.reconnectDelay);
  }

  private async reconnect(): Promise<void> {
    this.reconnecting = false;
    if (this.closing) return;
    try {
      await this.open();
    } catch (error) {
      if (errorText(error) === "unauthorized") {
        // The token is no longer accepted; retrying would hammer the server.
        forgetToken(this.platform.storage);
        this.update({ connection: { online: false, label: "unauthorized" } });
        this.notice(
          "The session token was refused. Reload the page with the link printed by `clite dashboard`.",
          "error",
        );
        return;
      }
      this.reconnectDelay = Math.min(this.reconnectDelay * 2, MAX_RECONNECT_DELAY_MS);
      this.scheduleReconnect();
      return;
    }
    this.reconnectDelay = 500;
    await this.reattach();
  }

  /** Take every open conversation back and apply what happened while the socket was down. */
  private async reattach(): Promise<void> {
    for (const view of this.state.views) {
      try {
        const result = await this.request("session.attach", { session_id: view.id, last_seq: view.lastSeq });
        this.setInfo(result.session);
        if (result.complete) {
          for (const event of result.events) this.handleEvent(event as unknown as EventEnvelope);
        } else {
          // Too much happened to replay: show the transcript as it is now.
          await this.reloadTranscript(view.id);
          this.notice("This conversation fell too far behind to replay; its transcript was reloaded.", "info", view.id);
        }
        this.updateView(view.id, (current) => ({ ...current, lastSeq: Math.max(current.lastSeq, result.last_seq) }));
      } catch (error) {
        this.notice(`Lost “${view.info.title || view.id}”: ${errorText(error)}`, "error", view.id);
      }
    }
    await this.refreshSessions();
  }

  private async runSetup(): Promise<void> {
    const { providers } = await this.request("providers.list", {});
    const submit = async (values: SetupValues): Promise<void> => {
      await this.request("setup.apply", {
        provider: values.provider,
        api_key: values.apiKey || null,
        model: values.model || null,
        base_url: values.baseUrl || null,
      });
      const system = await this.request("system.info", {});
      if (!system.configured) throw new Error("Still not configured: check the key and the model id.");
    };
    await this.ask<void>((answer) => ({
      kind: "setup",
      providers: providers.filter((entry) => entry.name !== "mock"),
      submit,
      answer,
    }));
  }

  /** Re-read the dashboard's own settings, after one of them changed. */
  async reloadPreferences(): Promise<void> {
    try {
      const system = await this.request("system.info", {});
      this.update({ notifications: system.notifications !== false });
    } catch {
      // A config we cannot read is not worth stopping the dashboard for: keep the default.
    }
  }

  // ── notifications ─────────────────────────────────────────────────────────────────────

  private notify(title: string, body: string, view: View | null): void {
    if (!this.state.notifications) return;
    this.platform.notify(title, body, () => {
      if (view) this.activate(view.id);
    });
  }

  // ── sessions ──────────────────────────────────────────────────────────────────────────

  async openSession(params: SessionCreateParams): Promise<void> {
    const info = await this.request("session.create", params);
    const view: View = { id: info.session_id, info, transcript: emptyTranscript, lastSeq: 0, attachments: [] };
    this.update({ views: [...this.state.views, view], activeId: view.id });
    if (info.message_count) await this.reloadTranscript(view.id);
    await this.refreshSessions();
  }

  /** Make a view the one on screen. A background view keeps receiving its events. */
  activate(sessionId: string): void {
    if (this.viewOf(sessionId)) this.update({ activeId: sessionId });
  }

  /** Let a runtime session go. Its stored history stays; only this connection forgets it. */
  async closeSession(sessionId: string): Promise<void> {
    if (!this.viewOf(sessionId)) return;
    await this.request("session.close", { session_id: sessionId }).catch(() => undefined);
    const views = this.state.views.filter((view) => view.id !== sessionId);
    if (this.state.activeId !== sessionId) {
      this.update({ views });
      return;
    }
    const next = views[views.length - 1];
    this.update({ views, activeId: next ? next.id : null });
    if (!next) await this.openSession({});
  }

  async refreshSessions(): Promise<void> {
    const { sessions } = await this.request("session.list", { limit: 40 });
    this.update({ stored: sessions });
  }

  private async reloadTranscript(sessionId: string): Promise<void> {
    const history = await this.request("session.history", { session_id: sessionId });
    this.updateView(sessionId, (view) => ({ ...view, transcript: fromHistory(history.messages) }));
  }

  private setInfo(info: SessionInfo): void {
    if (this.viewOf(info.session_id)) this.updateView(info.session_id, (view) => ({ ...view, info }));
  }

  // ── events ────────────────────────────────────────────────────────────────────────────

  /** Route one event to the view it belongs to, on screen or not. */
  private handleEvent(event: EventEnvelope): void {
    const view = this.viewOf(event.session_id);
    if (!view) return; // an event for a session this connection never opened
    this.updateView(view.id, (current) => ({
      ...current,
      lastSeq: typeof event.seq === "number" ? Math.max(current.lastSeq, event.seq) : current.lastSeq,
      transcript: reduce(current.transcript, event),
    }));
    if (event.type === "session.info") {
      this.setInfo(event.payload);
      this.refreshSessions().catch(() => undefined); // a refresh racing a dropped socket is not news
    } else if (event.type === "turn.complete") {
      const payload = event.payload;
      const body = payload.interrupted
        ? "The turn was interrupted."
        : payload.error
          ? `The turn failed: ${payload.error}`
          : payload.final_response || "The turn finished.";
      this.notify(view.info.title || "clite", body, view);
      this.request("session.info", { session_id: view.id })
        .then((info) => {
          this.setInfo(info);
          return this.refreshSessions();
        })
        .catch(() => undefined);
    }
  }

  /** Add a line to a transcript (the active one by default). With none open, it is the banner. */
  notice(text: string, level: "info" | "error" = "info", sessionId: string | null = this.state.activeId): void {
    if (!sessionId || !this.viewOf(sessionId)) {
      this.update({ banner: text });
      return;
    }
    this.updateView(sessionId, (view) => ({
      ...view,
      transcript: { ...view.transcript, items: [...view.transcript.items, { kind: "notice", level, text }] },
    }));
  }

  // ── sending ───────────────────────────────────────────────────────────────────────────

  async send(text: string): Promise<void> {
    const view = this.activeView();
    if (!this.client || !view) return;
    if (!text.trim() && !view.attachments.length) return;
    if (text.trim().startsWith("/")) {
      await this.runSlash(view.id, text.trim());
      return;
    }
    this.updateView(view.id, (current) => ({
      ...current,
      transcript: { ...current.transcript, items: [...current.transcript.items, { kind: "user", text }] },
    }));
    try {
      // An image rides along as an image part; any other file is spelled out as a path the
      // agent can read.
      const { images, files } = await this.takeAttachments(view.id);
      const outgoing = files.length ? `${text}\n\n[attached: ${files.join(", ")}]` : text;
      await this.request("prompt.submit", {
        session_id: view.id,
        text: outgoing,
        attachments: images.length ? images : null,
      });
    } catch (error) {
      this.notice(errorText(error), "error", view.id);
    }
  }

  private async runSlash(sessionId: string, command: string): Promise<void> {
    try {
      const result = await this.request("slash.exec", { session_id: sessionId, command });
      if (result.action === "new") await this.reloadTranscript(sessionId);
      if (result.text) this.notice(result.text, "info", sessionId);
    } catch (error) {
      this.notice(errorText(error), "error", sessionId);
    }
  }

  interrupt(): void {
    const view = this.activeView();
    if (view) this.request("session.interrupt", { session_id: view.id }).catch(() => undefined);
  }

  // ── attachments ───────────────────────────────────────────────────────────────────────

  addAttachments(files: { file: Blob; name: string; type: string }[]): void {
    const view = this.activeView();
    if (!view || !files.length) return;
    const added = files.map(({ file, name, type }) => ({
      file,
      name: name || "attachment",
      mime: type || "",
      image: (type || "").startsWith("image/"),
    }));
    this.updateView(view.id, (current) => ({ ...current, attachments: [...current.attachments, ...added] }));
  }

  removeAttachment(index: number): void {
    const view = this.activeView();
    if (!view) return;
    this.updateView(view.id, (current) => ({
      ...current,
      attachments: current.attachments.filter((_, position) => position !== index),
    }));
  }

  /**
   * Turn the pending files into paths the server can use, and clear them.
   *
   * The desktop app can hand over the real path of a dropped file, so nothing is copied. A
   * browser cannot: the bytes go up through `attachment.save` and land in the cache directory.
   */
  private async takeAttachments(sessionId: string): Promise<{ images: string[]; files: string[] }> {
    const pending = this.viewOf(sessionId)?.attachments ?? [];
    this.updateView(sessionId, (view) => ({ ...view, attachments: [] }));
    const images: string[] = [];
    const files: string[] = [];
    for (const entry of pending) {
      let path = await this.platform.pathForFile(entry.file);
      if (!path) {
        const saved = await this.request("attachment.save", {
          name: entry.name,
          data: await this.platform.base64(entry.file),
          mime: entry.mime,
        });
        path = saved.path;
      }
      (entry.image ? images : files).push(path);
    }
    return { images, files };
  }
}

export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
