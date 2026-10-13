# Spesifikasi: desktop

| | |
|---|---|
| Kode | `apps/desktop/` |
| Tes | `apps/desktop/test/` (11 tes untuk bagian tanpa Electron, 5 di antaranya tentang pemaketan) |
| Bergantung pada | `clite serve` ([server](server.md)) dan dashboard statisnya |
| Bedah Hermes | [10-gui-desktop-dashboard](../hermes/10-gui-desktop-dashboard.md) |

## Tanggung jawab

Cangkang Electron yang menjalankan backend, menunggu sampai siap, dan menampilkan dashboard
milik backend di sebuah jendela. Tidak ada UI kedua.

## Bagian-bagian

| File | Isi | Status |
|---|---|---|
| `src/backend-process.ts` | Menjalankan `clite serve`, membaca baris siap, membuat token, menghentikan proses | ✅ teruji |
| `src/window-policy.ts` | `decideNavigation`: ke mana jendela boleh pergi | ✅ teruji |
| `src/main.ts` | Proses utama Electron: jendela, satu instance, siklus hidup | ✅ teruji (`test/smoke.test.ts`) |
| `src/preload.ts` | Jembatan ke halaman (`window.cliteDesktop`) | ✅ teruji (lewat jendela di tes asap) |
| `build.mjs` | Bundel esbuild ke `dist/main.cjs` dan `dist/preload.cjs` | ✅ teruji (dijalankan tes asap) |
| `src/brand.ts` | Nama produk, satu kali | ✅ teruji |
| `src/menu.ts` | Template menu aplikasi (File, Edit, View, Window, Help) | ✅ teruji |
| `electron-builder.config.cjs` | Konfigurasi installer (dmg, nsis, AppImage) | ✅ teruji; dibangun lokal untuk Linux |
| `assets/icon.png` | Ikon 512×512, satu untuk ketiga sistem | ✅ teruji |

## Kontrak

- Backend dijalankan dengan `clite serve --host 127.0.0.1 --port 0`. Variabel
  `CLITE_DESKTOP_BACKEND` mengganti perintahnya untuk pengembangan.
- Token dibuat acak (32 byte) dan diberikan lewat `CLITE_SESSION_TOKEN`.
- Port dibaca dari baris `CLITE_BACKEND_READY port=<n>`. Hanya baris yang berbentuk persis
  itu yang diterima. Backend yang keluar sebelum siap, atau tidak siap dalam 30 detik,
  menjadi galat yang menyertakan stderr-nya. Pelaporan proses yang keluar menunggu pipe
  ditutup agar stderr terakhir ikut terbaca.
- Jendela memuat `http://127.0.0.1:<port>/#token=<token>`.
- Navigasi: origin backend tetap di jendela; tautan `http`, `https`, `mailto` lain dibuka di
  browser pengguna; skema lain (`file:`, `javascript:`) ditolak. Tidak pernah ada jendela
  kedua di dalam aplikasi.
- Menutup aplikasi menghentikan backend (SIGTERM, lalu SIGKILL setelah lima detik).

## Status fitur

| Fitur | Status | Catatan |
|---|---|---|
| Peluncur backend dan kebijakan navigasi | ✅ | |
| Jalan pertama Electron | ✅ | Dijalankan 8 Oktober 2026 di Linux dengan display X, Electron 44.5.1; hasil per butir daftar periksa ada di `apps/desktop/README.md` |
| Ikon, menu, pemaketan installer, auto-update, tanda tangan kode | ⬜ | F5-T4 |
| Beberapa sesi sekaligus di satu jendela | ✅ | F5-T5: tiap sesi punya transkripnya sendiri; event dirutekan lewat `session_id` |
| Lampiran berkas (seret dan tempel) | ✅ | F5-T5: chip di kotak tulis; gambar dikirim sebagai bagian gambar, berkas lain lewat `attachment.save` dan path-nya disebut di pesan. Di desktop path aslinya dipakai (`webUtils.getPathForFile`), jadi tidak ada salinan |
| Notifikasi sistem | ✅ | F5-T5: giliran selesai atau persetujuan dibutuhkan saat jendela tidak terfokus. Memakai Notification API, jadi di desktop ia jadi notifikasi sistem dan di browser notifikasi browser; bisa dimatikan lewat `dashboard.notifications` |
| Tray | ⬜ | Belum ada task-nya |
| Pemilihan profil | ✅ | F5-T5: header menyebut profil yang dilayani backend ini; tab Profiles mendaftar semuanya. Aplikasi desktop memilih profil saat mulai (`--profile`, atau dialog bila ada lebih dari satu) dan menjalankan satu backend per profil |

## Membawa backend

Aplikasi desktop **tidak** menyertakan runtime Python: ia memanggil `clite` yang sudah terpasang.
Alasannya tiga. Pertama, ukuran: satu runtime CPython plus dependensinya melipatgandakan
artefak, dan harus dibangun ulang untuk tiap sistem dan arsitektur. Kedua, backend adalah
program yang berguna sendiri — pengguna `clite` di terminal sudah punya. Ketiga, kegagalannya
sudah terbaca: tanpa `clite` di `PATH`, aplikasi menampilkan pesan galat yang menyuruh menjalankan
`clite doctor`, bukan jendela kosong.

Konsekuensinya disebut apa adanya: installer tidak cukup untuk pengguna yang belum punya Python.
Kalau kelak itu dibutuhkan, yang berubah hanya `resolveBackendCommand`: ia sudah satu-satunya
tempat yang tahu cara memanggil backend.

## Pemaketan

- `electron-builder.config.cjs` menghasilkan **dmg** (macOS, x64 + arm64), **nsis** (Windows,
  x64), dan **AppImage** (Linux, x64). Nama produk ada di `src/brand.ts` dan di konfigurasi;
  tes memastikan keduanya sama dengan `clite.core.brand.DISPLAY_NAME`, dan versinya sama dengan
  `clite.__version__`.
- Tanpa sertifikat, build tetap menghasilkan artefak: `mac.identity: null` membuat macOS tidak
  mencari sertifikat dan gagal. Tanda tangan dan notarisasi hanya berjalan bila rahasia CI ada.
- Pembaruan otomatis belum dipasang. Installer yang diunduh pengguna tidak memeriksa rilis
  baru; itu langkah berikutnya, bukan yang ini.
- Yang dibangun untuk Linux dicoba dengan tangan di mesin uji; lihat `docs/STATUS.md`.

## Yang sengaja berbeda dari Hermes

Aplikasi desktop Hermes adalah aplikasi React besar (788 ribu baris TypeScript di
`apps/desktop/`) dengan renderer sendiri. Di sini cangkangnya sengaja tipis: satu dashboard
melayani browser dan desktop, sehingga hanya ada satu UI untuk dipelihara. Bila kelak
dibutuhkan renderer khusus desktop, `packages/shared` (klien dan reducer transkrip) sudah
disiapkan untuk itu.

## Celah yang diketahui

- Di mesin uji, proses GPU Chromium tidak bisa dipakai, jadi tes asap menjalankan Electron
  dengan `--disable-gpu` (dan `--no-sandbox` di kontainer); di CI Linux di bawah `xvfb-run`.
- Tautan luar, instance kedua, dan backend yang mati mendadak belum dicoba dengan tangan
  (lihat `apps/desktop/README.md`).
- Tidak ada penanganan untuk backend yang sudah berjalan dari instance lain selain kunci
  satu-instance milik Electron.
- Installer yang keluar dari `electron-builder` tidak ditandatangani. Itu disengaja tanpa
  sertifikat, tetapi artinya pengguna melihat peringatan Gatekeeper atau SmartScreen, dan
  catatan rilis mengatakannya. Pembaruan otomatis juga belum dipasang: installer yang diunduh
  tidak memeriksa rilis baru.
- Hanya installer Linux yang pernah dibangun di mesin ini. dmg dan nsis baru sebatas konfigurasi
  yang diuji, bukan artefak yang dijalankan.
