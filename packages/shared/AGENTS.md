# packages/shared: aturan kerja

Klien protokol TypeScript (`@clite/shared`): kanal JSON-RPC, `GatewayClient`, transport, dan
reducer transkrip. Dipakai TUI (`apps/tui/`) dan dashboard (`apps/web/`) lewat nama paketnya,
tidak lewat path relatif. Spesifikasi: `docs/spesifikasi/tui.md` dan `docs/spesifikasi/rpc.md`.

Tes: `node --test test/*.test.ts`

## Aturan yang tidak boleh dilanggar

1. **`src/contracts.generated.ts` tidak pernah disunting.** Ubah kontrak di
   `src/clite/rpc/contracts/schema.py`, lalu `python scripts/gen_rpc_contracts.py`.
2. **Paket ini tidak punya dependensi runtime dan tidak tahu ia berjalan di mana.** Tidak ada
   import `node:*` atau DOM di `json-rpc-channel.ts`, `gateway-client.ts`, dan `transcript.ts`;
   yang spesifik lingkungan hanya di `transports.ts`.
3. **Yang dipakai aplikasi diekspor dari `src/index.ts`.** Aplikasi mengimpor
   `@clite/shared`, tidak menjangkau file di dalam `src/`.
4. **Setelah mengubah `src/`, bangun ulang kedua bundle** (`npm run build` di `apps/tui/` dan
   di `apps/web/`); tes Python menolak bundle yang dibangun dari sumber lama.
