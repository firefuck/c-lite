// The dashboard: a thin view over the JSON-RPC protocol.
//
// No framework and no build step. It ships inside the Python package, so `clite dashboard`
// works on a machine that has never seen npm. State lives in one object; every change calls
// a small render function for the part of the page it affects.

import { RpcClient, RpcError } from "/static/rpc.js";

const $ = (selector) => document.querySelector(selector);

// h("div", {class: "x"}, "text", child) -> element. Text is always set as text, never as
// HTML: nothing the model or a tool produced can inject markup.
function h(tag, attributes = {}, ...children) {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attributes)) {
    if (key === "class") element.className = value;
    else if (key.startsWith("on")) element.addEventListener(key.slice(2), value);
    else if (value !== false && value != null) element.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child == null) continue;
    element.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return element;
}

// One open conversation. Several can be open at once in one connection: every event carries
// its `session_id`, so each view keeps its own transcript, its own streaming element and its
// own running tools. Only the active one is in the document; the others keep their nodes in
// memory, so switching back is instant and nothing is re-rendered from scratch.
function newView(id, info) {
  return {
    id,
    info,
    busy: false,
    streaming: null,
    tools: new Map(),
    // The newest event this view has applied. A reconnect sends it back so the server can
    // replay exactly what was missed.
    lastSeq: 0,
    attachments: [], // files dropped or pasted but not sent yet
    // Each view owns its transcript element. Only the active one is in the document, so a
    // background session keeps receiving events into its own element without touching the page.
    container: h("div", { class: "transcript-body" }),
  };
}

const state = {
  rpc: null,
  views: new Map(), // runtime session id -> view
  activeId: null,
  closing: false, // the page is going away: do not try to reconnect
  notifications: true, // dashboard.notifications, read from the config
};

function activeView() {
  return state.views.get(state.activeId) || null;
}

function viewOf(sessionId) {
  return state.views.get(sessionId) || null;
}

// ── token and connection ────────────────────────────────────────────────────────────────

function takeToken() {
  const fromUrl = new URLSearchParams(location.hash.slice(1)).get("token") || new URLSearchParams(location.search).get("token");
  if (fromUrl) {
    sessionStorage.setItem("clite-token", fromUrl);
    history.replaceState(null, "", location.pathname); // keep the token out of the address bar and history
  }
  return sessionStorage.getItem("clite-token") || "";
}

function setConnection(online, label) {
  const pill = $("#status-connection");
  pill.textContent = label;
  pill.className = `pill ${online ? "online" : "offline"}`;
}

async function connect() {
  let token = takeToken();
  if (!token) token = await askToken();
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const rpc = new RpcClient(`${scheme}://${location.host}/api/ws?token=${encodeURIComponent(token)}`);
  rpc.onEvent(handleEvent);
  rpc.onServerRequest("approval.request", askApproval);
  rpc.onServerRequest("clarify.request", askClarification);
  rpc.onClose = () => onConnectionLost();
  try {
    await rpc.connect();
  } catch (error) {
    sessionStorage.removeItem("clite-token");
    setConnection(false, error.message);
    notice(`Could not connect: ${error.message}. Reload the page with the link printed by \`clite dashboard\`.`, "error");
    return;
  }
  state.rpc = rpc;
  setConnection(true, "connected");
  const system = await rpc.request("system.info");
  $("#status-profile").textContent = system.profile ? `profile: ${system.profile}` : "";
  if (!system.configured) await runSetup();
  state.notifications = system.notifications !== false;
  await openSession({});
  await refreshSessions();
}

/** The dashboard's own settings, which the server reports with everything else. */
async function loadDashboardPrefs() {
  try {
    const info = await state.rpc.request("system.info");
    state.notifications = info.notifications !== false;
  } catch {
    // A config we cannot read is not worth stopping the dashboard for: keep the default.
  }
}

// ── notifications ────────────────────────────────────────────────────────────────────────

/** Ask for the browser's permission, once, while a user gesture is on the stack. */
function askNotificationPermission() {
  if (typeof Notification === "undefined") return;
  if (Notification.permission === "default") Notification.requestPermission().catch(() => {});
}

/**
 * Tell the user something happened, if they are not looking.
 *
 * The point of a notification is the window you are *not* watching: when the dashboard has
 * focus the message is already on screen, so nothing is sent.
 */
function notify(title, body, view) {
  if (!state.notifications || typeof Notification === "undefined") return;
  if (Notification.permission !== "granted") return;
  if (document.hasFocus()) return;
  try {
    const note = new Notification(title, { body, tag: "clite" });
    note.onclick = () => {
      window.focus();
      if (view) activateSession(view.id).catch(() => {});
    };
  } catch {
    // Some browsers refuse outside a service worker; a missing notification is not an error.
  }
}

// ── coming back after the socket drops ───────────────────────────────────────────────────

let reconnectTimer = null;
let reconnectDelay = 500;

/** The socket went away. Try to come back; a turn that was running is still running. */
function onConnectionLost() {
  if (state.closing) return;
  setConnection(false, "reconnecting…");
  scheduleReconnect();
}

function scheduleReconnect() {
  if (reconnectTimer) return;
  reconnectTimer = setTimeout(async () => {
    reconnectTimer = null;
    try {
      await state.rpc.connect();
    } catch (error) {
      if (state.rpc.closeCode === 4401) {
        // The token is no longer accepted; retrying would hammer the server. Ask again.
        sessionStorage.removeItem("clite-token");
        setConnection(false, error.message);
        notice("The session token was refused. Reload the page with the link printed by `clite dashboard`.", "error");
        return;
      }
      reconnectDelay = Math.min(reconnectDelay * 2, 10_000);
      scheduleReconnect();
      return;
    }
    reconnectDelay = 500;
    setConnection(true, "connected");
    await reattach();
  }, reconnectDelay);
}

/** Take every open conversation back, and apply what happened while we were away. */
async function reattach() {
  for (const view of [...state.views.values()]) {
    try {
      const result = await state.rpc.request("session.attach", {
        session_id: view.id, last_seq: view.lastSeq,
      });
      setInfo(result.session);
      if (result.complete) {
        for (const event of result.events) handleEvent(event);
      } else {
        // Too much happened to replay: show the transcript as it is now.
        await reloadTranscript(view);
        notice("This conversation fell too far behind to replay; its transcript was reloaded.", "notice");
      }
      view.lastSeq = Math.max(view.lastSeq, result.last_seq);
    } catch (error) {
      notice(`Lost “${view.info.title || view.id}”: ${error.message}`, "error");
    }
  }
  await refreshSessions();
}

/** Rebuild a view's transcript from the stored history. */
async function reloadTranscript(view) {
  view.container.replaceChildren();
  view.streaming = null;
  view.tools.clear();
  const history = await state.rpc.request("session.history", { session_id: view.id });
  for (const message of history.messages) renderStored(message, view);
}

// ── sessions ─────────────────────────────────────────────────────────────────────────────

async function openSession(params) {
  const info = await state.rpc.request("session.create", params);
  const view = newView(info.session_id, info);
  state.views.set(view.id, view);
  await activateSession(view.id);
  if (info.message_count) {
    const history = await state.rpc.request("session.history", { session_id: view.id });
    for (const message of history.messages) renderStored(message);
  }
  await refreshSessions();
  return view;
}

/** Make a view the one in the document. A background view keeps its element and its events. */
async function activateSession(sessionId) {
  const view = viewOf(sessionId);
  if (!view) return;
  state.activeId = sessionId;
  $("#transcript").replaceChildren(view.container);
  setInfo(view.info);
  setBusy(view.busy);
  renderAttachments();
  renderOpenSessions();
  scrollDown();
  $("#prompt").focus();
}

/** Let a runtime session go. Its stored history stays; only this connection forgets it. */
async function closeSession(sessionId) {
  const view = viewOf(sessionId);
  if (!view) return;
  await state.rpc.request("session.close", { session_id: sessionId }).catch(() => {});
  state.views.delete(sessionId);
  if (state.activeId === sessionId) {
    state.activeId = null;
    const next = [...state.views.keys()].pop();
    if (next) await activateSession(next);
    else await openSession({});
  } else {
    renderOpenSessions();
  }
}

function setInfo(info) {
  const view = viewOf(info.session_id) || activeView();
  if (view) view.info = info;
  if (!view || view.id !== state.activeId) return; // the status bar shows the active session
  $("#status-model").textContent = `${info.model} · ${info.provider}`;
  const context = info.context;
  $("#status-context").textContent = context.context_length
    ? `context ${context.usage_percent}% · ${info.message_count} messages`
    : "";
  document.title = info.title ? `${info.title} · C-lite` : "C-lite";
  for (const button of document.querySelectorAll("#sessions button")) {
    button.classList.toggle("current", button.dataset.id === info.stored_session_id);
  }
}

/** The open conversations, with a dot when one is working in the background. */
function renderOpenSessions() {
  const open = [...state.views.values()];
  $("#open-sessions").replaceChildren(
    ...open.map((view) => h("li", {},
      h("button", {
        type: "button", "data-open": view.id,
        class: `${view.id === state.activeId ? "current" : ""}${view.busy ? " busy" : ""}`,
        onclick: () => activateSession(view.id).catch(() => {}),
      },
      h("span", { class: "dot" }),
      view.info.title || "(new chat)",
      view.busy ? h("span", { class: "meta" }, "working") : null,
      open.length > 1
        ? h("span", { class: "close", role: "button", "data-close": view.id, onclick: (event) => {
          event.stopPropagation();
          closeSession(view.id).catch((error) => notice(error.message, "error"));
        } }, "×")
        : null),
    )),
  );
}

async function refreshSessions() {
  const { sessions } = await state.rpc.request("session.list", { limit: 40 });
  const current = activeView()?.info?.stored_session_id;
  $("#sessions").replaceChildren(
    ...sessions.map((session) =>
      h("li", {}, h("button", {
        type: "button", "data-id": session.id, class: session.id === current ? "current" : "",
        onclick: () => openSession({ resume: session.id }).catch((error) => notice(error.message, "error")),
      }, session.title || "(untitled)", h("span", { class: "meta" }, `${session.message_count} messages · ${session.source}`))),
    ),
  );
}

// ── attachments ──────────────────────────────────────────────────────────────────────────

/** Files the user dropped or pasted, waiting to be sent with the next message. */
function addAttachments(files) {
  const view = activeView();
  if (!view || !files.length) return;
  for (const file of files) {
    view.attachments.push({
      file,
      name: file.name || "attachment",
      mime: file.type || "",
      image: (file.type || "").startsWith("image/"),
    });
  }
  renderAttachments();
}

function renderAttachments() {
  const view = activeView();
  const pending = view ? view.attachments : [];
  $("#attachments").replaceChildren(
    ...pending.map((entry, index) => h("span", { class: "chip", "data-name": entry.name },
      entry.image ? "image · " : "file · ",
      entry.name,
      h("span", {
        class: "remove", role: "button", "data-remove": index,
        onclick: () => {
          view.attachments.splice(index, 1);
          renderAttachments();
        },
      }, "×"))),
  );
}

function base64Of(file) {
  return file.arrayBuffer().then((buffer) => {
    const bytes = new Uint8Array(buffer);
    let binary = "";
    for (let index = 0; index < bytes.length; index += 0x8000) {
      binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
    }
    return btoa(binary);
  });
}

/**
 * Turn the pending files into paths the server can use, and clear the chips.
 *
 * The desktop app can hand over the real path of a dropped file (`cliteDesktop.pathForFile`),
 * so nothing is copied. A browser cannot: the bytes go up through `attachment.save` and land in
 * the cache directory, where the agent reads them like any other file.
 */
async function takeAttachments(view) {
  const pending = view.attachments;
  view.attachments = [];
  if (view.id === state.activeId) renderAttachments();
  const images = [];
  const files = [];
  for (const entry of pending) {
    let path = "";
    if (window.cliteDesktop && window.cliteDesktop.pathForFile) {
      path = await window.cliteDesktop.pathForFile(entry.file);
    }
    if (!path) {
      const saved = await state.rpc.request("attachment.save", {
        name: entry.name, data: await base64Of(entry.file), mime: entry.mime,
      });
      path = saved.path;
    }
    (entry.image ? images : files).push(path);
  }
  return { images, files };
}

// ── transcript ───────────────────────────────────────────────────────────────────────────

function scrollDown(view) {
  if (view && view.id !== state.activeId) return; // a background view scrolls when you open it
  const transcript = $("#transcript");
  transcript.scrollTop = transcript.scrollHeight;
}

// Plain text with fenced code blocks shown as <pre>. Deliberately not a Markdown renderer.
function renderText(element, text) {
  element.replaceChildren();
  const parts = text.split(/```[^\n]*\n?/);
  parts.forEach((part, index) => {
    if (!part) return;
    element.append(index % 2 === 1 ? h("pre", {}, part.replace(/\n$/, "")) : document.createTextNode(part));
  });
}

/** Append a message to a view's transcript. Defaults to the active view. */
function addMessage(role, text, view = activeView()) {
  if (!view) return null;
  const element = h("div", { class: `message ${role}` });
  element.dataset.text = text;
  renderText(element, text);
  view.container.append(element);
  scrollDown(view);
  return element;
}

function notice(text, kind = "notice") {
  return addMessage(kind, text);
}

function renderStored(message, view = activeView()) {
  if (!view) return;
  if (message.role === "tool") {
    view.container.append(h("div", { class: "tool" }, `✓ ${message.tool_name}`));
  } else if (message.text) {
    addMessage(message.role, message.text, view);
  }
}

function setBusy(busy) {
  const view = activeView();
  if (view) view.busy = busy;
  $("#send").hidden = busy;
  $("#stop").hidden = !busy;
  renderOpenSessions();
}

/** Route one event to the view it belongs to, active or not. */
function handleEvent(event) {
  const view = viewOf(event.session_id);
  if (!view) return; // an event for a session this connection never opened
  if (typeof event.seq === "number") view.lastSeq = Math.max(view.lastSeq, event.seq);
  const payload = event.payload;
  const markBusy = (busy) => {
    view.busy = busy;
    if (view.id === state.activeId) setBusy(busy);
    else renderOpenSessions();
  };
  switch (event.type) {
    case "turn.start":
      markBusy(true);
      break;
    case "message.delta":
      if (!view.streaming) view.streaming = addMessage("assistant", "", view);
      view.streaming.dataset.text += payload.text;
      renderText(view.streaming, view.streaming.dataset.text);
      scrollDown(view);
      break;
    case "message.complete":
      if (!view.streaming && payload.text) addMessage("assistant", payload.text, view);
      view.streaming = null;
      break;
    case "tool.start": {
      const element = h("div", { class: "tool running" }, `${payload.name}  ${payload.preview}`);
      view.tools.set(payload.call_id, element);
      view.container.append(element);
      scrollDown(view);
      break;
    }
    case "tool.complete": {
      const element = view.tools.get(payload.call_id);
      if (element) {
        element.className = `tool${payload.failed ? " failed" : ""}`;
        element.textContent = `${payload.failed ? "✗" : "✓"} ${element.textContent}  (${payload.duration.toFixed(1)}s)`;
      }
      break;
    }
    case "status.update":
      addMessage("notice", `[${payload.kind}] ${payload.text}`, view);
      break;
    case "subagent.update":
      addMessage("notice", `subagent ${payload.index + 1}: ${payload.event} ${payload.tool || payload.status}`, view);
      break;
    case "session.info":
      setInfo(payload);
      refreshSessions().catch(() => {}); // a refresh racing a dropped socket is not news
      break;
    case "turn.complete":
      view.streaming = null;
      markBusy(false);
      if (payload.interrupted) addMessage("notice", "(interrupted)", view);
      else if (payload.error) addMessage("error", payload.final_response || payload.error, view);
      notify(
        view.info.title || "clite",
        payload.interrupted
          ? "The turn was interrupted."
          : payload.error
            ? `The turn failed: ${payload.error}`
            : (payload.final_response || "The turn finished."),
        view,
      );
      state.rpc
        .request("session.info", { session_id: view.id })
        .then(setInfo)
        .then(refreshSessions)
        .catch(() => {});
      break;
    case "error":
      addMessage("error", payload.message, view);
      break;
    default:
      break;
  }
}

async function send(text) {
  const view = activeView();
  if (!state.rpc || !view) return;
  if (!text.trim() && !view.attachments.length) return;
  askNotificationPermission(); // this is a user gesture: the only moment a browser will ask
  if (text.trim().startsWith("/")) {
    try {
      const result = await state.rpc.request("slash.exec", { session_id: view.id, command: text.trim() });
      if (result.text) notice(result.text);
      if (result.action === "new") {
        view.container.replaceChildren();
        const history = await state.rpc.request("session.history", { session_id: view.id });
        for (const message of history.messages) renderStored(message);
      }
    } catch (error) {
      notice(error.message, "error");
    }
    return;
  }
  addMessage("user", text);
  try {
    // A dropped image rides along as an image part; anything else is a file the agent can
    // read, so its path is spelled out in the message.
    const { images, files } = await takeAttachments(view);
    const outgoing = files.length ? `${text}\n\n[attached: ${files.join(", ")}]` : text;
    await state.rpc.request("prompt.submit", {
      session_id: view.id, text: outgoing, attachments: images.length ? images : null,
    });
  } catch (error) {
    notice(error.message, "error");
  }
}

// ── dialogs ──────────────────────────────────────────────────────────────────────────────

function showDialog(...children) {
  const dialog = $("#dialog");
  $("#dialog-body").replaceChildren(...children);
  if (!dialog.open) dialog.showModal();
  return dialog;
}

function askToken() {
  return new Promise((resolve) => {
    const input = h("input", { id: "token-input", type: "password", autocomplete: "off" });
    const dialog = showDialog(
      h("h2", {}, "Session token"),
      h("p", {}, "Open the link printed by `clite dashboard`, or paste the token here."),
      input,
      h("div", { class: "buttons" }, h("button", {
        class: "primary", type: "button",
        onclick: () => {
          sessionStorage.setItem("clite-token", input.value.trim());
          dialog.close();
          resolve(input.value.trim());
        },
      }, "Connect")),
    );
  });
}

function askApproval(params) {
  notify(
    "Approval needed",
    params.description || params.command || "",
    viewOf(params.session_id) || activeView(),
  );
  return new Promise((resolve) => {
    const choose = (choice) => () => {
      $("#dialog").close();
      resolve({ choice });
    };
    showDialog(
      h("h2", {}, "Approve this command?"),
      h("p", {}, params.description),
      h("code", { id: "approval-command" }, params.command),
      h("div", { class: "buttons" },
        h("button", { type: "button", class: "danger", "data-choice": "deny", onclick: choose("deny") }, "Deny"),
        h("button", { type: "button", "data-choice": "once", onclick: choose("once") }, "Once"),
        h("button", { type: "button", "data-choice": "session", onclick: choose("session") }, "This session"),
        h("button", { type: "button", "data-choice": "always", onclick: choose("always") }, "Always")),
    );
  });
}

function askClarification(params) {
  return new Promise((resolve) => {
    const input = h("input", { id: "clarify-input", type: "text", placeholder: "Your answer" });
    const answer = (value) => () => {
      $("#dialog").close();
      resolve({ answer: value === undefined ? input.value : value });
    };
    showDialog(
      h("h2", {}, params.question),
      h("div", { class: "buttons" }, params.choices.map((choice) => h("button", { type: "button", onclick: answer(choice) }, choice))),
      input,
      h("div", { class: "buttons" }, h("button", { class: "primary", type: "button", onclick: answer() }, "Answer")),
    );
  });
}

async function runSetup() {
  const { providers } = await state.rpc.request("providers.list");
  return new Promise((resolve) => {
    const provider = h("select", { id: "setup-provider" },
      providers.filter((entry) => entry.name !== "mock").map((entry) => h("option", { value: entry.name }, `${entry.display_name} — ${entry.description}`)));
    const apiKey = h("input", { id: "setup-key", type: "password", autocomplete: "off" });
    const model = h("input", { id: "setup-model", type: "text", placeholder: "model id" });
    const baseUrl = h("input", { id: "setup-url", type: "text", placeholder: "http://localhost:8000/v1 (custom endpoints only)" });
    const problem = h("p", { class: "message error" });
    const save = async () => {
      try {
        await state.rpc.request("setup.apply", {
          provider: provider.value, api_key: apiKey.value || null, model: model.value || null, base_url: baseUrl.value || null,
        });
        const system = await state.rpc.request("system.info");
        if (!system.configured) throw new Error("Still not configured: check the key and the model id.");
        $("#dialog").close();
        resolve();
      } catch (error) {
        problem.textContent = error.message;
      }
    };
    showDialog(
      h("h2", {}, "Set up a model"),
      h("label", { for: "setup-provider" }, "Provider"), provider,
      h("label", { for: "setup-key" }, "API key (stored in .env on this machine)"), apiKey,
      h("label", { for: "setup-model" }, "Model"), model,
      h("label", { for: "setup-url" }, "Base URL"), baseUrl,
      problem,
      h("div", { class: "buttons" }, h("button", { class: "primary", type: "button", onclick: save }, "Save")),
    );
  });
}

// ── the other tabs ───────────────────────────────────────────────────────────────────────

function row(name, description, ...extra) {
  return h("div", { class: "row" }, h("div", { class: "name" }, name), h("div", { class: "desc" }, description), ...extra);
}

// A dialog with a text field: used to rename a session. Resolves when saved.
function askText(title, label, initial) {
  return new Promise((resolve) => {
    const input = h("input", { type: "text", id: "ask-text", value: initial });
    const save = () => {
      dialog.close();
      resolve(input.value);
    };
    const dialog = showDialog(
      h("h2", {}, title),
      h("label", { for: "ask-text" }, label),
      input,
      h("div", { class: "buttons" },
        h("button", { type: "button", onclick: () => { dialog.close(); resolve(null); } }, "Cancel"),
        h("button", { class: "primary", type: "button", onclick: save }, "Save")),
    );
    input.focus();
    input.select();
  });
}

// A yes/no dialog. Resolves true only when the confirming button is pressed.
function askConfirm(title, body, confirmLabel) {
  return new Promise((resolve) => {
    const dialog = showDialog(
      h("h2", {}, title),
      h("p", {}, body),
      h("div", { class: "buttons" },
        h("button", { type: "button", onclick: () => { dialog.close(); resolve(false); } }, "Cancel"),
        h("button", { class: "danger", type: "button", "data-confirm": "yes", onclick: () => { dialog.close(); resolve(true); } }, confirmLabel)),
    );
  });
}

// Save a session's JSON through the browser's download machinery.
async function exportSession(session) {
  const { filename, content } = await state.rpc.request("session.export", { stored_session_id: session.id });
  const url = URL.createObjectURL(new Blob([content], { type: "application/json" }));
  const link = h("a", { href: url, download: filename });
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

const panels = {
  async credentials(panel) {
    const show = async () => {
      const { credentials } = await state.rpc.request("credentials.list");
      const filled = credentials.filter((credential) => credential.filled).length;
      const save = async (credential, input) => {
        if (!input.value) return;
        await state.rpc.request("credentials.set", { name: credential.name, value: input.value });
        await show(); // rebuilds the rows, so the value never stays in the DOM
      };
      const remove = async (credential) => {
        if (!(await askConfirm("Delete this credential?", credential.name, "Delete"))) return;
        await state.rpc.request("credentials.delete", { name: credential.name });
        await show();
      };
      panel.replaceChildren(
        h("h2", {}, `Credentials (${filled}/${credentials.length} set)`),
        h("p", { class: "desc" }, "Values live in .env on this machine and are never sent back to this page."),
        ...credentials.map((credential) => {
          const input = h("input", {
            type: "password", id: `credential-${credential.name}`, autocomplete: "off",
            placeholder: credential.filled ? "(set — type to replace)" : "not set",
          });
          return h("div", { class: `row${credential.filled ? " filled" : ""}`, "data-name": credential.name },
            h("div", { class: "name" }, credential.name),
            h("div", { class: "desc" }, credential.filled ? `set (from ${credential.source})` : "not set"),
            h("div", { class: "actions" }, input,
              h("button", { type: "button", "data-action": "save", onclick: () => save(credential, input).catch((error) => notice(error.message, "error")) }, "Save"),
              credential.filled ? h("button", { type: "button", "data-action": "delete", class: "danger", onclick: () => remove(credential).catch((error) => notice(error.message, "error")) }, "Delete") : null));
        }),
      );
    };
    await show();
  },
  async config(panel) {
    const show = async () => {
      const { entries } = await state.rpc.request("config.list");
      const groups = new Map();
      for (const entry of entries) {
        if (!groups.has(entry.group)) groups.set(entry.group, []);
        groups.get(entry.group).push(entry);
      }
      const save = async (entry, input) => {
        let value;
        try {
          value = JSON.parse(input.value);
        } catch {
          value = input.value; // a plain string is a value too
        }
        if (entry.sensitive) {
          const ok = await askConfirm(
            "Change a security setting?",
            `${entry.key} changes what the agent may do without asking. Set it to ${JSON.stringify(value)}?`,
            "Change it",
          );
          if (!ok) return;
        }
        await state.rpc.request("config.set", { key: entry.key, value, confirm: entry.sensitive });
        if (entry.key.startsWith("dashboard.")) await loadDashboardPrefs();
        await show();
      };
      panel.replaceChildren(
        h("h2", {}, `Configuration (${entries.length} settings)`),
        ...[...groups].map(([group, groupEntries]) => h("section", { class: "config-group" },
          h("h3", {}, group),
          ...groupEntries.map((entry) => {
            const input = h("input", { type: "text", id: `config-${entry.key}`, value: JSON.stringify(entry.value) });
            return h("div", { class: `row${entry.sensitive ? " sensitive" : ""}`, "data-key": entry.key },
              h("div", { class: "name" }, entry.key, entry.sensitive ? h("span", { class: "badge" }, "needs confirmation") : null),
              h("div", { class: "desc" }, `default: ${JSON.stringify(entry.default)}`),
              h("div", { class: "actions" }, input,
                h("button", { type: "button", "data-action": "save", onclick: () => save(entry, input).catch((error) => notice(error.message, "error")) }, "Save")));
          }))),
      );
    };
    await show();
  },
  async sessions(panel) {
    const query = h("input", { type: "search", id: "session-search", placeholder: "Search every message…", autocomplete: "off" });
    const archived = h("input", { type: "checkbox", id: "session-archived" });
    const results = h("div", { id: "session-results" });

    const after = async () => {
      await refreshSessions();
      await draw();
    };
    const rename = async (session) => {
      const title = await askText("Rename session", "Title", session.title || "");
      if (title === null) return;
      await state.rpc.request("session.rename", { stored_session_id: session.id, title });
      await after();
    };
    const remove = async (session) => {
      if (!(await askConfirm("Delete this session?", session.title || session.id, "Delete"))) return;
      await state.rpc.request("session.delete", { stored_session_id: session.id });
      await after();
    };
    const open = (session) => openSession({ resume: session.id }).then(refreshSessions);

    const draw = async () => {
      const text = query.value.trim();
      if (text) {
        const { hits } = await state.rpc.request("session.search", { query: text });
        results.replaceChildren(
          h("h3", {}, `${hits.length} match${hits.length === 1 ? "" : "es"}`),
          ...(hits.length
            ? hits.map((hit) => h("div", { class: "row" },
              h("div", { class: "name" }, hit.title || hit.stored_session_id),
              h("div", { class: "desc" }, `${hit.role} · ${hit.source} · ${hit.snippet}`),
              h("div", { class: "actions" }, h("button", { type: "button", onclick: () => open({ id: hit.stored_session_id }) }, "Open"))))
            : [h("p", { class: "empty" }, "Nothing matched.")]),
        );
        return;
      }
      const { sessions } = await state.rpc.request("session.list", { limit: 100, include_archived: archived.checked });
      results.replaceChildren(
        h("h3", {}, `${sessions.length} session${sessions.length === 1 ? "" : "s"}`),
        ...(sessions.length
          ? sessions.map((session) => {
            const flags = [session.pinned && "pinned", session.archived && "archived"].filter(Boolean);
            return row(session.title || "(untitled)",
              `${session.message_count} messages · ${session.source}${flags.length ? " · " + flags.join(", ") : ""}`,
              h("div", { class: "actions" },
                h("button", { type: "button", "data-action": "open", onclick: () => open(session) }, "Open"),
                h("button", { type: "button", "data-action": "rename", onclick: () => rename(session) }, "Rename"),
                h("button", { type: "button", "data-action": "pin", onclick: () => state.rpc.request("session.pin", { stored_session_id: session.id, pinned: !session.pinned }).then(after) }, session.pinned ? "Unpin" : "Pin"),
                h("button", { type: "button", "data-action": "archive", onclick: () => state.rpc.request("session.archive", { stored_session_id: session.id, archived: !session.archived }).then(after) }, session.archived ? "Restore" : "Archive"),
                h("button", { type: "button", "data-action": "export", onclick: () => exportSession(session) }, "Export"),
                h("button", { type: "button", "data-action": "delete", class: "danger", onclick: () => remove(session) }, "Delete")));
          })
          : [h("p", { class: "empty" }, "No sessions yet.")]),
      );
    };

    query.addEventListener("input", () => draw().catch((error) => notice(error.message, "error")));
    archived.addEventListener("change", () => draw().catch((error) => notice(error.message, "error")));
    panel.replaceChildren(
      h("h2", {}, "Sessions"),
      h("div", { class: "filters" }, query, h("label", {}, archived, "include archived")),
      results,
    );
    await draw();
  },
  async skills(panel) {
    const { skills } = await state.rpc.request("skills.list");
    panel.replaceChildren(h("h2", {}, `Skills (${skills.length})`),
      ...skills.map((skill) => row(`/${skill.name}`, `${skill.description} · ${skill.category || "general"} · ${skill.tier}`)));
  },
  async tools(panel) {
    const { toolsets } = await state.rpc.request("tools.list", { session_id: state.activeId });
    panel.replaceChildren(h("h2", {}, "Toolsets"),
      ...toolsets.map((set) => row(`${set.name}  (${set.enabled_tools.length}/${set.tools.length})`, `${set.description} · ${set.tools.join(", ")}`)));
  },
  async cron(panel) {
    const show = async () => {
      const { jobs } = await state.rpc.request("cron.list");
      const act = (job, action) => async () => {
        await state.rpc.request("cron.action", { job_id: job.id, action });
        await show();
      };
      const create = async () => {
        const prompt = h("input", { type: "text", id: "cron-prompt", placeholder: "what to ask, e.g. summarise my open pull requests" });
        const schedule = h("input", { type: "text", id: "cron-schedule", placeholder: "when, e.g. every morning at 9" });
        const name = h("input", { type: "text", id: "cron-name", placeholder: "name (optional)" });
        const problem = h("p", { class: "message error" });
        const dialog = showDialog(
          h("h2", {}, "Schedule a job"),
          h("label", { for: "cron-prompt" }, "Prompt"), prompt,
          h("label", { for: "cron-schedule" }, "Schedule"), schedule,
          h("label", { for: "cron-name" }, "Name"), name,
          problem,
          h("div", { class: "buttons" },
            h("button", { type: "button", onclick: () => { dialog.close(); } }, "Cancel"),
            h("button", {
              class: "primary", type: "button", "data-action": "create",
              onclick: async () => {
                try {
                  await state.rpc.request("cron.create", { prompt: prompt.value, schedule: schedule.value, name: name.value });
                  dialog.close();
                  await show();
                } catch (error) {
                  problem.textContent = error.message;
                }
              },
            }, "Create")),
        );
        prompt.focus();
      };
      const output = async (job) => {
        const { content, truncated, path } = await state.rpc.request("cron.output", { job_id: job.id });
        showDialog(
          h("h2", {}, `Last output · ${job.name || job.id}`),
          content ? h("pre", { id: "cron-output" }, content + (truncated ? "\n… (truncated)" : ""))
                  : h("p", { class: "empty" }, "No output saved yet."),
          path ? h("div", { class: "desc" }, path) : null,
          h("div", { class: "buttons" }, h("button", { type: "button", onclick: () => $("#dialog").close() }, "Close")),
        );
      };
      panel.replaceChildren(
        h("h2", {}, "Scheduled jobs"),
        h("div", { class: "filters" }, h("button", { type: "button", id: "cron-new", onclick: create }, "+ New job")),
        ...(jobs.length ? jobs.map((job) => row(job.name || job.prompt.slice(0, 60),
          `${job.schedule_display} · ${job.enabled ? "active" : "paused"} · last: ${job.last_status || "never run"}`,
          h("div", { class: "actions" },
            h("button", { type: "button", "data-action": "toggle", onclick: act(job, job.enabled ? "pause" : "resume") }, job.enabled ? "Pause" : "Resume"),
            h("button", { type: "button", "data-action": "run", onclick: act(job, "run") }, "Run now"),
            h("button", { type: "button", "data-action": "output", onclick: () => output(job).catch((error) => notice(error.message, "error")) }, "Last output"),
            h("button", { type: "button", "data-action": "remove", class: "danger", onclick: act(job, "remove") }, "Remove"))))
          : [h("p", { class: "empty" }, "No jobs. Ask the agent to schedule one, e.g. “every morning at 9, summarise my open pull requests”.")]));
    };
    await show();
  },
  async plugins(panel) {
    const show = ({ plugins }) => panel.replaceChildren(h("h2", {}, "Plugins"),
      ...plugins.map((plugin) => row(`${plugin.name} ${plugin.version}`, `${plugin.status} · ${plugin.source} · ${plugin.error || plugin.description}`,
        h("div", { class: "actions" }, h("button", {
          type: "button",
          onclick: async () => show(await state.rpc.request("plugins.set_enabled", { name: plugin.name, enabled: plugin.status !== "loaded" })),
        }, plugin.status === "loaded" ? "Disable" : "Enable")))));
    // Pages plugins ship are frames, not markup: the sandbox drops allow-same-origin, so the
    // frame gets an origin of its own (and the served page comes from a port of its own too).
    // It cannot read this document, this origin's storage, or the session token.
    const frames = async () => {
      const response = await fetch("/api/plugin-pages", {
        headers: { "X-Clite-Token": sessionStorage.getItem("clite-token") || "" },
      });
      const { plugins } = await response.json();
      return plugins.filter((page) => page.url).map((page) => [
        h("h2", {}, page.title),
        h("iframe", {
          class: "plugin-page",
          src: page.url,
          sandbox: "allow-scripts allow-forms allow-popups",
          loading: "lazy",
          referrerpolicy: "no-referrer",
          title: `${page.name} dashboard page`,
        }),
      ]);
    };
    const listed = await state.rpc.request("plugins.list");
    show(listed);
    for (const block of await frames()) panel.append(...block.flat());
  },
  async memory(panel) {
    const show = async () => {
      const data = await state.rpc.request("memory.get");
      const act = async (params) => {
        const result = await state.rpc.request("memory.set", params);
        if (!result.success) notice(result.message, "error");
        await show();
      };
      const edit = async (target, entry) => {
        const content = await askText("Edit memory entry", "Entry", entry);
        if (content === null || content === entry) return;
        await act({ action: "replace", target, old_text: entry, content });
      };
      const add = async (target) => {
        const content = await askText("Add a memory entry", "Entry", "");
        if (content === null || !content.trim()) return;
        await act({ action: "add", target, content });
      };
      const section = (title, target, entries) => [
        h("h3", {}, title),
        h("div", { class: "filters" }, h("button", { type: "button", "data-action": `add-${target}`, onclick: () => add(target) }, "+ Add")),
        ...(entries.length ? entries.map((entry) => h("div", { class: "row", "data-target": target },
          h("div", { class: "desc" }, entry),
          h("div", { class: "actions" },
            h("button", { type: "button", "data-action": "edit", onclick: () => edit(target, entry) }, "Edit"),
            h("button", { type: "button", "data-action": "remove", class: "danger", onclick: () => act({ action: "remove", target, old_text: entry }) }, "Remove"))))
          : [h("p", { class: "empty" }, "Empty.")]),
      ];
      panel.replaceChildren(
        h("h2", {}, "Memory"),
        ...section("Agent notes (MEMORY.md)", "memory", data.memory),
        ...section("User profile (USER.md)", "user", data.user),
      );
    };
    await show();
  },
  async profiles(panel) {
    const { current, sticky, profiles } = await state.rpc.request("profiles.list");
    const describe = (profile) => {
      if (profile.name === current) return "this dashboard is running here";
      if (window.cliteDesktop) return `restart C-lite with --profile ${profile.name}`;
      return `run: clite dashboard -p ${profile.name}`;
    };
    panel.replaceChildren(
      h("h2", {}, "Profiles"),
      h("p", { class: "empty" },
        "A profile is a separate home: its own config, keys, memory and sessions. One backend "
        + "serves one profile, so switching means starting another one."),
      ...profiles.map((profile) => h("div", { class: `row${profile.name === current ? " current" : ""}`, "data-profile": profile.name },
        h("div", { class: "name" }, profile.name,
          profile.name === current ? h("span", { class: "badge" }, "running") : null,
          profile.name === sticky && profile.name !== current ? h("span", { class: "badge" }, "default for new shells") : null),
        h("div", { class: "desc" }, describe(profile)))),
    );
  },
  async logs(panel) {
    const source = h("select", { id: "logs-source" },
      h("option", { value: "agent" }, "agent.log"),
      h("option", { value: "errors" }, "errors.log"));
    const level = h("select", { id: "logs-level" },
      ...["all", "info", "warning", "error"].map((value) =>
        h("option", { value }, value === "all" ? "all levels" : value)));
    const body = h("pre", { id: "logs-body" });
    const load = async () => {
      const { lines, path, truncated } = await state.rpc.request("logs.tail", {
        source: source.value, level: level.value, lines: 300,
      });
      body.textContent = lines.length
        ? lines.join("\n") + (truncated ? "\n… (older lines omitted)" : "")
        : "(nothing logged yet)";
      body.dataset.path = path;
    };
    const reload = () => load().catch((error) => notice(error.message, "error"));
    source.addEventListener("change", reload);
    level.addEventListener("change", reload);
    panel.replaceChildren(
      h("h2", {}, "Logs"),
      h("div", { class: "filters" }, source, level,
        h("button", { type: "button", id: "logs-refresh", onclick: reload }, "Refresh")),
      body,
    );
    await load();
  },
  async hooks(panel) {
    const [hooks, mcp] = await Promise.all([
      state.rpc.request("hooks.status"),
      state.rpc.request("mcp.status"),
    ]);
    panel.replaceChildren(
      h("h2", {}, "Shell hooks"),
      h("p", { class: "desc" }, hooks.pending
        ? `${hooks.pending} hook(s) are waiting for approval. Approving one is a local act: run "clite hooks approve" on this machine.`
        : "Every configured hook is approved on this machine."),
      ...(hooks.hooks.length ? hooks.hooks.map((hook) => row(
        `${hook.event}${hook.matcher ? ` · ${hook.matcher}` : ""}`,
        `${hook.command} · ${hook.approved ? "approved" : "waiting for approval"}${hook.fail_closed ? " · fail-closed" : ""}`))
        : [h("p", { class: "empty" }, "No shell hooks configured.")]),
      h("h2", {}, "MCP servers"),
      ...(mcp.servers.length ? mcp.servers.map((server) => row(server.name,
        `${server.transport} · ${server.alive ? "connected" : "not connected"} · ${server.tools.length} tools · ${server.resources} resources · ${server.prompts} prompts`))
        : [h("p", { class: "empty" }, `${mcp.configured} configured; none connected in this session.`)]),
    );
  },
};

function selectTab(name) {
  for (const button of document.querySelectorAll("#tabs button")) button.classList.toggle("active", button.dataset.tab === name);
  for (const view of document.querySelectorAll(".view")) view.classList.toggle("active", view.id === `view-${name}`);
  if (panels[name] && state.rpc) {
    panels[name]($(`#panel-${name}`)).catch((error) => $(`#panel-${name}`).replaceChildren(h("p", { class: "message error" }, error.message)));
  }
}

// ── wiring ───────────────────────────────────────────────────────────────────────────────

$("#composer").addEventListener("submit", (event) => {
  event.preventDefault();
  const prompt = $("#prompt");
  const text = prompt.value;
  prompt.value = "";
  send(text);
});

$("#prompt").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    $("#composer").requestSubmit();
  }
});

const interrupt = () => state.rpc && state.activeId && state.rpc.request("session.interrupt", { session_id: state.activeId });
$("#stop").addEventListener("click", interrupt);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && activeView()?.busy && !$("#dialog").open) interrupt();
});
$("#new-chat").addEventListener("click", () => openSession({}).catch((error) => notice(error.message, "error")));
// The page is going away on purpose; a reconnect now would only fight the unload.
window.addEventListener("beforeunload", () => {
  state.closing = true;
});

// ── dropping and pasting files ───────────────────────────────────────────────────────────

const chatView = $("#view-chat");
for (const type of ["dragenter", "dragover"]) {
  chatView.addEventListener(type, (event) => {
    event.preventDefault(); // without this the browser just opens the file
    $("#composer").classList.add("dragging");
  });
}
for (const type of ["dragleave", "dragend"]) {
  chatView.addEventListener(type, () => $("#composer").classList.remove("dragging"));
}
chatView.addEventListener("drop", (event) => {
  event.preventDefault();
  $("#composer").classList.remove("dragging");
  addAttachments([...(event.dataTransfer?.files || [])]);
});
$("#prompt").addEventListener("paste", (event) => {
  const files = [...(event.clipboardData?.files || [])];
  if (files.length) {
    event.preventDefault();
    addAttachments(files);
  }
});

$("#tabs").addEventListener("click", (event) => {
  if (event.target.dataset.tab) selectTab(event.target.dataset.tab);
});

connect().catch((error) => notice(error instanceof RpcError ? error.message : String(error), "error"));
