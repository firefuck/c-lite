# runtime: aturan kerja

Yang dipakai bersama semua surface: `build_agent`, `ChatSession`, slash command. Spesifikasi:
`docs/spesifikasi/runtime.md`.

Tes: `pytest tests/runtime -q`

## Aturan yang tidak boleh dilanggar

1. **Surface tidak saling mengimpor.** Bila `cli`, `rpc`, `gateway`, atau `server` butuh kode
   yang sama, pindahkan ke sini. Dijaga `tests/test_architecture.py`.
2. **Setiap `AIAgent` untuk surface dibuat lewat `build_agent`.** Jangan membuat `AIAgent`
   langsung di surface: plugin, tool, MCP, dan toolset platform akan terlewat.
3. **Handler perintah tidak mencetak dan tidak membaca input.** Ia mengembalikan
   `SlashResult`. Ia berjalan di CLI, TUI, desktop, dan Telegram sekaligus.
4. **Satu perintah, satu baris di `COMMAND_REGISTRY`, satu `_handle_<nama>`.**
5. **Tidak ada import dari `cli`, `rpc`, `server`, `gateway`.**

## Resep

### Menambah slash command

1. Tambahkan `CommandDef(...)` ke `COMMAND_REGISTRY` (`commands.py`). Pilih kategori,
   `args_hint`, `cli_only` bila butuh terminal lokal, dan `busy_policy=BUSY_ALLOW` hanya bila
   aman dijalankan saat giliran berlangsung.
2. Tulis `def _handle_<nama>(session: ChatSession, args: str) -> SlashResult` di `slash.py`.
   Tabel `SLASH_HANDLERS` dibangun otomatis dari nama fungsi.
3. Logika yang menyentuh agent sebaiknya menjadi method `ChatSession`, dan handler hanya
   memanggilnya dan menyusun teks.
4. Tes di `tests/runtime/test_session_and_slash.py` dengan fixture `make_session`.
5. `python scripts/gen_docs.py`. Perintah langsung tersedia di CLI, TUI, dashboard, dan
   gateway.

### Menambah opsi sesi yang berlaku di semua surface

Tambahkan parameter ke `build_agent` dan `ChatSession.__init__`, lalu buka di tiap surface
yang perlu: `cli/subcommands/chat.py` (flag), `rpc/contracts/schema.py`
(`SessionCreateParams`), `gateway/runner.py`.

## Jebakan

- `ChatSession._options` menyimpan pilihan pembuatan agent supaya `/new` dan `/reload`
  membangun agent yang setara. Opsi baru yang tidak disimpan di sana akan hilang setelah
  `/new`.
- `ChatSession.agent` diganti oleh `/new`, `/resume`, dan `/reload`. Jangan menyimpan
  referensi ke agent di surface; ambil dari `session.agent` setiap kali.
- `apply_setup` menulis `.env` dan config. Tes yang memakainya berjalan di home sementara
  (fixture `clite_home` otomatis).
