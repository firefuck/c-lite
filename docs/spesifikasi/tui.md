# Spesifikasi: TUI dan klien bersama

| | |
|---|---|
| Kode | `ui-tui/` (TUI), `apps/shared/` (klien protokol) |
| Bundle yang dikirim | `src/clite/tui_dist/clite-tui.mjs` (dibangun dari dua direktori di atas) |
| Tes | `ui-tui/test/` (18), `apps/shared/test/` (21), `tests/cli/test_tui_bundle.py` |
| Bahasa | TypeScript, dijalankan langsung oleh Node 22 (type stripping) |
| Bedah Hermes | [09-tui-dan-rpc](../hermes/09-tui-dan-rpc.md) |

## Tanggung jawab

Antarmuka terminal yang berbicara dengan backend Python lewat JSON-RPC di atas stdio. TUI
memiliki siklus hidup backend: ia menjalankan `python -m clite.rpc.entry`, dan backend keluar
ketika stdin-nya ditutup.

Dibanding REPL klasik, TUI menambah satu hal yang memerlukan dua proses: pengguna bisa
mengetik selagi agent bekerja.

## Bagian-bagian

**`apps/shared/src/`** (dipakai TUI dan aplikasi desktop)

| File | Isi |
|---|---|
| `contracts.generated.ts` | Tipe protokol, dihasilkan dari kontrak Python. Jangan disunting |
| `json-rpc-channel.ts` | `JsonRpcChannel`: peer JSON-RPC di atas transport apa pun |
| `transports.ts` | `LineTransport` (stdio), `WebSocketTransport` |
| `gateway-client.ts` | `GatewayClient`: klien bertipe di atas kontrak |
| `transcript.ts` | Transkrip sebagai fungsi murni dari event (reducer tanpa I/O) |

**`ui-tui/src/`**

| File | Isi |
|---|---|
| `entry.ts` | Argumen, memulai backend, menjalankan TUI |
| `backend.ts` | Menjalankan dan menghentikan proses backend |
| `plain.ts` | `PlainTui`: antarmuka berbasis baris di atas `node:readline` |
| `render.ts` | Pemformatan sebagai fungsi murni (warna, baris tool, banner) |
| `build.mjs` | Bundel esbuild ke satu file, disalin ke dalam paket Python |

## Kontrak

**Klien bersama**
- `client.request("nama.method", params)` diperiksa terhadap kontrak Python saat kompilasi:
  nama method salah, parameter kurang, atau bidang hasil yang salah eja adalah galat tipe.
- Respons galat menjadi `RpcError` dengan `code`, `message`, `data`. Koneksi yang putus
  menolak semua permintaan yang menunggu.
- Permintaan server tanpa handler, atau handler yang melempar, dibalas dengan galat, tidak
  dibiarkan menggantung.
- Reducer transkrip tidak punya I/O. TUI dan renderer desktop memakai reducer yang sama.

**TUI**
- Tanpa dependensi runtime selain Node: hanya `node:readline`. Bisa dikendalikan tes dengan
  stream biasa.
- **Masukan terminal** (TTY): baris yang dikirim saat giliran berjalan diserahkan ke kebijakan
  sibuk server (interupsi, antre, atau steer).
- **Masukan pipa** (bukan TTY) adalah skrip: tiap baris menunggu giliran sebelumnya selesai,
  dan baris berikutnya menjawab pertanyaan agent (persetujuan, klarifikasi) bila ada.
  Akhir masukan membiarkan giliran terakhir selesai lalu menutup sesi.
- Ctrl+C menghentikan giliran yang berjalan; tanpa giliran, keluar dengan kode 130.
- Persetujuan: jawaban yang tidak jelas berarti tolak.
- Backend yang gagal mulai dilaporkan dengan stderr-nya, tidak menggantung.
- Instalasi yang belum dikonfigurasi menjelaskan apa yang harus dilakukan (`clite setup`).

**Bundle**
- `npm run build` di `ui-tui/` membuat `dist/clite-tui.mjs` dan menyalinnya ke
  `src/clite/tui_dist/`, sehingga `pip install` mengirim `clite tui` yang berfungsi tanpa
  langkah build Node di mesin pengguna.
- `build-info.json` mencatat hash source. Tes Python menghitung ulang hash itu: bundle yang
  tidak dibangun ulang setelah source berubah menggagalkan suite.

## Status fitur

| Fitur | Status | Catatan |
|---|---|---|
| Klien bersama, reducer transkrip | ✅ | |
| TUI berbasis baris | ✅ | Diuji ujung ke ujung terhadap backend sungguhan dengan provider `mock` |
| Bundle di dalam wheel | ✅ | |
| `npm install` dan skrip `npm` di root | ⬜ belum diverifikasi | Tes dijalankan langsung dengan `node --test`: F1-T1 |
| TUI layar penuh (Ink/React): panel, status bar, diff | ⬜ | Memakai ulang `backend.ts`, `render.ts`, dan reducer: F3-T3 |
| Pelengkapan slash command, riwayat input | ⬜ | `complete.slash` dan `commands.catalog` sudah ada di protokol: F3-T3 |
| Render Markdown | ⬜ | F3-T2 |
| Flag `--toolsets`, `--max-turns` | ⬜ | Karena itu `display.interface: tui` jatuh ke REPL klasik bila flag itu dipakai |

## Yang sengaja berbeda dari Hermes

- **Tanpa Ink untuk sekarang.** TUI Hermes adalah aplikasi React (Ink) 104 ribu baris. Di sini
  antarmuka baris yang kecil dan teruji, dengan pemisahan yang membuat penggantinya bisa
  memakai ulang lapisan di bawahnya.
- **Tanpa langkah kompilasi untuk pengembangan.** Node 22 menjalankan `.ts` langsung;
  `tsconfig` memakai `erasableSyntaxOnly`, jadi tidak ada sintaks TypeScript yang butuh
  transformasi (tanpa `enum`, tanpa parameter property).

## Celah yang diketahui

- Versi dependensi pengembangan yang dipakai saat verifikasi: TypeScript 6.0, esbuild 0.28,
  `@types/node` 26. Rentang di `package.json` lebih longgar dan belum pernah dipasang lewat
  `npm install`.
- Tidak ada penanganan ubah ukuran terminal, karena belum ada tata letak.
