"""``DEFAULT_CONFIG``: every setting, its default, and the reason for that default.

Rules:

* A new key is added here and deep-merges into existing installs automatically.
* ``_config_version`` is bumped ONLY to transform existing files (rename a key, restructure);
  the transform goes in ``clite.core.config.MIGRATIONS``.
* Every key has a runtime reader. A key nothing reads is a knob that does nothing.
* Secrets never live here. They go in ``.env`` (see ``clite.core.env``).
"""

from __future__ import annotations

from typing import Any

CONFIG_VERSION = 1

# Keys whose change alters what the agent is allowed to do without asking. The dashboard asks
# for an explicit confirmation before writing one, and `config.set` refuses without `confirm`.
SECURITY_SENSITIVE_KEYS: tuple[str, ...] = (
    "approvals",
    "gateway.allow_all_users",
    "plugins.enabled",
    "hooks",
    "command_allowlist",
    "mcp_servers",
)


def is_sensitive_config_key(key: str) -> bool:
    """True when writing ``key`` changes security behaviour and needs a confirmation."""
    return any(key == sensitive or key.startswith(sensitive + ".") for sensitive in SECURITY_SENSITIVE_KEYS)

DEFAULT_CONFIG: dict[str, Any] = {
    # ── Model route ──────────────────────────────────────────────────────────────────────
    "model": {
        "default": "",  # model id; empty until `clite setup` or `clite model` picks one
        "provider": "",  # provider name; empty = first provider with credentials
        "base_url": "",  # only for a custom endpoint; a provider's own URL comes from its profile
        "api_mode": "",  # chat_completions | anthropic_messages; empty = from the provider
        "context_length": None,  # explicit override always wins over catalog lookups
        "max_tokens": None,
        # Force image support on (true) or off (false) regardless of what the profile
        # declares. Empty = ask the provider profile. F2-T6.
        "vision": None,
    },
    # Named custom providers: {name: {base_url, api_key_env, api_mode, models: [..]}}
    "providers": {},
    # Tried in order when the primary route fails: [{provider, model}]
    "fallback_providers": [],
    # Pricing overrides per model or prefix; empty by default to use profile or catalog rates
    "pricing": {
        "overrides": {},
    },
    # ── Tools ────────────────────────────────────────────────────────────────────────────
    "toolsets": ["clite-cli"],
    "disabled_toolsets": [],
    # Per-platform override: {telegram: [clite-gateway], cron: [file, web]}. Without an entry a
    # local surface uses `toolsets`, cron uses clite-cron and messaging uses clite-gateway.
    "platform_toolsets": {},
    "agent": {
        # null = unlimited. A finite cap silently truncates long tasks, so it is opt-in.
        "max_turns": None,
        "api_max_retries": 3,
        "api_timeout": 600,  # seconds of silence from the provider before a call is abandoned
        "reasoning_effort": "",  # "" (model default), none, minimal, low, medium, high, xhigh, max
        "run_budget_seconds": None,  # wall-clock budget per turn; null = off
        "max_tool_workers": 8,
    },
    "terminal": {
        "backend": "local",  # local | docker | ssh (see the docker:/ssh: blocks below)
        "cwd": "",  # empty = the directory the process was started in
        "timeout": 180,
        # Credentials that commands run by the agent may see. By default every known one is
        # stripped from their environment: each name in .env, and each provider or platform
        # key (OPENAI_API_KEY, ...) even when it was exported in your shell.
        "env_passthrough": [],
        # Used when terminal.backend is "docker": one container per task_id, removed when the
        # session closes. The working directory is bind-mounted at the same path, so the file
        # tools see the same files. No host credential reaches the container: env_passthrough
        # does not apply to it, and only mounts spelled here carry anything in.
        "docker": {
            "image": "",  # required; e.g. "python:3.12-slim"
            "mounts": [],  # extra "-v host:container[:mode]" entries beyond the workspace
            "network": "none",  # Docker network; "none" means the container has no network
            "user": "",  # user inside the container; empty = the image's own
            "memory": "",  # e.g. "2g"; empty = no limit
            "keep_container": False,  # true = leave it running after the session closes
        },
        # Used when terminal.backend is "ssh": one connection per task_id over the system ssh
        # binary (ControlMaster), no credential from .env is forwarded.
        "ssh": {
            "host": "",  # user@host, or a Host alias from ~/.ssh/config; required
            "port": "",  # empty = 22 or the alias's own port
            "key": "",  # private key path; empty = your ssh agent and ~/.ssh/config
            "known_hosts": "",  # empty = the user's default known_hosts
            "cwd": "",  # remote working directory; empty = the login directory
        },
    },
    "tool_output": {"max_chars": 50_000, "max_lines": 2000},
    # Hard cap on any single tool result before it enters context.
    "tool_result_max_chars": 100_000,
    "file_read_max_chars": 100_000,
    # web_fetch refuses loopback, private and link-local addresses unless this is true.
    # web.search.provider selects a search backend plugin (empty = first available).
    "web": {"allow_private_urls": False, "timeout": 30, "search": {"provider": ""}},
    # image.provider selects an image-generation backend plugin (empty = first available).
    "image": {"provider": ""},
    # Images the user attaches to a message. `max_bytes` is the ceiling on one image after
    # downscaling; `max_images` is the ceiling per message; `max_edge` is the longest side in
    # pixels an oversized image is shrunk to (needs the `images` extra, Pillow).
    "attachments": {"max_bytes": 5_000_000, "max_images": 8, "max_edge": 1568},
    # Voice. Each half selects a backend plugin by name (empty = the first configured one).
    # `max_seconds` and `max_bytes` bound one inbound recording before it is sent for
    # transcription -- the byte ceiling only bites below `attachments.max_bytes`, since a larger
    # file is refused before it is stored. `max_chars` bounds the text one `text_to_speech` call
    # may speak; zero means no ceiling on either count.
    # `reply_with_voice` names the platforms whose answer to a voice message is spoken back.
    "speech": {
        "transcription": {"provider": "", "model": "", "language": ""},
        "speech": {"provider": "", "model": "", "voice": ""},
        "max_seconds": 300,
        "max_bytes": 10_000_000,
        "max_chars": 4000,
        "reply_with_voice": [],
    },
    # ── Context ──────────────────────────────────────────────────────────────────────────
    "compression": {
        "enabled": True,
        "threshold": 0.50,  # compress when prompt tokens exceed this share of the window
        "protect_first_n": 3,  # head messages kept verbatim (after the system prompt)
        "protect_last_n": 20,  # recent messages kept verbatim
        "max_attempts": 3,
    },
    "context": {"engine": "compressor"},
    "prompt_caching": {"cache_ttl": "5m"},  # 5m | 1h (Anthropic cache_control)
    "context_file_max_chars": None,  # null = scale with the model window (20k floor)
    # Side-LLM tasks. provider "main" reuses the conversation route (with the provider's cheap
    # model when it declares one). "approval" is the reviewer used by approvals.mode: smart.
    "auxiliary": {
        "compression": {"provider": "main", "model": ""},
        "title_generation": {"provider": "main", "model": ""},
        "approval": {"provider": "main", "model": ""},
        # What `ctx.llm` answers with. "main" reuses the conversation route; point it at a cheap
        # model so plugin side tasks do not pay for the big one.
        "plugin": {"provider": "main", "model": ""},
        # The model that reads images for `vision_analyze` when the conversation's own model
        # cannot see. "main" reuses the conversation route; point it at a vision model when the
        # main model has no eyes.
        "vision": {"provider": "main", "model": ""},
    },
    # ── Display ──────────────────────────────────────────────────────────────────────────
    "display": {
        "streaming": True,
        "show_reasoning": False,
        "tool_progress": "all",  # off | new | all | verbose | message
        "skin": "default",
        "busy_input_mode": "interrupt",  # interrupt | queue | steer
        # What a bare `clite` opens on a terminal: cli (classic) or tui (needs Node.js).
        # `--tui` and `--classic` override it for one run.
        "interface": "cli",
    },
    # ── Memory and skills ────────────────────────────────────────────────────────────────
    "memory": {
        "memory_enabled": True,
        "user_profile_enabled": True,
        "memory_char_limit": 2200,  # about 800 tokens; the cap is what forces curation
        "user_char_limit": 1375,  # about 500 tokens
        "nudge_interval": 10,  # turns between reminders to save durable knowledge; 0 = off
        "provider": "",  # external memory provider plugin; empty = built-in only
    },
    "skills": {
        "external_dirs": [],  # e.g. ["~/.agents/skills"]
        "disabled": [],
        "auto_load": [],  # skill names loaded into every session's stable prompt tier
        # Where `clite skills search` looks. Empty means the index that ships with the package.
        # A path or URL replaces it; `clite skills tap add` appends more.
        "hub": {"index": ""},
    },
    # Background review: after a turn that used at least `min_tool_calls` tool calls, a small
    # forked agent reads a copy of that turn and saves what it learned (memory and skills). It
    # runs on its own thread and never touches the session's own history. `min_interval_seconds`
    # is the per-session rate limit; a subagent, a cron run, or a busy session is never reviewed.
    "background_review": {
        "enabled": True,
        "min_tool_calls": 8,  # a turn shorter than this is not worth reviewing
        "min_interval_seconds": 900,  # at most one review per session per this many seconds
        "max_turns": 3,  # the reviewer's own (small) turn budget
        "timeout_seconds": 120,  # a review that overruns this is abandoned
    },
    # Curator: archive agent-created skills nobody uses (`clite skills curate` runs it by hand).
    # `run_startup_maintenance` runs it automatically at most once per `interval_hours`, the way
    # session auto-prune works. It archives to <home>/skills/.archive/; it never deletes.
    "curator": {
        "enabled": True,
        "interval_hours": 168,  # 7 days, like Hermes' default
        "stale_days": 30,  # unused for this many days = stale
    },
    "delegation": {
        "model": "",
        "provider": "",
        "max_iterations": 50,
        "max_concurrent_children": 3,
        "max_spawn_depth": 1,  # 1 = flat: children cannot delegate
    },
    # ── Safety ───────────────────────────────────────────────────────────────────────────
    "approvals": {
        # manual: ask about every flagged command. smart: an auxiliary model clears false
        # positives and refuses clear dangers; anything it is unsure about still asks you.
        # off: never ask (same as --yolo). Hardline patterns are refused in every mode.
        "mode": "manual",
        "timeout": 300,
        "cron_mode": "deny",
        "single_query_mode": "deny",
        "deny": [],  # fnmatch globs that block a command even under --yolo
    },
    "command_allowlist": [],  # pattern keys approved with "always"
    # ── Extension ────────────────────────────────────────────────────────────────────────
    "plugins": {
        "enabled": [],  # opt-in: nothing loads until it is listed here
        "disabled": [],  # always wins over enabled
        "entries": {},  # {plugin_id: {allow_tool_override, settings: {...}, llm: {calls}}}
        "hook_callback_timeout": 30,
        # What a plugin may ask of an auxiliary model (ctx.llm). A budget is granted per plugin
        # in plugins.entries.<id>.llm.calls (default 0: no access); this is the ceiling on one
        # call, whatever the plugin asks for.
        "llm": {"max_tokens": 1024},
        # Where `clite plugins search` looks. Empty means the catalog that ships with the
        # package (built from the bundled plugins by scripts/build_plugins_index.py).
        "hub": {"index": ""},
    },
    # Shell hooks: {event: [command | {command, matcher, timeout, fail_closed}]}. A hook runs
    # only after `clite hooks approve` (see clite.plugins.shell_hooks).
    "hooks": {},
    # MCP servers: {name: {command, args, env, cwd, timeout, enabled, tools: {include, exclude}}}
    # for a local process, or {name: {url, headers, timeout, enabled}} for a Streamable HTTP
    # endpoint. In `headers`, `${NAME}` reads NAME from .env.
    "mcp_servers": {},
    "quick_commands": {},  # {name: {type: exec|alias, command|target}}
    "platform_hints": {},  # {platform: "text" | {append: ..} | {replace: ..}}
    # ── Surfaces ─────────────────────────────────────────────────────────────────────────
    "gateway": {
        "platforms": {},  # {name: {enabled: true, ...adapter settings}}
        "allow_all_users": False,
        "group_sessions_per_user": True,
        "agent_cache_ttl_seconds": 3600,
        "session_reset": {
            "mode": "none",  # none | idle | daily
            "idle_minutes": 120,
            "daily_hour": 4,
        },
        "home_channels": {},  # {platform: chat_id}
        "send_targets": [],  # allowed destinations for send_message tool: ["telegram:12345", ...]
    },
    "cron": {
        "enabled": True,
        "catch_up_missed": True,
        "inactivity_timeout_seconds": 600,
        # Failed gateway sends are retried on later ticks, but never forever.
        "delivery_max_attempts": 3,
        # Cron jobs may overlap so one slow task does not delay the rest of a tick.
        "max_concurrent_jobs": 4,
        # The model-facing cronjob tool cannot fill the scheduler indefinitely.
        "max_jobs_from_tool": 20,
    },
    "server": {
        "host": "127.0.0.1",
        "port": 0,
        # Names this server answers to when it is bound to something other than loopback. Empty
        # means only the bind address itself. A loopback server always accepts loopback names
        # only, whatever this holds.
        "allowed_hosts": [],
        # Cap on one incoming RPC message, in bytes. The ASGI server refuses a bigger WebSocket
        # frame before this is even reached; this is the second check.
        "max_message_bytes": 1_000_000,
        # Wrong-token throttling, counted per client address and kept in memory only.
        "rate_limit": {"max_failures": 10, "window_seconds": 60, "delay_seconds": 5},
        # Reconnect replay: how many recent events per session are kept, how many sessions are
        # remembered at once, and how long a session outlives the connection that opened it.
        "replay_buffer_events": 500,
        "replay_sessions": 64,
        "resume_grace_seconds": 120,
        # Record connections, the token each used, and commands approved from the dashboard, in
        # <home>/logs/audit.log. Never holds a token value, only its name.
        "audit_log": True,
        # These externally callable routes are opt-in because the server token is powerful.
        "openai_api_enabled": False,
        "webhooks_enabled": False,
    },
    # Named inbound webhooks; their HMAC secrets live in .env as CLITE_WEBHOOK_<NAME>_SECRET.
    "webhooks": {},
    # ── Dashboard (browser and the desktop shell) ────────────────────────────────────────
    # A system notification when a turn finishes or an approval is needed while the window is
    # not focused. The page still needs the browser's own permission, which only a user
    # gesture can ask for.
    "dashboard": {"notifications": True},
    # auto_prune deletes sessions with no activity for retention_days, at most once a day, when
    # a surface starts. Pinned sessions are kept. `clite sessions prune` does it on demand.
    "sessions": {"auto_prune": False, "retention_days": 90},
    # File checkpoints kept so /rollback can undo the agent's edits. Groups older than
    # sessions.retention_days are dropped with their session, and the oldest groups are
    # deleted once the whole store grows past max_bytes.
    "checkpoints": {"max_bytes": 100_000_000},
    "logging": {"level": "INFO", "max_size_mb": 5, "backup_count": 3},
    "timezone": "",  # IANA name; empty = system local time
    "_config_version": CONFIG_VERSION,
}
