# Spesifikasi: cli

| | |
|---|---|
| Kode | `src/clite/cli/` |
| Tes | `tests/cli/` |
| Lapisan | 10 (teratas). Boleh mengimpor semua lapisan |
| Bedah Hermes | [08-cli](../hermes/08-cli.md) |

## Tanggung jawab

Perintah `clite`: sub-perintah untuk mengelola instalasi, dan REPL klasik untuk mengobrol.
CLI adalah satu-satunya surface yang selalu jalan: lewat SSH, di container, tanpa Node.

## Bagian-bagian

| File | Isi |
|---|---|
| `main.py` | Entry point, parser, pendaftaran sub-perintah bawaan dan dari plugin |
| `repl.py` | `Repl` (interaktif) dan `run_single_query` (`-q`) |
| `display.py` | Keluaran terminal: warna, baris progres tool, banner, skin |
| `subcommands/` | Satu modul per kelompok sub-perintah, masing-masing punya `register(subparsers)` |

Daftar lengkap sub-perintah ada di [katalog](../referensi/katalog.md).

## Kontrak

**Urutan startup** (`main`)
1. `-p/--profile` diproses lebih dulu, sebelum apa pun membaca home.
2. `.env` dimuat, lalu config, lalu logging untuk home itu.
3. Sub-perintah didaftarkan dari `SUBCOMMAND_MODULES` dan dari plugin yang aktif. Plugin yang
   rusak tidak mematahkan CLI, dan plugin tidak bisa mengganti perintah bawaan.
4. Config yang rusak hanya menjadi peringatan, supaya `clite config edit` dan `clite doctor`
   tetap bisa dipakai untuk memperbaikinya.

**Kode keluar**: 0 sukses, 1 galat yang dilaporkan (`CliteError` atau giliran gagal), 2 salah
pakai (argumen, profil tak dikenal), 130 Ctrl+C.

**Satu pertanyaan (`-q`)**
- Hanya jawaban yang ke stdout. Progres tool ke stderr. `--json` mencetak `TurnResult`
  lengkap. `--quiet` mematikan progres.
- Tidak ada yang bisa ditanya: perintah berbahaya mengikuti `approvals.single_query_mode`
  (default tolak).

**REPL klasik**
- Pustaka standar saja (`input` dan `readline` bila ada). Riwayat di `<home>/.cli_history`,
  pelengkapan Tab untuk slash command.
- Ctrl+C saat agent bekerja menginterupsi giliran. Ctrl+C kedua dalam dua detik keluar.
- Persetujuan: `[o]nce [s]ession [a]lways [d]eny`. Jawaban kosong atau tak dikenal berarti
  tolak. Pertanyaan `clarify` dijawab dengan nomor atau teks.
- EOF (Ctrl+D) keluar dengan bersih dan mencetak cara melanjutkan sesi.

**Pemilihan antarmuka**
- `clite` tanpa argumen membuka REPL klasik. `display.interface: tui` membuatnya membuka TUI,
  tetapi hanya di terminal sungguhan dan hanya bila semua opsi yang diberikan dikenal TUI.
  `--tui` dan `--classic` memaksa untuk satu kali jalan.
- Tanpa Node.js atau tanpa bundle, `--tui` mengatakan apa yang kurang dan membuka REPL klasik
  dengan opsi yang sama.
- Semua argumen setelah `clite tui` diteruskan ke TUI apa adanya, termasuk `-h`.

**Skin**
- Tampilan adalah data. `display.skin` memilih skin bawaan (`default`, `mono`) atau file
  `<home>/skins/<nama>.yaml`.

**`clite doctor`**
- Memeriksa versi Python, home bisa ditulis, config valid, FTS5, provider terkonfigurasi
  (`--online` mencoba mengambil daftar model), backend terminal, plugin aktif bisa dimuat,
  shell hook yang menunggu persetujuan, dan Node.js. Kode keluar 1 bila ada masalah wajib.

## Status fitur

| Fitur | Status | Catatan |
|---|---|---|
| 21 sub-perintah tingkat atas | ✅ | |
| REPL klasik, `-q`, `--json`, lanjut sesi (`-r`, `-c`) | ✅ | |
| Mengetik saat agent bekerja | ⬜ | Hanya TUI yang bisa. REPL klasik membaca input setelah giliran selesai: F3-T1 |
| Input multi-baris, tempel gambar | ⬜ | F3-T1, F2-T6 |
| Render Markdown dan diff | ⬜ | Teks polos: F3-T2 |
| `clite setup` | 🟡 | Satu alur: provider, kunci, model. Wizard bertahap: F3-T5 |
| `clite acp` | ⬜ | Hanya mencetak penunjuk ke roadmap: F6-T4 |
| `clite update`, `backup`, `uninstall`, pelengkapan shell | ⬜ | F3-T6, F3-T7 |
| `clite auth`, `clite mcp`, `clite webhook` | ⬜ | F2-T14, F2-T10, F4-T10 |

## Yang sengaja berbeda dari Hermes

- **Tanpa `prompt_toolkit` dan `rich`.** REPL klasik sengaja minimal; pengalaman kaya ada di
  TUI. Hermes menaruh ribuan baris TUI berbasis `prompt_toolkit` di `cli.py`.
- **Sub-perintah per modul** dengan `register()`, bukan satu `main.py` besar.

## Celah yang diketahui

- `clite config edit` membuka `$EDITOR`; tidak ada validasi setelah menyimpan selain yang
  dilakukan pembacaan berikutnya.
- Tidak ada pagar untuk `clite sessions delete` (tanpa konfirmasi).
