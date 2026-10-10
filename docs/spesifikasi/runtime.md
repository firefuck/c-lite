# Spesifikasi: runtime

| | |
|---|---|
| Kode | `src/clite/runtime/` |
| Tes | `tests/runtime/` |
| Lapisan | 7. Boleh mengimpor semua lapisan di bawahnya: `core`, `state`, `providers`, `skills`, `tools`, `agent`, `plugins`, `cron` |
| Bedah Hermes | [08-cli](../hermes/08-cli.md) (registry slash command) |

## Tanggung jawab

Semua yang dipakai bersama oleh setiap surface di atas agent. Aturannya: bila dua surface
membutuhkan kode yang sama, kode itu tinggal di sini, bukan di salah satu surface.

## Bagian-bagian

| File | Isi |
|---|---|
| `factory.py` | `build_agent`: satu-satunya tempat surface membuat `AIAgent` |
| `batch.py` | `run_batch`: banyak prompt tanpa pengawasan, hasil per baris di disk |
| `trajectory.py` | `build_trajectory`: bentuk ekspor percakapan yang diredaksi |
| `session.py` | `ChatSession`: satu percakapan sebagaimana dilihat surface; `TurnQueue`: antrean giliran bersama |
| `commands.py` | `COMMAND_REGISTRY`: tabel slash command |
| `slash.py` | Handler slash command (`_handle_<nama>`) |
| `presentation.py` | Pratinjau tool dan deteksi hasil gagal, dipakai semua surface |
| `setup.py` | `apply_setup`: menyimpan pilihan provider dan kunci |
| `maintenance.py` | Pekerjaan rumah saat surface mulai (auto-prune sesi, kurator skill) |

## Kontrak

**`build_agent`**
- Memuat plugin dan menemukan tool sebelum daftar tool diresolusi, menyambungkan server MCP
  bila ada, lalu membuat `AIAgent`.
- Toolset default per platform: entri `platform_toolsets` bila ada; kalau tidak, surface lokal
  (`cli`, `tui`, `desktop`, `api`, `acp`) memakai `toolsets` dari config, `cron` dan `batch`
  memakai `clite-cron`, platform pesan memakai `clite-gateway`. Platform pesan tidak pernah
  diam-diam mewarisi toolset terminal pengguna. `batch` sengaja tidak mendapat toolset lokal:
  tidak ada orang yang bisa ditanya dan tidak ada yang menjadwalkan pekerjaan baru dari dalam
  batch.
- `yolo=True` berarti `approval_mode="off"` untuk agent itu.
- Menjalankan `run_startup_maintenance` sekali per proses dan home; kegagalannya tidak pernah
  menghalangi sesi. Langkahnya: auto-prune sesi, pangkas checkpoint, lalu kurator skill
  (`run_curator_maintenance`, paling banyak sekali per `curator.interval_hours`, lewat cap
  waktu di database seperti auto-prune; `curator.enabled` mematikannya).

**`run_batch`** (`batch.py`)
- Berkas batch adalah JSONL: satu objek per baris, kunci yang dikenal `id`, `prompt`, `model`,
  `provider`, `toolsets`. `id` default `line-<nomor>`; `id` ganda ditolak. Setiap masalah
  menyebut barisnya, dan tak satu pun prompt dijalankan sebelum seluruh berkas terbaca bersih.
- Tiap baris berjalan di sesinya sendiri lewat `build_agent(platform="batch", ...)` dengan
  `auto_title=False` dan judul sesi dari `id`. Satu baris yang gagal tidak menghentikan batch:
  kegagalan dicatat sebagai `status="failed"` lalu batch lanjut.
- Kebijakan non-interaktif platform `batch` adalah `approvals.single_query_mode` (default
  `deny`), bukan `approvals.cron_mode`: batch tidak pernah memberi persetujuan sendiri.
- Hasil ditambahkan ke `results.jsonl` di direktori keluaran begitu satu baris selesai, di
  bawah kunci tulis, jadi urutan selesai tidak mengubah isi berkas. Menjalankan ulang berkas
  yang sama melewati baris ber-`status="completed"` dan mencoba lagi yang gagal; baris terakhir
  yang separuh tertulis (run terputus) diabaikan sehingga baris itu jalan lagi.
- Isi catatan hasil diredaksi (`core.redact`): prompt, jawaban akhir, dan galat. Bentuknya ada
  di [04-format-data.md](../arsitektur/04-format-data.md#berkas-batch).
- Aman dijalankan dengan beberapa pekerja. Registry transport
  (`providers/transports/base.py`) memuat transport bawaannya di bawah kunci dan menandai
  "sudah dimuat" di akhir, bukan di awal: dua agent yang dibangun bersamaan dulu bisa membaca
  registry yang belum terisi. Dijaga `tests/providers/test_transports.py`.

**`build_trajectory`** (`trajectory.py`)
- Menghasilkan satu dokumen `{"format": "clite-trajectory/1", "session": {...}, "steps": [...]}`.
- Hanya pesan percakapan yang masuk: pesan `system` dan pesan bertanda `internal` dilewati,
  begitu juga kunci penyimpanan seperti `_row_id` dan `provider_data`.
- Setiap nilai teks diredaksi, termasuk judul sesi: judul ditulis dari pesan pertama pengguna,
  dan di situlah kunci yang ditempelkan berakhir.
- Bentuk langkah dan tool call ada di
  [04-format-data.md](../arsitektur/04-format-data.md#lintasan-sesi).

**`ChatSession`**
- Memegang satu `AIAgent` dan semua yang dilakukan surface di sekitarnya: `submit`,
  `handle_input`, `run_slash`, `interrupt`, `steer`, `new_session`, `resume`, `reload`,
  `switch_model`, `set_yolo`, `undo`, `set_title`, `info`, `close`.
- `handle_input` membedakan prompt dari perintah. Perintah yang menghasilkan prompt (skill,
  `/retry`) mengembalikan `action="submit"`.
- Urutan resolusi perintah: bawaan, plugin, quick command dari config, skill, prompt MCP.
- Prompt server MCP (`mcp-<server>-<prompt>`) dikirim sebagai pesan pengguna, seperti skill:
  isinya diambil lewat `prompts/get` saat itu, jadi system prompt tidak pernah berubah.
- `/mcp` menampilkan status tiap server MCP (transport, hidup/mati, jumlah tool/resources/prompts).
- `/new` mempertahankan model yang sedang dipakai dan memulai sesi kosong.
- `/resume` menerima id, awalan id, atau judul.
- `/undo` menonaktifkan giliran pengguna terakhir dan semua setelahnya. `/retry` adalah undo
  lalu kirim ulang. Keduanya melewati pesan `internal` yang ditulis agent sendiri.
- `/model` mengganti model untuk sesi; `--global` juga menyimpannya ke config.
- `/image <path>` (alias `/attach`) mengantre gambar untuk pesan berikutnya; dengan teks
  setelah path, gambar dan teks dikirim dalam satu giliran. Path yang tidak ada dilaporkan
  langsung, bukan saat giliran dikirim.
- `/reload` memuat ulang config dan plugin, mempertahankan percakapan, dan membangun ulang
  system prompt (satu kali cache miss).
- `/branch [judul]` menyalin pesan aktif ke sesi baru tanpa `provider_data` (awalan percakapan
  berubah bagi sesi baru, jadi blok penalaran bertanda tangan induk tidak berlaku lagi),
  mencatat `parent_session_id`, dan berpindah ke sesi baru itu. Judul default mengikuti judul
  induk dengan akhiran `(branch)`.
- `/queue <teks>` menitipkan pesan ke giliran yang sedang berjalan lewat catatan agent; ia
  menempel pada hasil tool berikutnya atau menjadi pesan internal, tidak pernah menyisip ke
  pesan yang sudah terkirim. `/background <teks>` menjalankan satu giliran di sesi baru
  (`_build` sendiri) dan melaporkan hasilnya tanpa menyentuh percakapan ini.
- `/export [path]` menulis transkrip yang terlihat (tanpa pesan `internal`) sebagai Markdown
  atau JSON menurut ekstensi; tanpa path, ke direktori kerja dengan nama sesi.
- `/context` memecah jendela: token terpakai, peringkat prompt, skema tool, dan riwayat.
  `/tasks` menampilkan daftar `todo` sesi (`agent.todos.read()` dan `summary()`).
- `/hooks` menampilkan shell hook dari `plugins.shell_hooks.configured_hooks` dan mana yang
  menunggu persetujuan (`is_approved`).
- `/pin` dan `/archive` menandai baris sesi lewat `SessionDB.update_session(pinned=/archived=)`.
- `/verbose [off|new|all|verbose|message]` menetapkan `display.tool_progress` untuk sesi ini (dan
  menyimpannya ke config). `/skin`, `/logs`, dan `/copy` hanya untuk terminal lokal
  (`cli_only`): handler mengembalikan teks atau `action="clipboard"`, dan surface CLI yang
  menulis ke clipboard dan mengganti tema.
- Quick command bertipe `exec` berjalan tanpa model dan tanpa gerbang persetujuan: pengguna
  sendiri yang menulisnya ke config.
- Perintah `cli_only` ditolak di platform pesan.

**`TurnQueue`** (antrean giliran bersama)
- Satu implementasi untuk semua surface yang menerima masukan saat giliran berjalan: REPL
  klasik, `RpcSession`, dan gateway. Sebelumnya logika ini hanya ada di `RpcSession` (F3-T1).
- `TurnQueue(session, run, *, merge_bursts=False, thread_name=...)`: baris pertama saat idle
  memulai satu thread pekerja yang menguras antrean; surface tetap membaca masukan.
- `submit(turn, mode)` mengembalikan `started`/`queued`/`steered`/`rejected` sesuai
  `display.busy_input_mode`: `interrupt` (default) menyela giliran yang jalan, `steer`
  menyisipkan arahan tanpa menyela, `queue` mengantre, `reject` menolak dengan pesan.
- `busy` benar selama sesi sibuk atau thread pekerja hidup; `join`/`clear`/`pending` dipakai
  surface untuk menutup dengan rapi. `Turn` membawa `id`, `text`, dan `payload` (gambar untuk
  RPC, sumber untuk gateway).

**Registry perintah**
- Setiap perintah dideklarasikan sekali di `COMMAND_REGISTRY`. Teks bantuan, pelengkapan,
  katalog RPC, dan dispatch di semua surface dibangun dari tabel itu.
- Setiap `CommandDef` punya handler `_handle_<nama>` di `slash.py`, dan sebaliknya. Dijaga tes.
- `busy_policy` menentukan apakah perintah boleh jalan saat giliran berlangsung (`/stop`,
  `/steer`, `/status`, `/usage`, `/help`, `/quit`).

## Status fitur

| Fitur | Status | Catatan |
|---|---|---|
| `build_agent`, toolset per platform | ✅ | |
| `ChatSession` | ✅ | |
| 44 slash command | ✅ | Hermes punya 102. Tambahan: F3-T4 |
| Quick command (`exec`, `alias`) | ✅ | |
| Skill dan perintah plugin sebagai slash command | ✅ | |
| Auto-prune sesi | ✅ | |
| Kurator skill terjadwal | ✅ | `run_curator_maintenance` mengarsipkan skill buatan agent yang basi paling banyak sekali per `curator.interval_hours`; kegagalannya tidak menghalangi sesi. Dijaga `tests/agent/test_review.py`. F2-T12 |
| Checkpoint file: `/rollback`, `/checkpoints` | ✅ | `ChatSession.rollback_files` dan `list_file_checkpoints` memanggil `tools/checkpoints.py`; perintah tersedia di semua surface. Perubahan lewat perintah `terminal` tidak tercatat (lihat spesifikasi agent dan tools). Dijaga `tests/tools/test_checkpoints.py`. F2-T8 |
| Percabangan sesi (`/branch`), `/queue`, `/background`, `/export`, `/context`, `/tasks`, `/hooks`, `/pin`, `/archive`, `/verbose`, `/skin`, `/logs`, `/copy` | ✅ | F3-T4: dua belas perintah baru; `/branch` menyalin pesan aktif tanpa `provider_data` dan mencatat `parent_session_id`. Dijaga `tests/runtime/test_session_and_slash.py` |
| `/insights` | ✅ | Menampilkan analitik pemakaian: token dan biaya per model/hari, tool populer, dan sesi per platform; subagent diatribusikan ke induknya. Juga tersedia lewat `clite insights` (`--json`). Dijaga `tests/state/test_db.py` dan `tests/runtime/test_session_and_slash.py`: F3-T8 |
| Antrean giliran bersama (`TurnQueue`) untuk masukan saat sibuk | ✅ | F3-T1: dipakai REPL klasik, `RpcSession`, dan gateway; dijaga `tests/runtime/test_session_and_slash.py` |
| Batch runner dan ekspor lintasan | ✅ | F6-T8: `run_batch` (platform `batch`, bisa dilanjutkan, satu baris gagal tidak menghentikan sisanya) dan `build_trajectory` (diredaksi, tanpa pesan internal maupun `provider_data`). Dijaga `tests/runtime/test_batch.py` |

## Yang sengaja berbeda dari Hermes

- **Lapisan `runtime` eksplisit.** Di Hermes logika bersama tersebar di `cli.py`,
  `hermes_cli/`, dan `tui_gateway/`, dan setiap surface membuat agent dengan caranya sendiri.
  Di sini CLI, RPC, gateway, dan cron semuanya lewat `build_agent` dan `ChatSession`.
- **Handler perintah mengembalikan `SlashResult`** (teks, aksi, data), tidak mencetak. Surface
  yang memutuskan cara menampilkan.

## Celah yang diketahui

- `ChatSession` tidak aman dipakai dari dua thread sekaligus untuk operasi yang mengganti
  agent (`/new`, `/resume`, `/reload`). Sejak F3-T1 satu `TurnQueue` menjaga satu giliran
  berjalan pada satu waktu dan menegakkan `display.busy_input_mode` sama di semua surface;
  perintah yang menyentuh sesi harus menunggu giliran (kecuali yang `BUSY_ALLOW`).
- Batch tidak punya batas waktu per baris. `agent.run_budget_seconds` masih kosong secara
  default, jadi satu prompt yang menggantung menahan pekerja yang menjalankannya sampai
  prosesnya dihentikan; berhenti di tengah aman karena hasil ditulis dan run bisa dilanjutkan.
- Catatan hasil batch belum memuat biaya, hanya token: mesin biaya F2-T3 belum ada. Bidangnya
  ditambahkan begitu mesin itu ada, bukan dihitung ulang di sini.
