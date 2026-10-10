# Fase 3: CLI dan TUI

Fase ini memperbaiki pengalaman di terminal. Dua aturan dari arsitektur menentukan bentuknya:

- **Yang dipakai dua surface tinggal di `runtime`.** Slash command baru otomatis tersedia di
  CLI, TUI, dashboard, dan chat. Jangan menulis logika perintah di dalam REPL atau TUI.
- **TUI hanya berbicara lewat protokol RPC.** Bila TUI butuh data, tambahkan method RPC;
  jangan membaca file di home dari TypeScript.

Aturan yang berlaku untuk semua task ada di [README](README.md#selesai-itu-apa).

---

### F3-T1 Input REPL klasik: saat sibuk, multi-baris, riwayat

**Tujuan.** Di REPL klasik pengguna bisa mengetik selagi agent bekerja, menulis pesan
beberapa baris, dan menempel teks panjang tanpa terkirim sepotong-sepotong.

**Lingkup.**
- Giliran berjalan di thread pekerja; thread utama terus membaca masukan. Baris yang dikirim
  saat sibuk mengikuti `display.busy_input_mode`, sama seperti di RPC dan gateway. Pindahkan
  logika antrean dari `RpcSession` ke `runtime` supaya ketiga surface memakai kode yang sama.
- Masukan multi-baris (Alt+Enter atau baris berakhiran `\`) dan tempel berkurung
  (bracketed paste).
- Keluaran streaming tidak boleh merusak baris yang sedang diketik. Ini butuh pustaka
  terminal: tambahkan `prompt_toolkit` sebagai extra (`clite[cli]`), dan pertahankan REPL
  pustaka standar sebagai jalur cadangan yang tetap diuji.
- Pelengkapan Tab untuk argumen perintah (nama model, nama skill, id sesi) dari katalog yang
  sudah ada.

**File.** `src/clite/cli/repl.py`, `src/clite/cli/input.py (baru)`,
`src/clite/runtime/session.py`, `src/clite/rpc/session.py`, `pyproject.toml`,
`tests/cli/test_cli.py`, `tests/runtime/test_session_and_slash.py`.

**Rujukan Hermes.** `cli.py` (REPL berbasis `prompt_toolkit`), `hermes_cli/commands.py`
(pelengkapan).

**Selesai bila.**
- [x] Tes: baris yang masuk saat giliran berjalan diantrekan, menginterupsi, atau
      mengarahkan, sesuai mode, lewat `ChatSession` (`tests/runtime/test_session_and_slash.py`,
      `tests/cli/test_cli.py`).
- [x] Tes RPC dan gateway untuk mode sibuk tetap lulus setelah logikanya dipindah
      (`TurnQueue` di `runtime/session.py`; `tests/rpc`, `tests/gateway` hijau).
- [x] Tanpa `prompt_toolkit`, REPL tetap jalan dengan perilaku sekarang (jalur `StdlibReader`;
      seluruh `tests/cli` lulus dengan `prompt_toolkit` disembunyikan).
- [x] Baris "Mengetik saat agent bekerja" dan "Input multi-baris" di spesifikasi cli menjadi ✅.

**Ukuran.** M

**Bergantung pada.** -

---

### F3-T2 Render Markdown dan diff

**Tujuan.** Jawaban tampil dengan judul, daftar, tabel, dan blok kode yang terbaca; hasil
`patch` tampil sebagai diff berwarna.

**Lingkup.**
- Perender Markdown ke teks ANSI yang bekerja **bertahap** pada teks streaming: baris yang
  sudah lengkap dirender, baris yang belum selesai ditahan.
- Diff berwarna untuk hasil `patch` dan `write_file`, dengan batas panjang.
- Skin menentukan warna; perender tidak mengeja kode warna sendiri.
- Fungsi murni tanpa I/O, supaya bisa diuji dengan membandingkan string. Padanan
  TypeScript-nya di `ui-tui/src/render.ts` memakai aturan yang sama.
- `NO_COLOR`, terminal `dumb`, dan keluaran yang dialihkan ke file menghasilkan teks polos.

**File.** `src/clite/cli/markdown.py (baru)`, `src/clite/cli/display.py`,
`src/clite/runtime/presentation.py`, `ui-tui/src/render.ts`, `tests/cli/test_markdown.py (baru)`,
`ui-tui/test/render.test.ts`.

**Rujukan Hermes.** `agent/display.py`, `agent/markdown_tables.py`,
`hermes_cli/skin_engine.py`, `tools/working_diff.py`.

**Selesai bila.**
- [x] Tes: potongan streaming dalam ukuran acak menghasilkan keluaran yang sama dengan teks
      utuh.
- [x] Tes: blok kode tidak pernah dirender sebagai Markdown, dan tabel lebar dipotong sesuai
      lebar terminal.
- [x] Tes: tanpa warna, keluarannya teks polos yang tetap terbaca.
- [x] Baris "Render Markdown dan diff" di spesifikasi cli dan tui menjadi ✅.

**Ukuran.** M

**Bergantung pada.** -

---

### F3-T3 TUI layar penuh

**Tujuan.** `clite tui` membuka antarmuka layar penuh: transkrip yang bisa digulir, kotak
tulis yang tetap di bawah, bilah status, dan dialog untuk persetujuan dan pemilihan.

**Lingkup.** Ini task payung (XL). Ia sudah **dipecah** menjadi F3-T9 sampai F3-T15; tidak ada
yang dikerjakan langsung di sini. Setelah semua anaknya selesai, `clite tui` membuka TUI layar
penuh dan antarmuka baris (`plain.ts`) tetap ada sebagai `--plain` dan untuk masukan pipa.

**Keputusan desain (mengikat semua anak).**
- **Pustaka: Ink + React** (sama seperti Hermes), disetujui pemilik proyek pada 8 Oktober 2026.
  Ini melonggarkan aturan "tanpa dependensi runtime baru" di `ui-tui/AGENTS.md`: `ink` dan
  `react` masuk `ui-tui/package.json` sebagai `devDependencies`, dan esbuild menanamkan
  seluruhnya ke dalam satu file `.mjs` — pengguna tetap menjalankan `clite tui` tanpa
  `npm install`. `ui-tui/AGENTS.md` diperbarui untuk menyebut pengecualian ini di F3-T9.
- **Yang dipakai ulang tanpa diubah:** `ui-tui/src/backend.ts`,
  `apps/shared/src/gateway-client.ts`, `apps/shared/src/transcript.ts` (reducer transkrip yang
  sama untuk mode penuh dan `--plain`). TUI tetap tidak punya logika percakapan: ia mengirim
  permintaan dan merender event.
- **Antarmuka baris tetap diuji.** `plain.ts` tidak dibuang; `entry.ts` memilih TUI Ink bila
  `stdout`/`stdin` adalah TTY dan bukan `--plain`, dan jatuh ke `PlainTui` untuk masukan pipa
  atau bila Ink gagal dimuat. Tes ujung ke ujung yang ada harus lulus di kedua mode.

**Anak-anak task.**

| Task | Judul | Ukuran | Bergantung pada |
|---|---|---|---|
| F3-T9 | Kerangka aplikasi Ink | M | F1-T1 |
| F3-T10 | Bilah status | S | F3-T9 |
| F3-T11 | Dialog persetujuan dan klarifikasi | M | F3-T9 |
| F3-T12 | Pelengkapan slash command | M | F3-T9, F3-T4 |
| F3-T13 | Pemilih sesi dan model | M | F3-T9 |
| F3-T14 | Tema dari skin dan tahan ubah ukuran | S | F3-T9 |
| F3-T15 | Bundle Ink dalam satu `.mjs` | M | F3-T9 |

**File.** `ui-tui/src/app/ (baru)`, `ui-tui/src/entry.ts`, `ui-tui/build.mjs`,
`ui-tui/package.json`, `ui-tui/AGENTS.md`, `src/clite/cli/subcommands/tui.py`, `ui-tui/test/`.

**Rujukan Hermes.** `ui-tui/src/app.tsx`, `ui-tui/src/components/`, `ui-tui/src/entry.tsx`,
`ui-tui/src/gatewayClient.ts`, `ui-tui/README.md`.

**Selesai bila.**
- [x] Task ini sudah dipecah menjadi task bernomor di file ini, masing-masing berukuran M atau
      lebih kecil, dan terdaftar di indeks.
- [x] Setelah semua pecahan selesai: tes ujung ke ujung yang ada (`ui-tui/test/`) lulus
      terhadap TUI baru dan terhadap mode `--plain`.
- [x] `pip install` tetap menghasilkan `clite tui` yang jalan tanpa `npm install` di mesin
      pengguna.

**Ukuran.** XL

**Bergantung pada.** F1-T1

---

### F3-T9 Kerangka aplikasi Ink

**Tujuan.** `clite tui` membuka UI layar penuh: transkrip yang bisa digulir di atas, kotak
tulis yang tetap di bawah; `--plain` dan masukan pipa tetap memakai `PlainTui` yang sekarang.

**Lingkup.**
- Tambahkan `ink` dan `react` ke `devDependencies` `ui-tui/package.json`; perbarui
  `ui-tui/AGENTS.md` untuk mencatat pengecualian dependensi ini (lihat F3-T3).
- `ui-tui/src/app/ (baru)`: komponen akar Ink (`App`) yang merender transkrip dari reducer
  `apps/shared/src/transcript.ts` (dipakai ulang tanpa diubah) dan sebuah kotak tulis.
- `ui-tui/src/entry.ts`: pilih TUI Ink bila `stdin` dan `stdout` adalah TTY dan `--plain` tidak
  diberikan; selain itu (pipa, non-TTY) jalankan `PlainTui`. Bila `ink` gagal dimuat, jatuh ke
  `PlainTui` dengan catatan di stderr.
- Kirim pesan dan tampilkan jawaban streaming lewat `gateway-client.ts` yang sudah ada.

**File.** `ui-tui/src/app/ (baru)`, `ui-tui/src/entry.ts`, `ui-tui/package.json`,
`ui-tui/AGENTS.md`, `ui-tui/test/`.

**Rujukan Hermes.** `ui-tui/src/app.tsx`, `ui-tui/src/components/appLayout.tsx`,
`ui-tui/src/components/messageLine.tsx`, `ui-tui/src/app/useMainApp.ts`.

**Selesai bila.**
- [x] Tes: `entry.ts` memilih `PlainTui` saat masukan bukan TTY atau `--plain` diberikan, dan
      TUI Ink sebaliknya (fungsi pemilih diuji tanpa terminal sungguhan).
- [x] Tes: transkrip Ink memakai reducer `transcript.ts` yang sama (event masuk → item yang
      sama dengan mode `--plain`).
- [x] Tes ujung ke ujung yang ada tetap lulus di mode `--plain`.
- [x] Baris "TUI layar penuh (Ink/React)" di spesifikasi tui menjadi 🟡.

**Ukuran.** M

**Bergantung pada.** F1-T1

---

### F3-T10 Bilah status

**Tujuan.** Di bawah layar penuh ada bilah status: model/provider, pemakaian jendela konteks,
direktori kerja, identitas/judul sesi bila ada, aktivitas giliran/tool, dan token giliran terakhir.

**Lingkup.**
- Komponen bilah status Ink di `ui-tui/src/app/ (baru)`, memakai fakta yang sudah ada di
  `session.info` dan event `turn.start`/`turn.step`/`tool.start`/`tool.complete`/`turn.complete`.
- Setelah respons provider selesai, server memancarkan ulang `session.info` yang sudah ada agar
  pemakaian konteks terukur diperbarui tanpa polling atau kontrak TUI baru.
- Pada terminal sempit, aktivitas, model, dan konteks dipertahankan lebih dulu; rincian sesi,
  direktori, provider, lalu token dibuang bertahap sebelum elipsis satu baris.

**File.** `ui-tui/src/app/ (baru)`, `ui-tui/test/`.

**Rujukan Hermes.** `ui-tui/src/components/appChrome.tsx`, `ui-tui/src/components/themed.tsx`.

**Selesai bila.**
- [x] Tes: bilah status merender model, direktori, dan keadaan sibuk dari state yang diberikan.
- [x] Tes: event `session.info` memperbarui teksnya.
- [x] Baris baru "Bilah status TUI" di spesifikasi tui menjadi ✅.

**Ukuran.** S

**Bergantung pada.** F3-T9

---

### F3-T11 Dialog persetujuan dan klarifikasi

**Tujuan.** Persetujuan perintah dan pertanyaan agent muncul sebagai dialog di layar penuh,
menggantikan pertanyaan berbasis baris.

**Lingkup.**
- Dialog Ink di `ui-tui/src/app/ (baru)` untuk `approval.request` dan pertanyaan `clarify`,
  memakai RPC yang sudah ada (`approval.respond`, `clarify.respond`).
- Pilihan dapat diklik/dipilih dengan tombol panah dan Enter; pertanyaan bebas teks tetap
  didukung.

**File.** `ui-tui/src/app/ (baru)`, `ui-tui/test/`.

**Rujukan Hermes.** `ui-tui/src/components/prompts.tsx`,
`ui-tui/src/components/overlayPrimitives.tsx`.

**Selesai bila.**
- [x] Tes: dialog persetujuan merender perintah dan menerima jawaban ya/tidak/selalu.
- [x] Tes: dialog klarifikasi bernomor memilih opsi yang benar dan meneruskan teks bebas.
- [x] Tes ujung ke ujung: persetujuan lewat TUI menyelesaikan giliran seperti mode `--plain`.
- [x] Baris "Dialog persetujuan dan klarifikasi" di spesifikasi tui menjadi ✅.

**Ukuran.** M

**Bergantung pada.** F3-T9

---

### F3-T12 Pelengkapan slash command

**Tujuan.** Mengetik `/` di kotak tulis memunculkan daftar perintah yang cocok, dan Tab
melengkapinya; argumen tertentu (nama model, sesi) ikut dilengkapi.

**Lingkup.**
- Pelengkapan di kotak tulis Ink lewat `complete.slash` dan `commands.catalog` (RPC yang sudah
  ada); tidak ada daftar perintah yang dieja di TypeScript.
- Pilih dengan panah/Enter; Esc menutup.

**File.** `ui-tui/src/app/ (baru)`, `ui-tui/test/`.

**Rujukan Hermes.** `ui-tui/src/hooks/useCompletion.ts`,
`ui-tui/src/app/createSlashHandler.ts`.

**Selesai bila.**
- [x] Tes: awalan `/` menghasilkan kandidat dari `commands.catalog`, terurut, tanpa duplikat.
- [x] Tes: Tab pada satu kandidat menyelesaikan teks; beberapa kandidat membuka daftar.
- [x] Baris "Pelengkapan slash command di TUI" di spesifikasi tui menjadi ✅.

**Ukuran.** M

**Bergantung pada.** F3-T9, F3-T4

---

### F3-T13 Pemilih sesi dan model

**Tujuan.** Overlay untuk memilih sesi sebelumnya dan memilih model, tanpa mengetik id.

**Lingkup.**
- Overlay Ink di `ui-tui/src/app/ (baru)` memakai `session.list` dan `model.list`; memilih
  memanggil `session.create` (resume) atau `model.set`.
- Menampilkan judul, model, dan waktu aktivitas tiap sesi.

**File.** `ui-tui/src/app/ (baru)`, `ui-tui/test/`.

**Rujukan Hermes.** `ui-tui/src/components/modelPicker.tsx`,
`ui-tui/src/components/activeSessionSwitcher.tsx`.

**Selesai bila.**
- [x] Tes: pemilih sesi merender daftar dari `session.list` dan memilih satu memicu resume.
- [x] Tes: pemilih model merender daftar dari `model.list` dan memilih satu memicu `model.set`.
- [x] Baris "Pemilih sesi dan model" di spesifikasi tui menjadi ✅.

**Ukuran.** M

**Bergantung pada.** F3-T9

---

### F3-T14 Tema dari skin dan tahan ubah ukuran

**Tujuan.** TUI layar penuh memakai warna dari skin yang sama dengan CLI, dan tata letaknya
benar saat terminal diubah ukurannya.

**Lingkup.**
- Tema Ink dari skin (`cli/display.py` sudah memetakan peran → warna lewat
  `runtime/presentation.markdown_role_codes`; sediakan padanannya di RPC atau baca lewat
  `config`), sehingga CLI dan TUI seragam.
- Tangani `dimension`/resize dari Ink: transkrip dan bilah status menyesuaikan lebar.

**File.** `ui-tui/src/app/ (baru)`, `ui-tui/src/render.ts`, `ui-tui/test/`.

**Rujukan Hermes.** `ui-tui/src/theme.ts`, `ui-tui/src/components/themed.tsx`.

**Selesai bila.**
- [x] Tes: skin yang diberikan menghasilkan warna yang sama di TUI seperti di CLI
      (`markdown_role_codes` padanan TypeScript).
- [x] Tes: saat lebar berubah, transkrip membungkus ulang dan bilah status tetap satu baris.
- [x] Baris "Tema TUI dari skin" di spesifikasi tui menjadi ✅.

**Ukuran.** S

**Bergantung pada.** F3-T9

---

### F3-T15 Bundle Ink dalam satu `.mjs`

**Tujuan.** `pip install clite` tetap menghasilkan `clite tui` yang jalan tanpa `npm install`:
`ink` dan `react` tertanam di dalam satu `clite-tui.mjs`.

**Lingkup.**
- `ui-tui/build.mjs`: bangun entri TUI Ink (JSX) menjadi satu `.mjs`, dengan `ink` dan `react`
  dibundel (bukan `external`), `platform: node`, `format: esm`.
- `ui-tui/package.json`: `ink`/`react` di `devDependencies`; skrip build tetap `node build.mjs`.
- Tambahkan gerbang ukuran/waktu-mulai yang diuji: bundle tidak melewati batas ukuran yang
  wajar dan `--version`/bantuan TUI tetap cepat (batas ditulis di tes).
- `ui-tui/src/entry.ts` tetap memuat bundel tanpa impor luar pada waktu jalan.

**File.** `ui-tui/build.mjs`, `ui-tui/package.json`, `ui-tui/src/entry.ts`,
`src/clite/cli/subcommands/tui.py`, `src/clite/tui_dist/ (dibangun ulang)`, `ui-tui/test/`,
`tests/cli/test_tui_bundle.py`.

**Rujukan Hermes.** `ui-tui/scripts/build.mjs`, `ui-tui/README.md`.

**Selesai bila.**
- [x] Tes: bundle hasil build hanya berisi satu file `.mjs` dan mengimpornya tidak menarik
      paket dari `node_modules` (dependensi tertanam).
- [x] Tes: ukuran bundle di bawah batas yang ditulis di tes, dan `clite tui --help` selesai
      dalam batas waktu yang ditulis di tes.
- [x] `tests/cli/test_tui_bundle.py` (hash sumber) tetap lulus setelah `node build.mjs`.
- [x] Baris "Bundle TUI satu file" di spesifikasi tui menjadi ✅.

**Ukuran.** M

**Bergantung pada.** F3-T9

---

### F3-T4 Slash command tambahan

**Tujuan.** Perintah yang paling sering dipakai di Hermes tersedia di semua surface.

**Lingkup.** Setiap perintah adalah satu `CommandDef` dan satu handler `_handle_<nama>` yang
mengembalikan `SlashResult`.

| Perintah | Guna |
|---|---|
| `/branch [judul]` | Membuat sesi baru yang berisi salinan percakapan sampai titik ini |
| `/queue <teks>` | Mengantrekan pesan untuk dijalankan setelah giliran sekarang |
| `/background <teks>` | Menjalankan satu giliran di sesi terpisah dan melaporkan hasilnya |
| `/export [path]` | Menyimpan transkrip sebagai Markdown atau JSON |
| `/context` | Rincian pemakaian jendela konteks: prompt per tingkat, tool, riwayat |
| `/tasks` | Menampilkan daftar tugas (`todo`) sesi ini |
| `/hooks` | Shell hook yang terdaftar dan yang menunggu persetujuan |
| `/pin`, `/archive` | Menandai sesi supaya tidak dipangkas, atau menyembunyikannya |
| `/verbose [off\|new\|all\|verbose]` | Mengatur `display.tool_progress` untuk sesi ini |
| `/skin [nama]` | Mengganti tema (hanya CLI) |
| `/logs [jumlah]` | Baris terakhir log agent (hanya CLI) |
| `/copy` | Menyalin jawaban terakhir ke clipboard (hanya CLI) |

Perintah yang dimiliki task lain tidak dikerjakan di sini: `/rollback` (F2-T8), `/image`
(F2-T6), `/mcp` (F2-T10), `/insights` (F3-T8).

**File.** `src/clite/runtime/commands.py`, `src/clite/runtime/slash.py`,
`src/clite/runtime/session.py`, `src/clite/state/db.py`,
`tests/runtime/test_session_and_slash.py`.

**Rujukan Hermes.** `hermes_cli/commands.py`, `hermes_cli/slash_exec.py`,
`gateway/slash_commands.py`, `agent/context_breakdown.py`.

**Selesai bila.**
- [x] Setiap perintah punya tes lewat `ChatSession.run_slash`.
- [x] `/branch` menyalin pesan aktif tanpa `provider_data` (awalan percakapan berubah bagi
      sesi baru) dan mencatat `parent_session_id`.
- [x] `test_every_command_has_a_handler_and_every_handler_a_command` tetap lulus, dan
      halaman katalog dibuat ulang.
- [x] Baris slash command di spesifikasi runtime diperbarui dengan jumlah yang baru.

**Ukuran.** M

**Bergantung pada.** -

---

### F3-T5 Wizard setup

**Tujuan.** Pengguna baru sampai ke percakapan pertama tanpa membaca dokumentasi.

**Lingkup.**
- `clite setup` menjadi alur bertahap: pilih provider, masukkan kunci, **uji kunci itu dengan
  satu panggilan sungguhan**, pilih model dari daftar yang diambil dari provider, pilih
  toolset, lalu ringkasan.
- Langkah opsional: platform pesan (Telegram), dan mode persetujuan.
- Setiap langkah bisa dilewati dengan flag, sehingga setup tetap bisa dijalankan tanpa
  interaksi.
- Menjalankan ulang `clite setup` menampilkan nilai sekarang sebagai default dan tidak
  menghapus apa pun.
- Logika penyimpanan tetap di `runtime.setup.apply_setup`, yang juga dipakai layar setup di
  dashboard lewat `setup.apply`.

**File.** `src/clite/cli/subcommands/setup.py`, `src/clite/runtime/setup.py`,
`src/clite/providers/models.py`, `tests/cli/test_cli.py`.

**Rujukan Hermes.** `hermes_cli/setup.py`, `hermes_cli/setup_quick.py`,
`hermes_cli/main_provider_setup.py`.

**Selesai bila.**
- [x] Tes: alur lengkap dengan jawaban yang disuntikkan dan provider tiruan, termasuk kunci
      salah yang ditolak dengan pesan yang jelas.
- [x] Tes: setup tanpa interaksi lewat flag menghasilkan config yang sama.
- [x] Baris `clite setup` di spesifikasi cli menjadi ✅.

**Ukuran.** M

**Bergantung pada.** F1-T2

---

### F3-T6 `clite update`, `backup`, `uninstall`

**Tujuan.** Pengguna bisa memperbarui, mencadangkan, memulihkan, dan mencopot instalasi dengan
perintah agent itu sendiri.

**Lingkup.**
- `clite update`: mengenali cara pemasangan (pipx, pip, checkout git), memeriksa versi
  terbaru, memperbarui, lalu menjalankan migrasi config. `--check` hanya melaporkan.
- `clite backup create [path]` membuat arsip home: config, memori, skill, sesi, job cron.
  `.env` hanya ikut dengan `--include-secrets`, dan arsip yang memuatnya dibuat dengan izin
  0600. `clite backup restore <arsip>` memulihkan ke home kosong atau menolak.
- `clite uninstall`: menghapus paket; home hanya dihapus dengan `--purge` dan konfirmasi.
- Ketiganya termasuk CLI pengelolaan yang selalu ditanyakan bila agent mencoba
  menjalankannya: tambahkan ke pola di `src/clite/tools/approval.py`.

**File.** `src/clite/cli/subcommands/update.py (baru)`,
`src/clite/cli/subcommands/backup.py (baru)`, `src/clite/cli/main.py`,
`src/clite/tools/approval.py`, `tests/cli/test_cli.py`.

**Rujukan Hermes.** `hermes_cli/update_cmd.py`, `hermes_cli/backup.py`,
`hermes_cli/backup_restore.py`, `hermes_cli/uninstall.py`.

**Selesai bila.**
- [x] Tes: cadangkan lalu pulihkan ke home baru menghasilkan sesi, memori, dan skill yang sama.
- [x] Tes: arsip tanpa `--include-secrets` tidak memuat `.env` maupun `auth.json`.
- [x] Tes: `clite update --check` terhadap indeks paket tiruan melaporkan versi yang benar.
- [x] Tes: perintah `clite backup` dan `clite update` dikenali `detect_self_access`.

**Ukuran.** M

**Bergantung pada.** F1-T7

---

### F3-T7 Pelengkapan shell

**Tujuan.** Tab di bash, zsh, dan fish melengkapi sub-perintah dan opsi `clite`.

**Lingkup.**
- `clite completion bash | zsh | fish` mencetak skrip pelengkapan yang dibangun dari parser
  yang sama dengan `main`, termasuk sub-perintah dari plugin.
- Nilai dinamis (nama profil, nama model, id sesi) dilengkapi dengan memanggil
  `clite completion --values <jenis>`, yang harus kembali cepat dan tidak memuat plugin.

**File.** `src/clite/cli/subcommands/completion.py (baru)`, `src/clite/cli/main.py`,
`tests/cli/test_cli.py`.

**Rujukan Hermes.** `hermes_cli/completion.py`, `hermes_cli/commands_completion.py`.

**Selesai bila.**
- [x] Tes: skrip yang dihasilkan memuat setiap sub-perintah di `SUBCOMMAND_MODULES`.
- [x] Tes: skrip bash lulus `bash -n`.
- [x] Baris "pelengkapan shell" di spesifikasi cli menjadi ✅.

**Ukuran.** S

**Bergantung pada.** -

---

### F3-T8 `/insights`

**Tujuan.** Pengguna melihat bagaimana agent dipakai: token dan biaya per hari dan per model,
tool yang paling sering dipanggil, jumlah sesi per platform.

**Lingkup.**
- Kueri agregat di `SessionDB` atas tabel yang sudah ada. Tidak ada tabel baru.
- `/insights [hari]` di semua surface dan `clite insights --days N --json`.
- Biaya memakai `estimated_cost_usd` dari F2-T3; sesi tanpa harga dihitung terpisah, bukan
  sebagai nol.

**File.** `src/clite/state/db.py`, `src/clite/runtime/commands.py`,
`src/clite/runtime/slash.py`, `src/clite/cli/subcommands/misc.py`,
`tests/state/test_db.py`, `tests/runtime/test_session_and_slash.py`.

**Rujukan Hermes.** `agent/insights.py`, `hermes_cli/subcommands/insights.py`.

**Selesai bila.**
- [x] Tes: agregat atas database buatan dengan beberapa sesi, model, dan hari cocok dengan
      hitungan tangan.
- [x] Tes: subagent dihitung ke induknya, tidak dua kali.
- [x] Baris `/insights` di spesifikasi runtime menjadi ✅.

**Ukuran.** S

**Bergantung pada.** F2-T3
