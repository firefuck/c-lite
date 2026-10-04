# Spesifikasi: desktop

| | |
|---|---|
| Kode | `apps/desktop/` |
| Tes | `apps/desktop/test/` (7 tes untuk bagian tanpa Electron) |
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
| `src/main.ts` | Proses utama Electron: jendela, satu instance, siklus hidup | ⬜ belum pernah dijalankan |
| `src/preload.ts` | Jembatan ke halaman (`window.cliteDesktop`) | ⬜ belum pernah dijalankan |
| `build.mjs` | Bundel esbuild ke `dist/main.cjs` dan `dist/preload.cjs` | ⬜ belum pernah dijalankan |

## Kontrak

- Backend dijalankan dengan `clite serve --host 127.0.0.1 --port 0`. Variabel
  `CLITE_DESKTOP_BACKEND` mengganti perintahnya untuk pengembangan.
- Token dibuat acak (32 byte) dan diberikan lewat `CLITE_SESSION_TOKEN`.
- Port dibaca dari baris `CLITE_BACKEND_READY port=<n>`. Hanya baris yang berbentuk persis
  itu yang diterima. Backend yang keluar sebelum siap, atau tidak siap dalam 30 detik,
  menjadi galat yang menyertakan stderr-nya.
- Jendela memuat `http://127.0.0.1:<port>/#token=<token>`.
- Navigasi: origin backend tetap di jendela; tautan `http`, `https`, `mailto` lain dibuka di
  browser pengguna; skema lain (`file:`, `javascript:`) ditolak. Tidak pernah ada jendela
  kedua di dalam aplikasi.
- Menutup aplikasi menghentikan backend (SIGTERM, lalu SIGKILL setelah lima detik).

## Status fitur

| Fitur | Status | Catatan |
|---|---|---|
| Peluncur backend dan kebijakan navigasi | ✅ | |
| Jalan pertama Electron | ⬜ | Daftar periksa ada di `apps/desktop/README.md`: F5-T1 |
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

- Versi Electron di `package.json` (`^44.0.0`) adalah versi mayor terbaru saat scaffolding
  dibuat (5 Oktober 2026), bukan versi yang sudah dicoba.
- Tidak ada penanganan untuk backend yang sudah berjalan dari instance lain selain kunci
  satu-instance milik Electron.
