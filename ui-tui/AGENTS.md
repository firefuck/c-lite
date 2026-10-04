# ui-tui: aturan kerja

Antarmuka terminal (TypeScript) di atas protokol JSON-RPC. Spesifikasi:
`docs/spesifikasi/tui.md`. Klien protokolnya ada di `apps/shared/` (lihat `apps/AGENTS.md`).

Tes dan pemeriksaan (dari direktori ini):

    node --test test/*.test.ts      # butuh Node 22+ dan paket Python yang bisa diimpor
    npx tsc --noEmit -p .           # setelah npm install di root
    npm run build                   # membangun ulang bundle di src/clite/tui_dist/

## Aturan yang tidak boleh dilanggar

1. **Setelah mengubah `ui-tui/src/` atau `apps/shared/src/`, jalankan `npm run build` dan
   commit `src/clite/tui_dist/`.** Tes Python `test_the_committed_bundle_was_built_from_the_current_sources`
   gagal bila terlupa.
2. **TUI tidak punya logika percakapan.** Ia mengirim permintaan dan merender event. Aturan
   apa pun tentang sesi, perintah, atau persetujuan ada di backend.
3. **Hanya sintaks TypeScript yang bisa dihapus.** Tanpa `enum`, `namespace`, atau parameter
   property: Node menjalankan file ini dengan membuang tipe, bukan mengompilasi.
4. **Impor memakai akhiran `.ts`** dan `import type` untuk tipe (`verbatimModuleSyntax`).
5. **Pemformatan adalah fungsi murni di `render.ts`.** I/O hanya di `plain.ts` dan
   `backend.ts`.
6. **Tanpa dependensi runtime baru** tanpa keputusan eksplisit: bundle harus tetap satu file
   yang jalan hanya dengan Node.

## Resep

### Menampilkan event baru

1. Event dan payload-nya sudah dideklarasikan di kontrak Python dan
   `contracts.generated.ts` sudah dihasilkan ulang (lihat `src/clite/rpc/AGENTS.md`).
2. Bila event itu bagian dari transkrip, tangani di `apps/shared/src/transcript.ts` dan
   tambahkan tes di `apps/shared/test/transcript.test.ts`.
3. Tambahkan `case` di `PlainTui.handleEvent` (`src/plain.ts`) dan pemformatnya di
   `render.ts`.
4. Tes ujung ke ujung di `test/e2e.test.ts` memakai provider `mock`: arahan `!<tool> {json}`,
   `!sleep N`, `!error N` memicu perilaku yang diinginkan tanpa model sungguhan.
5. `npm run build`.

### Menambah flag baris perintah

`parseArgs` di `src/entry.ts`, teks `HELP` di file yang sama, lalu
`src/clite/cli/subcommands/tui.py::tui_arguments` bila flag itu juga diteruskan dari
`clite --tui`.

## Jebakan

- Tes ujung ke ujung menjalankan backend Python sungguhan. Ia menaruh `src/` repositori di
  `PYTHONPATH`; dependensi Python (pydantic, PyYAML, dan lain-lain) harus terpasang.
- `PlainTui` punya dua mode masukan. Tes yang meniru orang mengetik harus mengirim
  `interactive: true`; tanpa itu stream uji dianggap skrip dan tiap baris menunggu giliran.
- Respons dan event berbagi satu aliran. Event giliran bisa tiba sebelum respons
  `prompt.submit`; kode yang menunggu giliran membandingkan `turn_id`, bukan urutan.
