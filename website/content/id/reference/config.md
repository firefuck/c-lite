# Rujukan konfigurasi

Halaman ini dibuat dari kode oleh `scripts/gen_docs.py`, jadi isinya tidak pernah tertinggal dari programnya. Jangan disunting dengan tangan: ubah kodenya, lalu jalankan skrip itu.

Nilai bawaan setiap kunci. Menghapus sebuah kunci dari berkas Anda berarti kembali ke nilai ini, bukan mematikannya.

## Kunci konfigurasi

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
| `pricing.overrides` | `{}` |
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
| `speech.transcription.provider` | `""` |
| `speech.transcription.model` | `""` |
| `speech.transcription.language` | `""` |
| `speech.speech.provider` | `""` |
| `speech.speech.model` | `""` |
| `speech.speech.voice` | `""` |
| `speech.max_seconds` | `300` |
| `speech.max_bytes` | `10000000` |
| `speech.max_chars` | `4000` |
| `speech.reply_with_voice` | `[]` |
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
| `cron.delivery_max_attempts` | `3` |
| `cron.max_concurrent_jobs` | `4` |
| `cron.max_jobs_from_tool` | `20` |
| `server.host` | `"127.0.0.1"` |
| `server.port` | `0` |
| `server.allowed_hosts` | `[]` |
| `server.max_message_bytes` | `1000000` |
| `server.rate_limit.max_failures` | `10` |
| `server.rate_limit.window_seconds` | `60` |
| `server.rate_limit.delay_seconds` | `5` |
| `server.replay_buffer_events` | `500` |
| `server.replay_sessions` | `64` |
| `server.resume_grace_seconds` | `120` |
| `server.audit_log` | `true` |
| `server.openai_api_enabled` | `false` |
| `server.webhooks_enabled` | `false` |
| `webhooks` | `{}` |
| `dashboard.notifications` | `true` |
| `sessions.auto_prune` | `false` |
| `sessions.retention_days` | `90` |
| `checkpoints.max_bytes` | `100000000` |
| `logging.level` | `"INFO"` |
| `logging.max_size_mb` | `5` |
| `logging.backup_count` | `3` |
| `timezone` | `""` |
| `_config_version` | `1` |

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
| `email` |
| `local` |
| `matrix` |
| `signal` |
| `slack` |
| `telegram` |
| `whatsapp` |
