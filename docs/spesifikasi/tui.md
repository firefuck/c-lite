# Spesifikasi: TUI dan klien bersama

| | |
|---|---|
| Kode | `apps/tui/` (TUI), `packages/shared/` (klien protokol) |
| Bundle yang dikirim | `src/clite/tui_dist/clite-tui.mjs` (dibangun dari dua direktori di atas) |
| Tes | `apps/tui/test/`, `packages/shared/test/`, `tests/cli/test_tui_bundle.py`. Jumlah terkininya di [STATUS](../STATUS.md#dijaga-tes) |
| Bahasa | TypeScript, dijalankan langsung oleh Node 22 (type stripping) |
| Bedah Hermes | [09-tui-dan-rpc](../hermes/09-tui-dan-rpc.md) |

## Tanggung jawab

Antarmuka terminal yang berbicara dengan backend Python lewat JSON-RPC di atas stdio. TUI
memiliki siklus hidup backend: ia menjalankan `python -m clite.rpc.entry`, dan backend keluar
ketika stdin-nya ditutup.

Dibanding REPL klasik, TUI menambah satu hal yang memerlukan dua proses: pengguna bisa
mengetik selagi agent bekerja.

## Bagian-bagian

**`packages/shared/src/`** (dipakai TUI dan aplikasi desktop)

| File | Isi |
|---|---|
| `contracts.generated.ts` | Tipe protokol, dihasilkan dari kontrak Python. Jangan disunting |
| `json-rpc-channel.ts` | `JsonRpcChannel`: peer JSON-RPC di atas transport apa pun |
| `transports.ts` | `LineTransport` (stdio), `WebSocketTransport` |
| `gateway-client.ts` | `GatewayClient`: klien bertipe di atas kontrak |
| `transcript.ts` | Transkrip sebagai fungsi murni dari event (reducer tanpa I/O) |

**`apps/tui/src/`**

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
- `npm run build` di `apps/tui/` membuat `dist/clite-tui.mjs` dan menyalinnya ke
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
| `npm ci` dan skrip `npm` di root | ✅ | Job Node di CI menjalankan `npm ci`, tes, dan `npm run build` |
| TUI layar penuh (Ink/React): panel, dashboard status, diff | ✅ | Dashboard satu baris menampilkan aktivitas idle/berpikir/tool, model/provider, konteks terukur `terpakai/total` dan persen, token masuk/keluar giliran terakhir, judul/id sesi bila ada, serta cwd. Ia memakai `session.info` dan event yang sudah ada; server menerbitkan `session.info` segar sebelum `turn.complete` agar konteks terukur ikut berubah. Pada lebar sempit, aktivitas/model/konteks diprioritaskan. Dijaga `apps/tui/test/app.test.ts`, `tests/rpc/test_rpc.py`, dan `tests/cli/test_tui_bundle.py`: F3-T3/F3-T10 |
| Pelengkapan slash command di TUI | ✅ | Kotak tulis Ink melengkapi perintah slash dari `commands.catalog`; Tab melengkapi satu kandidat atau membuka daftar; Esc menutup. Dijaga `apps/tui/test/app.test.ts`: F3-T12 |
| Pemilih sesi dan model di TUI | ✅ | Overlay Ink memilih sesi dari `session.list` (memicu `session.create` resume) dan model dari `model.list` (memicu `model.set`). Dijaga `apps/tui/test/app.test.ts`: F3-T13 |
| Tema TUI dari skin | ✅ | Skin dipetakan ke kode ANSI via `markdownRoleCodes` (padanan `markdown_role_codes` Python); transkrip membungkus saat terminal mengecil dan status bar tetap satu baris. Dijaga `apps/tui/test/app.test.ts`: F3-T14 |
| Bundle TUI satu file | ✅ | Bundle `clite-tui.mjs` memuat Ink dan React secara mandiri tanpa dependensi runtime eksternal di `node_modules`, ukuran < 3MB, dan waktu mulai cepat. Dijaga `tests/cli/test_tui_bundle.py`: F3-T15 |
| Render Markdown | ✅ | F3-T2: `apps/tui/src/render.ts` memakai aturan yang sama dengan `cli/markdown.py` — perender bertahap pada `message.delta`, blok kode tidak dibaca sebagai Markdown, tabel dipotong sesuai lebar; `tool.complete` membawa `diff` (string; kosong bila tool tidak mengubah berkas) yang dirender berwarna dengan batas panjang. Warna dari `MarkdownStyle` (tanpa kode warna sendiri); tanpa warna keluaran polos. Dijaga `apps/tui/test/render.test.ts` |
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
