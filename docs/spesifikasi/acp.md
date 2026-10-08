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

**Giliran**
- `session/prompt` adalah satu permintaan yang hasilnya adalah akhir giliran: `{"stopReason"}`.
  Teksnya menyusul lebih dulu sebagai notifikasi `session/update`.
- `prompt` adalah daftar blok. Hanya blok `text` yang diterima — handshake sudah menyatakan
  gambar, audio, dan sumber daya tertanam tidak didukung, jadi blok lain dibalas -32602 dengan
  menyebut indeksnya, bukan diam-diam dibuang. Beberapa blok teks digabung dengan baris baru.
- Satu sesi menjalankan satu giliran. `session/prompt` kedua saat giliran berjalan dibalas 4002,
  bukan diantre: protokolnya tidak punya tempat untuk giliran yang belum diminta klien.
- `stopReason` datang dari hasil giliran: `end_turn` (selesai), `cancelled` (diinterupsi),
  `refusal` (model menolak), `max_turn_requests` (anggaran giliran habis). Giliran yang berakhir
  tanpa jawaban — provider gagal, model diam — bukan `stopReason`: permintaannya dibalas galat
  4003, karena jawaban kosong yang tampak seperti `end_turn` menyesatkan editor.
- Teks yang mengalir menjadi `agent_message_chunk`, penalaran menjadi `agent_thought_chunk`;
  judul sesi yang berubah menjadi `session_info_update`. Status lain (kompresi, percobaan
  ulang) hanya masuk log, bukan ke protokol.
- `session/cancel` adalah notifikasi dan dijawab oleh permintaan prompt itu sendiri dengan
  `cancelled`. Ia dibaca di thread pembaca, bukan di pool: ia harus sampai saat giliran yang
  dibatalkannya masih memegang pekerja. Membatalkan sesi yang tidak ada bukan galat.

**Tool call**
- Tool yang mulai berjalan menjadi `tool_call`: `toolCallId`, `title` (satu baris dari argumen
  yang paling menjelaskan — path atau perintahnya — dipotong seperti tampilan lain), `kind`
  dari apa yang dikerjakan tool (`read`, `edit`, `search`, `fetch`, `execute`; yang tidak
  dikenal `other`, jadi tool baru tetap punya tampilan), `status: in_progress`, `rawInput`,
  dan `locations` berisi path bila tool menyentuh sebuah berkas supaya editor bisa
  membukanya. Statusnya `in_progress`, bukan `pending`: callback ini datang saat tool sudah
  mulai berjalan, dan izin yang mungkin ditanyakannya adalah bagian dari run itu.
- Tool yang selesai menjadi `tool_call_update` dengan `toolCallId` yang sama dan status
  `completed`, atau `failed` bila hasilnya muatan galat — termasuk perintah yang ditolak
  pengguna. Hasilnya dikirim sebagai satu blok teks yang dipotong 400 karakter, sama seperti
  permukaan RPC. `rawOutput` sengaja tidak dipakai: hasil yang besar tidak boleh masuk ke
  kawat. Diff juga tidak dikirim sebagai blok `diff` — isi berkas sesudah perubahan tidak ada
  di hasil tool.

**Izin**
- `approve` menjadi permintaan `session/request_permission` yang menunggu jawaban klien
  selama `approvals.timeout` (default 300 detik). Opsinya: `allow_once`, `allow_session`
  (diingat untuk sesi ini; berjenis `allow_once` karena protokolnya tidak punya jenis "sesi",
  tapi id opsinya milik kita), `allow_always` (masuk allowlist permanen), dan `reject_once`.
- Jawaban apa pun selain salah satu optionId itu — `cancelled`, optionId yang tidak pernah
  ditawarkan, jawaban yang bukan objek — berarti tolak. Diam juga berarti tolak: tanpa
  jawaban, giliran menunggu sampai batas waktunya lalu perintahnya tidak dijalankan. Klien
  tidak bisa membuka sebuah perintah hanya dengan tidak menjawab.
- Permintaan izin menamai tool call yang sedang berjalan; pelacakannya per thread, karena tool
  bisa berjalan paralel. Izin yang ditanyakan di luar tool call sama sekali (belum ada
  pemanggil seperti itu, tapi jalurnya ada) diberi tool call buatan ber-id `approval-N`, supaya
  pertanyaannya tidak menggantung tanpa sasaran.

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
| `session/prompt`: potongan pesan dan alasan berhenti | ✅ | Hanya blok teks; satu giliran per sesi; galat provider menjadi galat permintaan |
| `session/cancel` | ✅ | Notifikasi, dibaca di thread pembaca; prompt menjawab `cancelled` |
| Pembaruan tool call dan izin | ✅ | F6-T4: `tool_call`/`tool_call_update` dengan kind, status, `rawInput`, `locations`; izin lewat `session/request_permission` ke callback `approve`, dengan diam berarti tolak. Dijaga `tests/acp/test_acp.py`, termasuk satu giliran sungguhan lewat pipa dengan tool call dan permintaan izin |
| `plan` dari `agent.todos` dan `available_commands_update` | ⬜ | F6-T4 |
| `session/load`: memutar ulang riwayat tersimpan | ⬜ | F6-T4 |
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
- Perubahan berkas tidak dikirim sebagai blok `diff` (hanya teks hasil tool yang dipotong),
  dan `rawOutput` tidak dipakai.
- `clarify` belum dipetakan ke `elicitation/create`: alat itu menjawab bahwa tidak ada yang
  bisa ditanya. Editor yang mengumumkan kemampuan `elicitation` belum dimanfaatkan.
