# Spesifikasi: desktop

| | |
|---|---|
| Kode | `apps/desktop/` |
| Tes | `apps/desktop/test/` (8 tes untuk bagian tanpa Electron) |
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
| Multi-sesi, lampiran file, notifikasi, tray | ⬜ | F5-T5 |
| Pemilihan profil | ⬜ | F5-T5 |

## Yang sengaja berbeda dari Hermes

Aplikasi desktop Hermes adalah aplikasi React besar (788 ribu baris TypeScript di
`apps/desktop/`) dengan renderer sendiri. Di sini cangkangnya sengaja tipis: satu dashboard
melayani browser dan desktop, sehingga hanya ada satu UI untuk dipelihara. Bila kelak
dibutuhkan renderer khusus desktop, `apps/shared` (klien dan reducer transkrip) sudah
disiapkan untuk itu.

## Celah yang diketahui

- Di mesin uji, proses GPU Chromium tidak bisa dipakai, jadi tes asap menjalankan Electron
  dengan `--disable-gpu` (dan `--no-sandbox` di kontainer); di CI Linux di bawah `xvfb-run`.
- Tautan luar, instance kedua, dan backend yang mati mendadak belum dicoba dengan tangan
  (lihat `apps/desktop/README.md`).
- Tidak ada penanganan untuk backend yang sudah berjalan dari instance lain selain kunci
  satu-instance milik Electron.
