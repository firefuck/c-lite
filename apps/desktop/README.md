# Aplikasi desktop C-lite

Cangkang Electron tipis: menjalankan backend Python (`clite serve`), lalu menampilkan dashboard
milik backend itu di sebuah jendela. Tidak ada UI kedua di sini. Halaman yang tampil adalah
halaman yang sama dengan `clite dashboard`, jadi fitur baru di dashboard otomatis muncul di
aplikasi desktop.

## Status verifikasi

| Bagian | Status | Bukti |
| --- | --- | --- |
| `src/backend-process.ts` (menjalankan backend, membaca port, token) | Teruji | `test/backend-process.test.ts` menjalankan `python -m clite serve` sungguhan |
| `src/window-policy.ts` (ke mana jendela boleh bernavigasi) | Teruji | tes yang sama |
| Halaman dashboard yang dimuat | Teruji | `tests/server/test_dashboard_browser.py` (Chromium sungguhan) |
| `src/main.ts` (proses utama Electron) | Teruji | `test/smoke.test.ts` membuka aplikasi sungguhan, mengirim satu pesan ke provider `mock`, membaca jawabannya, lalu menutup jendela dan memastikan backend ikut berhenti |
| `src/preload.ts` | Teruji | idem: jendela yang dimuat di tes memakai jembatan ini |
| `npm install`, `npm start` | Teruji | `test/smoke.test.ts` menjalankan bundel `dist/main.cjs` yang sama dengan `npm start` |
| Pemaketan installer | Teruji sebagian | `electron-builder` menghasilkan `release/C-lite-0.1.0.AppImage` (Linux), dijalankan di mesin ini: jendela memuat dashboard dari backend yang dijalankannya sendiri. macOS dan Windows belum pernah dibangun. `test/packaging.test.ts` menjaga nama, versi, ikon, dan daftar berkas |
| `src/brand.ts`, `src/menu.ts` | Teruji | `test/packaging.test.ts` |
| Pemilihan profil saat mulai | Teruji | `test/backend-process.test.ts` (`--profile` masuk ke argv backend) dan `tests/server/test_dashboard_browser.py` (halaman Profiles) |

Versi Electron di `package.json` (`44.5.1`) adalah versi yang benar-benar dipakai menjalankan
tes asap, bukan versi terbaru saat scaffolding dibuat. Verifikasinya task `F5-T1` di
`docs/roadmap/`.

## Cara kerja

```
Electron main (main.ts)
  ├─ startBackend()                  backend-process.ts
  │    spawn: clite serve --host 127.0.0.1 --port 0
  │    env:   CLITE_SESSION_TOKEN=<token acak>      (tidak pernah lewat argumen)
  │    tunggu baris stdout: CLITE_BACKEND_READY port=<n>
  ├─ BrowserWindow.loadURL("http://127.0.0.1:<n>/#token=<token>")
  └─ decideNavigation()              window-policy.ts
       origin backend  -> tetap di jendela
       http/https/mailto lain -> dibuka di browser pengguna
       lainnya (file:, javascript:) -> ditolak
```

Renderer tidak mendapat akses Node (`contextIsolation: true`, `nodeIntegration: false`,
`sandbox: true`). Ia berbicara dengan backend lewat WebSocket `/api/ws`, sama seperti browser
biasa. `preload.ts` hanya memberi tahu halaman bahwa ia berjalan di aplikasi desktop.

## Menjalankan

Prasyarat: Node.js 22.12 atau lebih baru, dan perintah `clite` yang berfungsi di terminal
(`clite doctor`).

```bash
npm install            # di root repositori (workspaces)
npm test --workspace apps/desktop
npm start --workspace apps/desktop
```

Saat mengembangkan tanpa memasang paket Python, arahkan ke source:

```bash
CLITE_DESKTOP_BACKEND="python3 -m clite" PYTHONPATH=../../src npm start
```

## Memilih profil

Satu backend melayani satu profil, jadi profil dipilih sebelum backend dijalankan:

```bash
npm start --workspace apps/desktop -- --profile work
```

Tanpa `--profile`, aplikasi bertanya lebih dulu bila mesin punya lebih dari satu profil. Yang
sudah terpasang (`npm run package`) memakai flag yang sama. Daftar profilnya dibaca dengan
`clite profile list --json`.

## Membuat installer

```bash
npm run package --workspace apps/desktop -- --linux
npm run package --workspace apps/desktop -- --mac
npm run package --workspace apps/desktop -- --win
```

Hasilnya muncul di subdirektori `release` milik aplikasi desktop (diabaikan git, seperti `dist`).
Yang tidak ditandatangani tetap dibangun: tanpa sertifikat
macOS Gatekeeper dan Windows SmartScreen akan memperingatkan pengguna. Runtime Python **tidak**
disertakan — aplikasi memanggil `clite` yang sudah terpasang; alasannya di
`docs/spesifikasi/desktop.md`, bagian "Membawa backend".

## Percobaan pertama (8 Oktober 2026)

Dijalankan di Linux dengan display X, Electron 44.5.1, provider `mock`.

| # | Yang diperiksa | Hasil |
| --- | --- | --- |
| 1 | Jendela terbuka dan dashboard tampil | Ya. `test/smoke.test.ts` menunggu `#status-connection.online` dan status model terisi, lalu mengirim satu pesan dan membaca jawabannya (`You said: …`) |
| 2 | Menutup jendela menghentikan proses backend | Ya. Tes yang sama menutup jendela lewat DevTools (`Page.close`) dan menunggu port backend berhenti menerima sambungan |
| 3 | Tautan `https://` terbuka di browser pengguna | Belum dicoba dengan klik sungguhan. Aturannya dijaga `decideNavigation` (`test/backend-process.test.ts`) |
| 4 | Aplikasi kedua hanya memfokuskan jendela yang ada | Belum dicoba dengan dua peluncuran bersamaan. Jalurnya memakai kunci satu-instance Electron |
| 5 | Backend yang mati mendadak menampilkan dialog galat | Belum dicoba. Jalur kodenya ada di `main.ts`; `dialog.showErrorBox` menunggu ditekan, jadi tidak diotomatiskan |

Catatan lingkungan: di mesin uji ini proses GPU Chromium tidak bisa dipakai, jadi tes
menjalankan Electron dengan `--disable-gpu` (dan `--no-sandbox` di kontainer). Flag itu bisa
diganti lewat `CLITE_SMOKE_FLAGS`. Di CI Linux, tes berjalan di bawah `xvfb-run`.

## Belum ada

Pembaruan otomatis (installer tidak memeriksa rilis baru), tanda tangan kode dan notarisasi
(butuh sertifikat), dan build macOS/Windows yang belum pernah dijalankan. Semuanya ada di
roadmap fase 5.
