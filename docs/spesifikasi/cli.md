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
| `input.py` | Pembaca baris: `prompt_toolkit` bila ada (extra `clite[cli]`), fallback pustaka standar; input multi-baris, tempel berkurung, pelengkapan |
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
- `--image <path>` (boleh berulang) melampirkan gambar pada prompt. Path yang salah atau
  gambar yang terlalu besar menghasilkan galat di stderr dan kode keluar 1, bukan giliran yang
  gagal separuh.
- Tidak ada yang bisa ditanya: perintah berbahaya mengikuti `approvals.single_query_mode`
  (default tolak).

**REPL klasik**
- Dua jalur input. Dengan `prompt_toolkit` (extra `clite[cli]`) REPL memakai penyunting baris
  yang mempertahankan baris yang sedang diketik saat keluaran streaming datang, riwayat di
  `<home>/.cli_history`, pelengkapan Tab untuk perintah dan argumennya, input multi-baris, dan
  tempel berkurung. Tanpa `prompt_toolkit` REPL jatuh ke `input`/`readline` pustaka standar
  dengan perilaku yang sama seperti sebelumnya — jalur ini tetap didukung dan diuji.
- Giliran berjalan di thread pekerja; thread utama terus membaca masukan. Baris yang dikirim
  saat agent bekerja mengikuti `display.busy_input_mode` (`steer`, `interrupt`, `queue`,
  `reject`), sama seperti RPC dan gateway: ketiganya memakai antrean `runtime` yang sama.
  Perintah slash yang menyentuh sesi menunggu giliran selesai; `/stop` dan `/status` boleh
  jalan saat sibuk.
- Input multi-baris: akhiri baris dengan `\` (atau Alt+Enter di `prompt_toolkit`). Tempel
  berkurung (`bracketed paste`) masuk sebagai satu pesan, bukan sebagai beberapa giliran.
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

**`clite acp`**
- Menjalankan server ACP di atas stdin/stdout untuk editor; tidak menerima argumen. Stdout
  menjadi kawat protokol dan `sys.stdout` dialihkan ke stderr selama proses hidup, sehingga
  `print` nyasar tidak merusak aliran. Proses keluar ketika stdin ditutup.
- Yang belum ada dan yang sudah ada di [acp.md](acp.md).

**Distribusi dan versi**
- Distribusi bernama `c-lite` (MIT), sementara import dan perintah tetap `clite`.
- `src/clite/__init__.py` adalah sumber versi tunggal; metadata `pyproject.toml` membaca
  atribut itu. `scripts/release.py check --tag v0.1.0` memeriksa kecocokan calon tag dan
  changelog; tes juga menjalankan `clite --version`.
- Wheel/sdist diterbitkan melalui GitHub Releases saja. Rilis v0.1.0, unduhan
  terautentikasi, instalasi pipx, doctor mock dan smoke test telah diverifikasi (F1-T7).

## Status fitur

| Fitur | Status | Catatan |
|---|---|---|
| 28 sub-perintah tingkat atas | ✅ | |
| Versi CLI, metadata dinamis, dan calon tag konsisten | ✅ | `tests/test_release.py` |
| Distribusi `c-lite` melalui GitHub Releases | ✅ | F1-T7: workflow `37563420757`, aset terbit/pipx/doctor lulus |
| REPL klasik, `-q`, `--json`, lanjut sesi (`-r`, `-c`) | ✅ | |
| Mengetik saat agent bekerja | ✅ | F3-T1: giliran di thread pekerja, thread utama terus membaca; baris saat sibuk ikut `display.busy_input_mode` lewat antrean `runtime` bersama RPC dan gateway |
| Input multi-baris, tempel gambar | ✅ | F3-T1: multi-baris (`\` atau Alt+Enter) dan tempel berkurung lewat `prompt_toolkit`, dengan fallback pustaka standar. Tempel gambar: `clite chat --image` dan `/image` (F2-T6) |
| Render Markdown dan diff | ✅ | F3-T2: `cli/markdown.py` merender jawaban BERTAHAP saat mengalir (baris lengkap dirender, baris belum selesai ditahan), blok kode tidak pernah dibaca sebagai Markdown, tabel lebar dipotong sesuai lebar terminal. Diff `patch`/`write_file` berwarna per baris dengan batas panjang. Warna datang dari skin lewat `MarkdownStyle` (perender tidak mengeja kode warna sendiri); `NO_COLOR`, terminal dumb, dan keluaran dialihkan ke berkas menghasilkan teks polos. Dijaga `tests/cli/test_markdown.py` |
| `clite setup` | ✅ | Alur bertahap: provider, kunci (diuji dengan satu panggilan nyata; ditolak bila salah), model dari provider, toolset, dan opsi keselamatan/Telegram; flag non-interaktif menghasilkan config yang sama. Dijaga `tests/cli/test_cli.py`: F3-T5 |
| `clite acp` | ✅ | F6-T4: server ACP di stdio untuk editor. Handshake, `session/new`, `session/load`, giliran prompt (potongan pesan, tool call, permintaan izin, pembatalan, `plan`, daftar perintah) jalan dan diuji lewat pipa nyata. Belum pernah dicoba di editor sungguhan. Uraiannya di [acp.md](acp.md) |
| `clite update`, `backup`, `uninstall` | ✅ | Update mendeteksi cara pasang (git/pipx/pip) dan mengecek versi baru (`--check`); backup create membuat arsip home (rahasia hanya dengan `--include-secrets` mode 0600) dan restore memulihkan ke home baru; uninstall mencopot paket (`--purge` menghapus data home); ketiganya dijaga `detect_self_access`. Dijaga `tests/cli/test_cli.py`: F3-T6 |
| `clite completion bash`, `zsh`, `fish` | ✅ | Skrip pelengkapan dibangun dari parser `main` yang sama, jadi tiap sub-perintah dan opsi (termasuk dari plugin) selalu ikut; nilai dinamis lewat `clite completion --values profiles\|models\|sessions` yang cepat dan tidak memuat plugin. Dijaga `tests/cli/test_cli.py` (termasuk `bash -n`) |
| `clite auth`, `clite webhook` | ⬜ | F2-T14, F4-T10 |
| `clite serve token` | ✅ | `create` (mencetak nilainya sekali), `list`, `revoke`. Nilai disimpan sebagai hash di `<home>/tokens.json` dan tidak bisa dibaca lagi. F5-T6 |
| `clite mcp` | ✅ | `add`, `list`, `remove`, `test`. `add` menulis `mcp_servers` lewat `atomic_config_update` (komentar config tetap utuh); `test` menyambung sekali dan melaporkan tool, resources, dan prompts yang ditemukan. Dijaga `tests/tools/test_mcp.py`. F2-T10 |
| `clite batch run` | ✅ | F6-T8: menjalankan berkas JSONL tanpa pengawasan, `--workers N` pekerja, hasil per baris di `results.jsonl` (default `<nama-berkas>-out` di sebelah masukan). Berhenti lalu dijalankan lagi melanjutkan, bukan mengulang; baris yang gagal dicoba lagi dan kode keluarnya 1. Dijaga `tests/runtime/test_batch.py` |
| `clite sessions export --format {json,trajectory}` | ✅ | F6-T8: `trajectory` adalah bentuk yang diredaksi dan tanpa `provider_data` untuk evaluasi dan pelatihan; `json` (default) tetap transkrip apa adanya. Bentuknya di [04-format-data.md](../arsitektur/04-format-data.md#lintasan-sesi) |
| `/mcp` | ✅ | Menampilkan status tiap server MCP: transport, hidup/mati, jumlah tool/resources/prompts, dan catatan bila daftar toolnya berubah untuk sesi berikutnya. F2-T10 |

## Yang sengaja berbeda dari Hermes

- **`prompt_toolkit` opsional, bukan wajib.** REPL klasik tetap minimal dan jalan dengan
  pustaka standar saja; penyuntingan baris yang lebih kaya (`prompt_toolkit`) adalah extra
  `clite[cli]`, bukan ketergantungan inti. Pengalaman kaya penuh ada di TUI. Hermes menaruh
  ribuan baris TUI berbasis `prompt_toolkit` di `cli.py` sebagai satu-satunya jalur.
- **Sub-perintah per modul** dengan `register()`, bukan satu `main.py` besar.

## Celah yang diketahui

- `clite config edit` membuka `$EDITOR`; tidak ada validasi setelah menyimpan selain yang
  dilakukan pembacaan berikutnya.
- Tidak ada pagar untuk `clite sessions delete` (tanpa konfirmasi).
