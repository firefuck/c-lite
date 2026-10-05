# cli: aturan kerja

Perintah `clite` dan REPL klasik. Spesifikasi: `docs/spesifikasi/cli.md`.

Tes: `pytest tests/cli -q`

## Aturan yang tidak boleh dilanggar

1. **CLI hanya menerjemahkan.** Logika percakapan ada di `runtime.ChatSession`; logika slash
   command ada di `runtime/slash.py`. Sub-perintah memanggil fungsi dari lapisan bawah dan
   mencetak hasilnya.
2. **Pustaka standar saja di jalur REPL klasik.** Ia harus jalan di mana pun Python jalan.
3. **Stdout untuk hasil, stderr untuk progres dan peringatan.** `clite -q "..." | jq` harus
   tetap bekerja.
4. **Pesan galat mengatakan apa yang harus dilakukan.** "No model provider is configured.
   Run `clite setup` ..." bukan "provider is None".
5. **Keluaran dalam bahasa Inggris.** Dokumen proyek berbahasa Indonesia; antarmuka dan
   kode berbahasa Inggris.
6. **Profil diproses pertama.** Entry point baru memanggil `apply_profile_override` sebelum
   membaca apa pun dari home.

## Resep

### Menambah sub-perintah

1. Buat `subcommands/<nama>.py` dengan fungsi `run_*(args) -> int` dan
   `register(subparsers)`. Contoh ringkas: `subcommands/hooks.py`.
2. Tambahkan nama modul ke `SUBCOMMAND_MODULES` (`subcommands/__init__.py`). `main.py` tidak
   berubah.
3. Kembalikan 0 untuk sukses dan 1 untuk kegagalan yang dilaporkan. Lempar `CliteError` untuk
   galat yang cukup dicetak tanpa traceback.
4. Tes di `tests/cli/test_cli.py` dengan fixture `cli` (menjalankan `main([...])` di dalam
   proses dan mengembalikan stdout).
5. `python scripts/gen_docs.py`.

### Menambah flag ke `clite chat`

Tambahkan di `add_chat_arguments` (`subcommands/chat.py`), teruskan lewat `session_options`,
dan pastikan `ChatSession` menerimanya. Bila TUI juga perlu, tambahkan ke
`subcommands/tui.py::tui_arguments` dan ke `ui-tui/src/entry.ts`; kalau tidak, tambahkan ke
syarat di `wants_tui`.

## Jebakan

- `argparse.REMAINDER` berhenti di argumen pertama yang mirip opsi. Perintah yang meneruskan
  argumennya ke program lain memakai `accepts_extra_args` (lihat `subcommands/tui.py`).
- Tes memanggil `main()` di dalam proses: jangan memanggil `sys.exit` di handler, kembalikan
  kode keluar.
- `Repl` menerima `input_fn` supaya tes bisa menyuapi masukan. Jangan memanggil `input()`
  langsung.
