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

const state = {
  rpc: null,
  sessionId: null, // runtime id
  info: null,
  busy: false,
  streaming: null, // the assistant element receiving deltas
  tools: new Map(), // call id -> element
};

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
  rpc.onClose = () => setConnection(false, "disconnected");
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
  if (!system.configured) await runSetup();
  await openSession({});
  await refreshSessions();
}

// ── sessions ─────────────────────────────────────────────────────────────────────────────

async function openSession(params) {
  if (state.sessionId) await state.rpc.request("session.close", { session_id: state.sessionId }).catch(() => {});
  const info = await state.rpc.request("session.create", params);
  state.sessionId = info.session_id;
  setInfo(info);
  $("#transcript").replaceChildren();
  state.streaming = null;
  state.tools.clear();
  const history = await state.rpc.request("session.history", { session_id: state.sessionId });
  for (const message of history.messages) renderStored(message);
  $("#prompt").focus();
}

function setInfo(info) {
  state.info = info;
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

async function refreshSessions() {
  const { sessions } = await state.rpc.request("session.list", { limit: 40 });
  const current = state.info && state.info.stored_session_id;
  $("#sessions").replaceChildren(
    ...sessions.map((session) =>
      h("li", {}, h("button", {
        type: "button", "data-id": session.id, class: session.id === current ? "current" : "",
        onclick: () => openSession({ resume: session.id }).then(refreshSessions),
      }, session.title || "(untitled)", h("span", { class: "meta" }, `${session.message_count} messages · ${session.source}`))),
    ),
  );
}

// ── transcript ───────────────────────────────────────────────────────────────────────────

function scrollDown() {
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

function addMessage(role, text) {
  const element = h("div", { class: `message ${role}` });
  element.dataset.text = text;
  renderText(element, text);
  $("#transcript").append(element);
  scrollDown();
  return element;
}

function notice(text, kind = "notice") {
  return addMessage(kind, text);
}

function renderStored(message) {
  if (message.role === "tool") {
    $("#transcript").append(h("div", { class: "tool" }, `✓ ${message.tool_name}`));
  } else if (message.text) {
    addMessage(message.role, message.text);
  }
}

function setBusy(busy) {
  state.busy = busy;
  $("#send").hidden = busy;
  $("#stop").hidden = !busy;
}

function handleEvent(event) {
  if (event.session_id && event.session_id !== state.sessionId) return;
  const payload = event.payload;
  switch (event.type) {
    case "turn.start":
      setBusy(true);
      break;
    case "message.delta":
      if (!state.streaming) state.streaming = addMessage("assistant", "");
      state.streaming.dataset.text += payload.text;
      renderText(state.streaming, state.streaming.dataset.text);
      scrollDown();
      break;
    case "message.complete":
      if (!state.streaming && payload.text) addMessage("assistant", payload.text);
      state.streaming = null;
      break;
    case "tool.start": {
      const element = h("div", { class: "tool running" }, `${payload.name}  ${payload.preview}`);
      state.tools.set(payload.call_id, element);
      $("#transcript").append(element);
      scrollDown();
      break;
    }
    case "tool.complete": {
      const element = state.tools.get(payload.call_id);
      if (element) {
        element.className = `tool${payload.failed ? " failed" : ""}`;
        element.textContent = `${payload.failed ? "✗" : "✓"} ${element.textContent}  (${payload.duration.toFixed(1)}s)`;
      }
      break;
    }
    case "status.update":
      notice(`[${payload.kind}] ${payload.text}`);
      break;
    case "subagent.update":
      notice(`subagent ${payload.index + 1}: ${payload.event} ${payload.tool || payload.status}`);
      break;
    case "session.info":
      setInfo(payload);
      refreshSessions();
      break;
    case "turn.complete":
      state.streaming = null;
      setBusy(false);
      if (payload.interrupted) notice("(interrupted)");
      else if (payload.error) notice(payload.final_response || payload.error, "error");
      state.rpc.request("session.info", { session_id: state.sessionId }).then(setInfo).then(refreshSessions);
      break;
    case "error":
      notice(payload.message, "error");
      break;
    default:
      break;
  }
}

async function send(text) {
  if (!text.trim() || !state.rpc) return;
  if (text.trim().startsWith("/")) {
    try {
      const result = await state.rpc.request("slash.exec", { session_id: state.sessionId, command: text.trim() });
      if (result.text) notice(result.text);
      if (result.action === "new") {
        $("#transcript").replaceChildren();
        const history = await state.rpc.request("session.history", { session_id: state.sessionId });
        for (const message of history.messages) renderStored(message);
      }
    } catch (error) {
      notice(error.message, "error");
    }
    return;
  }
  addMessage("user", text);
  try {
    await state.rpc.request("prompt.submit", { session_id: state.sessionId, text });
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

const panels = {
  async skills(panel) {
    const { skills } = await state.rpc.request("skills.list");
    panel.replaceChildren(h("h2", {}, `Skills (${skills.length})`),
      ...skills.map((skill) => row(`/${skill.name}`, `${skill.description} · ${skill.category || "general"} · ${skill.tier}`)));
  },
  async tools(panel) {
    const { toolsets } = await state.rpc.request("tools.list", { session_id: state.sessionId });
    panel.replaceChildren(h("h2", {}, "Toolsets"),
      ...toolsets.map((set) => row(`${set.name}  (${set.enabled_tools.length}/${set.tools.length})`, `${set.description} · ${set.tools.join(", ")}`)));
  },
  async cron(panel) {
    const { jobs } = await state.rpc.request("cron.list");
    const act = (job, action) => async () => {
      await state.rpc.request("cron.action", { job_id: job.id, action });
      panels.cron(panel);
    };
    panel.replaceChildren(h("h2", {}, "Scheduled jobs"),
      ...(jobs.length ? jobs.map((job) => row(job.name || job.prompt.slice(0, 60),
        `${job.schedule_display} · ${job.enabled ? "active" : "paused"} · last: ${job.last_status || "never run"}`,
        h("div", { class: "actions" },
          h("button", { type: "button", onclick: act(job, job.enabled ? "pause" : "resume") }, job.enabled ? "Pause" : "Resume"),
          h("button", { type: "button", onclick: act(job, "run") }, "Run now"),
          h("button", { type: "button", class: "danger", onclick: act(job, "remove") }, "Remove"))))
        : [h("p", { class: "empty" }, "No jobs. Ask the agent to schedule one, e.g. “every morning at 9, summarise my open pull requests”.")]));
  },
  async plugins(panel) {
    const show = ({ plugins }) => panel.replaceChildren(h("h2", {}, "Plugins"),
      ...plugins.map((plugin) => row(`${plugin.name} ${plugin.version}`, `${plugin.status} · ${plugin.source} · ${plugin.error || plugin.description}`,
        h("div", { class: "actions" }, h("button", {
          type: "button",
          onclick: async () => show(await state.rpc.request("plugins.set_enabled", { name: plugin.name, enabled: plugin.status !== "loaded" })),
        }, plugin.status === "loaded" ? "Disable" : "Enable")))));
    show(await state.rpc.request("plugins.list"));
  },
  async memory(panel) {
    const memory = await state.rpc.request("memory.get");
    const list = (title, entries) => [h("h2", {}, title), ...(entries.length ? entries.map((entry) => row("", entry)) : [h("p", { class: "empty" }, "Empty.")])];
    panel.replaceChildren(...list("Agent notes (MEMORY.md)", memory.memory), ...list("User profile (USER.md)", memory.user));
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

const interrupt = () => state.rpc && state.sessionId && state.rpc.request("session.interrupt", { session_id: state.sessionId });
$("#stop").addEventListener("click", interrupt);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && state.busy && !$("#dialog").open) interrupt();
});
$("#new-chat").addEventListener("click", () => openSession({}).then(refreshSessions));
$("#tabs").addEventListener("click", (event) => {
  if (event.target.dataset.tab) selectTab(event.target.dataset.tab);
});

connect().catch((error) => notice(error instanceof RpcError ? error.message : String(error), "error"));
