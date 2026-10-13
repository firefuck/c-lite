# web: aturan kerja

Dashboard (React + TypeScript, dibangun Vite) di atas protokol JSON-RPC. Spesifikasi:
`docs/spesifikasi/server.md` (bagian Dashboard). Klien protokolnya ada di `packages/shared/`
(lihat `packages/shared/AGENTS.md`). Hasil build-nya disajikan backend dari `src/clite/server/static/`
dan dimuat juga oleh jendela aplikasi desktop.

Tes dan pemeriksaan (dari direktori ini):

    node --test test/*.test.ts      # state dashboard terhadap server tiruan, tanpa browser
    npx tsc --noEmit -p .           # setelah npm install di root
    npm run build                   # membangun ulang bundle di src/clite/server/static/

Tes browser ada di `tests/server/test_dashboard_browser.py` (butuh `playwright` dan Chromium).

## Aturan yang tidak boleh dilanggar

1. **Setelah mengubah `apps/web/src/`, `apps/web/index.html`, atau `packages/shared/src/`, jalankan
   `npm run build` dan commit `src/clite/server/static/`.** Tes Python
   `test_the_committed_bundle_was_built_from_the_current_sources` gagal bila terlupa.
2. **State tidak tahu React maupun DOM.** Semua yang mengubah state ada di
   `src/state/dashboard.ts`; yang spesifik browser hanya di `src/state/browser.ts`
   (`Platform`). Komponen membaca snapshot lewat `useDashboardState` dan memanggil method
   `Dashboard`. Dengan begitu `node --test` bisa menguji perilakunya tanpa halaman.
3. **Teks dari model, tool, atau berkas adalah teks.** Tidak ada `dangerouslySetInnerHTML` dan
   tidak ada `innerHTML`. Bingkai halaman plugin tetap ber-sandbox tanpa `allow-same-origin`.
4. **Token tidak pernah masuk log.** Ia dibaca dari fragmen URL, disimpan di
   `sessionStorage`, dan dihapus dari bilah alamat.
5. **Hanya sintaks TypeScript yang bisa dihapus** di file `.ts` (tanpa `enum`, `namespace`,
   parameter property): Node menjalankan tes dengan membuang tipe, bukan mengompilasi.
6. **Pertanyaan ke pengguna adalah data.** Dialog baru ditambahkan sebagai varian
   `DialogSpec` (`src/state/dialogs.ts`) beserta arti menutupnya dengan Escape (`dismissal`),
   lalu digambar di `src/dialogs/DialogHost.tsx`.

## Resep

### Menambah panel

1. Bila butuh data baru: tambahkan method RPC dulu (lihat `src/clite/rpc/AGENTS.md`).
2. Buat komponen di `src/panels/`, muat datanya dengan `useLoad`, jalankan aksi dengan
   `useAction`, dan baris dengan `Row`.
3. Daftarkan di `PANELS` di `src/App.tsx`.
4. Tambahkan tes browser di `tests/server/test_dashboard_browser.py`, lalu `npm run build`.

### Menampilkan event baru

1. Bila event itu bagian dari transkrip, tangani di `packages/shared/src/transcript.ts` (dipakai
   juga oleh TUI) dan gambar jenis item barunya di `src/components/Transcript.tsx`.
2. Bila ia mengubah state lain, tangani di `Dashboard.handleEvent` dan tambahkan tes di
   `test/dashboard.test.ts`.

## Jebakan

- Bundle tidak memakai hash di nama berkas (`assets/app.js`), supaya diff commit dan pola
  `package-data` tetap stabil. Server mengirim halaman dengan `Cache-Control: no-store`.
- `dashboard.start()` dipanggil sekali dari `src/main.tsx`; jangan memanggilnya dari komponen,
  karena `StrictMode` menjalankan efek dua kali saat pengembangan.
- Halaman plugin baru terdaftar setelah plugin dimuat, jadi bingkainya diambil sesudah
  `plugins.list` selesai.
