# apps/desktop: aturan kerja

Cangkang Electron. Spesifikasi: `docs/spesifikasi/desktop.md`, dan baca
`apps/desktop/README.md` untuk status verifikasinya.

Tes: `node --test test/*.test.ts`

## Aturan yang tidak boleh dilanggar

1. **Aplikasi desktop tidak punya UI sendiri.** Jendelanya memuat dashboard milik backend
   (`src/clite/server/static/`, dibangun dari `apps/web/`). Fitur UI ditambahkan di dashboard.
2. **Renderer tidak mendapat akses Node.** `contextIsolation: true`, `nodeIntegration: false`,
   `sandbox: true` tidak diubah. `preload.ts` membuka fakta, bukan kemampuan.
3. **Token sesi lewat environment, tidak pernah lewat argumen.**
4. **Bagian yang belum pernah dijalankan diberi tanda.** `main.ts` dan `preload.ts` memuat
   tulisan "NOT VERIFIED" di kepalanya. Hapus tanda itu hanya setelah benar-benar
   menjalankannya dan mencatat hasilnya di `apps/desktop/README.md`.

## Jebakan

- Logika yang bisa diuji tanpa Electron ditaruh di luar `main.ts`
  (`backend-process.ts`, `window-policy.ts`). Pertahankan pemisahan itu: `main.ts` sebaiknya
  hanya perekat.
- `tsc` untuk `apps/desktop` membutuhkan paket `electron` terpasang (untuk tipenya).
