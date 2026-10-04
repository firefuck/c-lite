# Spesifikasi: gateway

| | |
|---|---|
| Kode | `src/clite/gateway/` |
| Tes | `tests/gateway/` |
| Lapisan | 8. Boleh mengimpor `runtime` dan semua di bawahnya. Tidak mengimpor `rpc`, `server`, `cli` |
| Bedah Hermes | [12-gateway-cron](../hermes/12-gateway-cron.md) |

## Tanggung jawab

Satu proses berumur panjang yang melayani setiap platform chat yang dikonfigurasi: menerima
pesan, memutuskan siapa yang boleh bicara, mengarahkan pesan ke sesinya, menjalankan giliran,
dan mengirim jawaban. Proses yang sama menjalankan penjadwal cron.

## Bagian-bagian

| File | Isi |
|---|---|
| `event.py` | `MessageEvent`, `SessionSource`, `SendResult`: satu-satunya bentuk yang dikenal runner |
| `session.py` | `build_session_key`, `SessionMap` (kunci sesi ke id sesi tersimpan) |
| `pairing.py` | `PairingStore`: kode pairing untuk pengguna tak dikenal |
| `runner.py` | `GatewayRunner`: lapisan kebijakan antara platform dan agent |
| `platforms/base.py` | `BasePlatformAdapter`, registry `PLATFORMS`, `split_message` |
| `platforms/local.py` | Adapter dalam-proses untuk tes dan penyematan |
| `platforms/telegram.py` | Telegram lewat Bot API dengan long polling (pustaka standar) |

## Kontrak

**Adapter**
- Adapter melakukan tiga hal: tersambung dan mulai menerima, mengirim satu pesan, memutus.
  Ia menerjemahkan pesan platform menjadi `MessageEvent` dan memanggil `handle_message`.
  Ia **tidak** memutuskan siapa yang diizinkan atau apa arti sebuah perintah.
- Platform yang gagal mulai tidak menghentikan platform lain.

**Urutan untuk setiap pesan masuk** (`GatewayRunner.dispatch`)
1. Plugin boleh membuang atau menulis ulang pesan (`pre_gateway_dispatch`).
2. Otorisasi: `allowed_users` milik platform, `gateway.allow_all_users`, atau pengguna yang
   sudah di-pair. Orang asing di pesan langsung ditawari kode pairing; di tempat lain
   diabaikan.
3. Pesan diarahkan ke sesinya.
4. Bila sesi itu sedang menunggu jawaban (persetujuan atau klarifikasi), pesan itulah
   jawabannya.
5. Slash command dijalankan; selain itu menjadi giliran berikutnya, tunduk pada kebijakan
   sibuk.

**Kunci sesi**
- Pesan langsung: satu sesi per chat. Grup: satu sesi per chat dan thread, dan secara default
  juga per pengguna (`gateway.group_sessions_per_user`), supaya dua orang di grup yang sama
  tidak berbagi satu konteks.
- Pemetaan kunci ke id sesi disimpan (`<home>/gateway/sessions.json`). Memulai ulang gateway
  melanjutkan setiap percakapan.
- Sesi yang menganggur lebih lama dari `gateway.agent_cache_ttl_seconds` ditutup dari memori;
  pesan berikutnya melanjutkannya dari database.

**Pairing**
- Kode delapan karakter tanpa huruf yang mirip angka. Berlaku satu jam. Satu permintaan per
  pengguna per sepuluh menit, paling banyak tiga yang menunggu per platform, lima percobaan
  salah mengunci persetujuan selama satu jam.
- Pemilik menyetujui di mesin gateway: `clite gateway pair approve <platform> <kode>`.

**Giliran**
- Tiap giliran berjalan di thread sendiri: satu tugas panjang tidak menghalangi chat lain.
- Kebijakan sibuk (`display.busy_input_mode`): `interrupt` (default) menghentikan giliran
  berjalan dan menjalankan pesan baru; rentetan pesan digabung menjadi satu giliran. `queue`
  menjalankan berurutan. `steer` menyisipkan ke giliran berjalan.
- Jawaban panjang dipotong pada batas paragraf, lalu baris, lalu kata, sesuai
  `max_message_length` adapter.
- Giliran yang gagal dilaporkan di chat.

**Persetujuan dan klarifikasi lewat chat**
- Perintah berbahaya: agent mengirim perintahnya dan menunggu `/approve`, `/approve session`,
  `/approve always`, atau `/deny`. Diam sampai `approvals.timeout` berarti tolak.
- Klarifikasi dijawab dengan nomor pilihan atau teks bebas.

**Toolset**
- Platform pesan memakai `clite-gateway` kecuali `platform_toolsets` menentukan lain.

**Telegram**
- Token dari `TELEGRAM_BOT_TOKEN` di `.env`. Long polling, tanpa webhook.
- Di grup, agent hanya menanggapi perintah, mention, atau balasan ke pesannya sendiri.
  Perintah yang ditujukan ke bot lain (`/cmd@botlain`) diabaikan.

## Status fitur

| Fitur | Status | Catatan |
|---|---|---|
| Runner, kunci sesi, pairing, kebijakan sibuk | ✅ | |
| Persetujuan dan klarifikasi lewat chat | ✅ | |
| Adapter `local` | ✅ | |
| Adapter Telegram | 🟡 | Diuji terhadap Bot API tiruan, belum terhadap Telegram sungguhan: F1-T3 |
| Penjadwal cron di dalam gateway | ✅ | |
| Discord, Slack | ⬜ | F4-T1, F4-T2 |
| WhatsApp, Signal, Matrix, email, lainnya | ⬜ | F4-T3 |
| Lampiran masuk dan keluar (gambar, suara, dokumen) | ⬜ | `MessageEvent.attachments` ada, belum dipakai: F4-T4 |
| Jawaban streaming (menyunting pesan), progres tool | ⬜ | Hanya `send_typing`: F4-T5 |
| Layanan sistem (systemd, launchd), restart dengan drain | ⬜ | `clite gateway run` berjalan di latar depan: F4-T6 |
| Kebijakan reset sesi (menganggur, harian), home channel | ⬜ | F4-T7 |
| Tool `send_message` | ⬜ | F4-T8 |
| Endpoint API kompatibel OpenAI, webhook masuk | ⬜ | F4-T10 |

## Yang sengaja berbeda dari Hermes

- **Thread, bukan asyncio.** Gateway Hermes sepenuhnya asinkron. Di sini adapter menjalankan
  loop terimanya sendiri di thread, dan runner sinkron. Lebih sederhana; adapter berbasis
  WebSocket (Discord) perlu menjalankan event loop-nya sendiri di thread itu.
- **Runner tipis di atas `ChatSession`.** `gateway/run.py` Hermes enam ribu baris karena
  membuat dan mengelola agent sendiri.
- **Semua adapter lewat registry yang sama**, termasuk yang bawaan.

## Celah yang diketahui

- Tidak ada antrean keluar yang tahan lama: pesan yang gagal dikirim hanya dicatat di log.
- Tidak ada pembatasan laju per pengguna.
- `SessionMap` dan `PairingStore` membaca dan menulis seluruh file JSON pada setiap operasi.
