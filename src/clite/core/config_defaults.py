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

DEFAULT_CONFIG: dict[str, Any] = {
    # ── Model route ──────────────────────────────────────────────────────────────────────
    "model": {
        "default": "",  # model id; empty until `clite setup` or `clite model` picks one
        "provider": "",  # provider name; empty = first provider with credentials
        "base_url": "",  # only for a custom endpoint; a provider's own URL comes from its profile
        "api_mode": "",  # chat_completions | anthropic_messages; empty = from the provider
        "context_length": None,  # explicit override always wins over catalog lookups
        "max_tokens": None,
    },
    # Named custom providers: {name: {base_url, api_key_env, api_mode, models: [..]}}
    "providers": {},
    # Tried in order when the primary route fails: [{provider, model}]
    "fallback_providers": [],
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
        "backend": "local",
        "cwd": "",  # empty = the directory the process was started in
        "timeout": 180,
        # Credentials that commands run by the agent may see. By default every known one is
        # stripped from their environment: each name in .env, and each provider or platform
        # key (OPENAI_API_KEY, ...) even when it was exported in your shell.
        "env_passthrough": [],
    },
    "tool_output": {"max_chars": 50_000, "max_lines": 2000},
    # Hard cap on any single tool result before it enters context.
    "tool_result_max_chars": 100_000,
    "file_read_max_chars": 100_000,
    # web_fetch refuses loopback, private and link-local addresses unless this is true.
    "web": {"allow_private_urls": False, "timeout": 30},
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
    },
    # ── Display ──────────────────────────────────────────────────────────────────────────
    "display": {
        "streaming": True,
        "show_reasoning": False,
        "tool_progress": "all",  # off | new | all | verbose
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
        "entries": {},  # {plugin_id: {allow_tool_override, settings: {...}}}
        "hook_callback_timeout": 30,
    },
    # Shell hooks: {event: [command | {command, matcher, timeout, fail_closed}]}. A hook runs
    # only after `clite hooks approve` (see clite.plugins.shell_hooks).
    "hooks": {},
    # MCP servers over stdio: {name: {command, args, env, cwd, timeout, enabled,
    # tools: {include: [..], exclude: [..]}}}
    "mcp_servers": {},
    "quick_commands": {},  # {name: {type: exec|alias, command|target}}
    "platform_hints": {},  # {platform: "text" | {append: ..} | {replace: ..}}
    # ── Surfaces ─────────────────────────────────────────────────────────────────────────
    "gateway": {
        "platforms": {},  # {name: {enabled: true, ...adapter settings}}
        "allow_all_users": False,
        "group_sessions_per_user": True,
        "agent_cache_ttl_seconds": 3600,
    },
    "cron": {"enabled": True, "catch_up_missed": True, "inactivity_timeout_seconds": 600},
    "server": {"host": "127.0.0.1", "port": 0},
    # auto_prune deletes sessions with no activity for retention_days, at most once a day, when
    # a surface starts. Pinned sessions are kept. `clite sessions prune` does it on demand.
    "sessions": {"auto_prune": False, "retention_days": 90},
    "logging": {"level": "INFO", "max_size_mb": 5, "backup_count": 3},
    "timezone": "",  # IANA name; empty = system local time
    "_config_version": CONFIG_VERSION,
}
