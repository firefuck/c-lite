# Spesifikasi: server

| | |
|---|---|
| Kode | `src/clite/server/` (termasuk dashboard di `static/`) |
| Tes | `tests/server/` (HTTP dan WebSocket sungguhan; dashboard di Chromium sungguhan) |
| Lapisan | 9. Boleh mengimpor `rpc` dan semua di bawahnya |
| Bedah Hermes | [10-gui-desktop-dashboard](../hermes/10-gui-desktop-dashboard.md) |

## Tanggung jawab

Backend tanpa kepala untuk aplikasi desktop dan dashboard web: server HTTP kecil yang
menyajikan protokol JSON-RPC lewat WebSocket, beberapa rute REST hanya-baca, dan dashboard
statis.

## Rute

| Rute | Token | Isi |
|---|---|---|
| `GET /api/health` | tidak | Hidup atau tidak, versi |
| `GET /api/status` | ya | Versi, profil, model terkonfigurasi |
| `GET /api/sessions` | ya | Sesi tersimpan |
| `GET /api/sessions/{id}/messages` | ya | Satu transkrip |
| `WS /api/ws` | ya | JSON-RPC, protokol yang sama dengan TUI |
| `GET /` dan `/static/*` | tidak | Dashboard (tidak memuat rahasia) |

Semua yang bisa **dilakukan** klien lewat WebSocket. Rute REST hanya untuk integrasi baca dan
pemeriksaan kesehatan.

## Kontrak

**Startup** (`clite serve`, `clite dashboard`)
- Token sesi diambil dari `CLITE_SESSION_TOKEN` bila ada (proses induk sudah tahu, dan token
  tidak pernah muncul di baris perintah); kalau tidak, dibuat acak dan URL dashboard dicetak
  ke stderr. `clite serve` dan `clite dashboard` sengaja tidak punya opsi `--token`.
- Setelah soket terikat, tepat satu baris `CLITE_BACKEND_READY port=<n>` ditulis ke stdout.
  Dengan `--port 0`, dari situlah induk mengetahui port.
- Default hanya mendengarkan di `127.0.0.1`. Host lain memicu peringatan di stderr.

**Autentikasi**
- Satu token untuk semua rute `/api` kecuali health, dibandingkan dalam waktu konstan.
  Diterima sebagai `Authorization: Bearer`, header `X-Clite-Token`, atau parameter `token`
  (WebSocket dari browser tidak bisa mengirim header).
- WebSocket juga memeriksa `Origin`: hanya origin dashboard sendiri yang lolos, yaitu host dan
  port yang sama dengan tujuan permintaan (`localhost` dan `127.0.0.1` dianggap sama). Halaman
  dari port lain, halaman `file://`, dan frame ber-sandbox (`Origin: null`) ditolak. Klien
  non-browser tidak mengirim `Origin` dan lolos.
- Server yang terikat ke loopback hanya melayani permintaan `/api` yang ditujukan ke nama
  loopback (header `Host`). Situs yang namanya dialihkan ke 127.0.0.1 (DNS rebinding) tidak
  mendapat apa pun, juga dengan token yang benar.
- URL dashboard membawa token di fragmen (`#token=`), yang tidak pernah dikirim ke server atau
  ditulis ke log. Dashboard memindahkannya dari URL setelah dibaca.

**Koneksi**
- Satu `RpcServer` per koneksi WebSocket. Memutus koneksi mengakhiri sesi milik koneksi itu.

**Dashboard**
- JavaScript polos, tanpa langkah build, dikirim di dalam wheel. Empat file: `index.html`,
  `style.css`, `rpc.js`, `app.js`.
- Semua teks dari model dan tool dimasukkan sebagai teks, tidak pernah sebagai HTML.
- Fitur: obrolan dengan streaming, tampilan tool call dan hasilnya, dialog persetujuan dan
  klarifikasi, slash command, daftar dan pembukaan ulang sesi, tab tool/skill/plugin, layar
  setup saat belum ada provider.

## Status fitur

| Fitur | Status | Catatan |
|---|---|---|
| Server, token, pemeriksaan origin, baris siap | ✅ | |
| Dashboard obrolan | ✅ | 9 tes browser |
| Halaman konfigurasi, cron, log, memori, analitik | ⬜ | F5-T2 |
| Dashboard React + Vite | ⬜ | Hanya bila JS polos tidak lagi cukup: F5-T3 |
| TLS, autentikasi pengguna, akses jarak jauh | ⬜ | F5-T6 |
| Endpoint kompatibel OpenAI (`/v1/chat/completions`) | ⬜ | F4-T10 |
| Halaman dari plugin | ⬜ | F6-T5 |

## Yang sengaja berbeda dari Hermes

- **Satu server untuk desktop dan dashboard.** Hermes punya server dashboard terpisah
  (`hermes_cli/web_server.py`, FastAPI, puluhan rute REST) di samping gateway TUI.
- **Dashboard tanpa build.** Dashboard Hermes adalah aplikasi React (`web/`).
- **Starlette, bukan FastAPI.** Validasi sudah dilakukan kontrak RPC.

## Celah yang diketahui

- Token berumur sepanjang proses dan tidak bisa dicabut tanpa memulai ulang.
- Tidak ada pembatasan laju pada percobaan token.
