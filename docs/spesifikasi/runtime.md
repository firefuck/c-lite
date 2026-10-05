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
| `session.py` | `ChatSession`: satu percakapan sebagaimana dilihat surface |
| `commands.py` | `COMMAND_REGISTRY`: tabel slash command |
| `slash.py` | Handler slash command (`_handle_<nama>`) |
| `presentation.py` | Pratinjau tool dan deteksi hasil gagal, dipakai semua surface |
| `setup.py` | `apply_setup`: menyimpan pilihan provider dan kunci |
| `maintenance.py` | Pekerjaan rumah saat surface mulai (auto-prune sesi) |

## Kontrak

**`build_agent`**
- Memuat plugin dan menemukan tool sebelum daftar tool diresolusi, menyambungkan server MCP
  bila ada, lalu membuat `AIAgent`.
- Toolset default per platform: entri `platform_toolsets` bila ada; kalau tidak, surface lokal
  (`cli`, `tui`, `desktop`, `api`, `acp`) memakai `toolsets` dari config, `cron` memakai
  `clite-cron`, platform pesan memakai `clite-gateway`. Platform pesan tidak pernah diam-diam
  mewarisi toolset terminal pengguna.
- `yolo=True` berarti `approval_mode="off"` untuk agent itu.
- Menjalankan `run_startup_maintenance` sekali per proses dan home; kegagalannya tidak pernah
  menghalangi sesi.

**`ChatSession`**
- Memegang satu `AIAgent` dan semua yang dilakukan surface di sekitarnya: `submit`,
  `handle_input`, `run_slash`, `interrupt`, `steer`, `new_session`, `resume`, `reload`,
  `switch_model`, `set_yolo`, `undo`, `set_title`, `info`, `close`.
- `handle_input` membedakan prompt dari perintah. Perintah yang menghasilkan prompt (skill,
  `/retry`) mengembalikan `action="submit"`.
- Urutan resolusi perintah: bawaan, plugin, quick command dari config, skill.
- `/new` mempertahankan model yang sedang dipakai dan memulai sesi kosong.
- `/resume` menerima id, awalan id, atau judul.
- `/undo` menonaktifkan giliran pengguna terakhir dan semua setelahnya. `/retry` adalah undo
  lalu kirim ulang. Keduanya melewati pesan `internal` yang ditulis agent sendiri.
- `/model` mengganti model untuk sesi; `--global` juga menyimpannya ke config.
- `/reload` memuat ulang config dan plugin, mempertahankan percakapan, dan membangun ulang
  system prompt (satu kali cache miss).
- Quick command bertipe `exec` berjalan tanpa model dan tanpa gerbang persetujuan: pengguna
  sendiri yang menulisnya ke config.
- Perintah `cli_only` ditolak di platform pesan.

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
| 27 slash command | ✅ | Hermes punya 102. Tambahan: F3-T4 |
| Quick command (`exec`, `alias`) | ✅ | |
| Skill dan perintah plugin sebagai slash command | ✅ | |
| Auto-prune sesi | ✅ | |
| Percabangan sesi (`/branch`), `/rollback`, `/background`, `/queue` | ⬜ | F3-T4 |
| `/insights` | ⬜ | F3-T8 |

## Yang sengaja berbeda dari Hermes

- **Lapisan `runtime` eksplisit.** Di Hermes logika bersama tersebar di `cli.py`,
  `hermes_cli/`, dan `tui_gateway/`, dan setiap surface membuat agent dengan caranya sendiri.
  Di sini CLI, RPC, gateway, dan cron semuanya lewat `build_agent` dan `ChatSession`.
- **Handler perintah mengembalikan `SlashResult`** (teks, aksi, data), tidak mencetak. Surface
  yang memutuskan cara menampilkan.

## Celah yang diketahui

- `ChatSession` tidak aman dipakai dari dua thread sekaligus untuk operasi yang mengganti
  agent (`/new`, `/resume`, `/reload`). Surface yang mengizinkan masukan saat sibuk
  (`RpcSession`, gateway) menanganinya dengan kebijakan sibuk mereka sendiri.
