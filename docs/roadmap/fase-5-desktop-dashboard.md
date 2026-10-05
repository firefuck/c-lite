# Fase 5: desktop dan dashboard

Antarmuka grafis C-lite adalah **satu dashboard** yang disajikan backend (`clite serve`), dan
aplikasi desktop adalah cangkang Electron yang memuat dashboard itu di sebuah jendela. Jadi
hampir semua pekerjaan fitur di fase ini adalah pekerjaan dashboard, dan otomatis berlaku
untuk browser dan desktop.

Dua aturan yang menentukan bentuk pekerjaan di sini:

- **Semua yang bisa dilakukan klien lewat protokol RPC.** Halaman baru yang butuh data baru
  berarti method RPC baru dengan kontraknya; lihat
  [arsitektur/05-protokol-rpc.md](../arsitektur/05-protokol-rpc.md#menambah-method-atau-event).
  Rute REST tidak ditambah untuk fitur.
- **Teks dari model dan tool tidak pernah dimasukkan sebagai HTML.** Tes browser yang ada
  menjaga ini; setiap halaman baru mendapat tes serupa.

Aturan yang berlaku untuk semua task ada di [README](README.md#selesai-itu-apa).

---

### F5-T1 Jalankan dan verifikasi cangkang Electron

**Tujuan.** Aplikasi desktop terbukti berjalan: jendela terbuka, backend menyala, percakapan
berjalan, dan menutup jendela mematikan backend.

**Lingkup.**
- `npm install`, lalu `npm run start` di `apps/desktop/`. File `src/main.ts`, `src/preload.ts`,
  dan `build.mjs` belum pernah dijalankan; perbaiki sampai jalan.
- Lalui daftar periksa di `apps/desktop/README.md`: jendela memuat dashboard dengan token di
  fragmen, tautan luar terbuka di browser pengguna, instance kedua memfokuskan yang pertama,
  backend yang gagal mulai tampil sebagai pesan galat dengan stderr-nya, menutup aplikasi
  menghentikan backend.
- Tes asap otomatis yang membuka aplikasi dengan provider `mock`, mengirim satu pesan, dan
  memeriksa jawabannya. Di CI Linux berjalan di bawah layar virtual.
- Sesuaikan versi Electron di `package.json` ke versi yang benar-benar dicoba.

**File.** `apps/desktop/src/main.ts`, `apps/desktop/src/preload.ts`, `apps/desktop/build.mjs`,
`apps/desktop/package.json`, `apps/desktop/test/smoke.test.ts (baru)`,
`apps/desktop/README.md`, `docs/spesifikasi/desktop.md`, `.github/workflows/ci.yml`.

**Rujukan Hermes.** `apps/desktop/electron/backend-child.ts`,
`apps/desktop/electron/backend-ready.ts`, `apps/desktop/electron/dashboard-token.ts`,
`apps/desktop/BUILDING.md`.

**Selesai bila.**
- [ ] Tes asap lulus di CI.
- [ ] Type check `apps/desktop` berjalan di CI (saat ini dilewati tanpa Electron).
- [ ] Baris `main.ts`, `preload.ts`, dan `build.mjs` di spesifikasi desktop menjadi ✅, dan
      butirnya dicoret dari "belum diverifikasi" di `docs/STATUS.md`.

**Ukuran.** S

**Bergantung pada.** F1-T1

**Butuh dari Anda.** Mesin dengan layar untuk mencoba dengan tangan (macOS, Windows, atau
Linux desktop).

---

### F5-T2 Halaman dashboard: config, cron, log, memori, sesi

**Tujuan.** Semua yang sekarang hanya bisa dikelola lewat CLI bisa dikelola dari dashboard.

**Lingkup.** Satu halaman per sub-langkah, masing-masing dengan method RPC, tes Python, dan
tes browser.
1. **Sesi.** Cari, ganti judul, sematkan, arsipkan, hapus, ekspor.
2. **Config.** Menampilkan kunci dari `DEFAULT_CONFIG` berkelompok, dengan nilai efektif dan
   default-nya. Menyunting lewat `config.set`. Kunci yang menyangkut keamanan (`approvals.*`,
   `plugins.enabled`, `hooks`, `gateway.allow_all_users`) meminta konfirmasi eksplisit.
3. **Kredensial.** Daftar nama kredensial yang dikenal dan apakah terisi. Nilai tidak pernah
   dikirim ke klien; hanya bisa diisi atau dihapus.
4. **Cron.** Daftar, buat, jeda, jalankan sekarang, hapus, dan keluaran run terakhir.
5. **Memori.** Lihat dan sunting entri `MEMORY.md` dan `USER.md`, lewat jalur yang sama
   dengan tool `memory` (pemindaian dan batas ukuran tetap berlaku).
6. **Log.** Ekor log agent dengan penyaring tingkat. Log diredaksi sebelum dikirim.
7. **Shell hook dan MCP.** Status saja: yang terdaftar, yang menunggu persetujuan. Menyetujui
   hook tetap hanya lewat `clite hooks approve` di mesin itu.

**File.** `src/clite/rpc/contracts/schema.py`, `src/clite/rpc/methods.py`,
`src/clite/server/static/app.js`, `src/clite/server/static/index.html`,
`src/clite/server/static/style.css`, `tests/rpc/test_rpc.py`,
`tests/server/test_dashboard_browser.py`.

**Rujukan Hermes.** `web/src/pages/` (terutama `ConfigPage.tsx`, `CronPage.tsx`,
`SessionsPage.tsx`, `LogsPage.tsx`), `hermes_cli/web_server_config.py`,
`hermes_cli/web_server_cron.py`, `hermes_cli/web_server_sessions.py`,
`hermes_cli/web_server_memory.py`.

**Selesai bila.**
- [ ] Setiap method baru punya kontrak, handler, dan tes; tipe TypeScript dibuat ulang.
- [ ] Tes: tidak ada method yang mengembalikan nilai kredensial, dan `config.get` atas seluruh
      config tidak memuat rahasia yang diekspansi dari `${VAR}`.
- [ ] Tes browser: setiap halaman dimuat, satu aksi utamanya berjalan, dan teks berisi
      `<script>` tampil sebagai teks.
- [ ] Baris halaman dashboard di spesifikasi server dan rpc menjadi ✅.

**Ukuran.** L

**Bergantung pada.** -

---

### F5-T3 Dashboard React dan Vite

**Tujuan.** Dashboard berpindah ke kerangka komponen, **bila dan hanya bila** JavaScript polos
sudah menghambat: file `app.js` terlalu besar untuk dirawat, atau keadaan antarhalaman sulit
dijaga.

**Lingkup.** Task ini berukuran XL dan harus dipecah sebelum dikerjakan. Sebelum memecahnya,
tuliskan di sini alasan konkret mengapa JavaScript polos tidak lagi cukup. Tanpa alasan itu,
task ini tidak dikerjakan. Pecahan yang disarankan:
1. Kerangka build: Vite, React, TypeScript; keluaran build di-commit ke dalam paket Python
   dengan pemeriksaan kesegaran seperti bundle TUI.
2. Lapisan data: `apps/shared` (klien dan reducer transkrip) dipakai langsung.
3. Halaman obrolan dipindah lebih dulu, dengan semua tes browser yang ada tetap lulus.
4. Halaman pengelolaan dari F5-T2 dipindah satu per satu.
5. Dashboard lama dihapus.

**Di luar lingkup.** Protokol RPC tidak berubah karena perpindahan ini.

**File.** `web/ (baru)`, `src/clite/server/static/`, `src/clite/server/app.py`,
`package.json`, `tests/server/test_dashboard_browser.py`.

**Rujukan Hermes.** `web/src/App.tsx`, `web/src/pages/`, `web/src/components/`.

**Selesai bila.**
- [ ] Alasan perpindahan tertulis, dan task sudah dipecah menjadi task bernomor.
- [ ] Setelah semua pecahan selesai: seluruh tes browser lulus terhadap dashboard baru, dan
      `pip install` tetap menghasilkan dashboard yang jalan tanpa Node di mesin pengguna.

**Ukuran.** XL

**Bergantung pada.** F5-T2

---

### F5-T4 Pemaketan desktop

**Tujuan.** Pengguna mengunduh satu installer, membukanya, dan aplikasinya jalan.

**Lingkup.**
- Putuskan cara membawa backend: mengandalkan `clite` yang sudah terpasang, atau menyertakan
  runtime Python di dalam aplikasi. Tulis keputusan dan alasannya di spesifikasi desktop.
- Konfigurasi pembuat installer untuk macOS (dmg), Windows (nsis), dan Linux (AppImage).
- Ikon, nama produk dari satu sumber, dan menu aplikasi standar.
- Tanda tangan kode dan notarisasi di CI, memakai rahasia CI. Tanpa sertifikat, build tetap
  menghasilkan artefak tak bertanda yang dilabeli demikian.
- Pembaruan otomatis dari rilis GitHub.

**File.** `apps/desktop/electron-builder.config.cjs (baru)`, `apps/desktop/package.json`,
`apps/desktop/assets/ (baru)`, `apps/desktop/src/main.ts`,
`.github/workflows/release.yml (dibuat F1-T7)`, `docs/spesifikasi/desktop.md`.

**Rujukan Hermes.** `apps/desktop/electron-builder.config.cjs`, `apps/desktop/BUILDING.md`,
`apps/desktop/electron/app-updater.ts`.

**Selesai bila.**
- [ ] CI menghasilkan installer untuk ketiga sistem pada tag rilis.
- [ ] Installer dicoba dengan tangan di tiap sistem yang tersedia, dan hasilnya dicatat di
      `docs/STATUS.md` per sistem.
- [ ] Tes: nama produk dan versi di installer sama dengan yang di `pyproject.toml`.

**Ukuran.** M

**Bergantung pada.** F5-T1

**Butuh dari Anda.** Sertifikat penanda tangan (Apple Developer ID, sertifikat Windows) bila
ingin installer yang tidak memicu peringatan sistem.

---

### F5-T5 Fitur desktop: multi-sesi, lampiran, notifikasi, putar ulang event

**Tujuan.** Dashboard nyaman dipakai sebagai aplikasi harian: beberapa percakapan sekaligus,
menyeret file ke jendela, diberi tahu saat pekerjaan selesai, dan tidak kehilangan apa pun
saat koneksi putus sebentar.

**Lingkup.** Satu sub-langkah per fitur.
1. **Multi-sesi.** Daftar sesi di sisi, beberapa sesi berjalan bersamaan dalam satu koneksi
   (protokol sudah membawa `session_id` di setiap event).
2. **Putar ulang event.** Server menyimpan event terakhir per sesi runtime dalam penyangga
   berbatas; klien yang menyambung ulang mengirim `seq` terakhirnya dan menerima yang
   terlewat. Sesi runtime bertahan sebentar setelah koneksi putus, alih-alih langsung ditutup.
3. **Lampiran.** Seret dan tempel gambar atau file ke kotak tulis (memakai F2-T6).
4. **Notifikasi.** Saat giliran selesai atau persetujuan dibutuhkan dan jendela tidak
   terfokus: notifikasi sistem di desktop, notifikasi browser bila diizinkan.
5. **Profil.** Memilih profil saat mulai; satu backend per profil.

**File.** `src/clite/rpc/server.py`, `src/clite/rpc/session.py`,
`src/clite/rpc/contracts/schema.py`, `src/clite/server/app.py`,
`src/clite/server/static/app.js`, `src/clite/server/static/rpc.js`,
`apps/shared/src/gateway-client.ts`, `apps/desktop/src/main.ts`,
`apps/desktop/src/preload.ts`, `tests/rpc/test_rpc.py`, `tests/server/test_server.py`.

**Rujukan Hermes.** `tui_gateway/event_replay.py`, `tui_gateway/prompt_attachments.py`,
`tui_gateway/session_notifications.py`, `tui_gateway/methods_profiles.py`,
`apps/shared/src/json-rpc-gateway.ts`.

**Selesai bila.**
- [ ] Tes: klien yang putus di tengah giliran lalu menyambung ulang menerima event yang
      terlewat, berurutan dan tanpa ganda, dan giliran itu tidak terhenti.
- [ ] Tes: penyangga event berbatas; klien yang tertinggal terlalu jauh diberi tahu untuk
      memuat ulang riwayat, bukan menerima aliran yang bolong.
- [ ] Tes browser: dua sesi berjalan bersamaan tanpa event yang tertukar.
- [ ] Baris "Pemutaran ulang event" di spesifikasi rpc dan baris fitur di spesifikasi desktop
      menjadi ✅.

**Ukuran.** L

**Bergantung pada.** F5-T1, F5-T2

---

### F5-T6 Akses jarak jauh yang aman

**Tujuan.** Dashboard bisa dibuka dari perangkat lain tanpa menyerahkan mesin kepada siapa pun
yang menemukan port-nya.

**Lingkup.**
- Token yang bisa dikelola: beberapa token bernama, masa berlaku, pencabutan tanpa memulai
  ulang, dan `clite serve token create | list | revoke`. Token disimpan sebagai hash.
- Pembatasan laju untuk percobaan token yang salah, per alamat.
- Batas ukuran pesan RPC masuk, dan tekanan balik untuk klien yang lambat membaca.
- TLS: sertifikat dari pengguna, atau panduan memasang di belakang reverse proxy. Bila server
  diikat ke alamat selain loopback tanpa TLS, ia menolak mulai kecuali dipaksa dengan flag.
- Daftar nama host yang diterima (`server.allowed_hosts`) menggantikan "semua nama diterima"
  untuk server yang tidak terikat ke loopback.
- Log audit: sambungan, token yang dipakai, dan perintah berbahaya yang disetujui lewat
  dashboard.

**File.** `src/clite/server/app.py`, `src/clite/server/run.py`,
`src/clite/server/tokens.py (baru)`, `src/clite/rpc/server.py`,
`src/clite/cli/subcommands/serve.py`, `src/clite/core/config_defaults.py`,
`tests/server/test_server.py`, `docs/arsitektur/06-keamanan.md`.

**Rujukan Hermes.** `plugins/dashboard_auth/`, `hermes_cli/web_server_oauth.py`.

**Selesai bila.**
- [ ] Tes: token yang dicabut ditolak pada permintaan berikutnya dan memutus WebSocket yang
      sedang memakainya.
- [ ] Tes: sepuluh percobaan salah dari satu alamat memicu penundaan, tanpa memengaruhi
      alamat lain.
- [ ] Tes: pesan RPC yang melebihi batas ditolak tanpa memuat seluruhnya ke memori.
- [ ] Tabel "Celah yang diketahui" di dokumen keamanan diperbarui: baris token dan batas
      ukuran dihapus atau diubah.

**Ukuran.** M

**Bergantung pada.** F5-T2
