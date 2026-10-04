# 02. Agent Loop

Inti Hermes adalah kelas `AIAgent`. Bab ini menjelaskan bentuknya, urutan fase dalam
satu giliran, dan invarian alur pesan yang selalu dijaga.

## Bentuk `AIAgent`

`run_agent.py` adalah **fasad publik**. Kelas `AIAgent` dirakit dari 14 mixin
(`ClientLifecycleMixin`, `StreamDeliveryMixin`, `InterruptControlMixin`,
`SessionPersistenceMixin`, `CompressionFacadeMixin`, `TurnFacadeMixin`, dan lainnya).
Konstruksi dijalankan `agent/agent_init.py::init_agent`. Satu giliran dijalankan
`agent/conversation_loop.py::run_conversation`.

`AIAgent.__init__` menerima sekitar 60 parameter. Yang paling sering disentuh:

| Parameter | Arti |
|---|---|
| `base_url`, `api_key`, `provider`, `api_mode` | Rute ke penyedia model. `api_mode` salah satu dari `chat_completions`, `codex_responses`, `anthropic_messages` |
| `model` | Kosong berarti diambil dari konfigurasi atau provider |
| `max_iterations` | Batas panggilan API per giliran |
| `enabled_toolsets`, `disabled_toolsets` | Pemilihan tool |
| `platform` | `"cli"`, `"telegram"`, `"tui"`, `"cron"`, dan seterusnya |
| `session_id`, `session_db`, `parent_session_id` | Identitas dan penyimpanan sesi |
| `skip_context_files`, `skip_memory` | Dipakai subagent dan cron |
| `fallback_model`, `credential_pool` | Rantai cadangan dan rotasi kredensial |
| `iteration_budget` | Anggaran iterasi, bisa dibagikan dari luar |
| `*_callback` | Belasan callback untuk progres, streaming, klarifikasi |

Dua pintu masuk:

```python
response = agent.chat("Perbaiki bug di main.py")          # mengembalikan string

result = agent.run_conversation(                           # mengembalikan dict
    user_message="Perbaiki bug di main.py",
    system_message=None,          # dirakit otomatis bila kosong
    conversation_history=None,    # dimuat dari sesi bila kosong
    task_id="task_abc123",
)
# result berisi final_response, messages, dan metadata pemakaian
```

`chat()` hanyalah pembungkus tipis yang mengambil `final_response` dari hasil
`run_conversation()`.

## Format pesan internal

Semua pesan memakai format OpenAI, apa pun penyedianya:

```python
{"role": "system", "content": "..."}
{"role": "user", "content": "..."}
{"role": "assistant", "content": "...", "tool_calls": [...]}
{"role": "tool", "tool_call_id": "...", "content": "..."}
```

Isi penalaran model disimpan di `assistant_msg["reasoning"]`. Data khusus protokol
(blok thinking bertanda tangan milik Anthropic, item reasoning Codex) ikut disimpan
pada pesan asisten supaya bisa diputar ulang ke penyedia yang sama.

## Aturan selang-seling peran

Ini diperiksa pada setiap perubahan loop:

- Setelah pesan sistem: `user → assistant → user → assistant → ...`
- Saat memanggil tool: `assistant (dengan tool_calls) → tool → tool → ... → assistant`
- Tidak pernah dua pesan `assistant` berurutan.
- Tidak pernah dua pesan `user` berurutan.
- Hanya peran `tool` yang boleh berurutan (hasil tool paralel).
- Tidak pernah ada pesan `user` sintetis yang disisipkan di tengah loop.

Satu-satunya pengecualian adalah `/steer`: pesan pengguna yang dikirim setelah hasil
tool, dalam bentuk `assistant(tool_calls) → tool → user`, yang sah di semua penyedia.

Penyedia memvalidasi urutan ini dan menolak riwayat yang cacat. Karena itu apa pun yang
perlu menyisipkan isi di tengah percakapan **menumpang pada pesan pengguna atau hasil
tool**, tidak pernah pada system prompt: slash command skill disisipkan sebagai pesan
pengguna, dan petunjuk `AGENTS.md` subdirektori ditempelkan ke hasil tool.

## Kerangka loop

Loop sepenuhnya sinkron. Versi yang disederhanakan:

```python
while (api_call_count < max_iterations and iteration_budget.remaining > 0) or budget_grace_call:
    if interrupt_requested: break
    response = client.chat.completions.create(model=model, messages=messages, tools=tool_schemas)
    if response.tool_calls:
        for tc in response.tool_calls:
            messages.append(tool_result_message(handle_function_call(tc.name, tc.args, task_id)))
        api_call_count += 1
    else:
        return response.content
```

Versi aslinya memecah setiap fase menjadi modul tersendiri, sehingga perubahan pada
satu hal, misalnya penanganan overflow, hanya menyentuh satu file berukuran sekitar
600 baris.

### Keadaan loop dan pola verdict

`agent/conversation_loop.py` mendefinisikan dataclass `_LoopState` yang memuat semua
variabel lokal loop: pesan, hitungan panggilan API, hitungan retry, respons terakhir,
dan seterusnya. Setiap fase adalah fungsi yang menerima `agent` plus argumen kata kunci
bernama sama dengan field `_LoopState`, lalu mengembalikan dataclass **verdict**.

`_run_phase(fn, agent, state)` memeriksa tanda tangan fungsi, mengoper field yang
diminta, lalu menyalin balik field verdict ke state berdasarkan nama. Field `action`
pada verdict menentukan langkah loop selanjutnya: `"return"` (giliran selesai dengan
`result`), `"break"`, `"continue"`, atau lanjut ke fase berikutnya.

Keuntungan pola ini: fase baru cukup menambah field di `_LoopState`, tanpa mengubah
cara loop mengoper data.

### Urutan fase satu iterasi

```text
build_turn_context                agent/turn_context.py
│   tambah pesan pengguna, pulihkan atau rakit system prompt, kompresi pra-giliran
▼
while anggaran masih ada:
  begin_iteration                 agent/turn_iteration_prep.py
  │   terapkan redirect tertunda, cek interupsi, pakai satu jatah anggaran
  prepare_iteration               agent/turn_iteration_prep.py
  assemble_api_request            agent/turn_request_assembly.py
  │   salin pesan untuk dikirim, lapisan sementara, penanda cache
  run_preflight_gate              agent/turn_preflight_gate.py
  │   kompres dulu bila konteks terlalu besar
  announce_api_call               agent/turn_iteration_prep.py
  ┌─ loop retry ───────────────────────────────────────────────┐
  │ build_api_request             agent/turn_api_request.py    │
  │ perform_api_call              agent/turn_api_call.py       │
  │ check_api_response            agent/turn_response_check.py │
  │ handle_api_interrupt / handle_api_error                    │
  │                               agent/turn_api_error.py      │
  └────────────────────────────────────────────────────────────┘
  apply_retry_restarts            agent/turn_iteration_prep.py
  normalize_model_response        agent/turn_response_intake.py
  run_tool_round                  agent/turn_tool_round.py       bila ada tool_calls
  finish_text_response            agent/turn_final_response.py   bila jawaban teks
  handle_outer_loop_error         agent/turn_loop_errors.py
▼
finalize_turn                     agent/turn_finalizer.py
    simpan sesi, sinkronkan memori, hook akhir giliran, hitung pemakaian
```

Fase tambahan yang berdiri sendiri: `turn_overflow`, `turn_truncation`,
`turn_context_compaction`, `turn_recovery`, `turn_empty_response`, `turn_stop_gates`,
`turn_liveness`, `turn_usage`, `turn_summary`.

## Panggilan API yang dapat diinterupsi

Permintaan HTTP dijalankan di thread latar, sementara thread utama menunggu salah satu
dari tiga hal: respons siap, event interupsi, atau batas waktu.

```text
Thread utama                         Thread API
  menunggu:                            HTTP POST ke penyedia
   - respons siap            ◄────
   - event interupsi
   - timeout
```

Saat diinterupsi (pengguna mengirim pesan baru, perintah `/stop`, atau sinyal):

- Thread API ditinggalkan dan responsnya dibuang.
- Tidak ada respons parsial yang masuk ke riwayat percakapan.
- Agent bisa memproses input baru atau berhenti dengan bersih.

## Eksekusi tool

### Berurutan atau bersamaan

Kebijakan ada di `agent/tool_dispatch_helpers.py`:

- **Tidak pernah paralel**: `clarify` dan tool interaktif lain. Kehadirannya dalam satu batch menjadi pembatas.
- **Aman paralel**: tool baca-saja tanpa keadaan bersama, yaitu `read_file`, `search_files`, `session_search`, `skill_view`, `skills_list`, `vision_analyze`, `web_extract`, `web_search`, `image_generate`.
- **Berlingkup path**: `read_file` dan `search_files` sebagai pembaca, `write_file` dan `patch` sebagai penulis. Pembaca boleh berbagi subtree. Penulis berkonflik dengan reservasi mana pun yang tumpang tindih, sehingga pembacaan dalam batch tidak pernah melihat keadaan sebelum mutasi.
- Selain itu berjalan berurutan.

Batch paralel memakai `ThreadPoolExecutor` dengan paling banyak 8 pekerja
(`_MAX_TOOL_WORKERS`). Hasil dimasukkan kembali **sesuai urutan panggilan asli**, tidak
peduli urutan selesainya.

### Alur satu panggilan tool

```text
1. Validasi nama tool. Nama tak dikenal mendapat hasil error, tool lain di batch tetap jalan.
2. Pesan asisten berisi tool_calls ditambahkan ke riwayat DAN disimpan ke SessionDB.
3. Hook plugin pre_tool_call (bisa memblokir, meminta persetujuan, atau mengubah argumen).
4. Pemeriksaan perintah berbahaya (tools/approval.py). Bila berbahaya, panggil callback persetujuan.
5. Jalankan handler dengan args dan task_id.
6. Hook post_tool_call, lalu transform_tool_result.
7. Tambahkan {"role": "tool", "tool_call_id": ..., "content": hasil} ke riwayat.
```

Langkah 2 adalah **invarian ketahanan**: pesan asisten disimpan *sebelum* tool
dijalankan. Bila tool yang merusak membuat Hermes restart, sesi yang dilanjutkan harus
melihat blok yang sudah dieksekusi.

### Tool tingkat agent

Beberapa tool dicegat sebelum mencapai `handle_function_call()` karena butuh keadaan
agent yang hidup. Daftarnya ada di tabel `INLINE_TOOL_EXECUTORS` pada
`agent/inline_tool_executors.py`, bukan rantai `if name == ...`.

| Tool | Alasan dicegat |
|---|---|
| `todo_list` | Membaca dan menulis daftar tugas lokal agent |
| `memory` | Menulis file memori persisten dengan batas karakter |
| `session_search` | Mencari riwayat sesi lewat SessionDB milik agent |
| `delegate_task` | Membuat subagent dengan konteks terisolasi |

Skema tool ini tetap terdaftar di registry agar ikut `get_tool_definitions`, tetapi
handler registry-nya mengembalikan error bila dipanggil langsung.

## Callback

`AIAgent` menyediakan callback agar setiap permukaan bisa menampilkan progres langsung.

| Callback | Kapan dipanggil | Dipakai oleh |
|---|---|---|
| `tool_progress_callback` | Sebelum dan sesudah tiap tool | Spinner CLI, pesan progres gateway |
| `tool_start_callback`, `tool_complete_callback` | Awal dan akhir tool | TUI, Desktop |
| `thinking_callback` | Model mulai atau berhenti berpikir | Indikator CLI |
| `reasoning_callback` | Model mengembalikan isi penalaran | Tampilan penalaran |
| `clarify_callback` | Tool `clarify` dipanggil | Prompt input CLI, pesan interaktif gateway |
| `step_callback` | Setelah tiap iterasi selesai | Pelacakan langkah gateway, ACP |
| `stream_delta_callback` | Tiap token streaming | Tampilan streaming |
| `tool_gen_callback` | Panggilan tool terurai dari stream | Pratinjau tool di spinner |
| `status_callback` | Perubahan keadaan | Pembaruan status ACP |

## Anggaran dan cadangan

### Anggaran iterasi

`agent/iteration_budget.py` berisi kelas `IterationBudget`: penghitung `consume()` dan
`refund()` yang aman antar-thread.

- `agent.max_turns` bernilai `null` secara bawaan, artinya tanpa batas. Komentar di `hermes_cli/config_defaults.py` menyebut alasannya: batas membuat tugas terpotong diam-diam di tengah jalan. Dokumen Hermes yang lebih lama masih menyebut angka 500; yang berlaku adalah kodenya.
- Tiap agent punya anggaran sendiri. Subagent dibatasi `delegation.max_iterations`, bawaan 250.
- Iterasi `execute_code` dikembalikan (`refund`) agar tidak menggerus anggaran.
- Saat anggaran terbatas habis, model mendapat satu **panggilan tambahan** tanpa tool untuk merangkum pekerjaan (`_budget_grace_call`).
- `agent.run_budget_seconds` memberi batas waktu dinding per giliran; pada 80% model menerima pemberitahuan untuk menutup pekerjaan.

### Klasifikasi error dan pemulihan

`agent/error_classifier.py` mengubah setiap kegagalan API menjadi `ClassifiedError`
dengan `reason` bertipe `FailoverReason` dan empat petunjuk pemulihan: `retryable`,
`should_compress`, `should_rotate_credential`, `should_fallback`. Loop retry membaca
petunjuk itu, tidak mengklasifikasi ulang.

Alasan yang paling penting:

| `FailoverReason` | Pemicu | Tindakan |
|---|---|---|
| `auth` | 401 atau 403 sementara | Segarkan kredensial atau rotasi |
| `billing` | 402 atau kredit habis | Rotasi segera |
| `rate_limit` | 429 | Mundur lalu rotasi |
| `overloaded`, `server_error` | 503, 529, 500, 502 | Mundur dan coba lagi |
| `timeout` | Batas waktu koneksi | Bangun ulang klien lalu coba lagi |
| `context_overflow`, `payload_too_large` | Konteks terlalu besar, 413 | Kompres, bukan pindah penyedia |
| `model_not_found` | 404 atau model tidak valid | Pindah ke model cadangan |
| `content_policy_blocked` | Filter keamanan penyedia | Jangan ulangi tanpa perubahan |
| `format_error` | 400 | Batalkan atau buang bagian bermasalah lalu coba lagi |
| `unknown` | Tidak terklasifikasi | Coba lagi dengan mundur |

### Model cadangan

`fallback_providers` di konfigurasi berisi daftar pasangan `(provider, model)` yang
dicoba berurutan. Aktivasi (`try_activate_fallback()` di
`agent/chat_completion_helpers.py`) mengganti `model`, `provider`, `base_url`,
`api_mode`, dan klien secara langsung pada agent, mengevaluasi ulang cache prompt, lalu
mengulang iterasi. Cadangan dipicu dari tiga tempat: retry habis pada respons tidak
valid, error klien yang tidak bisa diulang (401, 403, 404), dan retry habis pada error
sementara (429, 500, 502, 503).

Subagent mewarisi provider induknya tetapi tidak mewarisi konfigurasi cadangan.

## Delegasi ke subagent

`tools/delegate_tool.py` membuat `AIAgent` anak dengan konteks dan sesi terminal
terisolasi. Induk menunggu ringkasan, kecuali `background=true`.

- Bentuk tunggal: `goal`, ditambah `context` dan `toolsets` opsional.
- Bentuk batch: `tasks: [...]`, dibatasi `delegation.max_concurrent_children` (bawaan 10).
- Peran `leaf` (bawaan): tidak punya `delegate_task`, `clarify`, `memory`, `cronjob`.
- Peran `orchestrator`: boleh mendelegasikan lagi, dibatasi `delegation.max_spawn_depth` (bawaan 1, artinya datar; 2 berarti orkestrator ke leaf).
- Proses latar milik anak dimatikan saat anak selesai.
- Delegasi latar hanya hidup selama proses. Pekerjaan yang harus bertahan melewati restart memakai cron.

## Kompresi dan penyimpanan

- **Pra-giliran**: bila percakapan melewati ambang (`compression.threshold`, bawaan 0,50 dari jendela konteks, dengan lantai 0,75 untuk model berjendela di bawah 512 ribu token), kompres sebelum memanggil API.
- **Kebersihan sesi gateway**: ambang 85%, berjalan di antara giliran sebagai jaring pengaman.
- Kompresi adalah satu-satunya mutasi konteks yang direstui. Rinciannya di [03-prompt-dan-cache.md](03-prompt-dan-cache.md).

Setelah tiap giliran: pesan disimpan ke SQLite, perubahan memori ditulis ke
`MEMORY.md` dan `USER.md`, dan sesi bisa dilanjutkan dengan `/resume` atau
`hermes chat --resume`.

## Yang perlu ditiru persis

1. Format pesan internal OpenAI sebagai satu-satunya bahasa di dalam inti.
2. Aturan selang-seling peran, diperiksa oleh test.
3. Pola fase dengan verdict, supaya loop tidak menjadi satu fungsi raksasa.
4. Simpan pesan asisten sebelum tool berjalan.
5. Hasil tool paralel dikembalikan sesuai urutan panggilan.
6. Tabel untuk tool tingkat agent, bukan rantai `if`.
7. Klasifikasi error menjadi petunjuk pemulihan yang dibaca loop.

## Rujukan di Hermes

`run_agent.py`, `agent/agent_init.py`, `agent/conversation_loop.py`, `agent/turn_*.py`,
`agent/tool_executor.py`, `agent/tool_dispatch_helpers.py`,
`agent/inline_tool_executors.py`, `agent/iteration_budget.py`,
`agent/error_classifier.py`, `tools/delegate_tool.py`, `agent/AGENTS.md`,
`website/docs/developer-guide/agent-loop.md`.
