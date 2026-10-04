<!-- Dibuat oleh scripts/gen_docs.py. Jangan disunting dengan tangan: ubah kodenya, lalu jalankan skrip itu. -->

# Peta modul

Setiap modul Python di `src/clite`: isinya (baris pertama docstring modul) dan simbol publik
yang didefinisikannya. Gunakan halaman ini untuk menemukan tempat sebuah perubahan, lalu baca
`AGENTS.md` di direktori itu sebelum mengubah apa pun.

## `clite/`

| File | Isi | Simbol publik |
| --- | --- | --- |
| `__init__.py` | C-lite: one agent core served through a CLI, a TUI, a desktop app and a messaging gateway. |  |
| `__main__.py` | ``python -m clite`` runs the CLI. |  |

## `clite/acp/`

| File | Isi | Simbol publik |
| --- | --- | --- |
| `__init__.py` | Agent Client Protocol server: lets an editor (Zed and others) drive the agent over stdio. |  |

## `clite/agent/`

| File | Isi | Simbol publik |
| --- | --- | --- |
| `__init__.py` | The agent: one conversation loop shared by every surface. |  |
| `agent.py` | ``AIAgent``: one conversation, usable from any surface. | `AIAgent` |
| `budget.py` | Iteration budget: how many model calls one turn may make. | `IterationBudget` |
| `callbacks.py` | ``AgentCallbacks``: how a surface observes and answers the agent. | `AgentCallbacks` |
| `delegation.py` | Delegation: run subagents with their own context and return only their reports. | `delegate()` |
| `loop.py` | The turn loop: a short driver over phase functions. | `run_turn()` |
| `messages.py` | Message hygiene: keep the transcript in a shape every provider accepts. | `content_text()`, `append_to_content()`, `sanitize_for_api()`, `parse_tool_arguments()` |
| `state.py` | Per-turn state and the verdicts phases return. | `Verdict`, `TurnState`, `TurnResult` |
| `title.py` | Session titles: a short label generated after the first exchange. | `fallback_title()`, `clean_title()`, `generate_title()`, `generate_title_async()` |
| `todo.py` | In-session task list, owned by the agent and edited through the ``todo`` tool. | `TodoStore` |
| `tool_executor.py` | Run one round of tool calls and return the tool messages, in the model's order. | `can_run_in_parallel()`, `run_tool_round()` |

## `clite/agent/context/`

| File | Isi | Simbol publik |
| --- | --- | --- |
| `__init__.py` |  |  |
| `compressor.py` | The default context engine: summarise the middle, keep the ends. | `serialize_for_summary()`, `prune_tool_outputs()`, `repair_tool_pairs()`, `ContextCompressor` |
| `engine.py` | ``ContextEngine``: the strategy that keeps a conversation inside the model's window. | `ContextEngine`, `register_context_engine()`, `create_context_engine()` |
| `tokens.py` | Rough token estimates. | `estimate_text_tokens()`, `estimate_message_tokens()`, `estimate_messages_tokens()` |

## `clite/agent/memory/`

| File | Isi | Simbol publik |
| --- | --- | --- |
| `__init__.py` | Memory: the built-in bounded store plus an optional external provider. |  |
| `manager.py` | ``MemoryManager``: the one object the agent talks to about memory. | `register_memory_provider()`, `memory_provider_names()`, `wrap_memory_context()`, `strip_memory_context()`, `MemoryManager` |
| `provider.py` | ``MemoryProvider``: the interface for an external memory backend (a plugin). | `MemoryProvider` |
| `store.py` | Built-in memory: two small files the agent curates itself. | `MemoryStore` |

## `clite/agent/prompt/`

| File | Isi | Simbol publik |
| --- | --- | --- |
| `__init__.py` |  |  |
| `builder.py` | System prompt assembly. | `PromptInputs`, `build_prompt_tiers()`, `build_system_prompt()` |
| `caching.py` | Prompt-cache breakpoints for providers that take explicit ``cache_control`` markers. | `cache_marker()`, `apply_cache_markers()` |
| `context_files.py` | Context files: SOUL.md (identity) and project instructions. | `truncate_middle()`, `load_soul()`, `load_project_context()` |
| `identity.py` | Static prompt text: the default identity and the guidance blocks. |  |

## `clite/agent/turn/`

| File | Isi | Simbol publik |
| --- | --- | --- |
| `__init__.py` |  |  |
| `context.py` | Phase: set the turn up. | `build_turn_context()` |
| `finalize.py` | Phase: close the turn. | `close_open_tool_calls()`, `finalize_turn()` |
| `iteration.py` | Phases that open each iteration: interrupt and budget checks, then pre-flight compression. | `begin_iteration()`, `prepare_iteration()` |
| `request.py` | Phase: call the model, with the whole recovery ladder around it. | `assemble_api_messages()`, `call_model()` |
| `response.py` | Phases after the model answered: validate the response, then act on it. | `normalize_response()`, `dispatch_response()` |

## `clite/cli/`

| File | Isi | Simbol publik |
| --- | --- | --- |
| `__init__.py` | The command-line surface: ``clite <subcommand>`` and the classic interactive REPL. |  |
| `display.py` | Terminal output for the classic CLI: colours, tool progress lines, the banner. | `load_skin()`, `Display` |
| `main.py` | ``clite``: the command-line entry point. | `build_parser()`, `main()` |
| `repl.py` | The classic interactive CLI: a read-eval-print loop over a ``ChatSession``. | `Repl`, `run_single_query()` |

## `clite/cli/subcommands/`

| File | Isi | Simbol publik |
| --- | --- | --- |
| `__init__.py` | One module per subcommand group. |  |
| `chat.py` | ``clite chat``: the interactive REPL, or one query with ``-q``. | `add_chat_arguments()`, `session_options()`, `wants_tui()`, `run_chat()`, `register()` |
| `config.py` | ``clite config``: read and write config.yaml. | `run_show()`, `run_get()`, `run_set()`, `run_unset()`, `run_path()`, `run_env()`, `run_edit()`, `run_migrate()`, `register()` |
| `cron.py` | ``clite cron``: scheduled agent tasks. | `run_list()`, `run_add()`, `run_tick()`, `run_daemon()`, `register()` |
| `gateway.py` | ``clite gateway``: run the messaging gateway and manage who may talk to it. | `run_gateway()`, `run_status()`, `run_pair_list()`, `run_pair_approve()`, `run_pair_revoke()`, `register()` |
| `hooks.py` | ``clite hooks``: review, approve, revoke and try the shell hooks from ``config.yaml``. | `run_list()`, `run_approve()`, `run_revoke()`, `run_test()`, `register()` |
| `misc.py` | Small commands: version, status, doctor, logs, memory, acp. | `run_version()`, `run_status()`, `run_doctor()`, `run_logs()`, `run_memory()`, `run_acp()`, `register()` |
| `model.py` | ``clite model``: show, list and choose models. | `run_show()`, `run_list()`, `run_set()`, `run_providers()`, `register()` |
| `plugins.py` | ``clite plugins``: list, enable, disable, install, remove. | `run_list()`, `run_install()`, `run_remove()`, `register()` |
| `profile.py` | ``clite profile``: separate homes with their own config, keys, memory and sessions. | `run_list()`, `run_show()`, `run_create()`, `run_use()`, `run_delete()`, `register()` |
| `serve.py` | ``clite serve`` and ``clite dashboard``: the HTTP + WebSocket backend. | `run_serve()`, `register()` |
| `sessions.py` | ``clite sessions``: browse, search, export and prune stored conversations. | `run_list()`, `run_show()`, `run_rename()`, `run_delete()`, `run_export()`, `run_search()`, `run_prune()`, `register()` |
| `setup.py` | ``clite setup``: choose a provider, store its key, pick a model. | `run_setup()`, `register()` |
| `skills.py` | ``clite skills``: browse, install and curate skills. | `run_list()`, `run_view()`, `run_install()`, `run_remove()`, `run_curate()`, `register()` |
| `tools.py` | ``clite tools``: see and switch toolsets. | `run_list()`, `register()` |
| `tui.py` | ``clite tui``: the Node terminal interface, which talks to this package over JSON-RPC. | `find_tui_bundle()`, `tui_arguments()`, `launch_tui()`, `run_tui()`, `register()` |

## `clite/core/`

| File | Isi | Simbol publik |
| --- | --- | --- |
| `__init__.py` | Leaf layer: brand, home resolution, config, secrets, logging, profiles. |  |
| `brand.py` | Every product-name string in one place. |  |
| `config.py` | Configuration: ``config.yaml`` holds settings, ``.env`` holds secrets. | `deep_merge()`, `get_path()`, `load_user_config_raw()`, `load_config()`, `config_get()`, `reset_config_cache()`, `atomic_config_update()`, `config_set()`, `config_unset()`, `migrate_config_file()`, … (+1) |
| `config_defaults.py` | ``DEFAULT_CONFIG``: every setting, its default, and the reason for that default. |  |
| `constants.py` | Profile-aware home resolution. | `set_home_override()`, `reset_home_override()`, `get_home_override()`, `home_scope()`, `get_default_root()`, `get_process_home()`, `get_home()`, `home_key()`, `display_home()`, `ensure_dir()`, … (+13) |
| `env.py` | Secrets: ``<home>/.env`` and nothing else. | `SecretSpec`, `register_secret()`, `read_env_file()`, `load_env()`, `loaded_secret_names()`, `secret_scope()`, `get_secret()`, `save_secret()`, `remove_secret()`, `mask_secret()` |
| `errors.py` | Exception types shared across packages. | `CliteError`, `ConfigError`, `AuthError`, `ProviderError`, `ProfileError` |
| `io.py` | Atomic file writes. | `atomic_write_text()`, `atomic_write_json()`, `read_json()` |
| `logging.py` | File logging under ``<home>/logs``: ``agent.log`` (INFO+) and ``errors.log`` (WARNING+). | `setup_logging()`, `reset_logging()` |
| `profiles.py` | Profiles: fully separate homes under ``<default root>/profiles/<name>``. | `ProfileInfo`, `validate_profile_name()`, `get_sticky_profile()`, `get_active_profile_name()`, `list_profiles()`, `profile_exists()`, `create_profile()`, `delete_profile()`, `set_sticky_profile()`, `apply_profile_override()` |
| `redact.py` | Redaction: keep credentials out of transcripts and logs. | `redact()` |
| `threats.py` | Scan text that will be injected into the system prompt. | `Threat`, `scan_text()`, `describe()` |

## `clite/cron/`

| File | Isi | Simbol publik |
| --- | --- | --- |
| `__init__.py` | Scheduled jobs: agent tasks that run on a schedule in fresh sessions. |  |
| `jobs.py` | Scheduled jobs: storage and state transitions. | `JobError`, `JobStore`, `get_job_store()`, `reset_job_stores()` |
| `schedule.py` | Schedules: parsing what the user wrote and computing the next run time. | `ScheduleError`, `Schedule`, `get_timezone()`, `parse_duration()`, `CronExpression`, `parse_schedule()`, `next_run()` |
| `scheduler.py` | Running scheduled jobs. | `build_job_prompt()`, `run_job()`, `tick()`, `Scheduler` |

## `clite/gateway/`

| File | Isi | Simbol publik |
| --- | --- | --- |
| `__init__.py` | The messaging gateway: one long-running process serving every configured chat platform. |  |
| `event.py` | What a platform adapter hands to the gateway, and what it gets back. | `SessionSource`, `MessageEvent`, `SendResult` |
| `pairing.py` | DM pairing: how an unknown user gets access without the owner editing config. | `PairingStore` |
| `runner.py` | ``GatewayRunner``: the policy layer between chat platforms and the agent. | `GatewaySession`, `GatewayRunner` |
| `session.py` | Session keys: which conversation a message belongs to. | `build_session_key()`, `SessionMap` |

## `clite/gateway/platforms/`

| File | Isi | Simbol publik |
| --- | --- | --- |
| `__init__.py` | Platform adapters. |  |
| `base.py` | ``BasePlatformAdapter``: the three things a chat platform must do. | `BasePlatformAdapter`, `register_platform()`, `split_message()` |
| `local.py` | An in-process platform: messages go in through ``inject`` and replies land in ``outbox``. | `LocalAdapter` |
| `telegram.py` | Telegram, over the Bot API with long polling. | `TelegramAdapter` |

## `clite/plugins/`

| File | Isi | Simbol publik |
| --- | --- | --- |
| `__init__.py` | Plugin system: discovery, loading, and the hook bus. |  |
| `context.py` | ``PluginContext``: the API a plugin's ``register(ctx)`` receives. | `PluginCommand`, `PluginCliCommand`, `Registration`, `PluginContext` |
| `hooks.py` | Lifecycle hooks: the bus core fires and plugins subscribe to. | `HookRegistration`, `HookBus`, `get_hook_bus()`, `reset_hook_buses()`, `invoke_hook()`, `has_hook()`, `first_result()` |
| `manager.py` | Plugin discovery and loading (and, with them, the shell hooks from ``config.yaml``). | `PluginInfo`, `PluginManager`, `get_plugin_manager()`, `ensure_plugins_loaded()`, `reset_plugin_managers()`, `set_plugin_enabled()`, `install_plugin()`, `remove_plugin()` |
| `manifest.py` | ``plugin.yaml``: what a plugin says about itself before any of its code runs. | `ManifestError`, `PluginManifest`, `parse_manifest()`, `load_manifest()` |
| `shell_hooks.py` | Shell hooks: run your own commands on lifecycle events, configured in ``config.yaml``. | `ShellHook`, `HookRun`, `configured_hooks()`, `allowlist_path()`, `is_approved()`, `approve_hooks()`, `revoke_hooks()`, `build_payload()`, `run_hook()`, `evaluate()`, … (+1) |

## `clite/providers/`

| File | Isi | Simbol publik |
| --- | --- | --- |
| `__init__.py` |  |  |
| `auxiliary.py` | Auxiliary model calls: summaries, titles and other side tasks. | `resolve_auxiliary_route()`, `call_auxiliary()` |
| `base.py` | ``ProviderProfile``: everything about one inference provider, declared in one place. | `ProviderProfile` |
| `client.py` | ``LLMClient``: one model call, in any protocol, streamed or not. | `ModelClient`, `LLMClient` |
| `credentials.py` | Credential pool: several keys for one provider, rotated when one is exhausted. | `Credential`, `CredentialPool`, `get_credential_pool()`, `reset_credential_pools()` |
| `errors.py` | API error classification: one place decides what a failure means and what to try next. | `FailoverReason`, `ClassifiedError`, `classify_api_error()` |
| `http.py` | The HTTP seam for model calls: standard library only, cancellable, proxy-aware. | `ProviderHTTPError`, `Cancelled`, `CancelHandle`, `SSEEvent`, `HttpClient`, `parse_sse()` |
| `model_switch.py` | Model switching: one pipeline for ``/model`` in the CLI, the TUI, the desktop app and the gateway. | `ModelSwitchResult`, `parse_model_input()`, `switch_model()` |
| `models.py` | Model catalog: which models a provider offers, and how large their context windows are. | `ModelInfo`, `fetch_models()`, `list_models()`, `get_context_length()` |
| `registry.py` | Provider registry with lazy, layered discovery. | `register_provider()`, `list_providers()`, `get_provider()`, `reset_providers()`, `reset_user_layers()` |
| `runtime.py` | Runtime provider resolution: from "what the user asked for" to a route that can be called. | `RuntimeRoute`, `resolve_runtime_provider()`, `resolve_fallback_routes()` |
| `testing.py` | Test doubles for the model client. | `text_response()`, `tool_call_response()`, `mock_route()`, `ScriptedClient` |

## `clite/providers/transports/`

| File | Isi | Simbol publik |
| --- | --- | --- |
| `__init__.py` |  |  |
| `anthropic_messages.py` | Anthropic Messages API. | `convert_messages()`, `convert_tools()`, `parse_usage()`, `response_from_blocks()`, `AnthropicAccumulator`, `AnthropicMessagesTransport` |
| `base.py` | ``ProviderTransport``: one class per wire protocol (``api_mode``). | `StreamAccumulator`, `ProviderTransport`, `register_transport()`, `get_transport()`, `transport_modes()` |
| `chat_completions.py` | OpenAI Chat Completions: the protocol most providers speak. | `wire_messages()`, `parse_usage()`, `ChatCompletionsAccumulator`, `ChatCompletionsTransport` |
| `mock.py` | Offline provider: deterministic answers without a network or an API key. | `MockTransport` |
| `types.py` | Provider-neutral shapes the agent loop works with. | `ToolCall`, `Usage`, `NormalizedResponse`, `RequestParams`, `HttpRequest` |

## `clite/rpc/`

| File | Isi | Simbol publik |
| --- | --- | --- |
| `__init__.py` |  |  |
| `entry.py` | Stdio entry point: ``python -m clite.rpc.entry``. | `serve_stdio()`, `main()` |
| `methods.py` | RPC method handlers. | `ping()`, `system_info()`, `session_create()`, `session_info()`, `session_list()`, `session_history()`, `session_close()`, `session_interrupt()`, `session_steer()`, `session_title()`, … (+22) |
| `server.py` | The JSON-RPC server: one instance per client connection. | `RpcError`, `rpc_method()`, `RpcServer`, `reset_server_state()` |
| `session.py` | ``RpcSession``: a ``ChatSession`` whose callbacks become JSON-RPC events. | `RpcSession` |
| `transport.py` | Transports: how JSON-RPC messages leave the server. | `Transport`, `StdioTransport`, `MemoryTransport`, `WebSocketTransport` |

## `clite/rpc/contracts/`

| File | Isi | Simbol publik |
| --- | --- | --- |
| `__init__.py` |  |  |
| `base.py` | Contract registries: every JSON-RPC method, event and server request is declared once. | `Params`, `Result`, `Payload`, `Empty`, `Ok`, `MethodSpec`, `ServerRequestSpec`, `method()`, `event()`, `server_request()` |
| `schema.py` | The protocol, declared: methods (client to server), events and server requests. | `ContextStatus`, `SessionInfo`, `StoredSession`, `TranscriptMessage`, `UsageTotals`, `CommandEntry`, `PingResult`, `SystemInfoResult`, `SessionCreateParams`, `SessionRef`, … (+59) |

## `clite/runtime/`

| File | Isi | Simbol publik |
| --- | --- | --- |
| `__init__.py` | Runtime: what every surface shares on top of the agent. |  |
| `commands.py` | The slash command registry: one table every surface reads. | `CommandDef`, `resolve_command()`, `commands_for()`, `split_command()`, `command_catalog()` |
| `factory.py` | ``build_agent``: the one place a surface turns "what the user asked for" into an ``AIAgent``. | `default_toolsets()`, `build_agent()` |
| `maintenance.py` | Housekeeping a surface runs when it starts. | `reset_maintenance_state()`, `auto_prune_sessions()`, `run_startup_maintenance()` |
| `presentation.py` | Small presentation helpers shared by every surface (terminal, RPC clients, gateway). | `tool_preview()`, `result_failed()` |
| `session.py` | ``ChatSession``: one conversation as a surface sees it. | `SlashResult`, `ChatSession` |
| `setup.py` | Applying a provider choice: shared by ``clite setup`` and the setup screens of the UIs. | `apply_setup()` |
| `slash.py` | Slash command handlers. |  |

## `clite/server/`

| File | Isi | Simbol publik |
| --- | --- | --- |
| `__init__.py` | The headless backend: HTTP + WebSocket JSON-RPC for the desktop app and the dashboard. |  |
| `app.py` | The ASGI app behind ``clite serve`` and ``clite dashboard``. | `presented_token()`, `origin_allowed()`, `create_app()` |
| `run.py` | Starting the backend: bind, announce readiness, serve. | `bind_socket()`, `dashboard_url()`, `serve()` |

## `clite/skills/`

| File | Isi | Simbol publik |
| --- | --- | --- |
| `__init__.py` | Skills: on-demand knowledge documents the agent loads when a task calls for them. |  |
| `catalog.py` | Skill discovery across tiers. | `Skill`, `find_project_root()`, `register_extra_root()`, `unregister_extra_root()`, `skill_roots()`, `discover_skills()`, `get_skill()`, `linked_files()`, `read_skill_file()`, `reset_skill_cache()` |
| `commands.py` | Skills as slash commands: ``/<skill-name> [instruction]``. | `skill_slug()`, `skill_commands()`, `build_skill_message()` |
| `curator.py` | Curator: keep the agent's own skill library from growing without bound. | `archive_dir()`, `find_stale_skills()`, `archive_skill()`, `restore_skill()`, `run_curator()` |
| `frontmatter.py` | SKILL.md parsing and validation. | `SkillFormatError`, `SkillMeta`, `validate_skill_name()`, `split_frontmatter()`, `parse_skill_text()`, `parse_skill_file()`, `platform_matches()`, `render_skill()` |
| `hub.py` | Skill installation from outside sources. | `SkillBundle`, `SkillSource`, `LocalDirSource`, `GitHubSource`, `register_skill_source()`, `installed_skills()`, `install_skill()` |
| `index.py` | The skills index: the only part of the skill system that costs tokens on every request. | `visible_skills()`, `build_skills_index()` |
| `manager.py` | Skill writes: create, patch, rewrite, delete, and supporting files. | `SkillError`, `create_skill()`, `edit_skill()`, `patch_skill()`, `delete_skill()`, `write_skill_file()`, `remove_skill_file()` |
| `usage.py` | Skill usage sidecar: who created a skill and how often it is used. | `load_usage()`, `record_created()`, `record_use()` |

## `clite/state/`

| File | Isi | Simbol publik |
| --- | --- | --- |
| `__init__.py` | Session storage: one SQLite file per profile with FTS5 search. |  |
| `db.py` | ``SessionDB``: durable sessions and messages in ``<home>/state.db``. | `new_session_id()`, `get_session_db()`, `close_all_session_dbs()`, `SessionDB` |
| `schema.py` | SQLite schema for sessions and messages. |  |

## `clite/tools/`

| File | Isi | Simbol publik |
| --- | --- | --- |
| `__init__.py` | Tools: the registry, toolsets, the dispatch entry points and the built-in tools. |  |
| `approval.py` | Command approval: the gate between the model and a destructive shell command. | `DangerMatch`, `ApprovalDecision`, `reset_approval_state()`, `normalize_command()`, `detect_dangerous_command()`, `detect_hardline()`, `smart_verdict()`, `check_command()` |
| `context.py` | ``ToolContext``: what a tool handler may know about the call it is serving. | `ToolContext` |
| `dispatch.py` | The two entry points the agent loop uses: tool definitions in, tool results out. | `reset_definition_cache()`, `resolve_enabled_tools()`, `get_tool_definitions()`, `coerce_args()`, `cap_result()`, `handle_function_call()` |
| `file_safety.py` | Write guard for the file tools. | `write_denied_reason()` |
| `registry.py` | Tool registry: one process-wide table of every tool the model can call. | `ToolEntry`, `ToolRegistry`, `get_background_loop()`, `run_async()`, `tool_error()`, `tool_result()`, `discover_builtin_tools()`, `reset_check_cache()` |
| `toolsets.py` | Toolsets: named groups of tools, composable through ``includes``. | `register_toolset()`, `toolset_exists()`, `resolve_toolset()`, `resolve_toolsets()`, `all_toolsets()`, `toolset_for_tool()` |

## `clite/tools/builtin/`

| File | Isi | Simbol publik |
| --- | --- | --- |
| `__init__.py` | Built-in tools. |  |
| `clarify.py` | ``clarify``: ask the user a question and wait for the answer. | `clarify_tool()` |
| `cronjob.py` | ``cronjob``: let the agent schedule its own future work. | `cronjob_tool()` |
| `delegate.py` | ``delegate_task``: hand focused work to subagents with isolated context. | `delegate_tool()` |
| `file_tools.py` | File tools: read_file, write_file, patch, search_files. | `read_file_tool()`, `write_file_tool()`, `patch_tool()`, `search_files_tool()` |
| `memory.py` | ``memory``: persistent notes across sessions (MEMORY.md and USER.md). | `memory_tool()` |
| `process.py` | Background processes: start with ``terminal(background=true)``, manage with ``process``. | `ManagedProcess`, `ProcessRegistry`, `reset_process_registry()`, `process_tool()` |
| `session_search.py` | ``session_search``: recall past conversations from the session database. | `session_search_tool()` |
| `skills.py` | Skill tools: list, view (progressive disclosure), and manage (procedural memory). | `skills_list_tool()`, `skill_view_tool()`, `skill_manage_tool()` |
| `terminal.py` | ``terminal``: run a shell command in the session's execution environment. | `clip_lines()`, `terminal_tool()` |
| `todo.py` | ``todo``: the agent's task list for multi-step work. | `todo_tool()` |
| `web.py` | ``web_fetch``: download a page and return readable text. | `html_to_text()`, `private_address_reason()`, `web_fetch_tool()` |

## `clite/tools/environments/`

| File | Isi | Simbol publik |
| --- | --- | --- |
| `__init__.py` | Environment registry: one execution environment per task, created on first use. | `register_environment_backend()`, `environment_backends()`, `get_environment()`, `cleanup_environment()`, `cleanup_all_environments()` |
| `base.py` | Execution environments: where the ``terminal`` tool actually runs a command. | `ExecResult`, `BaseEnvironment` |
| `local.py` | Local execution: a subprocess on the host, in its own process group. | `build_child_env()`, `find_shell()`, `kill_process_tree()`, `LocalEnvironment` |

## `clite/tools/mcp/`

| File | Isi | Simbol publik |
| --- | --- | --- |
| `__init__.py` | MCP (Model Context Protocol) client: tools served by external processes. |  |
| `client.py` | A small MCP client over stdio. | `McpError`, `safe_name()`, `McpServer`, `connect_mcp_servers()`, `shutdown_mcp_servers()` |

Jumlah: 158 modul.
