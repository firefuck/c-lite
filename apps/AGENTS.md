# apps: aturan kerja

- `apps/shared/`: klien protokol TypeScript, dipakai TUI dan desktop. Spesifikasi:
  `docs/spesifikasi/tui.md`.
- `apps/desktop/`: cangkang Electron. Spesifikasi: `docs/spesifikasi/desktop.md`, dan baca
  `apps/desktop/README.md` untuk status verifikasinya.

Tes (dari masing-masing direktori): `node --test test/*.test.ts`

## Aturan yang tidak boleh dilanggar

1. **`apps/shared/src/contracts.generated.ts` tidak pernah disunting.** Ubah kontrak di
   `src/clite/rpc/contracts/schema.py`, lalu `python scripts/gen_rpc_contracts.py`.
2. **`apps/shared` tidak punya dependensi runtime dan tidak tahu ia berjalan di mana.** Tidak
   ada import `node:*` atau DOM di `json-rpc-channel.ts`, `gateway-client.ts`, dan
   `transcript.ts`; yang spesifik lingkungan hanya di `transports.ts`.
3. **Aplikasi desktop tidak punya UI sendiri.** Jendelanya memuat dashboard milik backend
   (`src/clite/server/static/`). Fitur UI ditambahkan di dashboard.
4. **Renderer tidak mendapat akses Node.** `contextIsolation: true`, `nodeIntegration: false`,
   `sandbox: true` tidak diubah. `preload.ts` membuka fakta, bukan kemampuan.
5. **Token sesi lewat environment, tidak pernah lewat argumen.**
6. **Bagian yang belum pernah dijalankan diberi tanda.** `main.ts` dan `preload.ts` memuat
   tulisan "NOT VERIFIED" di kepalanya. Hapus tanda itu hanya setelah benar-benar
   menjalankannya dan mencatat hasilnya di `apps/desktop/README.md`.
7. **Setelah mengubah `apps/shared/src/`, bangun ulang bundle TUI** (`npm run build` di
   `ui-tui/`).

## Jebakan

- Logika yang bisa diuji tanpa Electron ditaruh di luar `main.ts`
  (`backend-process.ts`, `window-policy.ts`). Pertahankan pemisahan itu: `main.ts` sebaiknya
  hanya perekat.
- `tsc` untuk `apps/desktop` membutuhkan paket `electron` terpasang (untuk tipenya).
