<!-- Dibuat oleh scripts/gen_docs.py. Jangan disunting dengan tangan: ubah kodenya, lalu jalankan skrip itu. -->

# Katalog

Semua yang terdaftar di sebuah instalasi baru, dibaca langsung dari registry di kode.

## Tool

| Tool | Toolset | Paralel | Deskripsi |
| --- | --- | --- | --- |
| `clarify` | `clarify` | never | Ask the user a question when you cannot proceed without their decision: the request is ambiguous in a way that changes the work, or a choice is theirs to make. |
| `cronjob` | `cronjob` | never | Schedule a task for later. |
| `delegate_task` | `delegation` | never | Run one or more subagents, each on a focused task, and get back only their final reports. |
| `patch` | `file` | path | Replace text in a file. |
| `read_file` | `file` | path | Read a text file with line numbers (`LINE\|content`). |
| `search_files` | `file` | safe | Search the project. |
| `write_file` | `file` | path | Create a file or replace its whole content. |
| `memory` | `memory` | never | Save durable facts to persistent memory. |
| `session_search` | `session_search` | safe | Search past conversations (all sessions, including parts that were summarised away) by keyword. |
| `skill_manage` | `skills` | never | Create and maintain skills: your procedural memory. |
| `skill_view` | `skills` | safe | Load a skill's full instructions. |
| `skills_list` | `skills` | safe | List available skills with their descriptions. |
| `process` | `terminal` | never | Manage background processes started with terminal(background=true). |
| `terminal` | `terminal` | never | Run a shell command. |
| `todo` | `todo` | never | Read or update your task list for the current session. |
| `web_fetch` | `web` | safe | Fetch a URL and return its text content (HTML is converted to plain text with links kept as `text (url)`). |

## Toolset

| Toolset | Deskripsi | Berisi (setelah `includes` diurai) |
| --- | --- | --- |
| `terminal` | Run shell commands and manage background processes | `terminal`, `process` |
| `file` | Read, write, patch and search files | `read_file`, `write_file`, `patch`, `search_files` |
| `web` | Fetch web pages as text | `web_fetch` |
| `todo` | Task list for multi-step work | `todo` |
| `memory` | Persistent notes across sessions | `memory` |
| `skills` | List, read and maintain skills | `skills_list`, `skill_view`, `skill_manage` |
| `session_search` | Search past conversations | `session_search` |
| `clarify` | Ask the user a question | `clarify` |
| `delegation` | Spawn subagents with isolated context | `delegate_task` |
| `cronjob` | Schedule recurring or one-off agent tasks | `cronjob` |
| `clite-cli` | Everything, for the interactive terminal | `terminal`, `process`, `read_file`, `write_file`, `patch`, `search_files`, `web_fetch`, `todo`, `memory`, `skills_list`, `skill_view`, `skill_manage`, `session_search`, `clarify`, `delegate_task`, `cronjob` |
| `clite-gateway` | Messaging platforms | `terminal`, `process`, `read_file`, `write_file`, `patch`, `search_files`, `web_fetch`, `todo`, `memory`, `skills_list`, `skill_view`, `skill_manage`, `session_search`, `clarify`, `delegate_task`, `cronjob` |
| `clite-cron` | Scheduled runs | `terminal`, `process`, `read_file`, `write_file`, `patch`, `search_files`, `web_fetch`, `todo`, `memory`, `skills_list`, `skill_view`, `skill_manage`, `session_search`, `delegate_task` |
| `clite-subagent` | Delegated workers | `terminal`, `process`, `read_file`, `write_file`, `patch`, `search_files`, `web_fetch`, `todo`, `skills_list`, `skill_view`, `skill_manage`, `session_search` |

## Slash command

| Perintah | Alias | Kategori | Argumen | Saat sibuk | Hanya CLI | Deskripsi |
| --- | --- | --- | --- | --- | --- | --- |
| `/new` | `/reset` | Session |  | queue |  | Start a fresh session |
| `/retry` |  | Session |  | queue |  | Remove the last exchange and send your last message again |
| `/undo` |  | Session |  | queue |  | Remove the last exchange |
| `/history` |  | Session | `[count]` | queue |  | Show the conversation so far |
| `/title` |  | Session | `[title]` | queue |  | Show or set the session title |
| `/sessions` |  | Session | `[count]` | queue |  | List recent sessions |
| `/resume` |  | Session | `<id \| title>` | queue |  | Switch to an earlier session |
| `/compress` |  | Session | `[focus]` | queue |  | Summarise older turns to free context |
| `/stop` |  | Session |  | allow |  | Interrupt the running turn |
| `/steer` |  | Session | `<text>` | allow |  | Guide the running turn without interrupting it |
| `/quit` | `/exit`, `/q` | Session |  | allow | ya | Exit |
| `/model` |  | Configuration | `[provider:model] [--global]` | queue |  | Show or switch the model |
| `/provider` |  | Configuration |  | queue |  | List model providers and whether they are configured |
| `/tools` |  | Configuration | `[enable\|disable <toolset>]` | queue |  | List toolsets, or enable/disable one |
| `/reasoning` |  | Configuration | `[none\|minimal\|low\|medium\|high\|xhigh\|max]` | queue |  | Show or set the reasoning effort |
| `/yolo` |  | Configuration |  | queue |  | Toggle command approval for this session |
| `/config` |  | Configuration | `[key]` | queue |  | Show a setting or the config file path |
| `/reload` |  | Configuration |  | queue |  | Reload config and plugins |
| `/profile` |  | Configuration |  | queue |  | Show the active profile and list the others |
| `/skills` |  | Tools & Skills | `[filter]` | queue |  | List skills |
| `/plugins` |  | Tools & Skills |  | queue |  | List plugins and their status |
| `/memory` |  | Tools & Skills |  | queue |  | Show what is in persistent memory |
| `/cron` |  | Tools & Skills |  | queue |  | List scheduled jobs |
| `/help` | `/?` | Info |  | allow |  | List commands |
| `/status` |  | Info |  | allow |  | Show model, session and context usage |
| `/usage` |  | Info |  | allow |  | Show token usage for this session |
| `/debug` |  | Info |  | queue |  | Show prompt and context internals |

## Perintah CLI

| Perintah | Fungsi | Sub-perintah |
| --- | --- | --- |
| `clite chat` | talk to the agent (default command) |  |
| `clite setup` | choose a provider, store its API key and pick a model |  |
| `clite model` | show, list or set the model | `show`, `list`, `set`, `providers` |
| `clite config` | show or change settings | `show`, `get`, `set`, `unset`, `path`, `env`, `edit`, `migrate` |
| `clite tools` | list, enable or disable toolsets | `list`, `enable`, `disable` |
| `clite skills` | list, view, install and curate skills | `list`, `view`, `install`, `remove`, `curate` |
| `clite plugins` | list, enable, disable, install or remove plugins | `list`, `enable`, `disable`, `install`, `remove` |
| `clite hooks` | review, approve or test shell hooks from config.yaml | `list`, `approve`, `revoke`, `test` |
| `clite sessions` | list, show, search, export or delete sessions | `list`, `show`, `rename`, `delete`, `export`, `search`, `prune` |
| `clite profile` | manage profiles (separate homes) | `list`, `show`, `create`, `use`, `delete` |
| `clite cron` | schedule agent tasks | `list`, `add`, `pause`, `resume`, `run`, `remove`, `tick`, `daemon` |
| `clite gateway` | run the messaging gateway | `run`, `status`, `pair` |
| `clite serve` | run the headless backend (for the desktop app or a remote client) |  |
| `clite dashboard` | run the backend and open the web dashboard |  |
| `clite tui` | start the terminal UI (needs Node.js) |  |
| `clite version` | print version information |  |
| `clite status` | show what is configured |  |
| `clite doctor` | check the installation |  |
| `clite logs` | show the agent log |  |
| `clite memory` | show persistent memory |  |
| `clite acp` | editor integration server (not implemented yet) |  |

## Protokol JSON-RPC (versi 1)

### Method

| Method | Parameter | Hasil | Keterangan |
| --- | --- | --- | --- |
| `ping` | (kosong) | `pong?`, `version?` | Liveness check. |
| `system.info` | (kosong) | `version`, `protocol_version`, `home`, `profile`, `configured`, `model?`, `provider?` | Version, active profile and whether a model is configured. |
| `session.create` | `cwd?`, `model?`, `provider?`, `toolsets?`, `yolo?`, `resume?`, `platform?` | `session_id`, `stored_session_id`, `title?`, `platform?`, `model?`, `provider?`, `cwd?`, `busy?`, `yolo?`, `message_count?`, `tools?`, `toolsets?`, `reasoning_effort?`, `context?` | Open a runtime session (new, or resuming a stored one). |
| `session.info` | `session_id` | `session_id`, `stored_session_id`, `title?`, `platform?`, `model?`, `provider?`, `cwd?`, `busy?`, `yolo?`, `message_count?`, `tools?`, `toolsets?`, `reasoning_effort?`, `context?` |  |
| `session.list` | `limit?`, `source?` | `sessions` | Stored sessions, most recent first. |
| `session.history` | `session_id` | `messages` | The transcript, in display form. |
| `session.close` | `session_id` | `ok?` |  |
| `session.interrupt` | `session_id` | `ok?` | Stop the running turn. |
| `session.steer` | `session_id`, `text` | `ok?` | Guide the running turn without stopping it. |
| `session.title` | `session_id`, `title?` | `title?` | Read the title, or set it when `title` is given. |
| `session.delete` | `stored_session_id` | `ok?` |  |
| `session.compress` | `session_id`, `focus?` | `compressed`, `message_count` |  |
| `session.usage` | `session_id` | `usage`, `context` |  |
| `prompt.submit` | `session_id`, `text`, `busy_mode?` | `accepted`, `turn_id?`, `queued?` | Start a turn. Returns at once; the answer arrives as events ending with turn.complete. |
| `slash.exec` | `session_id`, `command` | `text?`, `action?`, `turn_id?`, `data?` | Run a slash command. |
| `commands.catalog` | `session_id?` | `commands` | Every command available now, for help and autocomplete. |
| `complete.slash` | `prefix`, `session_id?` | `items` | Commands starting with a prefix. |
| `config.get` | `key?` | `value?` | One value by dotted key, or the whole effective config. |
| `config.set` | `key`, `value?` | `ok?` |  |
| `model.list` | `provider?`, `refresh?` | `provider`, `models`, `current?` |  |
| `model.set` | `session_id`, `model`, `persist?` | `success`, `message`, `model?`, `provider?` | Switch the session's model; `persist` saves it as the default. |
| `providers.list` | (kosong) | `providers`, `current?` |  |
| `setup.apply` | `provider`, `api_key?`, `model?`, `base_url?` | `provider`, `model` | Store a provider choice (and its API key) from a setup screen. |
| `tools.list` | `session_id?` | `toolsets` |  |
| `skills.list` | (kosong) | `skills` |  |
| `skills.view` | `name`, `file_path?` | `name`, `content`, `linked_files?` |  |
| `plugins.list` | (kosong) | `plugins` |  |
| `plugins.set_enabled` | `name`, `enabled` | `plugins` |  |
| `memory.get` | (kosong) | `memory?`, `user?`, `memory_limit?`, `user_limit?`, `provider?` |  |
| `cron.list` | (kosong) | `jobs` |  |
| `cron.create` | `prompt`, `schedule`, `name?`, `deliver?`, `repeat?` | `id`, `name?`, `prompt?`, `schedule_display?`, `enabled?`, `deliver?`, `next_run_at?`, `last_run_at?`, `last_status?`, `last_error?`, `run_count?` |  |
| `cron.action` | `job_id`, `action` | `jobs` |  |

### Event

| Event | Payload |
| --- | --- |
| `gateway.ready` | `version`, `protocol_version` |
| `session.info` | `session_id`, `stored_session_id`, `title?`, `platform?`, `model?`, `provider?`, `cwd?`, `busy?`, `yolo?`, `message_count?`, `tools?`, `toolsets?`, `reasoning_effort?`, `context?` |
| `turn.start` | `turn_id`, `text` |
| `turn.step` | `iteration` |
| `message.delta` | `text` |
| `reasoning.delta` | `text` |
| `message.complete` | `role`, `text?`, `tool_calls?` |
| `tool.start` | `call_id`, `name`, `args?`, `preview?` |
| `tool.complete` | `call_id`, `name`, `duration`, `failed?`, `result_preview?` |
| `status.update` | `kind`, `text` |
| `subagent.update` | `event`, `index?`, `goal?`, `tool?`, `status?` |
| `turn.complete` | `turn_id`, `final_response`, `completed`, `interrupted?`, `error?`, `exit_reason?`, `api_calls?`, `duration?`, `usage?` |
| `error` | `message`, `code?` |

### Permintaan dari server ke klien

| Permintaan | Parameter | Jawaban | Keterangan |
| --- | --- | --- | --- |
| `approval.request` | `session_id`, `command`, `description`, `pattern_keys?` | `choice` | A dangerous command needs the user's decision. No reply within the timeout means deny. |
| `clarify.request` | `session_id`, `question`, `choices?` | `answer?` | The agent asks the user a question. |

## Hook

| Hook | Bisa dari shell hook | Gagal = blokir |
| --- | --- | --- |
| `api_request_error` | ya |  |
| `on_session_end` | ya |  |
| `on_session_reset` | ya |  |
| `on_session_start` | ya |  |
| `on_skill_lifecycle` | ya |  |
| `post_api_request` | ya |  |
| `post_approval_response` | ya |  |
| `post_llm_call` | ya |  |
| `post_tool_call` | ya |  |
| `pre_api_request` | ya |  |
| `pre_approval_request` | ya |  |
| `pre_gateway_dispatch` |  |  |
| `pre_llm_call` | ya |  |
| `pre_tool_call` | ya | ya |
| `subagent_start` | ya |  |
| `subagent_stop` | ya |  |
| `transform_llm_output` |  |  |
| `transform_terminal_output` |  |  |
| `transform_tool_result` |  |  |

## Provider bawaan

| Provider | Alias | `api_mode` | Variabel kunci | Base URL | Model default |
| --- | --- | --- | --- | --- | --- |
| `anthropic` | `claude` | `anthropic_messages` | `ANTHROPIC_API_KEY` | https://api.anthropic.com |  |
| `custom` |  | `chat_completions` | `CUSTOM_API_KEY` |  |  |
| `deepseek` |  | `chat_completions` | `DEEPSEEK_API_KEY` | https://api.deepseek.com/v1 |  |
| `gemini` | `google` | `chat_completions` | `GEMINI_API_KEY`, `GOOGLE_API_KEY` | https://generativelanguage.googleapis.com/v1beta/openai |  |
| `mock` |  | `mock` |  |  | mock-1 |
| `ollama` |  | `chat_completions` |  | http://localhost:11434/v1 |  |
| `openai` |  | `chat_completions` | `OPENAI_API_KEY` | https://api.openai.com/v1 |  |
| `openrouter` |  | `chat_completions` | `OPENROUTER_API_KEY` | https://openrouter.ai/api/v1 |  |

## Platform gateway

| Platform |
| --- |
| `local` |
| `telegram` |

## Plugin bawaan

| Plugin | Jenis | Deskripsi |
| --- | --- | --- |
| `audit-log` | standalone | Record every tool call to logs/tool-audit.jsonl and show recent ones with /audit |

## Skill bawaan

| Skill | Kategori | Deskripsi |
| --- | --- | --- |
| `skill-authoring` | meta | Write or improve a skill (SKILL.md). Use when saving a reusable procedure with skill_manage, or when a skill turned out wrong or incomplete. |
| `plan-before-acting` | productivity | Break a large or ambiguous task into verifiable steps before starting. Use when a request spans several files or systems, or when the first step is not obvious. |
| `systematic-debugging` | software-development | Find the root cause of a bug before changing code. Use for any failing test, crash, or behaviour that does not match what the code appears to say. |
| `test-driven-development` | software-development | Implement a feature or fix by writing a failing test first. Use when adding behaviour to tested code or when a bug needs a regression test. |

## Kunci konfigurasi

Nilai default dari `clite/core/config_defaults.py`. Penjelasan tiap kunci ada di file itu.

| Kunci | Default |
| --- | --- |
| `model.default` | `""` |
| `model.provider` | `""` |
| `model.base_url` | `""` |
| `model.api_mode` | `""` |
| `model.context_length` | `null` |
| `model.max_tokens` | `null` |
| `providers` | `{}` |
| `fallback_providers` | `[]` |
| `toolsets` | `["clite-cli"]` |
| `disabled_toolsets` | `[]` |
| `platform_toolsets` | `{}` |
| `agent.max_turns` | `null` |
| `agent.api_max_retries` | `3` |
| `agent.api_timeout` | `600` |
| `agent.reasoning_effort` | `""` |
| `agent.run_budget_seconds` | `null` |
| `agent.max_tool_workers` | `8` |
| `terminal.backend` | `"local"` |
| `terminal.cwd` | `""` |
| `terminal.timeout` | `180` |
| `terminal.env_passthrough` | `[]` |
| `tool_output.max_chars` | `50000` |
| `tool_output.max_lines` | `2000` |
| `tool_result_max_chars` | `100000` |
| `file_read_max_chars` | `100000` |
| `web.allow_private_urls` | `false` |
| `web.timeout` | `30` |
| `compression.enabled` | `true` |
| `compression.threshold` | `0.5` |
| `compression.protect_first_n` | `3` |
| `compression.protect_last_n` | `20` |
| `compression.max_attempts` | `3` |
| `context.engine` | `"compressor"` |
| `prompt_caching.cache_ttl` | `"5m"` |
| `context_file_max_chars` | `null` |
| `auxiliary.compression.provider` | `"main"` |
| `auxiliary.compression.model` | `""` |
| `auxiliary.title_generation.provider` | `"main"` |
| `auxiliary.title_generation.model` | `""` |
| `auxiliary.approval.provider` | `"main"` |
| `auxiliary.approval.model` | `""` |
| `display.streaming` | `true` |
| `display.show_reasoning` | `false` |
| `display.tool_progress` | `"all"` |
| `display.skin` | `"default"` |
| `display.busy_input_mode` | `"interrupt"` |
| `display.interface` | `"cli"` |
| `memory.memory_enabled` | `true` |
| `memory.user_profile_enabled` | `true` |
| `memory.memory_char_limit` | `2200` |
| `memory.user_char_limit` | `1375` |
| `memory.nudge_interval` | `10` |
| `memory.provider` | `""` |
| `skills.external_dirs` | `[]` |
| `skills.disabled` | `[]` |
| `skills.auto_load` | `[]` |
| `delegation.model` | `""` |
| `delegation.provider` | `""` |
| `delegation.max_iterations` | `50` |
| `delegation.max_concurrent_children` | `3` |
| `delegation.max_spawn_depth` | `1` |
| `approvals.mode` | `"manual"` |
| `approvals.timeout` | `300` |
| `approvals.cron_mode` | `"deny"` |
| `approvals.single_query_mode` | `"deny"` |
| `approvals.deny` | `[]` |
| `command_allowlist` | `[]` |
| `plugins.enabled` | `[]` |
| `plugins.disabled` | `[]` |
| `plugins.entries` | `{}` |
| `plugins.hook_callback_timeout` | `30` |
| `hooks` | `{}` |
| `mcp_servers` | `{}` |
| `quick_commands` | `{}` |
| `platform_hints` | `{}` |
| `gateway.platforms` | `{}` |
| `gateway.allow_all_users` | `false` |
| `gateway.group_sessions_per_user` | `true` |
| `gateway.agent_cache_ttl_seconds` | `3600` |
| `cron.enabled` | `true` |
| `cron.catch_up_missed` | `true` |
| `cron.inactivity_timeout_seconds` | `600` |
| `server.host` | `"127.0.0.1"` |
| `server.port` | `0` |
| `sessions.auto_prune` | `false` |
| `sessions.retention_days` | `90` |
| `logging.level` | `"INFO"` |
| `logging.max_size_mb` | `5` |
| `logging.backup_count` | `3` |
| `timezone` | `""` |
| `_config_version` | `1` |
