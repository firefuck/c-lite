# Spesifikasi: rpc

| | |
|---|---|
| Kode | `src/clite/rpc/` |
| Klien | `apps/shared/src/` (TypeScript), `src/clite/server/static/rpc.js` (browser) |
| Tes | `tests/rpc/`, `apps/shared/test/` |
| Lapisan | 8. Boleh mengimpor `runtime` dan semua di bawahnya. Tidak mengimpor `gateway`, `server`, `cli` |
| Bedah Hermes | [09-tui-dan-rpc](../hermes/09-tui-dan-rpc.md) |

## Tanggung jawab

Protokol antara backend Python dan setiap front-end yang bukan Python: TUI, aplikasi desktop,
dashboard. Satu protokol, dua transport: stdio (satu dokumen JSON per baris) dan WebSocket
(satu per frame teks).

## Bagian-bagian

| File | Isi |
|---|---|
| `contracts/base.py` | Registry method, event, dan permintaan server; `PROTOCOL_VERSION` |
| `contracts/schema.py` | Deklarasi protokol sebagai model Pydantic |
| `server.py` | `RpcServer`: satu instance per koneksi klien |
| `session.py` | `RpcSession`: `ChatSession` yang callback-nya menjadi event |
| `methods.py` | Handler method |
| `transport.py` | `StdioTransport`, `WebSocketTransport`, `MemoryTransport` (tes) |
| `entry.py` | `python -m clite.rpc.entry`: entry point stdio untuk TUI |

Daftar lengkap method, event, dan permintaan server ada di
[katalog](../referensi/katalog.md). Uraian amplop dan alurnya ada di
[arsitektur/05-protokol-rpc](../arsitektur/05-protokol-rpc.md).

## Kontrak

**Kontrak adalah sumber kebenaran**
- Setiap method, event, dan permintaan server dideklarasikan sekali sebagai model Pydantic.
  `scripts/gen_rpc_contracts.py` menghasilkan `apps/shared/src/contracts.generated.ts` dari
  sana. File hasil generate tidak pernah disunting dengan tangan. Dijaga tes.
- `Params` menolak bidang tak dikenal. Menambah bidang opsional kompatibel ke belakang;
  menghapus atau mengganti nama tidak: buat method baru.
- Setiap method yang dideklarasikan punya handler, dan sebaliknya. Dijaga tes.
- Payload event divalidasi terhadap kontraknya saat dikirim, sehingga penyimpangan gagal di
  tes, bukan di klien.

**Server**
- Agnostik transport dan tanpa logika percakapan: ia hanya menerjemahkan antara JSON-RPC dan
  `ChatSession`.
- Galat protokol adalah balasan, bukan crash: JSON rusak (-32700), bukan objek (-32600),
  method tak dikenal (-32601), parameter salah (-32602, dengan daftar bidang), kegagalan
  handler (-32603).
- Kode aplikasi: 4001 sesi tidak ada, 4002 sesi sibuk, 4003 belum dikonfigurasi (membawa
  `code` dan `provider` supaya UI bisa membuka layar setup), 4004 permintaan gagal.
- Handler berjalan di luar thread pembaca, supaya handler yang lambat tidak menghalangi
  balasan klien atas permintaan server.
- Menutup server mengakhiri semua sesinya dan membatalkan permintaan yang menunggu klien.

**Sesi**
- `session_id` di protokol adalah id runtime (per koneksi). `stored_session_id` adalah id di
  database. `session.create` dengan `resume` membuka sesi tersimpan.
- `prompt.submit` langsung kembali. Jawabannya datang sebagai event yang diakhiri
  `turn.complete`. Klien **selalu** menerima `turn.complete`, juga setelah galat.
- Mode sibuk (`busy_mode` atau `display.busy_input_mode`): `interrupt` menghentikan giliran
  berjalan lalu menjalankan pesan baru, `queue` mengantre, `steer` menyisipkan tanpa
  menghentikan, `reject` membalas galat 4002.
- Slash command yang tidak `BUSY_ALLOW` ditolak (4002) saat giliran berjalan.

**Permintaan server ke klien**
- `approval.request` dan `clarify.request` dikirim dengan id `srq-N` dan dijawab klien dengan
  respons ber-id sama. Tanpa jawaban dalam batas waktu, atau koneksi putus, berarti tolak
  (approval) atau tanpa jawaban (clarify).

**Stdio**
- Stdout adalah kawat. `entry.py` mengalihkan `sys.stdout` ke stderr selama proses hidup,
  supaya `print` nyasar dari tool atau plugin tidak merusak aliran.
- Proses keluar ketika stdin ditutup.

## Status fitur

| Fitur | Status | Catatan |
|---|---|---|
| 32 method, 13 event, 2 permintaan server | ✅ | Hermes: 251 method, 69 event, 13 permintaan server |
| Transport stdio dan WebSocket | ✅ | |
| Generator TypeScript dan pemeriksaan kesegaran | ✅ | |
| Klien TypeScript bersama (`apps/shared`) | ✅ | 21 tes |
| Pemutaran ulang event setelah sambung ulang | ⬜ | `seq` sudah ada di tiap event; belum ada penyangga: F5-T5 |
| Lampiran (gambar, file) pada prompt | ⬜ | F2-T6 |
| Method untuk profil, MCP, hook, log | ⬜ | F5-T2 |
| Versi protokol dinegosiasikan | 🟡 | `gateway.ready` membawa `protocol_version`; klien belum menolak versi yang tidak cocok |

## Yang sengaja berbeda dari Hermes

- **Nama `rpc`**, bukan `tui_gateway`: paket ini melayani TUI, desktop, dan dashboard.
- **Server tanpa state percakapan.** Di Hermes `tui_gateway` membuat dan mengelola agent
  sendiri; di sini semua lewat `runtime.ChatSession`.
- **Kontrak jauh lebih kecil**, sengaja: setiap method di sini punya tes.

## Celah yang diketahui

- Tidak ada batas ukuran pesan masuk.
- Satu koneksi WebSocket yang lambat membaca tidak diberi tekanan balik; event menumpuk di
  antrean pengirim.
