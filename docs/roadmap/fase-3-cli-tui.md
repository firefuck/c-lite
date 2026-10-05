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
- [ ] Tes: baris yang masuk saat giliran berjalan diantrekan, menginterupsi, atau
      mengarahkan, sesuai mode, lewat `ChatSession`.
- [ ] Tes RPC dan gateway untuk mode sibuk tetap lulus setelah logikanya dipindah.
- [ ] Tanpa `prompt_toolkit`, REPL tetap jalan dengan perilaku sekarang.
- [ ] Baris "Mengetik saat agent bekerja" dan "Input multi-baris" di spesifikasi cli menjadi ✅.

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
- [ ] Tes: potongan streaming dalam ukuran acak menghasilkan keluaran yang sama dengan teks
      utuh.
- [ ] Tes: blok kode tidak pernah dirender sebagai Markdown, dan tabel lebar dipotong sesuai
      lebar terminal.
- [ ] Tes: tanpa warna, keluarannya teks polos yang tetap terbaca.
- [ ] Baris "Render Markdown dan diff" di spesifikasi cli dan tui menjadi ✅.

**Ukuran.** M

**Bergantung pada.** -

---

### F3-T3 TUI layar penuh

**Tujuan.** `clite tui` membuka antarmuka layar penuh: transkrip yang bisa digulir, kotak
tulis yang tetap di bawah, bilah status, dan dialog untuk persetujuan dan pemilihan.

**Lingkup.** Task ini berukuran XL dan **harus dipecah** sebelum dikerjakan. Sesi pertama
hanya menghasilkan task-task baru di file ini. Pecahan yang disarankan:
1. Kerangka aplikasi Ink (React untuk terminal): tata letak, transkrip dari reducer bersama,
   kotak tulis. Antarmuka baris (`plain.ts`) tetap ada sebagai `--plain` dan untuk masukan
   pipa.
2. Bilah status: model, pemakaian konteks, direktori kerja, keadaan sibuk.
3. Dialog persetujuan dan klarifikasi, menggantikan pertanyaan berbasis baris.
4. Pelengkapan slash command dan argumennya (`complete.slash`, `commands.catalog`).
5. Pemilih sesi dan pemilih model.
6. Tema dari skin, dan penanganan ubah ukuran terminal.
7. Bundle: ukuran, waktu mulai, dan dependensi `ink` serta `react` di dalam satu file `.mjs`.

Yang dipakai ulang tanpa diubah: `ui-tui/src/backend.ts`, `apps/shared/src/gateway-client.ts`,
dan `apps/shared/src/transcript.ts`.

**File.** `ui-tui/src/app/ (baru)`, `ui-tui/src/entry.ts`, `ui-tui/build.mjs`,
`ui-tui/package.json`, `src/clite/cli/subcommands/tui.py`, `ui-tui/test/`.

**Rujukan Hermes.** `ui-tui/src/app.tsx`, `ui-tui/src/components/`, `ui-tui/src/entry.tsx`,
`ui-tui/src/gatewayClient.ts`, `ui-tui/README.md`, `tui_gateway/AGENTS.md`.

**Selesai bila.**
- [ ] Task ini sudah dipecah menjadi task bernomor di file ini, masing-masing berukuran M atau
      lebih kecil, dan terdaftar di indeks.
- [ ] Setelah semua pecahan selesai: tes ujung ke ujung yang ada (`ui-tui/test/`) lulus
      terhadap TUI baru dan terhadap mode `--plain`.
- [ ] `pip install` tetap menghasilkan `clite tui` yang jalan tanpa `npm install` di mesin
      pengguna.

**Ukuran.** XL

**Bergantung pada.** F1-T1

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
- [ ] Setiap perintah punya tes lewat `ChatSession.run_slash`.
- [ ] `/branch` menyalin pesan aktif tanpa `provider_data` (awalan percakapan berubah bagi
      sesi baru) dan mencatat `parent_session_id`.
- [ ] `test_every_command_has_a_handler_and_every_handler_a_command` tetap lulus, dan
      halaman katalog dibuat ulang.
- [ ] Baris slash command di spesifikasi runtime diperbarui dengan jumlah yang baru.

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
- [ ] Tes: alur lengkap dengan jawaban yang disuntikkan dan provider tiruan, termasuk kunci
      salah yang ditolak dengan pesan yang jelas.
- [ ] Tes: setup tanpa interaksi lewat flag menghasilkan config yang sama.
- [ ] Baris `clite setup` di spesifikasi cli menjadi ✅.

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
- [ ] Tes: cadangkan lalu pulihkan ke home baru menghasilkan sesi, memori, dan skill yang sama.
- [ ] Tes: arsip tanpa `--include-secrets` tidak memuat `.env` maupun `auth.json`.
- [ ] Tes: `clite update --check` terhadap indeks paket tiruan melaporkan versi yang benar.
- [ ] Tes: perintah `clite backup` dan `clite update` dikenali `detect_self_access`.

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
- [ ] Tes: skrip yang dihasilkan memuat setiap sub-perintah di `SUBCOMMAND_MODULES`.
- [ ] Tes: skrip bash lulus `bash -n`.
- [ ] Baris "pelengkapan shell" di spesifikasi cli menjadi ✅.

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
- [ ] Tes: agregat atas database buatan dengan beberapa sesi, model, dan hari cocok dengan
      hitungan tangan.
- [ ] Tes: subagent dihitung ke induknya, tidak dua kali.
- [ ] Baris `/insights` di spesifikasi runtime menjadi ✅.

**Ukuran.** S

**Bergantung pada.** F2-T3
