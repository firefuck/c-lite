# Peta file: Hermes ke C-lite

Tabel padanan untuk dua pertanyaan: "fitur ini di Hermes ada di file mana?" dan "kalau saya
membawa file Hermes ini, tempatnya di C-lite di mana?".

Cara membaca:

- Kolom **Hermes** berisi path di repositori Hermes pada commit rujukan (lihat
  [README](README.md)). Semua path di kolom itu diperiksa keberadaannya oleh skrip
  [check_hermes_refs.py](../../scripts/check_hermes_refs.py).
- Kolom **C-lite** berisi path di repositori ini, diperiksa oleh
  [test_docs.py](../../tests/test_docs.py). Tanda "belum ada" berarti padanannya belum ditulis;
  kolom catatan menyebut task roadmap-nya.
- Satu file Hermes sering sepadan dengan sebagian file C-lite, dan sebaliknya. Hermes memecah
  satu tanggung jawab ke banyak file kecil; yang dicantumkan adalah file pintu masuknya.

Sebelum membawa sesuatu, baca
[cara memindahkan fitur](../arsitektur/07-beda-dengan-hermes.md#memindahkan-fitur-dari-hermes).

## Inti agent

| Hermes | C-lite | Catatan |
|---|---|---|
| `run_agent.py` | `src/clite/agent/agent.py` | `AIAgent`. Di Hermes kelas ini dirakit dari banyak mixin |
| `agent/conversation_loop.py` | `src/clite/agent/loop.py` | Loop giliran |
| `agent/turn_context.py` | `src/clite/agent/turn/context.py` | Menyiapkan giliran |
| `agent/turn_iteration_prep.py`, `agent/turn_preflight.py` | `src/clite/agent/turn/iteration.py` | Awal iterasi, kompresi pra-terbang |
| `agent/turn_request_assembly.py`, `agent/turn_api_call.py`, `agent/turn_recovery.py` | `src/clite/agent/turn/request.py` | Menyusun permintaan, memanggil model, pemulihan |
| `agent/turn_response_check.py`, `agent/turn_empty_response.py`, `agent/turn_truncation.py` | `src/clite/agent/turn/response.py` | Jawaban kosong dan terpotong |
| `agent/turn_tool_round.py`, `agent/tool_executor.py` | `src/clite/agent/tool_executor.py` | Satu ronde tool, kebijakan paralel |
| `agent/turn_finalizer.py` | `src/clite/agent/turn/finalize.py` | Menutup giliran |
| `agent/iteration_budget.py` | `src/clite/agent/budget.py` | Anggaran iterasi |
| `agent/interrupt_control.py` | `src/clite/agent/agent.py` | `interrupt()` dan `steer()` |
| `agent/message_sanitization.py`, `agent/transcript_repair.py` | `src/clite/agent/messages.py` | Membersihkan riwayat sebelum dikirim |
| `agent/title_generator.py` | `src/clite/agent/title.py` | Judul sesi |
| `agent/subagent_lifecycle.py`, `tools/delegate_tool.py` | `src/clite/agent/delegation.py`, `src/clite/tools/builtin/delegate.py` | Delegasi sinkron |
| `tools/async_delegation.py` | belum ada | F2-T13 |
| `agent/background_review.py` | belum ada | F2-T12 |
| `agent/insights.py` | belum ada | F3-T8 |
| `agent/trajectory.py`, `batch_runner.py`, `trajectory_compressor.py` | belum ada | F6-T8 |

## Prompt, konteks, memori

| Hermes | C-lite | Catatan |
|---|---|---|
| `agent/system_prompt.py` | `src/clite/agent/prompt/builder.py` | Perakitan prompt, sekali per sesi |
| `agent/prompt_builder.py` | `src/clite/agent/prompt/identity.py`, `src/clite/agent/prompt/context_files.py` | Teks panduan; `SOUL.md`, `AGENTS.md`, dan sejenisnya |
| `agent/prompt_caching.py` | `src/clite/agent/prompt/caching.py` | Penanda `cache_control` |
| `agent/context_engine.py` | `src/clite/agent/context/engine.py` | Antarmuka `ContextEngine` |
| `agent/context_compressor.py`, `agent/conversation_compression.py` | `src/clite/agent/context/compressor.py` | Kompresor bawaan. Peningkatan: F2-T11 |
| `agent/model_metadata.py` | `src/clite/agent/context/tokens.py`, `src/clite/providers/models.py` | Perkiraan token, panjang konteks |
| `agent/memory_manager.py` | `src/clite/agent/memory/manager.py` | |
| `agent/memory_provider.py` | `src/clite/agent/memory/provider.py` | Antarmuka provider memori |
| `tools/memory_tool.py` | `src/clite/agent/memory/store.py`, `src/clite/tools/builtin/memory.py` | Penyimpanan dan tool-nya |
| `plugins/memory/` | belum ada | Provider memori contoh: F6-T3 |
| `plugins/context_engine/` | belum ada | F6-T6 |

## Provider dan model

| Hermes | C-lite | Catatan |
|---|---|---|
| `providers/base.py` | `src/clite/providers/base.py` | `ProviderProfile` |
| `providers/__init__.py` | `src/clite/providers/registry.py` | Registry berlapis |
| `plugins/model-providers/` | `src/clite/bundled/plugins/model-providers/` | Hermes 38 profil, di sini 8. Tambahan: F2-T2 |
| `hermes_cli/runtime_provider.py` | `src/clite/providers/runtime.py` | Resolusi rute |
| `agent/transports/base.py`, `agent/transports/types.py` | `src/clite/providers/transports/base.py`, `src/clite/providers/transports/types.py` | |
| `agent/transports/chat_completions.py` | `src/clite/providers/transports/chat_completions.py` | |
| `agent/transports/anthropic.py`, `agent/anthropic_adapter.py`, `agent/anthropic_message_convert.py`, `agent/anthropic_thinking_replay.py` | `src/clite/providers/transports/anthropic_messages.py` | |
| `agent/transports/codex.py`, `agent/codex_responses_adapter.py` | belum ada | Responses API: F2-T1 |
| `agent/transports/bedrock.py`, `agent/bedrock_adapter.py`, `agent/vertex_adapter.py`, `agent/gemini_native_adapter.py` | belum ada | F2-T2 |
| `agent/error_classifier.py` | `src/clite/providers/errors.py` | |
| `agent/credential_pool.py` | `src/clite/providers/credentials.py` | |
| `agent/auxiliary_client.py` | `src/clite/providers/auxiliary.py` | |
| `hermes_cli/models.py`, `agent/models_dev.py` | `src/clite/providers/models.py` | Katalog model |
| `hermes_cli/model_switch.py` | `src/clite/providers/model_switch.py` | |
| `agent/reasoning_effort.py` | `src/clite/bundled/plugins/model-providers/anthropic/__init__.py` | Di sini aturan penalaran milik profil |
| `agent/usage_pricing.py`, `hermes_cli/models_pricing.py` | belum ada | F2-T3 |
| `hermes_cli/auth.py`, `hermes_cli/auth_commands.py` | belum ada | OAuth dan `clite auth`: F2-T14 |

## Tool

| Hermes | C-lite | Catatan |
|---|---|---|
| `tools/registry.py` | `src/clite/tools/registry.py` | |
| `toolsets.py` | `src/clite/tools/toolsets.py` | |
| `model_tools.py` | `src/clite/tools/dispatch.py` | `get_tool_definitions`, `handle_function_call` |
| `tools/approval.py`, `tools/approval_detection.py`, `tools/approval_smart.py` | `src/clite/tools/approval.py` | Pola di Hermes jauh lebih banyak |
| `agent/file_safety.py`, `tools/path_security.py` | `src/clite/tools/file_safety.py` | |
| `agent/redact.py` | `src/clite/core/redact.py` | |
| `tools/threat_patterns.py` | `src/clite/core/threats.py` | |
| `tools/terminal_tool.py` | `src/clite/tools/builtin/terminal.py` | |
| `tools/process_registry.py` | `src/clite/tools/builtin/process.py` | |
| `tools/env_passthrough.py` | `src/clite/tools/environments/local.py` | Daftar izin variabel; di sini `terminal.env_passthrough` dan `build_child_env` |
| `tools/environments/base.py`, `tools/environments/local.py` | `src/clite/tools/environments/base.py`, `src/clite/tools/environments/local.py` | |
| `tools/environments/docker.py`, `tools/environments/ssh.py` | belum ada | F2-T7 |
| `tools/file_tools.py`, `tools/file_operations.py` | `src/clite/tools/builtin/file_tools.py` | |
| `tools/fuzzy_match.py`, `tools/patch_parser.py` | belum ada | Patch toleran dan multi-file: F2-T4 |
| `tools/checkpoint_manager.py` | belum ada | F2-T8 |
| `tools/web_tools.py`, `tools/url_safety.py` | `src/clite/tools/builtin/web.py` | Hanya `web_fetch`. Pencarian: F2-T5 |
| `tools/vision_tools.py`, `tools/image_generation_tool.py` | belum ada | F2-T6 |
| `tools/code_execution_tool.py` | belum ada | F2-T9 |
| `tools/todo_tool.py` | `src/clite/agent/todo.py`, `src/clite/tools/builtin/todo.py` | |
| `tools/clarify_tool.py` | `src/clite/tools/builtin/clarify.py` | |
| `tools/session_search_tool.py` | `src/clite/tools/builtin/session_search.py` | |
| `tools/cronjob_tools.py` | `src/clite/tools/builtin/cronjob.py` | |
| `tools/mcp_tool.py` | `src/clite/tools/mcp/client.py` | Hermes memakai SDK `mcp`. HTTP, OAuth, resources: F2-T10 |
| `tools/send_message_tool.py` | belum ada | F4-T8 |
| `tools/browser_tool.py` | belum ada | Belum dijadwalkan |
| `tools/tts_tool.py`, `tools/transcription_tools.py`, `tools/voice_mode.py` | belum ada | F6-T7 |

## Skill

| Hermes | C-lite | Catatan |
|---|---|---|
| `agent/skill_utils.py` | `src/clite/skills/frontmatter.py`, `src/clite/skills/catalog.py` | Parse dan penemuan |
| `tools/skills_tool.py` | `src/clite/skills/index.py`, `src/clite/tools/builtin/skills.py` | Indeks, `skills_list`, `skill_view` |
| `tools/skill_manager_tool.py` | `src/clite/skills/manager.py` | `skill_manage` |
| `agent/skill_commands.py` | `src/clite/skills/commands.py` | Skill sebagai slash command |
| `tools/skill_usage.py` | `src/clite/skills/usage.py` | |
| `agent/curator.py`, `hermes_cli/curator.py` | `src/clite/skills/curator.py` | |
| `tools/skills_hub.py`, `tools/skills_hub_github.py` | `src/clite/skills/hub.py` | Hub lengkap: F6-T1 |
| `tools/skills_guard.py` | `src/clite/core/threats.py` | Pemindai Hermes jauh lebih dalam: F6-T1 |
| `tools/skills_sync.py` | tidak dibawa | Di sini skill bawaan dibaca di tempat |
| `skills/`, `optional-skills/` | `src/clite/bundled/skills/` | Hermes 58 dan 152, di sini 4. Porting: F6-T2 |

## Plugin dan hook

| Hermes | C-lite | Catatan |
|---|---|---|
| `hermes_cli/plugins.py` | `src/clite/plugins/manager.py`, `src/clite/plugins/context.py`, `src/clite/plugins/hooks.py` | Manager, `PluginContext`, bus hook |
| `hermes_cli/plugins_manifest.py` | `src/clite/plugins/manifest.py` | |
| `hermes_cli/plugins_ledger.py` | `src/clite/plugins/context.py` | Ledger pembatalan |
| `hermes_cli/plugins_cmd.py` | `src/clite/cli/subcommands/plugins.py` | |
| `agent/shell_hooks.py`, `hermes_cli/hooks.py` | `src/clite/plugins/shell_hooks.py`, `src/clite/cli/subcommands/hooks.py` | |
| `agent/plugin_llm.py` | belum ada | F6-T5 |
| `plugin-catalog/` | belum ada | F6-T5 |

## State

| Hermes | C-lite | Catatan |
|---|---|---|
| `hermes_state.py`, `hermes_state_sessions.py`, `hermes_state_messages.py` | `src/clite/state/db.py` | Hermes memecahnya ke lebih dari 30 file |
| `hermes_state_schema.py` | `src/clite/state/schema.py` | |
| `hermes_state_search.py`, `hermes_state_fts.py` | `src/clite/state/db.py` | `search_messages` |
| `hermes_state_compression.py`, `hermes_state_rewind.py` | `src/clite/state/db.py` | `replace_active_messages`, `deactivate_from` |
| `hermes_state_maintenance.py` | `src/clite/state/db.py`, `src/clite/runtime/maintenance.py` | `prune_sessions`, auto-prune |
| `hermes_state_repair.py` | belum ada | Belum dijadwalkan |

## Core

| Hermes | C-lite | Catatan |
|---|---|---|
| `hermes_constants.py` | `src/clite/core/constants.py`, `src/clite/core/brand.py` | Home, nama produk |
| `hermes_cli/config.py`, `hermes_cli/config_defaults.py`, `hermes_cli/config_migrations.py` | `src/clite/core/config.py`, `src/clite/core/config_defaults.py` | |
| `hermes_cli/env_loader.py`, `agent/secret_scope.py` | `src/clite/core/env.py` | |
| `hermes_cli/profiles.py` | `src/clite/core/profiles.py` | |
| `hermes_logging.py` | `src/clite/core/logging.py` | |
| `hermes_yaml.py` | belum ada | Penulis config yang mempertahankan komentar: F1-T6 |

## CLI

| Hermes | C-lite | Catatan |
|---|---|---|
| `hermes_cli/main.py`, `hermes_cli/_parser.py` | `src/clite/cli/main.py` | |
| `hermes_cli/subcommands/` | `src/clite/cli/subcommands/` | Satu modul per kelompok sub-perintah |
| `cli.py` | `src/clite/cli/repl.py` | REPL. Hermes memakai `prompt_toolkit`: F3-T1 |
| `agent/display.py`, `hermes_cli/skin_engine.py`, `hermes_cli/banner.py` | `src/clite/cli/display.py` | Render Markdown dan diff: F3-T2 |
| `hermes_cli/commands.py` | `src/clite/runtime/commands.py`, `src/clite/runtime/slash.py` | Registry slash command dan handler |
| `hermes_cli/setup.py` | `src/clite/cli/subcommands/setup.py`, `src/clite/runtime/setup.py` | Wizard bertahap: F3-T5 |
| `hermes_cli/doctor.py`, `hermes_cli/status.py`, `hermes_cli/logs.py` | `src/clite/cli/subcommands/misc.py` | |
| `hermes_cli/sessions_cmd.py` | `src/clite/cli/subcommands/sessions.py` | |
| `hermes_cli/tools_config.py` | `src/clite/cli/subcommands/tools.py` | |
| `hermes_cli/skills_config.py`, `hermes_cli/skills_hub.py` | `src/clite/cli/subcommands/skills.py` | |
| `hermes_cli/main_tui_launch.py` | `src/clite/cli/subcommands/tui.py` | |
| `hermes_cli/update_cmd.py`, `hermes_cli/backup.py`, `hermes_cli/uninstall.py` | belum ada | F3-T6 |
| `hermes_cli/completion.py` | belum ada | F3-T7 |
| `hermes_cli/mcp_config.py` | belum ada | `clite mcp`: F2-T10 |

## RPC, TUI, desktop, dashboard

| Hermes | C-lite | Catatan |
|---|---|---|
| `tui_gateway/server.py`, `tui_gateway/rpc_dispatch.py` | `src/clite/rpc/server.py` | |
| `tui_gateway/entry.py` | `src/clite/rpc/entry.py` | Entry point stdio |
| `tui_gateway/transport.py`, `tui_gateway/ws.py` | `src/clite/rpc/transport.py` | |
| `tui_gateway/contracts/` | `src/clite/rpc/contracts/` | Hermes 251 method, di sini 32 |
| `tui_gateway/methods_session.py`, `tui_gateway/methods_prompt.py`, `tui_gateway/methods_config.py` | `src/clite/rpc/methods.py` | |
| `tui_gateway/agent_callbacks.py`, `tui_gateway/prompt_turn.py` | `src/clite/rpc/session.py` | Callback menjadi event |
| `tui_gateway/server_requests.py` | `src/clite/rpc/server.py` | `request_client` |
| `tui_gateway/event_replay.py` | belum ada | F5-T5 |
| `tui_gateway/prompt_attachments.py` | belum ada | F2-T6 |
| `scripts/gen_gateway_contracts.py` | `scripts/gen_rpc_contracts.py` | Generator tipe TypeScript |
| `apps/shared/src/gateway-contract.generated.ts` | `apps/shared/src/contracts.generated.ts` | Hasil generate |
| `apps/shared/src/json-rpc-channel.ts` | `apps/shared/src/json-rpc-channel.ts` | |
| `apps/shared/src/json-rpc-gateway.ts` | `apps/shared/src/gateway-client.ts` | Klien bertipe |
| `ui-tui/src/entry.tsx`, `ui-tui/src/gatewayClient.ts` | `ui-tui/src/entry.ts`, `ui-tui/src/backend.ts` | |
| `ui-tui/src/app.tsx`, `ui-tui/src/components/` | `ui-tui/src/plain.ts`, `ui-tui/src/render.ts` | Hermes memakai Ink. TUI layar penuh: F3-T3 |
| `hermes_cli/web_server.py` | `src/clite/server/app.py`, `src/clite/server/run.py` | Di sini satu server untuk desktop dan dashboard |
| `web/src/` | `src/clite/server/static/` | Hermes: React. Di sini JavaScript polos. Halaman tambahan: F5-T2 |
| `apps/desktop/electron/` | `apps/desktop/src/` | Proses utama Electron. Belum diverifikasi: F5-T1 |
| `apps/desktop/src/` | tidak dibawa | Renderer React Hermes. Di sini jendela memuat dashboard |
| `acp_adapter/` | `src/clite/acp/` | Baru penanda tempat: F6-T4 |

## Gateway dan cron

| Hermes | C-lite | Catatan |
|---|---|---|
| `gateway/run.py` | `src/clite/gateway/runner.py` | Hermes asinkron, di sini thread |
| `gateway/session.py` | `src/clite/gateway/session.py` | Kunci sesi |
| `gateway/pairing.py` | `src/clite/gateway/pairing.py` | |
| `gateway/platforms/base.py`, `gateway/platform_registry.py` | `src/clite/gateway/platforms/base.py` | |
| `gateway/platforms/event.py` | `src/clite/gateway/event.py` | `MessageEvent` |
| `plugins/platforms/telegram/adapter.py` | `src/clite/gateway/platforms/telegram.py` | Belum diuji terhadap Telegram sungguhan: F1-T3 |
| `plugins/platforms/discord/` | belum ada | F4-T1 |
| `plugins/platforms/slack/` | belum ada | F4-T2 |
| `plugins/platforms/whatsapp/`, `gateway/platforms/signal.py`, `plugins/platforms/matrix/`, `plugins/platforms/email/` | belum ada | F4-T3 |
| `gateway/stream_consumer.py` | belum ada | Jawaban streaming: F4-T5 |
| `gateway/delivery.py` | `src/clite/gateway/runner.py` | `reply`, `deliver` |
| `hermes_cli/gateway_launchd.py`, `gateway/restart.py` | belum ada | Layanan sistem: F4-T6 |
| `gateway/config.py` | belum ada | Kebijakan reset sesi (menganggur, harian): F4-T7 |
| `gateway/platforms/api_server.py`, `gateway/platforms/webhook.py` | belum ada | F4-T10 |
| `cron/jobs.py` | `src/clite/cron/jobs.py`, `src/clite/cron/schedule.py` | Hermes memakai `croniter` |
| `cron/scheduler.py`, `cron/scheduler_tick.py` | `src/clite/cron/scheduler.py` | |
| `cron/scheduler_script.py`, `cron/executions.py`, `cron/delivery_queue.py` | belum ada | F4-T9 |

## Skrip dan dokumen pengembang

| Hermes | C-lite | Catatan |
|---|---|---|
| `scripts/run_tests.sh` | `scripts/run_tests.sh` | |
| `AGENTS.md` | `AGENTS.md` | Aturan kerja untuk AI |
| `website/docs/developer-guide/architecture.md` | `docs/arsitektur/README.md` | |
| `website/docs/developer-guide/agent-loop.md` | `docs/arsitektur/02-alur-giliran.md` | |
| `website/docs/developer-guide/adding-tools.md` | `src/clite/tools/AGENTS.md` | Resep menambah tool |
| `website/docs/developer-guide/adding-providers.md` | `src/clite/providers/AGENTS.md` | Resep menambah provider |
| `website/docs/developer-guide/adding-platform-adapters.md`, `gateway/platforms/ADDING_A_PLATFORM.md` | `src/clite/gateway/AGENTS.md` | Resep menambah platform |
| `website/docs/developer-guide/session-storage.md` | `docs/spesifikasi/state.md` | |
| `website/docs/developer-guide/gateway-session-lifecycle.md` | `docs/spesifikasi/gateway.md` | |
| `website/docs/developer-guide/prompt-assembly.md`, `website/docs/developer-guide/context-compression-and-caching.md` | `docs/spesifikasi/agent.md` | |
| `website/docs/developer-guide/provider-runtime.md` | `docs/spesifikasi/providers.md` | |
