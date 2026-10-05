# Format data

Bentuk data yang berpindah antar-bagian, dan bentuk setiap file yang ditulis agent. Yang bisa
dibaca dari kode (daftar kunci config, kolom tabel) hanya dirujuk, tidak disalin.

## Pesan

Format internal adalah gaya OpenAI Chat Completions. Riwayat (`agent.messages`) dan database
menyimpan bentuk ini. Transport mengonversinya ke protokol lain **pada salinan** saat mengirim.

| Kunci | Pada peran | Isi | Dikirim ke provider |
|---|---|---|---|
| `role` | semua | `user`, `assistant`, `tool` (`system` tidak pernah ada di riwayat) | ya |
| `content` | semua | String, atau daftar bagian konten (`[{"type": "text", ...}, ...]`) | ya |
| `tool_calls` | assistant | `[{"id", "type": "function", "function": {"name", "arguments"}}]`. `arguments` adalah **teks JSON** persis dari model | ya |
| `tool_call_id` | tool | Id tool call yang dijawab | ya |
| `name` | tool | Nama tool | ya |
| `finish_reason` | assistant | `stop`, `tool_calls`, `length`, `content_filter` | tidak |
| `reasoning` | assistant | Teks penalaran yang boleh ditampilkan | tidak |
| `provider_data` | assistant | Data buram yang diminta kembali provider yang sama (blok penalaran bertanda tangan) | hanya oleh transport yang mengenalnya |
| `turn_context` | user | Konteks giliran (ingatan, keluaran hook, pengingat). Digabung ke `content` saat mengirim | sebagai bagian dari `content` |
| `display_kind` | user | `internal` untuk pesan yang ditulis agent sendiri | tidak |
| `is_summary` | user/assistant | Menandai ringkasan hasil kompresi | tidak |
| `timestamp` | semua | Diisi saat disimpan | tidak |
| `_row_id` | semua | Id baris di database. Hanya di memori; jangan disalin ke pesan baru | tidak |

Contoh satu giliran dengan satu tool call, sebagaimana tersimpan:

```json
[
  {"role": "user", "content": "Ada berapa file Python di sini?",
   "turn_context": "<memory-context>...</memory-context>"},
  {"role": "assistant", "content": null, "finish_reason": "tool_calls",
   "tool_calls": [{"id": "call_1", "type": "function",
                   "function": {"name": "search_files", "arguments": "{\"pattern\": \"*.py\", \"target\": \"files\"}"}}]},
  {"role": "tool", "tool_call_id": "call_1", "name": "search_files",
   "content": "{\"files\": [\"a.py\", \"b.py\"], \"count\": 2, \"truncated\": false, \"root\": \"/home/user/project\"}"},
  {"role": "assistant", "content": "Ada dua: a.py dan b.py.", "finish_reason": "stop"}
]
```

Aturan:

- Pesan yang ditulis agent dengan peran `user` (permintaan "lanjutkan", permintaan penutup,
  catatan steer yang berdiri sendiri) dibuat dengan `internal_user_message(...)`. Transkrip
  untuk pengguna menyembunyikannya, dan `/undo` melewatinya.
- Kunci berawalan `_` tidak pernah keluar dari proses. `sanitize_for_api` membuangnya.
- Kunci baru pada pesan butuh tiga perubahan: kolom di `state/schema.py` (lewat
  `COLUMN_ADDITIONS`), pemetaan di `state/db.py`, dan keputusan apakah ia ikut ke kawat
  (`INTERNAL_MESSAGE_KEYS` di `providers/transports/base.py`).

## Definisi dan hasil tool

Definisi yang ditawarkan ke model berbentuk OpenAI, diurutkan menurut nama:

```json
{"type": "function",
 "function": {"name": "read_file", "description": "...",
              "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}}}
```

Handler menerima argumen sebagai satu `dict` dan mengembalikan **string JSON**:

| Hasil | Bentuk | Pembuat |
|---|---|---|
| Sukses | Objek JSON apa pun yang berguna bagi model | `tool_result(...)` |
| Galat | `{"error": "pesan yang menjelaskan cara memperbaiki"}`, boleh dengan kunci tambahan | `tool_error(...)` |
| Diblokir hook | `{"error": "...", "blocked": true}` | `handle_function_call` |
| Dibatalkan | `{"error": "cancelled: ..."}` | `run_tool_round` |

Pesan galat ditulis untuk model: sebutkan apa yang salah dan apa yang bisa dicoba. Model
membaca hasil itu dan memperbaiki panggilannya sendiri.

## Jawaban model dan hasil giliran

Setiap transport menormalkan jawaban provider menjadi `NormalizedResponse`
(`providers/transports/types.py`), sehingga loop tidak pernah bercabang menurut provider:

| Bidang | Isi |
|---|---|
| `content` | Teks jawaban, atau `None` |
| `tool_calls` | Daftar `ToolCall(id, name, arguments)` |
| `finish_reason` | `stop`, `tool_calls`, `length`, `content_filter` |
| `reasoning` | Teks penalaran, bila ada |
| `usage` | `Usage(input_tokens, output_tokens, cache_read_tokens, cache_write_tokens, reasoning_tokens)` |
| `provider_data` | Data buram untuk diputar ulang |

`Usage.input_tokens` **tidak** termasuk token yang dibaca dari cache. `Usage.prompt_tokens`
adalah jumlah semua yang dibaca model, dan itulah yang dibandingkan dengan jendela konteks.

Hasil satu giliran adalah `TurnResult` (`agent/state.py`): `final_response`, `completed`,
`interrupted`, `error`, `exit_reason`, `api_calls`, `usage`, `session_id`, `model`, `provider`,
`duration`, `messages` (pesan yang ditambahkan giliran itu). Nilai `exit_reason` ada di
[02-alur-giliran.md](02-alur-giliran.md#alasan-giliran-berakhir).

## Rute provider

`RuntimeRoute` (`providers/runtime.py`) adalah hasil resolusi "pengguna ingin model X":
`provider`, `model`, `api_mode`, `base_url`, `api_key`, `headers`, `profile`, `source`,
`credential`, `context_length`, `max_tokens`. Hanya `describe()` yang boleh dicatat di log atau
dikirim ke UI; ia tidak memuat kunci.

## File di home

Lokasi dan penulis setiap file ada di [spesifikasi core](../spesifikasi/core.md#isi-home).
Semua file JSON dan YAML ditulis secara atomik (`core.io`).

### `config.yaml` dan `.env`

`config.yaml` hanya memuat yang berbeda dari default. Daftar kunci dan defaultnya ada di
[katalog](../referensi/katalog.md#kunci-konfigurasi); penjelasan tiap kunci ada sebagai
komentar di `src/clite/core/config_defaults.py`.

```yaml
model:
  default: claude-fable-5-1
  provider: anthropic
toolsets: [clite-cli]
approvals:
  mode: smart
hooks:
  pre_tool_call:
    - command: "~/.clite/hooks/guard.py"
      matcher: "terminal"
      fail_closed: true
```

`.env` berisi `NAMA=nilai` per baris, hanya rahasia:

```
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=...
```

### `state.db`

SQLite dengan FTS5. Skema ada di `src/clite/state/schema.py`, kontraknya di
[spesifikasi state](../spesifikasi/state.md). Satu baris `messages` adalah satu pesan dalam
format di atas; `content` berstruktur disimpan sebagai JSON dengan `content_is_json=1`.

### `SKILL.md`

Frontmatter YAML diikuti isi Markdown. Format lengkap di
[spesifikasi skills](../spesifikasi/skills.md#format).

### `plugin.yaml`

```yaml
name: audit-log              # huruf kecil, angka, tanda hubung, garis bawah
version: 1.0.0
description: Record every tool call
kind: standalone             # standalone | backend | exclusive | platform | model-provider
manifest_version: 1
requires_env: [SOME_TOKEN]   # diperiksa sebelum kode plugin dijalankan
```

Di samping manifest ada `__init__.py` yang mendefinisikan `register(ctx)`.

### `cron/jobs.json`

Daftar job. Satu job:

```json
{"id": "a1b2c3d4", "name": "Laporan pagi", "prompt": "Ringkas commit kemarin.",
 "schedule": {"kind": "cron", "display": "0 9 * * 1-5", "run_at": null, "interval_seconds": null,
              "expr": "0 9 * * 1-5"},
 "schedule_display": "0 9 * * 1-5",
 "enabled": true, "deliver": "origin", "repeat": null,
 "model": null, "provider": null, "toolsets": null, "skills": [],
 "origin": {"platform": "telegram", "chat_id": "12345"},
 "created_at": 1759600000.0, "next_run_at": 1759654800.0,
 "last_run_at": null, "last_status": null, "last_error": null, "run_count": 0}
```

`schedule.kind` adalah `once` (memakai `run_at`), `interval` (memakai `interval_seconds`), atau
`cron` (memakai `expr`); bentuknya ditentukan `Schedule.to_dict()` di `cron/schedule.py`.
Keluaran tiap run
disimpan sebagai `cron/output/<id job>/<cap waktu>.md`.

### File gateway

| File | Bentuk |
|---|---|
| `gateway/sessions.json` | `{"<kunci sesi>": "<id sesi tersimpan>"}` |
| `gateway/pairing.json` | Empat kunci: `pending` (kode yang menunggu, per platform: `user_id`, `user_name`, `expires_at`), `approved` (pengguna yang disetujui, per platform), `requests` (waktu permintaan terakhir, untuk pembatasan laju), `failures` (percobaan salah dan `locked_until`, per platform) |

### `shell-hooks-allowlist.json`

`{"approvals": [{"event", "command", "approved_at"}]}`. Persetujuan berlaku untuk pasangan
event dan perintah yang persis sama. File ini tidak bisa ditulis lewat tool file.

### File skill

| File | Bentuk |
|---|---|
| `skills/.usage.json` | `{"<nama>": {"use_count", "created_by": "user" atau "agent", "created_at", "last_used_at"}}` |
| `skills/.hub/lock.json` | `{"<nama>": {"source", "identifier", "installed_at", "version"}}` |
| `skills/.archive/<nama>/` | Skill yang diarsipkan kurator, utuh |

### Memori bawaan

`memories/MEMORY.md` dan `memories/USER.md`: teks polos, entri dipisah baris berisi `§`.
Dibatasi `memory.memory_char_limit` dan `memory.user_char_limit` karakter.

## Kawat shell hook

Satu objek JSON di stdin perintah:

```json
{"hook_event_name": "pre_tool_call", "tool_name": "terminal",
 "tool_input": {"command": "rm -rf build"}, "session_id": "20261005_101500_ab12cd34",
 "cwd": "/home/user/project", "extra": {}}
```

Stdout opsional, satu objek JSON:

| Keluaran | Arti | Berlaku pada |
|---|---|---|
| `{"decision": "block", "reason": "..."}` atau `{"action": "block", "message": "..."}` | Blokir tool call | `pre_tool_call` |
| `{"decision": "modify", "tool_input": {...}}` | Ganti argumen | `pre_tool_call` |
| `{"context": "..."}` | Tempel ke pesan pengguna giliran ini | `pre_llm_call` |
| Kode keluar 2 | Blokir; stderr menjadi alasannya | `pre_tool_call` |

## Protokol RPC

Amplop, alur, dan kode galat ada di [05-protokol-rpc.md](05-protokol-rpc.md). Daftar method dan
event ada di [katalog](../referensi/katalog.md#protokol-json-rpc-versi-1).

## File yang dihasilkan build

| File | Dibuat oleh | Dijaga oleh |
|---|---|---|
| `apps/shared/src/contracts.generated.ts` | `scripts/gen_rpc_contracts.py` | `test_typescript_contracts_match_the_python_contracts` |
| `docs/referensi/katalog.md`, `docs/referensi/peta-modul.md` | `scripts/gen_docs.py` | `test_generated_reference_pages_are_current` |
| `src/clite/tui_dist/clite-tui.mjs`, `src/clite/tui_dist/build-info.json` | `ui-tui/build.mjs` | `test_the_committed_bundle_was_built_from_the_current_sources` |

Ketiganya di-commit. Mengubah sumbernya tanpa menjalankan ulang pembuatnya menggagalkan suite.
