# server: aturan kerja

Backend HTTP dan WebSocket, serta dashboard statis. Spesifikasi: `docs/spesifikasi/server.md`.

Tes: `pytest tests/server -q` (tes browser butuh `playwright` dan Chromium; tanpa itu
dilewati).

## Aturan yang tidak boleh dilanggar

1. **Tindakan lewat WebSocket, bukan REST.** Jangan menambah rute REST yang mengubah sesuatu.
   Kemampuan baru adalah method RPC, sehingga TUI dan desktop ikut mendapatkannya.
2. **Setiap rute `/api` selain health memeriksa token.** Bungkus dengan `guarded(...)`, yang
   juga menolak permintaan ke server loopback bila header `Host`-nya bukan nama loopback.
   WebSocket dari browser hanya diterima dari origin dashboard sendiri (`origin_allowed`).
   Jangan melonggarkan keduanya untuk "memudahkan pengembangan".
3. **Token tidak pernah masuk log, baris perintah, atau query string yang dicetak.**
4. **Default hanya loopback.** Jangan mengubah host default.
5. **Dashboard tidak pernah memasang HTML dari model atau tool.** Pakai `textContent` dan
   pembuatan elemen; tidak ada `innerHTML` dengan data.
6. **Dashboard tetap tanpa build** sampai roadmap F5-T3 dikerjakan. Tidak ada dependensi npm
   di `static/`.

## Resep

### Menambah sesuatu ke dashboard

1. Bila butuh data baru: tambahkan method RPC dulu (lihat `src/clite/rpc/AGENTS.md`).
2. Ubah `static/app.js` (dan `index.html`, `style.css`).
3. Tambahkan tes di `tests/server/test_dashboard_browser.py`. Tes itu menjalankan server
   sungguhan dengan provider `mock` dan mengendalikan Chromium.
4. File statis baru harus cocok dengan pola `server/static/*.{html,css,js}` di
   `pyproject.toml`, kalau tidak ia tidak ikut ke wheel.

## Jebakan

- Handler REST berjalan di executor (kode sinkron); handler WebSocket berjalan di event loop.
  Jangan memanggil kode yang memblokir langsung dari coroutine.
- `RpcServer.close()` menginterupsi giliran dan menunggu thread-nya. Ia dipanggil lewat
  executor supaya event loop tidak terblokir.
- Tes memakai `--port 0` dan membaca baris `CLITE_BACKEND_READY`. Jangan mencetak apa pun ke
  stdout sebelum baris itu.
