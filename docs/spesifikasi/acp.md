# Spesifikasi: acp

| | |
|---|---|
| Kode | `src/clite/acp/` |
| Tes | `tests/acp/` |
| Lapisan | 9. Boleh mengimpor `runtime` dan semua di bawahnya. Tidak mengimpor `server`, `cli` |
| Protokol | [Agent Client Protocol](https://agentclientprotocol.com) v1 (JSON-RPC 2.0) |
| Bedah Hermes | `acp_adapter/` di repositori Hermes |

## Tanggung jawab

Editor yang berbicara Agent Client Protocol — Zed dan klien lain — bisa memakai C-lite sebagai
agent-nya. `clite acp` menjalankan satu proses per editor di atas stdio; protokolnya milik
pihak luar, jadi bentuk yang dipakai di sini ditulis di halaman ini, bukan diambil dari
kontrak internal kita.

Kawatnya sama dengan yang dipakai TUI: satu dokumen JSON per baris di stdout
(`clite.rpc.transport`), tanpa `Content-Length`. Kunci JSON memakai camelCase dan jalur
absolut, seperti yang diminta protokolnya.

## Bagian-bagian

| File | Isi |
|---|---|
| `server.py` | `AcpServer`: pembacaan baris, tabel method, pool pekerja, permintaan ke klien, sesi |
| `session.py` | `AcpSession`: `ChatSession` yang menyampaikan pembaruan sebagai notifikasi |
| `entry.py` | `python -m clite.acp.entry`: entry point stdio, aturan stdout sama dengan RPC |

Tidak ada logika percakapan di ketiganya. Satu sesi adalah satu `runtime.ChatSession`,
dibangun `runtime.build_agent` dengan platform `acp`.

## Kontrak

**Handshake**
- Klien mengirim `initialize` lebih dulu; method lain menolak dengan -32600 bila belum.
  `protocolVersion` harus bilangan bulat. Versi yang tidak dikenal tidak ditolak: versi kita
  yang dikembalikan, dan klien memutuskan sendiri — dua versi yang berbeda bisa saja sepakat
  pada semua yang kita pakai.
- Jawabannya membawa `agentCapabilities.loadSession: true`, `promptCapabilities` yang
  menyatakan gambar, audio, dan sumber daya tertanam **tidak** didukung, `agentInfo`, dan
  `authMethods` kosong (tidak ada autentikasi).

**Kawat**
- JSON rusak menjawab -32700 dengan `id: null`; baris kosong tidak menjawab apa pun.
- Objek tanpa `method` dianggap balasan atas permintaan kita ke klien dan diserahkan ke
  permintaan yang menunggu.
- Method tak dikenal menjawab -32601 dan koneksi tetap hidup.
- Notifikasi (`session/cancel`) tidak pernah dijawab, termasuk saat gagal.
- Balasan hanya berisi `jsonrpc`, `id`, dan `result` atau `error`; tidak ada amplop sendiri.
  Galat hanya membawa `code` dan `message`.
- Kesalahan pada satu permintaan tidak mematikan koneksi: handler yang melempar dibalas -32603.

**Permintaan ke klien**
- Server bisa mengirim permintaan ber-id `acp-N` dan menunggu balasannya. Tanpa jawaban dalam
  `CLIENT_REQUEST_TIMEOUT_SECONDS`, atau saat koneksi putus, hasilnya `None` — pemanggil yang
  menentukan artinya, dan untuk permintaan izin artinya tolak.

**Sesi**
- `session/new` butuh `cwd` absolut; `cwd` relatif atau kosong dibalas -32602, bukan sesi yang
  salah tempat.
- `mcpServers` dari klien diterima tanpa galat tetapi diabaikan: c-lite mengambil server MCP
  dari config-nya sendiri. Diabaikannya dicatat di log.
- Id sesi berawalan `sess_`. Menutup server menutup semua sesi dan membatalkan permintaan yang
  menunggu klien.

**Stdio**
- Stdout adalah kawat. `entry.py` mengalihkan `sys.stdout` ke stderr selama proses hidup,
  sehingga `print` nyasar dari sebuah tool tidak merusak aliran protokol.
- Proses keluar ketika stdin ditutup.

## Status fitur

| Fitur | Status | Catatan |
|---|---|---|
| `initialize` dan negosiasi kemampuan | ✅ | Versi tidak dikenal dijawab dengan versi kita |
| `session/new` atas `ChatSession` | ✅ | `cwd` wajib absolut; `mcpServers` klien diabaikan |
| `clite acp` dan `python -m clite.acp.entry` | ✅ | Entry point sungguhan diuji lewat pipa di `tests/acp/test_acp.py` |
| `session/prompt`: potongan pesan dan alasan berhenti | ⬜ | F6-T4 |
| `session/cancel` | ⬜ | F6-T4 |
| Pembaruan tool call, izin, dan `plan` dari `todo` | ⬜ | F6-T4 |
| `session/load`: memutar ulang riwayat tersimpan | ⬜ | F6-T4 |
| `available_commands_update` dari `command_catalog` | ⬜ | F6-T4 |
| Kemampuan sisi klien (editor menjalankan terminal, membaca berkas) | ⬜ | Di luar lingkup F6-T4 |

## Yang sengaja berbeda dari Hermes

- **Protokol ditulis tangan, tanpa paket pihak ketiga.** Tidak ada `agent_client_protocol`
  yang terpasang, dan spesifikasinya masih bergerak; validasi parameter ditulis dengan tangan
  dengan galat -32602 yang menyebut bidangnya, bukan lewat model Pydantic.
- **Kawatnya dipinjam, tidak disalin.** Framing NDJSON dan transport datang dari
  `clite.rpc.transport` — satu transport untuk TUI, dashboard, dan ACP.

## Celah yang diketahui

- Belum pernah dijalankan di editor sungguhan; hanya lewat klien berskrip dan pipa nyata.
- Permintaan MCP dari klien dibuang diam-diam kecuali satu baris peringatan di log.
- Tidak ada batas ukuran pesan masuk.
