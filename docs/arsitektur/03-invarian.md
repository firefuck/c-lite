# Invarian

Aturan di halaman ini tidak boleh dilanggar oleh perubahan apa pun. Setiap aturan menyebut
alasannya dan tes yang menjaganya. Bila sebuah tugas tampaknya menuntut pelanggaran, berhenti
dan laporkan: itu tanda rancangan tugasnya perlu diubah, bukan aturannya dilonggarkan.

Nama tes ditulis tanpa path bila filenya jelas dari judul bagian. Semua nama tes di halaman
ini diperiksa keberadaannya oleh `tests/test_docs.py`.

## A. Percakapan

### A1. System prompt tidak berubah di tengah sesi

System prompt dibangun sekali saat giliran pertama, disimpan di baris sesi, dan dipakai ulang
byte demi byte di setiap permintaan, termasuk setelah sesi dilanjutkan. Daftar tool juga tetap
sepanjang sesi.

**Mengapa.** Provider meng-cache awalan permintaan. Satu byte yang berubah di system prompt
membatalkan cache seluruh percakapan, dan biaya giliran berikutnya naik berkali lipat.

**Yang boleh membangun ulang.** Hanya `compress_context`, `switch_model`, dan `/reload`. Ketiganya
memang mengubah awalan.

**Cara melanggarnya tanpa sengaja.** Menaruh jam, jumlah pesan, isi memori terbaru, status
tugas, atau apa pun yang berubah antar-giliran ke `agent/prompt/builder.py`. Informasi semacam
itu masuk ke `turn_context` pesan pengguna atau ke hasil tool.

**Tes** (`tests/agent/`): `test_system_prompt_and_tools_are_byte_stable_across_turns_and_resume`,
`test_memory_written_mid_session_does_not_change_that_sessions_prompt`,
`test_same_inputs_give_the_same_bytes`, `test_the_date_line_has_no_clock_time`,
`test_manual_compression_keeps_the_session_and_rebuilds_the_prompt`. Kestabilan daftar tool:
`test_definitions_are_sorted_and_openai_shaped`, `test_a_recently_passing_check_survives_one_flake`
(`tests/tools/`).

### A2. Yang sudah dikirim tidak pernah berubah

Setiap permintaan sama dengan permintaan sebelumnya ditambah pesan baru di ujungnya. Bentuk
kawat sebuah pesan yang sudah dikirim tidak pernah berubah, juga setelah sesi dilanjutkan.

**Mengapa.** Selain cache, model Claude generasi 5 menandatangani blok penalarannya terhadap
percakapan sebelum blok itu. Permintaan yang riwayatnya diubah ditolak dengan galat 400.

**Akibatnya.**
- Tidak ada yang dikirim tanpa disimpan. Permintaan penutup saat anggaran habis dan permintaan
  "lanjutkan" disimpan sebagai pesan internal.
- Tidak ada yang dikirim sekali lalu dibuang. Konteks giliran disimpan sebagai `turn_context`
  dan digabung ke isi pesan pada setiap permintaan.
- `sanitize_for_api` deterministik: riwayat tersimpan yang sama selalu menghasilkan daftar yang
  sama.
- Penanda cache dan konversi protokol dikerjakan pada salinan.
- `provider_data` diputar ulang apa adanya, dan dibuang seluruhnya ketika awalan sengaja
  diubah (kompresi pada provider yang mengikatnya, ganti model) atau ketika provider
  menolaknya.

**Tes** (`tests/agent/test_loop.py`):
`test_every_request_repeats_the_previous_one_and_adds_to_its_end`,
`test_turn_context_rides_the_user_message_and_is_stored_beside_it`,
`test_cache_markers_are_applied_on_the_wire_only`, `test_replay_data_is_stored_and_sent_back`,
`test_rejected_replay_data_is_dropped_and_the_request_retried_once`,
`test_switching_models_drops_replay_data`,
`test_compression_drops_replay_data_only_when_it_is_bound_to_the_prefix`. Di
`tests/providers/test_transports.py`: `test_chat_request_does_not_mutate_the_history`,
`test_anthropic_conversion_replays_signed_thinking_blocks_verbatim`.

### A3. Riwayat tersimpan hanya bertambah

Pesan tahan lama begitu `append_message` kembali, dan tidak pernah dihapus atau disunting.
Operasi yang mengubah apa yang aktif hanya empat, dan tidak ada yang menghapus baris:

| Operasi | Yang dilakukan | Dipakai oleh |
|---|---|---|
| `replace_active_messages` | Baris lama menjadi `active=0, compacted=1` di sesi yang sama | Kompresi |
| `deactivate_from` | Menonaktifkan dari satu baris ke belakang | `/undo`, `/retry` |
| `replace_last_content` | Mengganti pesan terbaru, yaitu pesan yang belum dijawab model | `/steer` |
| `clear_provider_data` | Mengosongkan data putar ulang, transkrip tidak disentuh | `drop_replay_data` |

**Tes**: `test_transcript_is_durable_and_resumable`,
`test_assistant_tool_call_is_persisted_before_the_tool_runs`,
`test_steer_attaches_to_the_latest_tool_result` (`tests/agent/test_loop.py`);
`test_compaction_keeps_session_id_and_archives_old_rows`,
`test_deactivate_from_rewinds_the_active_transcript`,
`test_replay_data_can_be_cleared_without_touching_the_transcript` (`tests/state/test_db.py`).

### A4. Setiap tool call punya hasil

Transkrip tersimpan selalu berbentuk yang diterima provider: tidak ada tool call tanpa hasil,
tidak ada hasil tanpa tool call. Interupsi, crash, dan kompresi tidak boleh merusaknya.

**Tes**: `test_interrupt_during_tools_skips_the_rest_and_keeps_the_transcript_valid`,
`test_sanitize_adds_stubs_and_drops_orphans` (`tests/agent/test_loop.py`);
`test_tool_calls_are_never_separated_from_their_results`, `test_repair_tool_pairs`
(`tests/agent/test_compression.py`).

### A5. Satu giliran per agent

`run_conversation` menolak giliran kedua selagi yang pertama berjalan. Surface yang menerima
masukan saat sibuk menerapkan kebijakan sibuknya sendiri.

**Tes**: `test_only_one_turn_runs_at_a_time`, `test_busy_modes` (`tests/rpc/test_rpc.py`).

## B. Struktur kode

### B1. Import mengarah ke bawah

Lihat [01-lapisan.md](01-lapisan.md). Import tingkat modul hanya ke peringkat lebih rendah,
area berperingkat sama tidak saling mengimpor, `core` adalah daun.

**Tes** (`tests/test_architecture.py`): `test_imports_point_down_the_layers`,
`test_every_package_has_a_layer`, `test_core_imports_nothing_from_the_rest_of_the_package`,
`test_bundled_plugins_use_only_the_plugin_api`.

### B2. Yang dipakai dua surface tinggal di `runtime`

CLI, RPC, gateway, dan cron membuat agent lewat `build_agent` dan berbicara dengannya lewat
`ChatSession`. Tidak ada surface yang punya versi sendiri dari slash command, pemilihan
toolset, atau pergantian model.

**Tes**: aturan peringkat sama di B1 mencegah surface saling mengimpor.
`test_every_command_has_a_handler_and_every_handler_a_command`, `test_platform_toolsets`
(`tests/runtime/test_session_and_slash.py`).

### B3. Dideklarasikan sekali

Setiap hal yang didaftar punya tepat satu tempat deklarasi, dan semua turunannya dibangun dari
sana.

| Hal | Tempat deklarasi | Turunan |
|---|---|---|
| Tool | `registry.register(...)` di modul tool | Definisi untuk model, toolset, katalog |
| Slash command | `COMMAND_REGISTRY` | Bantuan, pelengkapan, katalog RPC, dispatch di semua surface |
| Method, event, permintaan server RPC | `rpc/contracts/schema.py` | Validasi, tipe TypeScript |
| Pengaturan | `DEFAULT_CONFIG` | Default, katalog |
| Hook | `VALID_HOOKS` | Validasi saat mendaftar, daftar untuk shell hook |
| Provider | Direktori profil | Registry, `clite setup`, katalog |

**Tes**: `test_every_declared_method_has_a_handler_and_the_reverse` (`tests/rpc/test_rpc.py`),
`test_typescript_contracts_match_the_python_contracts`,
`test_generated_reference_pages_are_current`, `test_every_config_key_has_a_reader`
(`tests/test_architecture.py`), `test_unknown_hook_name_is_rejected`
(`tests/plugins/test_hooks.py`), `test_schema_name_must_match` (`tests/tools/test_registry.py`).

### B4. Tidak ada nama vendor di luar profilnya

Kode inti tidak pernah bertanya "apakah ini OpenAI?". Yang berbeda antar-vendor adalah method
pada `ProviderProfile` yang di-override profil vendor itu. `mock` dan `custom` bukan vendor.

**Tes**: `test_vendors_are_named_only_in_their_provider_profiles`,
`test_the_profile_decides_whether_a_temperature_is_sent`
(`tests/providers/test_transports.py`).

### B5. Fasad tetap fasad

`agent/agent.py` dan `agent/loop.py` tidak menampung perilaku baru. Perilaku baru adalah fase
di `agent/turn/`, tool, atau plugin. Tool tingkat agent (`todo`, `memory`, `delegate_task`,
`clarify`) adalah tool biasa yang menerima `ctx.agent`; loop tidak punya cabang untuk nama tool.

**Tes**: tidak ada tes mekanis. Dijaga lewat review dan aturan di `src/clite/agent/AGENTS.md`.

## C. Lingkungan

### C1. Home dinamis dan terisolasi per profil

Path didapat dari `get_home()` dan kawan-kawannya **pada saat dipanggil**, tidak pernah
disimpan di konstanta tingkat modul dan tidak pernah dieja sebagai teks. Registry dan cache
yang bergantung pada home dikunci dengan `home_key()`. Thread yang bekerja untuk sebuah sesi
dimulai dengan `core.threads.start_thread`.

**Mengapa.** Satu proses (gateway, server) bisa melayani beberapa profil, dan nama proyek bisa
diganti dengan `scripts/rename_project.py`.

**Tes**: `test_the_home_directory_name_is_spelled_only_in_brand`,
`test_override_wins_and_is_restored`,
`test_a_thread_started_for_session_work_keeps_the_callers_home`,
`test_database_lives_in_the_active_home`, `test_each_profile_has_its_own_plugins`,
`test_each_home_has_its_own_bus`,
`test_user_plugin_overrides_a_bundled_provider_for_that_home_only`.

### C2. Rahasia hanya di `.env`, dan tidak bocor

- Rahasia hanya di `<home>/.env`. Pengaturan perilaku hanya di `config.yaml`.
- Kode membaca rahasia lewat `core.env.get_secret`. Variabel lingkungan proses hanya dibaca di
  file yang terdaftar di `ENVIRONMENT_READERS`.
- Kredensial yang dikenal (`core.env.secret_names`: semua nama dari `.env`, dan semua kunci
  provider atau platform walaupun di-`export` di shell) tidak masuk ke lingkungan perintah yang
  dijalankan agent, tidak masuk ke lingkungan server MCP, tidak dikirim ke host selain host
  asal kuncinya, tidak muncul di `RuntimeRoute.describe()`, dan diredaksi dari semua yang
  dibaca model: keluaran terminal, isi file, hasil pencarian.
- Agent tidak bisa membaca `.env` miliknya lewat tool file, dan tidak bisa menulis `.env`,
  `config.yaml`, atau daftar persetujuan hook miliknya. Perintah shell yang menjangkau file
  itu, atau menjalankan CLI pengelolaan agent sendiri, selalu meminta persetujuan pengguna.

**Tes**: `test_the_process_environment_is_read_only_where_listed`,
`test_secrets_from_dotenv_do_not_reach_the_command`,
`test_provider_keys_exported_in_the_shell_do_not_reach_the_command_either`,
`test_key_shaped_output_is_redacted`, `test_credentials_are_redacted_from_what_the_model_reads`,
`test_server_environment_excludes_secrets_unless_listed`,
`test_a_provider_key_is_not_sent_to_another_host`, `test_describe_never_contains_the_key`,
`test_credential_files_cannot_be_read`, `test_agent_cannot_write_its_own_credentials_or_settings`,
`test_reaching_for_the_agents_settings_is_asked_about_every_time`,
`test_create_clone_copies_settings_but_not_secrets`,
`test_dashboard_url_keeps_the_token_in_the_fragment`.

### C3. Konfigurasi

- Setiap kunci di `DEFAULT_CONFIG` punya kode yang membacanya.
- File config yang rusak melempar `ConfigError` dan tidak pernah ditimpa.
- Semua penulisan lewat `config_set`, `config_unset`, atau `atomic_config_update`.
- Sebuah sesi memakai potret config saat ia dibuat (`agent.config`).

**Tes**: `test_every_config_key_has_a_reader`, `test_broken_file_is_never_overwritten`,
`test_callers_cannot_poison_the_cache`, `test_migrations_run_up_to_the_current_version`,
`test_reload_picks_up_config_and_keeps_the_conversation`.

### C4. Stdout bukan tempat mencetak

Kode pustaka memakai logging, mengembalikan teks ke surface, atau memanggil callback. Pada
transport stdio, stdout adalah kawat protokol.

**Tes**: `test_only_the_command_line_prints`, `test_stdio_entry_point_end_to_end`.

## D. Kegagalan

### D1. Keputusan keamanan gagal tertutup, pengamat gagal terbuka

| Yang gagal | Akibat |
|---|---|
| Hook `pre_tool_call` melempar atau kehabisan waktu | Tool call **diblokir** |
| Callback persetujuan melempar, menjawab aneh, atau diam | Perintah **ditolak** |
| Tidak ada pengguna untuk ditanya | Kebijakan non-interaktif; default **tolak** |
| Peninjau `smart` gagal atau ragu | Naik ke pengguna |
| Hook pengamat (`post_*`, `on_*`) melempar atau kehabisan waktu | Diabaikan, dicatat di log |
| Callback tampilan melempar | Diabaikan, dicatat di log |
| Provider memori eksternal gagal | Giliran berlanjut |
| Pekerjaan rumah startup gagal | Sesi tetap dimulai |

Aturan untuk kode baru: bila kegagalan sebuah komponen bisa membuat sesuatu yang berbahaya
lolos, kegagalan itu berarti "tidak". Selain itu, kegagalan tidak boleh menghentikan giliran.

**Tes**: `test_policy_hook_that_raises_blocks`, `test_policy_hook_that_times_out_blocks`,
`test_a_crashing_guard_blocks_the_call`,
`test_unexpected_answer_or_crashing_prompt_fails_closed`,
`test_no_one_to_ask_means_deny_by_default`, `test_no_answer_to_an_approval_means_deny`,
`test_deny_and_silence_both_refuse`,
`test_smart_mode_asks_the_user_whenever_the_reviewer_is_not_clear`,
`test_a_failing_observer_does_not_affect_the_others`, `test_observer_that_times_out_is_skipped`,
`test_a_failing_callback_does_not_break_the_turn`,
`test_a_failing_provider_never_fails_the_turn`, `test_maintenance_failure_never_stops_a_session`,
`test_a_broken_hook_fails_open_by_default_and_closed_on_request`.

### D2. Tidak ada yang dilempar ke model atau ke surface

- Handler tool mengembalikan galat sebagai `{"error": ...}`. Exception di handler ditangkap
  registry dan menjadi hasil galat.
- `run_turn` selalu mengembalikan `TurnResult`.
- Galat protokol RPC adalah balasan. Klien selalu menerima `turn.complete`.
- Satu plugin, profil provider, platform, server MCP, atau job cron yang rusak dilaporkan dan
  dilewati. Yang lain tetap jalan.

**Tes**: `test_handler_exception_becomes_an_error_result`,
`test_unknown_tool_is_an_error_result_not_an_exception`,
`test_an_internal_error_is_reported_not_raised`, `test_protocol_errors_are_replies_not_crashes`,
`test_a_turn_is_a_stream_of_events_ending_with_turn_complete`,
`test_a_broken_plugin_is_reported_and_leaves_nothing_behind`,
`test_a_broken_provider_plugin_does_not_hide_the_others`,
`test_a_platform_that_fails_to_start_does_not_stop_the_gateway`,
`test_broken_servers_are_skipped_not_fatal`,
`test_a_failing_job_is_recorded_and_does_not_stop_the_others`.

## E. Kode dan konten dari luar

### E1. Kode dari luar harus diaktifkan pengguna secara eksplisit

- Plugin hanya berjalan bila namanya ada di `plugins.enabled`. Memasang tidak mengaktifkan.
- Plugin proyek (`./.clite/plugins/`) butuh variabel lingkungan tersendiri.
- Shell hook hanya berjalan setelah pasangan event dan perintah yang persis sama disetujui.
- Plugin tidak bisa mengganti tool bawaan tanpa izin per plugin di config.
- Memasang skill tidak mengeksekusi apa pun.

**Tes**: `test_a_discovered_plugin_does_nothing_until_enabled`,
`test_install_copies_but_does_not_enable`, `test_disabled_wins_over_enabled`,
`test_a_plugin_cannot_replace_a_builtin_tool_without_consent`,
`test_a_configured_hook_does_not_run_until_it_is_approved`,
`test_approval_is_for_the_exact_event_and_command`,
`test_the_allowlist_cannot_be_written_with_the_file_tools`.

### E2. Teks tak tepercaya dipindai sebelum masuk prompt

File konteks proyek, skill dari proyek dan dari direktori eksternal (setiap kali ditemukan),
skill lokal (saat ditulis dan saat dipasang), entri memori, dan prompt job cron dipindai dengan
`core.threats.scan_text`. Yang kena **diblokir dengan alasan**, tidak dibersihkan lalu
dilanjutkan.

**Tes**: `test_injected_context_file_is_blocked_not_loaded`,
`test_a_flagged_skill_from_a_repository_is_not_offered`,
`test_duplicates_and_unsafe_content_are_refused`,
`test_install_refuses_a_flagged_skill_unless_forced`,
`test_threat_scan_flags_injection_and_passes_ordinary_text`, `test_invalid_jobs_are_refused`.

### E3. Platform pesan tidak mewarisi hak terminal

Toolset platform pesan, cron, dan subagent ditentukan terpisah dari toolset pengguna di
terminal. Subagent tidak bisa mendelegasikan lagi, bertanya, atau menulis memori; job cron
tidak bisa bertanya atau menjadwalkan job.

**Tes**: `test_platform_toolsets`, `test_subagent_toolset_cannot_delegate_ask_or_write_memory`,
`test_cron_toolset_cannot_ask_or_schedule`, `test_children_cannot_delegate_further`,
`test_child_toolsets_are_limited_to_what_the_parent_has`.

## F. Protokol, tes, dan dokumen

### F1. Kontrak RPC adalah sumber kebenaran

Tipe TypeScript dihasilkan dari model Pydantic. File hasil generate tidak disunting tangan.
Payload event divalidasi saat dikirim. Menghapus atau mengganti nama bidang berarti method
baru.

**Tes**: `test_typescript_contracts_match_the_python_contracts`,
`test_every_declared_method_has_a_handler_and_the_reverse`,
`test_the_committed_bundle_was_built_from_the_current_sources`.

### F2. Tes tidak memakai jaringan dan tidak menyentuh home asli

Fixture `clite_home` (otomatis untuk semua tes) memberi home sementara, mengalihkan
`Path.home()`, dan menghapus kredensial dari lingkungan. Ujung jauh ditiru dengan server
lokal sungguhan; model ditiru dengan `ScriptedClient`. Tes yang butuh jaringan diberi
`@pytest.mark.network`.

**Dijaga oleh**: fixture di `tests/conftest.py`. Aturan lengkapnya di `tests/AGENTS.md`.

### F3. Status ditulis jujur

Sebuah fitur diberi tanda ✅ hanya bila ada tes yang gagal saat fitur itu rusak. Kode yang
ditulis tetapi belum pernah dijalankan terhadap hal yang sebenarnya diberi tanda "belum
diverifikasi". Halaman referensi dihasilkan dari kode, dan dokumen tidak boleh menyebut file,
tes, atau task yang tidak ada.

**Tes**: `test_generated_reference_pages_are_current`,
`test_relative_links_in_the_docs_resolve`, `test_paths_named_in_the_docs_exist`,
`test_tests_named_in_the_docs_exist`, `test_roadmap_tasks_cited_in_the_docs_are_defined`.
