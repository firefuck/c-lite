"""The protocol, declared: methods (client to server), events and server requests.

Two session identities appear throughout:

``session_id``          a runtime id, valid for one server process. Every call names it.
``stored_session_id``   the durable id in the session database. It changes when the runtime
                        session starts a new conversation or resumes an old one.
"""

from __future__ import annotations

from typing import Any, Literal

from clite.rpc.contracts.base import Empty, Ok, Params, Payload, Result, event, method, server_request

# ── shared shapes ────────────────────────────────────────────────────────────────────────


class ContextStatus(Result):
    engine: str = ""
    context_length: int = 0
    threshold_tokens: int = 0
    last_prompt_tokens: int = 0
    compression_count: int = 0
    usage_percent: float = 0.0
    messages: int = 0
    model: str = ""
    provider: str = ""


class SessionInfo(Result):
    session_id: str
    stored_session_id: str
    title: str = ""
    platform: str = ""
    model: str = ""
    provider: str = ""
    cwd: str = ""
    busy: bool = False
    yolo: bool = False
    message_count: int = 0
    tools: list[str] = []
    toolsets: list[str] = []
    reasoning_effort: str = ""
    context: ContextStatus = ContextStatus()


class StoredSession(Result):
    id: str
    title: str = ""
    source: str = ""
    model: str = ""
    message_count: int = 0
    started_at: float = 0.0
    last_activity_at: float | None = None


class TranscriptMessage(Result):
    role: Literal["user", "assistant", "tool", "system"]
    text: str = ""
    tool_name: str = ""
    tool_calls: list[str] = []
    is_summary: bool = False
    timestamp: float | None = None


class UsageTotals(Result):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    reasoning_tokens: int = 0
    prompt_tokens: int = 0


class CommandEntry(Result):
    name: str
    description: str = ""
    category: str = ""
    aliases: list[str] = []
    args_hint: str = ""
    subcommands: list[str] = []
    kind: str = "builtin"


# ── system ───────────────────────────────────────────────────────────────────────────────


class PingResult(Result):
    pong: bool = True
    version: str = ""


class SystemInfoResult(Result):
    version: str
    protocol_version: int
    home: str
    profile: str
    configured: bool
    model: str = ""
    provider: str = ""


method("ping", Empty, PingResult, "Liveness check.")
method("system.info", Empty, SystemInfoResult, "Version, active profile and whether a model is configured.")

# ── sessions ─────────────────────────────────────────────────────────────────────────────


class SessionCreateParams(Params):
    cwd: str | None = None
    model: str | None = None
    provider: str | None = None
    toolsets: list[str] | None = None
    yolo: bool = False
    resume: str | None = None  # a stored session id, id prefix or title
    platform: str | None = None


class SessionRef(Params):
    session_id: str


class SessionListParams(Params):
    limit: int = 30
    source: str | None = None


class SessionListResult(Result):
    sessions: list[StoredSession]


class SessionHistoryResult(Result):
    messages: list[TranscriptMessage]


class SessionSteerParams(Params):
    session_id: str
    text: str


class SessionTitleParams(Params):
    session_id: str
    title: str | None = None


class SessionTitleResult(Result):
    title: str = ""


class SessionDeleteParams(Params):
    stored_session_id: str


class SessionCompressParams(Params):
    session_id: str
    focus: str | None = None


class SessionCompressResult(Result):
    compressed: bool
    message_count: int


class SessionUsageResult(Result):
    usage: UsageTotals
    context: ContextStatus


method("session.create", SessionCreateParams, SessionInfo, "Open a runtime session (new, or resuming a stored one).")
method("session.info", SessionRef, SessionInfo)
method("session.list", SessionListParams, SessionListResult, "Stored sessions, most recent first.")
method("session.history", SessionRef, SessionHistoryResult, "The transcript, in display form.")
method("session.close", SessionRef, Ok)
method("session.interrupt", SessionRef, Ok, "Stop the running turn.")
method("session.steer", SessionSteerParams, Ok, "Guide the running turn without stopping it.")
method("session.title", SessionTitleParams, SessionTitleResult, "Read the title, or set it when `title` is given.")
method("session.delete", SessionDeleteParams, Ok)
method("session.compress", SessionCompressParams, SessionCompressResult)
method("session.usage", SessionRef, SessionUsageResult)

# ── prompts and commands ─────────────────────────────────────────────────────────────────


class PromptSubmitParams(Params):
    session_id: str
    text: str
    # What to do when a turn is already running. Default: the server's display.busy_input_mode.
    busy_mode: Literal["interrupt", "queue", "steer", "reject"] | None = None


class PromptSubmitResult(Result):
    accepted: bool
    turn_id: str = ""
    queued: bool = False


class SlashExecParams(Params):
    session_id: str
    command: str


class SlashExecResult(Result):
    text: str = ""
    action: str | None = None  # "quit", "new", or "submit" (a turn was started; see turn_id)
    turn_id: str = ""
    data: dict[str, Any] = {}


class CatalogParams(Params):
    session_id: str | None = None


class CatalogResult(Result):
    commands: list[CommandEntry]


class CompleteParams(Params):
    prefix: str
    session_id: str | None = None


class CompleteResult(Result):
    items: list[CommandEntry]


method("prompt.submit", PromptSubmitParams, PromptSubmitResult,
       "Start a turn. Returns at once; the answer arrives as events ending with turn.complete.")
method("slash.exec", SlashExecParams, SlashExecResult, "Run a slash command.")
method("commands.catalog", CatalogParams, CatalogResult, "Every command available now, for help and autocomplete.")
method("complete.slash", CompleteParams, CompleteResult, "Commands starting with a prefix.")

# ── configuration, models, providers ─────────────────────────────────────────────────────


class ConfigGetParams(Params):
    key: str | None = None


class ConfigGetResult(Result):
    value: Any = None


class ConfigSetParams(Params):
    key: str
    value: Any = None


class ModelListParams(Params):
    provider: str | None = None
    refresh: bool = False


class ModelEntry(Result):
    id: str
    context_length: int | None = None


class ModelListResult(Result):
    provider: str
    models: list[ModelEntry]
    current: str = ""


class ModelSetParams(Params):
    session_id: str
    model: str
    persist: bool = False


class ModelSetResult(Result):
    success: bool
    message: str
    model: str = ""
    provider: str = ""


class ProviderEntry(Result):
    name: str
    display_name: str
    description: str = ""
    configured: bool = False
    env_vars: list[str] = []
    needs_base_url: bool = False
    signup_url: str = ""


class ProvidersResult(Result):
    providers: list[ProviderEntry]
    current: str = ""


class SetupApplyParams(Params):
    provider: str
    api_key: str | None = None
    model: str | None = None
    base_url: str | None = None


class SetupApplyResult(Result):
    provider: str
    model: str


method("config.get", ConfigGetParams, ConfigGetResult, "One value by dotted key, or the whole effective config.")
method("config.set", ConfigSetParams, Ok)
method("model.list", ModelListParams, ModelListResult)
method("model.set", ModelSetParams, ModelSetResult, "Switch the session's model; `persist` saves it as the default.")
method("providers.list", Empty, ProvidersResult)
method("setup.apply", SetupApplyParams, SetupApplyResult, "Store a provider choice (and its API key) from a setup screen.")

# ── tools, skills, plugins, memory, cron ─────────────────────────────────────────────────


class ToolsetEntry(Result):
    name: str
    description: str = ""
    tools: list[str] = []
    enabled_tools: list[str] = []


class ToolsListResult(Result):
    toolsets: list[ToolsetEntry]


class SkillEntry(Result):
    name: str
    description: str = ""
    category: str = ""
    tier: str = ""
    version: str = ""
    tags: list[str] = []


class SkillsListResult(Result):
    skills: list[SkillEntry]


class SkillViewParams(Params):
    name: str
    file_path: str | None = None


class SkillViewResult(Result):
    name: str
    content: str
    linked_files: dict[str, list[str]] = {}


class PluginEntry(Result):
    name: str
    version: str = ""
    description: str = ""
    kind: str = ""
    source: str = ""
    status: str = ""
    error: str = ""
    path: str = ""


class PluginsListResult(Result):
    plugins: list[PluginEntry]


class PluginSetEnabledParams(Params):
    name: str
    enabled: bool


class MemoryGetResult(Result):
    memory: list[str] = []
    user: list[str] = []
    memory_limit: int = 0
    user_limit: int = 0
    provider: str = ""


class CronJob(Result):
    id: str
    name: str = ""
    prompt: str = ""
    schedule_display: str = ""
    enabled: bool = True
    deliver: str = "local"
    next_run_at: float | None = None
    last_run_at: float | None = None
    last_status: str | None = None
    last_error: str | None = None
    run_count: int = 0


class CronListResult(Result):
    jobs: list[CronJob]


class CronCreateParams(Params):
    prompt: str
    schedule: str
    name: str = ""
    deliver: str = "local"
    repeat: int | None = None


class CronActionParams(Params):
    job_id: str
    action: Literal["pause", "resume", "run", "remove"]


method("tools.list", CatalogParams, ToolsListResult)
method("skills.list", Empty, SkillsListResult)
method("skills.view", SkillViewParams, SkillViewResult)
method("plugins.list", Empty, PluginsListResult)
method("plugins.set_enabled", PluginSetEnabledParams, PluginsListResult)
method("memory.get", Empty, MemoryGetResult)
method("cron.list", Empty, CronListResult)
method("cron.create", CronCreateParams, CronJob)
method("cron.action", CronActionParams, CronListResult)

# ── events (server to client notifications) ──────────────────────────────────────────────


class ReadyPayload(Payload):
    version: str
    protocol_version: int


class TextPayload(Payload):
    text: str


class TurnStartPayload(Payload):
    turn_id: str
    text: str


class StepPayload(Payload):
    iteration: int


class MessagePayload(Payload):
    role: str
    text: str = ""
    tool_calls: list[str] = []


class ToolStartPayload(Payload):
    call_id: str
    name: str
    args: dict[str, Any] = {}
    preview: str = ""


class ToolCompletePayload(Payload):
    call_id: str
    name: str
    duration: float
    failed: bool = False
    result_preview: str = ""


class StatusPayload(Payload):
    kind: str
    text: str


class SubagentPayload(Payload):
    event: str
    index: int = 0
    goal: str = ""
    tool: str = ""
    status: str = ""


class TurnCompletePayload(Payload):
    turn_id: str
    final_response: str
    completed: bool
    interrupted: bool = False
    error: str | None = None
    exit_reason: str = ""
    api_calls: int = 0
    duration: float = 0.0
    usage: UsageTotals = UsageTotals()


class ErrorPayload(Payload):
    message: str
    code: int = 0


event("gateway.ready", ReadyPayload)  # first message on every connection
event("session.info", SessionInfo)  # the session changed (new, resume, model, title)
event("turn.start", TurnStartPayload)
event("turn.step", StepPayload)  # a model call is starting
event("message.delta", TextPayload)  # streamed answer text
event("reasoning.delta", TextPayload)
event("message.complete", MessagePayload)  # an assistant message is finished
event("tool.start", ToolStartPayload)
event("tool.complete", ToolCompletePayload)
event("status.update", StatusPayload)  # retry, fallback, compressing, compressed, warning
event("subagent.update", SubagentPayload)
event("turn.complete", TurnCompletePayload)  # always the last event of a turn
event("error", ErrorPayload)

# ── server requests (server to client, awaiting a reply) ─────────────────────────────────


class ApprovalRequestParams(Params):
    session_id: str
    command: str
    description: str
    pattern_keys: list[str] = []


class ApprovalRequestResult(Result):
    choice: Literal["once", "session", "always", "deny"]


class ClarifyRequestParams(Params):
    session_id: str
    question: str
    choices: list[str] = []


class ClarifyRequestResult(Result):
    answer: str = ""


server_request("approval.request", ApprovalRequestParams, ApprovalRequestResult,
               "A dangerous command needs the user's decision. No reply within the timeout means deny.")
server_request("clarify.request", ClarifyRequestParams, ClarifyRequestResult, "The agent asks the user a question.")
