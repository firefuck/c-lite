<!-- Dibuat oleh scripts/gen_docs.py. Jangan disunting dengan tangan: ubah kodenya, lalu jalankan skrip itu. -->

# Katalog

Semua yang terdaftar di sebuah instalasi baru, dibaca langsung dari registry di kode.

## Tool

| Tool | Toolset | Paralel | Deskripsi |
| --- | --- | --- | --- |
| `clarify` | `clarify` | never | Ask the user a question when you cannot proceed without their decision: the request is ambiguous in a way that changes the work, or a choice is theirs to make. |
| `cronjob` | `cronjob` | never | Schedule a task for later. |
| `delegate_task` | `delegation` | never | Run one or more subagents, each on a focused task, and get back only their final reports. |
| `patch` | `file` | path | Replace text in a file, or apply a multi-file V4A patch. |
| `read_file` | `file` | path | Read a text file with line numbers (`LINE\|content`). |
| `search_files` | `file` | safe | Search the project. |
| `write_file` | `file` | path | Create a file or replace its whole content. |
| `memory` | `memory` | never | Save durable facts to persistent memory. |
| `send_message` | `messaging` | never | Send a message to a chat on a connected platform, for example to tell the user something later on Telegram while working elsewhere. |
| `session_search` | `session_search` | safe | Search past conversations (all sessions, including parts that were summarised away) by keyword. |
| `skill_manage` | `skills` | never | Create and maintain skills: your procedural memory. |
| `skill_view` | `skills` | safe | Load a skill's full instructions. |
| `skills_list` | `skills` | safe | List available skills with their descriptions. |
| `execute_code` | `terminal` | never | Run a short Python program and get back its stdout, stderr and exit code. |
| `process` | `terminal` | never | Manage background processes started with terminal(background=true). |
| `terminal` | `terminal` | never | Run a shell command. |
| `todo` | `todo` | never | Read or update your task list for the current session. |
| `image_generate` | `vision` | never | Create an image from a text description (and optionally edit an existing one) and save it to a file. |
| `vision_analyze` | `vision` | safe | Look at an image file and return a description written by a helper model that can see. |
| `web_fetch` | `web` | safe | Fetch a URL and return its text content (HTML is converted to plain text with links kept as `text (url)`). |
| `web_search` | `web` | safe | Search the web for a query and return results: title, URL, and a short snippet for each. |

## Toolset

| Toolset | Deskripsi | Berisi (setelah `includes` diurai) |
| --- | --- | --- |
| `terminal` | Run shell commands, Python snippets and background processes | `terminal`, `process`, `execute_code` |
| `file` | Read, write, patch and search files | `read_file`, `write_file`, `patch`, `search_files` |
| `web` | Search and fetch web pages as text | `web_fetch`, `web_search` |
| `vision` | Look at images through a helper model | `vision_analyze`, `image_generate` |
| `todo` | Task list for multi-step work | `todo` |
| `memory` | Persistent notes across sessions | `memory` |
| `skills` | List, read and maintain skills | `skills_list`, `skill_view`, `skill_manage` |
| `session_search` | Search past conversations | `session_search` |
| `clarify` | Ask the user a question | `clarify` |
| `delegation` | Spawn subagents with isolated context | `delegate_task` |
| `cronjob` | Schedule recurring or one-off agent tasks | `cronjob` |
| `messaging` | Send messages to connected chat platforms | `send_message` |
| `clite-cli` | Everything, for the interactive terminal | `terminal`, `process`, `execute_code`, `read_file`, `write_file`, `patch`, `search_files`, `web_fetch`, `web_search`, `vision_analyze`, `image_generate`, `todo`, `memory`, `skills_list`, `skill_view`, `skill_manage`, `session_search`, `clarify`, `delegate_task`, `cronjob`, `send_message` |
| `clite-gateway` | Messaging platforms | `terminal`, `process`, `execute_code`, `read_file`, `write_file`, `patch`, `search_files`, `web_fetch`, `web_search`, `vision_analyze`, `image_generate`, `todo`, `memory`, `skills_list`, `skill_view`, `skill_manage`, `session_search`, `clarify`, `delegate_task`, `cronjob`, `send_message` |
| `clite-cron` | Scheduled runs | `terminal`, `process`, `execute_code`, `read_file`, `write_file`, `patch`, `search_files`, `web_fetch`, `web_search`, `vision_analyze`, `image_generate`, `todo`, `memory`, `skills_list`, `skill_view`, `skill_manage`, `session_search`, `delegate_task` |
| `clite-subagent` | Delegated workers | `terminal`, `process`, `execute_code`, `read_file`, `write_file`, `patch`, `search_files`, `web_fetch`, `web_search`, `todo`, `skills_list`, `skill_view`, `skill_manage`, `session_search` |

## Slash command

| Perintah | Alias | Kategori | Argumen | Saat sibuk | Hanya CLI | Deskripsi |
| --- | --- | --- | --- | --- | --- | --- |
| `/new` | `/reset` | Session |  | queue |  | Start a fresh session |
| `/image` | `/attach` | Session | `<path>` | queue |  | Attach an image file to your next message |
| `/retry` |  | Session |  | queue |  | Remove the last exchange and send your last message again |
| `/undo` |  | Session |  | queue |  | Remove the last exchange |
| `/history` |  | Session | `[count]` | queue |  | Show the conversation so far |
| `/title` |  | Session | `[title]` | queue |  | Show or set the session title |
| `/sessions` |  | Session | `[count]` | queue |  | List recent sessions |
| `/resume` |  | Session | `<id \| title>` | queue |  | Switch to an earlier session |
| `/branch` |  | Session | `[title]` | queue |  | Copy this conversation into a new session |
| `/queue` |  | Session | `<text>` | allow |  | Queue a message to run after the running turn |
| `/background` | `/bg` | Session | `<text>` | allow |  | Run one turn in a separate session and report the result |
| `/export` |  | Session | `[path]` | queue |  | Save the transcript as Markdown or JSON |
| `/pin` |  | Session |  | queue |  | Mark this session so it is never pruned |
| `/archive` |  | Session |  | queue |  | Hide this session from the session list |
| `/compress` |  | Session | `[focus]` | queue |  | Summarise older turns to free context |
| `/rollback` |  | Session | `[turns]` | queue |  | Undo the files the agent changed in the last turn(s) |
| `/checkpoints` |  | Session |  | queue |  | List the file checkpoints kept for this session |
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
| `/verbose` |  | Configuration | `[off\|new\|all\|verbose]` | queue |  | Set how much tool progress is shown |
| `/skin` |  | Configuration | `[name]` | queue | ya | Show or change the display skin/theme |
| `/skills` |  | Tools & Skills | `[filter]` | queue |  | List skills |
| `/plugins` |  | Tools & Skills |  | queue |  | List plugins and their status |
| `/hooks` |  | Tools & Skills |  | queue |  | List shell hooks and which await approval |
| `/mcp` |  | Tools & Skills | `[name]` | queue |  | Show the status of the MCP servers |
| `/memory` |  | Tools & Skills |  | queue |  | Show what is in persistent memory |
| `/cron` |  | Tools & Skills |  | queue |  | List scheduled jobs |
| `/help` | `/?` | Info |  | allow |  | List commands |
| `/status` |  | Info |  | allow |  | Show model, session and context usage |
| `/context` |  | Info |  | queue |  | Break down the context window: prompt tiers, tools, history |
| `/usage` |  | Info |  | allow |  | Show token usage for this session |
| `/tasks` |  | Info |  | queue |  | Show this session's todo list |
| `/logs` |  | Info | `[count]` | queue | ya | Show the last lines of the agent log |
| `/copy` |  | Info |  | queue | ya | Copy the last answer to the clipboard |
| `/insights` |  | Info | `[days]` | queue |  | Show usage insights, tokens and costs |
| `/sethome` |  | Gateway |  | queue |  | Set this chat as the platform's home channel |
| `/debug` |  | Info |  | queue |  | Show prompt and context internals |

## Perintah CLI

| Perintah | Fungsi | Sub-perintah |
| --- | --- | --- |
| `clite chat` | talk to the agent (default command) |  |
| `clite setup` | choose a provider, store its API key and pick a model |  |
| `clite model` | show, list or set the model | `show`, `list`, `set`, `providers` |
| `clite config` | show or change settings | `show`, `get`, `set`, `unset`, `path`, `env`, `edit`, `migrate` |
| `clite tools` | list, enable or disable toolsets | `list`, `enable`, `disable` |
| `clite skills` | list, search, install and curate skills | `list`, `search`, `info`, `view`, `install`, `update`, `tap`, `remove`, `curate` |
| `clite plugins` | list, enable, disable, install or remove plugins | `list`, `enable`, `disable`, `install`, `remove`, `search`, `info`, `update` |
| `clite hooks` | review, approve or test shell hooks from config.yaml | `list`, `approve`, `revoke`, `test` |
| `clite mcp` | add, list, remove and test MCP servers | `list`, `add`, `remove`, `test` |
| `clite sessions` | list, show, search, export or delete sessions | `list`, `show`, `rename`, `delete`, `export`, `search`, `prune` |
| `clite batch` | run many prompts unattended | `run` |
| `clite profile` | manage profiles (separate homes) | `list`, `show`, `create`, `use`, `delete` |
| `clite cron` | schedule agent tasks | `list`, `add`, `pause`, `resume`, `run`, `remove`, `tick`, `daemon` |
| `clite gateway` | run the messaging gateway | `run`, `status`, `pair` |
| `clite serve` | run the headless backend (for the desktop app or a remote client) |  |
| `clite dashboard` | run the backend and open the web dashboard |  |
| `clite tui` | start the terminal UI (needs Node.js) |  |
| `clite completion` | print a shell completion script for bash, zsh or fish |  |
| `clite update` | check for updates and upgrade c-lite |  |
| `clite backup` | archive or restore the agent's home directory | `create`, `restore` |
| `clite uninstall` | uninstall c-lite and optionally purge data |  |
| `clite version` | print version information |  |
| `clite status` | show what is configured |  |
| `clite doctor` | check the installation |  |
| `clite logs` | show the agent log |  |
| `clite memory` | show persistent memory |  |
| `clite acp` | Agent Client Protocol server for editors (Zed and others), on stdio |  |
| `clite insights` | show usage analytics, tokens and costs |  |

## Protokol JSON-RPC (versi 1)

### Method

| Method | Parameter | Hasil | Keterangan |
| --- | --- | --- | --- |
| `ping` | (kosong) | `pong?`, `version?` | Liveness check. |
| `system.info` | (kosong) | `version`, `protocol_version`, `home`, `profile`, `configured`, `model?`, `provider?` | Version, active profile and whether a model is configured. |
| `session.create` | `cwd?`, `model?`, `provider?`, `toolsets?`, `yolo?`, `resume?`, `platform?` | `session_id`, `stored_session_id`, `title?`, `platform?`, `model?`, `provider?`, `cwd?`, `busy?`, `yolo?`, `message_count?`, `tools?`, `toolsets?`, `reasoning_effort?`, `context?` | Open a runtime session (new, or resuming a stored one). |
| `session.info` | `session_id` | `session_id`, `stored_session_id`, `title?`, `platform?`, `model?`, `provider?`, `cwd?`, `busy?`, `yolo?`, `message_count?`, `tools?`, `toolsets?`, `reasoning_effort?`, `context?` |  |
| `session.list` | `limit?`, `source?`, `include_archived?` | `sessions` | Stored sessions, most recent first. |
| `session.history` | `session_id` | `messages` | The transcript, in display form. |
| `session.close` | `session_id` | `ok?` |  |
| `session.interrupt` | `session_id` | `ok?` | Stop the running turn. |
| `session.steer` | `session_id`, `text` | `ok?` | Guide the running turn without stopping it. |
| `session.title` | `session_id`, `title?` | `title?` | Read the title, or set it when `title` is given. |
| `session.delete` | `stored_session_id` | `ok?` |  |
| `session.rename` | `stored_session_id`, `title` | `title?` | Set the title of a stored session, open or not. |
| `session.search` | `query`, `limit?` | `hits` | Full-text search across stored sessions. |
| `session.pin` | `stored_session_id`, `pinned` | `ok?` | Pin or unpin a stored session. |
| `session.archive` | `stored_session_id`, `archived` | `ok?` | Archive or restore a stored session. |
| `session.export` | `stored_session_id`, `format?` | `filename`, `content`, `count?` | A stored session as JSON text, for the client to save. |
| `session.compress` | `session_id`, `focus?` | `compressed`, `message_count` |  |
| `session.usage` | `session_id` | `usage`, `context` |  |
| `prompt.submit` | `session_id`, `text`, `busy_mode?`, `attachments?` | `accepted`, `turn_id?`, `queued?` | Start a turn. Returns at once; the answer arrives as events ending with turn.complete. |
| `slash.exec` | `session_id`, `command` | `text?`, `action?`, `turn_id?`, `data?` | Run a slash command. |
| `commands.catalog` | `session_id?` | `commands` | Every command available now, for help and autocomplete. |
| `complete.slash` | `prefix`, `session_id?` | `items` | Commands starting with a prefix. |
| `config.get` | `key?` | `value?` | One value by dotted key, or the whole effective config. |
| `config.list` | (kosong) | `entries` | Every known setting with its value and default. |
| `config.set` | `key`, `value?`, `confirm?` | `ok?` | Write one setting; a security-relevant key needs `confirm`. |
| `model.list` | `provider?`, `refresh?` | `provider`, `models`, `current?` |  |
| `model.set` | `session_id`, `model`, `persist?` | `success`, `message`, `model?`, `provider?` | Switch the session's model; `persist` saves it as the default. |
| `providers.list` | (kosong) | `providers`, `current?` |  |
| `setup.apply` | `provider`, `api_key?`, `model?`, `base_url?` | `provider`, `model` | Store a provider choice (and its API key) from a setup screen. |
| `tools.list` | `session_id?` | `toolsets` |  |
| `skills.list` | (kosong) | `skills` |  |
| `skills.view` | `name`, `file_path?` | `name`, `content`, `linked_files?` |  |
| `plugins.list` | (kosong) | `plugins` |  |
| `plugins.set_enabled` | `name`, `enabled` | `plugins` |  |
| `credentials.list` | (kosong) | `credentials` | Known credential names and whether they are set. |
| `credentials.set` | `name`, `value` | `credentials` | Store one credential in .env; the value is never read back. |
| `credentials.delete` | `name` | `credentials` | Remove one stored credential. |
| `memory.get` | (kosong) | `memory?`, `user?`, `memory_limit?`, `user_limit?`, `provider?` |  |
| `cron.list` | (kosong) | `jobs` |  |
| `cron.create` | `prompt`, `schedule`, `name?`, `deliver?`, `repeat?` | `id`, `name?`, `prompt?`, `schedule_display?`, `enabled?`, `deliver?`, `next_run_at?`, `last_run_at?`, `last_status?`, `last_error?`, `run_count?` |  |
| `cron.action` | `job_id`, `action` | `jobs` |  |
| `cron.output` | `job_id`, `max_chars?` | `job_id`, `content?`, `path?`, `truncated?` | The last run's saved output, redacted and capped. |

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
| `tool.complete` | `call_id`, `name`, `duration`, `failed?`, `result_preview?`, `diff?` |
| `status.update` | `kind`, `text` |
| `subagent.update` | `event`, `index?`, `goal?`, `tool?`, `status?`, `args?`, `iteration?`, `model?`, `spawn_id?` |
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
| `on_compaction` |  |  |
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
| `pre_memory_write` |  | ya |
| `pre_tool_call` | ya | ya |
| `subagent_result` | ya |  |
| `subagent_start` | ya |  |
| `subagent_stop` | ya |  |
| `transform_llm_output` |  |  |
| `transform_terminal_output` |  |  |
| `transform_tool_result` |  |  |

## Provider bawaan

| Provider | Alias | `api_mode` | Variabel kunci | Base URL | Model default |
| --- | --- | --- | --- | --- | --- |
| `anthropic` | `claude` | `anthropic_messages` | `ANTHROPIC_API_KEY` | https://api.anthropic.com |  |
| `azure` |  | `chat_completions` | `AZURE_OPENAI_API_KEY` |  |  |
| `bedrock` |  | `chat_completions` | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` |  |  |
| `custom` |  | `chat_completions` | `CUSTOM_API_KEY` |  |  |
| `deepseek` |  | `chat_completions` | `DEEPSEEK_API_KEY` | https://api.deepseek.com/v1 |  |
| `fireworks` |  | `chat_completions` | `FIREWORKS_API_KEY` | https://api.fireworks.ai/inference/v1 |  |
| `gemini` | `google` | `chat_completions` | `GEMINI_API_KEY`, `GOOGLE_API_KEY` | https://generativelanguage.googleapis.com/v1beta/openai |  |
| `groq` |  | `chat_completions` | `GROQ_API_KEY` | https://api.groq.com/openai/v1 |  |
| `lmstudio` |  | `chat_completions` |  | http://localhost:1234/v1 |  |
| `mistral` |  | `chat_completions` | `MISTRAL_API_KEY` | https://api.mistral.ai/v1 |  |
| `mock` |  | `mock` |  |  | mock-1 |
| `moonshot` |  | `chat_completions` | `MOONSHOT_API_KEY` | https://api.moonshot.ai/v1 |  |
| `nvidia` |  | `chat_completions` | `NVIDIA_API_KEY` | https://integrate.api.nvidia.com/v1 |  |
| `ollama` |  | `chat_completions` |  | http://localhost:11434/v1 |  |
| `openai` |  | `chat_completions` | `OPENAI_API_KEY` | https://api.openai.com/v1 |  |
| `openrouter` |  | `chat_completions` | `OPENROUTER_API_KEY` | https://openrouter.ai/api/v1 |  |
| `together` |  | `chat_completions` | `TOGETHER_API_KEY` | https://api.together.ai/v1 |  |
| `vertex` |  | `chat_completions` | `GOOGLE_SERVICE_ACCOUNT_JSON` |  |  |
| `vllm` |  | `chat_completions` |  | http://localhost:8000/v1 |  |
| `xai` |  | `chat_completions` | `XAI_API_KEY` | https://api.x.ai/v1 |  |
| `zai` |  | `chat_completions` | `ZAI_API_KEY` | https://api.z.ai/api/paas/v4 |  |

## Platform gateway

| Platform |
| --- |
| `discord` |
| `local` |
| `slack` |
| `telegram` |

## Plugin bawaan

| Plugin | Jenis | Deskripsi |
| --- | --- | --- |
| `audit-log` | standalone | Record every tool call to logs/tool-audit.jsonl and show recent ones with /audit |
| `context-sliding-window` | backend | Sliding-window context engine: drop the middle, keep a protected head and tail (no summariser call) |
| `image-gen-openai` | backend | Image generation via the OpenAI Images API (requires OPENAI_API_KEY) |
| `memory-sqlite` | backend | Long-term memory in SQLite: facts saved with a tool, found again with FTS5 search in later sessions |
| `web-search-ddg` | backend | Web search via the DuckDuckGo HTML endpoint (no API key required) |
| `web-search-tavily` | backend | Web search via the Tavily API (requires TAVILY_API_KEY) |

## Skill bawaan

| Skill | Kategori | Deskripsi |
| --- | --- | --- |
| `skill-authoring` | meta | Write or improve a skill (SKILL.md). Use when saving a reusable procedure with skill_manage, or when a skill turned out wrong or incomplete. |
| `plan-before-acting` | productivity | Break a large or ambiguous task into verifiable steps before starting. Use when a request spans several files or systems, or when the first step is not obvious. |
| `systematic-debugging` | software-development | Find the root cause of a bug before changing code. Use for any failing test, crash, or behaviour that does not match what the code appears to say. |
| `test-driven-development` | software-development | Implement a feature or fix by writing a failing test first. Use when adding behaviour to tested code or when a bug needs a regression test. |
| `working-without-web-search` | web | How to find information when the web_search tool is not available. Use when web_search is not offered and the user asks something that needs current information. |

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
| `model.vision` | `null` |
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
| `terminal.docker.image` | `""` |
| `terminal.docker.mounts` | `[]` |
| `terminal.docker.network` | `"none"` |
| `terminal.docker.user` | `""` |
| `terminal.docker.memory` | `""` |
| `terminal.docker.keep_container` | `false` |
| `terminal.ssh.host` | `""` |
| `terminal.ssh.port` | `""` |
| `terminal.ssh.key` | `""` |
| `terminal.ssh.known_hosts` | `""` |
| `terminal.ssh.cwd` | `""` |
| `tool_output.max_chars` | `50000` |
| `tool_output.max_lines` | `2000` |
| `tool_result_max_chars` | `100000` |
| `file_read_max_chars` | `100000` |
| `web.allow_private_urls` | `false` |
| `web.timeout` | `30` |
| `web.search.provider` | `""` |
| `image.provider` | `""` |
| `attachments.max_bytes` | `5000000` |
| `attachments.max_images` | `8` |
| `attachments.max_edge` | `1568` |
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
| `auxiliary.plugin.provider` | `"main"` |
| `auxiliary.plugin.model` | `""` |
| `auxiliary.vision.provider` | `"main"` |
| `auxiliary.vision.model` | `""` |
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
| `skills.hub.index` | `""` |
| `background_review.enabled` | `true` |
| `background_review.min_tool_calls` | `8` |
| `background_review.min_interval_seconds` | `900` |
| `background_review.max_turns` | `3` |
| `background_review.timeout_seconds` | `120` |
| `curator.enabled` | `true` |
| `curator.interval_hours` | `168` |
| `curator.stale_days` | `30` |
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
| `plugins.llm.max_tokens` | `1024` |
| `plugins.hub.index` | `""` |
| `hooks` | `{}` |
| `mcp_servers` | `{}` |
| `quick_commands` | `{}` |
| `platform_hints` | `{}` |
| `gateway.platforms` | `{}` |
| `gateway.allow_all_users` | `false` |
| `gateway.group_sessions_per_user` | `true` |
| `gateway.agent_cache_ttl_seconds` | `3600` |
| `gateway.session_reset.mode` | `"none"` |
| `gateway.session_reset.idle_minutes` | `120` |
| `gateway.session_reset.daily_hour` | `4` |
| `gateway.home_channels` | `{}` |
| `gateway.send_targets` | `[]` |
| `cron.enabled` | `true` |
| `cron.catch_up_missed` | `true` |
| `cron.inactivity_timeout_seconds` | `600` |
| `server.host` | `"127.0.0.1"` |
| `server.port` | `0` |
| `sessions.auto_prune` | `false` |
| `sessions.retention_days` | `90` |
| `checkpoints.max_bytes` | `100000000` |
| `logging.level` | `"INFO"` |
| `logging.max_size_mb` | `5` |
| `logging.backup_count` | `3` |
| `timezone` | `""` |
| `_config_version` | `1` |
