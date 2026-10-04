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
| `src/main.ts` (proses utama Electron) | **Belum pernah dijalankan** | ditulis tanpa Electron terpasang |
| `src/preload.ts` | **Belum pernah dijalankan** | idem |
| `npm install`, `npm start`, pemaketan installer | **Belum pernah dijalankan** | registry npm tidak terjangkau saat scaffolding dibuat |

Versi Electron di `package.json` (`^44.0.0`) adalah versi mayor terbaru saat scaffolding
dibuat, bukan versi yang sudah dicoba. Pekerjaan verifikasinya adalah task `F5-T1` di
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

## Yang perlu diperiksa pada percobaan pertama

1. Jendela terbuka dan dashboard tampil (bukan halaman kosong). Jika kosong, lihat stderr
   backend: `startBackend` menyertakannya di pesan galat.
2. Menutup jendela menghentikan proses backend (cek dengan `ps`).
3. Tautan `https://` di jawaban model terbuka di browser, bukan di dalam jendela.
4. Menjalankan aplikasi dua kali hanya memfokuskan jendela yang sudah ada.
5. Backend yang mati mendadak menampilkan dialog galat, bukan jendela mati.

Catat hasilnya di `docs/spesifikasi/` (bagian desktop) dan ubah tabel status di atas.

## Belum ada

Ikon aplikasi, menu, pembaruan otomatis, pemaketan (`electron-builder` atau sejenisnya),
tanda tangan kode, dan pemilihan profil. Semuanya ada di roadmap fase 5.
