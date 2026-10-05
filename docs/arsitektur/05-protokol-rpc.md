# Protokol RPC

Satu protokol menghubungkan backend Python dengan setiap front-end yang bukan Python: TUI,
aplikasi desktop, dan dashboard. Protokolnya JSON-RPC 2.0 dengan dua tambahan: **event** dari
server, dan **permintaan dari server ke klien**.

Daftar method, event, dan bidangnya dihasilkan dari kode di
[katalog](../referensi/katalog.md#protokol-json-rpc-versi-1). Dokumen ini menjelaskan amplop
dan alurnya. Kontrak yang dijaga tes ada di [spesifikasi rpc](../spesifikasi/rpc.md).

## Siapa berbicara lewat apa

| Klien | Transport | Backend dijalankan sebagai | Kode klien |
|---|---|---|---|
| TUI | stdio: satu dokumen JSON per baris | `python -m clite.rpc.entry` (proses anak TUI) | `apps/shared/src/` |
| Desktop | WebSocket: satu dokumen JSON per frame teks | `clite serve` (proses anak Electron) | `src/clite/server/static/rpc.js` |
| Dashboard | WebSocket | `clite dashboard` atau `clite serve` | `src/clite/server/static/rpc.js` |

Server (`RpcServer`) tidak tahu transport mana yang dipakai. Satu koneksi klien adalah satu
`RpcServer`; memutus koneksi mengakhiri semua sesinya.

## Empat jenis pesan

```
permintaan (klien → server)
  {"jsonrpc": "2.0", "id": 7, "method": "prompt.submit", "params": {"session_id": "ab12", "text": "halo"}}

balasan (server → klien)
  {"jsonrpc": "2.0", "id": 7, "result": {"accepted": true, "turn_id": "9f3c", "queued": false}}
  {"jsonrpc": "2.0", "id": 7, "error": {"code": 4001, "message": "no session 'ab12'; call session.create first"}}

event (server → klien, tanpa id)
  {"jsonrpc": "2.0", "method": "event",
   "params": {"type": "message.delta", "session_id": "ab12", "payload": {"text": "Hal"}, "seq": 12}}

permintaan dari server (server → klien, id berawalan "srq-")
  {"jsonrpc": "2.0", "id": "srq-1", "method": "approval.request",
   "params": {"session_id": "ab12", "command": "rm -rf build", "description": "recursive or forced delete",
              "pattern_keys": ["rm_recursive_or_force"]}}
  dijawab klien dengan balasan ber-id sama:
  {"jsonrpc": "2.0", "id": "srq-1", "result": {"choice": "once"}}
```

Semua event memakai method `"event"`; jenisnya ada di `params.type`. `seq` naik satu untuk
setiap event dalam satu koneksi, mulai dari 1.

## Alur sebuah koneksi

```
klien                                        server
  │  (tersambung)                               │
  │ ◄──────────── event gateway.ready ──────────│  {version, protocol_version}
  │ ── system.info ───────────────────────────► │
  │ ◄──────────── {configured, model, ...} ─────│  configured=false: tampilkan layar setup
  │ ── session.create {cwd?, resume?} ────────► │
  │ ◄──────────── {session_id, stored_session_id, model, tools, ...}
  │ ── prompt.submit {session_id, text} ──────► │
  │ ◄──────────── {accepted, turn_id} ──────────│  langsung kembali
  │ ◄──────────── event turn.start ─────────────│
  │ ◄──────────── event turn.step ──────────────│  iterasi 1
  │ ◄──────────── event message.complete ───────│  pesan asisten berisi tool call
  │ ◄──────────── event tool.start ─────────────│
  │ ◄──────────── approval.request (srq-1) ─────│  hanya bila perintahnya berbahaya
  │ ── balasan srq-1 {choice} ────────────────► │
  │ ◄──────────── event tool.complete ──────────│
  │ ◄──────────── event turn.step ──────────────│  iterasi 2
  │ ◄──────────── event message.delta (banyak) ─│
  │ ◄──────────── event message.complete ───────│
  │ ◄──────────── event turn.complete ──────────│  selalu datang, juga setelah galat
  │ ── session.close ─────────────────────────► │
```

Dua id sesi berbeda dan tidak boleh tertukar:

- `session_id` adalah id **runtime**, berlaku selama koneksi. Semua method dan event memakainya.
- `stored_session_id` adalah id di database. Dipakai untuk `session.create` dengan `resume`,
  dan untuk `session.delete`.

## Giliran sebagai aliran event

`prompt.submit` tidak menunggu jawaban. Urutan event satu giliran:

1. `turn.start` dengan `turn_id` dan teks pengguna.
2. Untuk setiap iterasi: `turn.step`, lalu `message.delta` dan `reasoning.delta` selama model
   menulis, lalu `message.complete`. Bila ada tool call: `tool.start` dan `tool.complete` untuk
   masing-masing.
3. `turn.complete` dengan `final_response`, `completed`, `interrupted`, `error`,
   `exit_reason`, `api_calls`, `duration`, dan `usage`.

`status.update` (kompresi, coba ulang, fallback) dan `subagent.update` bisa muncul di antara
event itu. `session.info` dikirim ulang ketika sesuatu pada sesi berubah, misalnya judul.

Klien membangun transkrip dari event, tidak dari balasan. `apps/shared/src/transcript.ts`
adalah reducer murni untuk itu, dipakai TUI dan disiapkan untuk renderer desktop.

## Masukan saat giliran berjalan

`prompt.submit` saat sesi sibuk mengikuti `busy_mode` (parameter, atau
`display.busy_input_mode`):

| Mode | Yang terjadi | Balasan |
|---|---|---|
| `interrupt` (default) | Giliran berjalan dihentikan, pesan baru dijalankan sesudahnya | `{accepted, turn_id, queued: true}` |
| `queue` | Pesan baru menunggu giliran berjalan selesai | `{accepted, turn_id, queued: true}` |
| `steer` | Teks disisipkan ke giliran berjalan; tidak ada giliran baru | `{accepted, queued: false}` dengan `turn_id` kosong |
| `reject` | Ditolak | Galat 4002 |

`session.interrupt` dan `session.steer` melakukan hal yang sama secara eksplisit. Slash
command yang tidak boleh jalan saat sibuk ditolak dengan 4002.

## Permintaan dari server

| Permintaan | Kapan | Jawaban | Tanpa jawaban |
|---|---|---|---|
| `approval.request` | Perintah berbahaya butuh keputusan | `{choice}`: `once`, `session`, `always`, `deny` | Tolak, setelah `approvals.timeout` |
| `clarify.request` | Tool `clarify` bertanya | `{answer}` | Model diberi tahu tidak ada jawaban |

Giliran **berhenti menunggu** selama permintaan ini terbuka. Klien harus selalu menjawab,
juga saat pengguna menutup dialog. Klien bersama membalas dengan galat bila tidak ada handler,
supaya server tidak menunggu sampai batas waktu.

## Kode galat

| Kode | Arti | Catatan |
|---:|---|---|
| -32700 | JSON tidak bisa di-parse | |
| -32600 | Bukan objek permintaan | |
| -32601 | Method tidak dikenal | |
| -32602 | Parameter salah | `data` berisi daftar `{field, problem}` |
| -32603 | Handler gagal | Bug di server |
| 4001 | Sesi tidak ada | Panggil `session.create` dulu |
| 4002 | Sesi sibuk | |
| 4003 | Belum dikonfigurasi | `data` berisi `code` dan `provider`; UI membuka layar setup |
| 4004 | Permintaan gagal | Galat yang bisa dijelaskan ke pengguna (`CliteError`) |

Galat adalah balasan. Satu permintaan yang buruk tidak pernah memutus koneksi.

## Khusus tiap transport

**Stdio.** Stdout adalah kawat. `rpc/entry.py` mengalihkan `sys.stdout` ke stderr selama proses
hidup, sehingga `print` yang nyasar dari tool atau plugin tidak merusak aliran. Proses keluar
saat stdin ditutup.

**WebSocket.** Endpoint `/api/ws`. Token sesi wajib (header `Authorization: Bearer`, header
`X-Clite-Token`, atau parameter `token`), dan `Origin` diperiksa. Koneksi yang gagal salah
satunya ditutup dengan kode 4401 sebelum diterima.

## Versi dan kompatibilitas

`PROTOCOL_VERSION` (saat ini 1) dikirim di `gateway.ready` dan `system.info`.

| Perubahan | Kompatibel | Cara |
|---|---|---|
| Menambah method atau event | ya | Tambahkan saja |
| Menambah bidang opsional pada hasil atau payload | ya | Tambahkan saja |
| Menambah bidang opsional pada parameter | ya untuk klien lama | Server lama menolak bidang yang tidak dikenalnya (-32602) |
| Menghapus atau mengganti nama bidang atau method | tidak | Buat method baru, pertahankan yang lama |
| Mengubah arti bidang yang ada | tidak | Buat bidang baru |

`PROTOCOL_VERSION` hanya dinaikkan untuk perubahan yang tidak bisa dibuat kompatibel. Klien
belum menolak versi yang tidak cocok; itu tercatat sebagai celah di spesifikasi.

## Menambah method atau event

Langkah lengkapnya ada di `src/clite/rpc/AGENTS.md`. Ringkasnya, urutannya selalu **kontrak,
generate, handler, tes, klien**:

1. Deklarasi di `src/clite/rpc/contracts/schema.py`.
2. `python scripts/gen_rpc_contracts.py` dan `python scripts/gen_docs.py`.
3. Handler di `src/clite/rpc/methods.py`, atau `self._emit(...)` di `src/clite/rpc/session.py`.
4. Tes di `tests/rpc/test_rpc.py`.
5. Klien: `apps/shared/src/` (lalu bangun ulang bundle TUI) dan `src/clite/server/static/`.

Tiga tes menggagalkan suite bila sebuah langkah terlewat:
`test_every_declared_method_has_a_handler_and_the_reverse`,
`test_typescript_contracts_match_the_python_contracts`, dan
`test_the_committed_bundle_was_built_from_the_current_sources`.
