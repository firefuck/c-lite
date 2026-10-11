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
| `service.py` | Unit systemd/LaunchAgent, kunci per-home, dan drain SIGTERM |
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
- Pengguna yang diizinkan berbagi data profil: pencarian sesi dapat melihat percakapan
  pengguna lain, dan memori serta berkas juga bersama. Pemisahan konteks sesi tidak memberi
  privasi antar-pengguna. Model kepercayaan yang berlaku dijelaskan di
  [keamanan gateway](../arsitektur/06-keamanan.md#gateway).

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

**Suara**
- Pesan suara ditranskripsi sebelum menjadi giliran (`TranscriptionProvider` di
  `tools/speech.py`; plugin mendaftarkannya dengan `ctx.register_transcription_provider`).
  Giliran melihat kata-katanya, bukan path berkas; transkripnya masuk sebagai teks pengguna,
  sedangkan berkasnya tetap tersimpan di direktori media sesi. Batas `speech.max_seconds` dan
  `speech.max_bytes` diperiksa lebih dulu: rekaman yang melewatinya tidak dikirim ke mana pun
  untuk ditranskripsi. Batas ukuran itu hanya menggigit bila diset lebih ketat dari
  `attachments.max_bytes`, karena berkas yang lebih besar sudah ditolak sebelum disimpan.
- Tidak ada jalur suara yang boleh menggagalkan giliran. Tanpa provider, tanpa durasi yang bisa
  dibaca, atau dengan provider yang error, model tetap menerima pemberitahuan yang jujur dan
  pengguna tetap mendapat jawaban.
- Jawaban atas pesan suara dibalas suara hanya untuk platform yang disebut
  `speech.reply_with_voice`, dan hanya bila ada `SpeechProvider`. Jawaban yang lebih panjang
  dari `speech.max_chars` dibiarkan sebagai teks, bukan diucapkan sebagian. Salinan bersuara
  dibuat setelah jawaban teks terkirim dan bersifat bonus: kegagalannya tidak mengubah giliran.

**Persetujuan dan klarifikasi lewat chat**
- Perintah berbahaya: agent mengirim perintahnya dan menunggu `/approve`, `/approve session`,
  `/approve always`, atau `/deny`. Diam sampai `approvals.timeout` berarti tolak.
- Klarifikasi dijawab dengan nomor pilihan atau teks bebas.

**Toolset**
- Platform pesan memakai `clite-gateway` kecuali `platform_toolsets` menentukan lain.

**Telegram**
- Token dari `TELEGRAM_BOT_TOKEN` di `.env`. Long polling, tanpa webhook.
- Saat tersambung, adapter menerbitkan perintah gateway yang didukung ke menu slash native Telegram
  lewat `setMyCommands`. Nama dan deskripsi divalidasi terhadap batas Bot API (maksimum 100
  perintah, nama `[a-z0-9_]` hingga 32 karakter, deskripsi hingga 256 karakter). Kegagalan
  penerbitan menu hanya dicatat; polling dan chat tetap dimulai.
- Di grup, agent hanya menanggapi perintah, mention, atau balasan ke pesannya sendiri.
  Perintah yang ditujukan ke bot lain (`/cmd@botlain`) diabaikan.
- `/model` tanpa argumen di chat Telegram yang diizinkan mengirim keyboard inline berhalaman dari
  model yang tersedia. Tombol memanggil kembali ke runner, yang mengulang pemeriksaan otorisasi,
  menolak sesi sibuk, lalu mengganti model hanya untuk sesi chat tersebut dan mengganti pesan
  picker dengan konfirmasi. `/model <id>` tetap memakai jalur perintah teks yang sama di semua
  surface.
- Galat jaringan dan galat Bot API diredaksi sebelum dilempar atau dicatat: URL permintaan
  memuat token, dan sebagian galat `urllib` mengutip URL itu.

## Status fitur

| Fitur | Status | Catatan |
|---|---|---|
| Runner, kunci sesi, pairing, kebijakan sibuk | ✅ | |
| Persetujuan dan klarifikasi lewat chat | ✅ | |
| Adapter `local` | ✅ | |
| Adapter Telegram | 🟡 | Diuji terhadap Bot API tiruan; token tidak sampai ke log (`test_a_network_error_never_puts_the_bot_token_in_the_log`), menu slash native diterbitkan lewat `setMyCommands` tanpa menggagalkan chat bila Bot API menolaknya (`test_telegram_registers_the_supported_slash_commands_in_the_native_menu`, `test_telegram_starts_when_native_command_menu_registration_fails`), dan `/model` mengirim picker inline berhalaman, mengganti model sesi pada tap terotorisasi, serta menolak tap orang asing (`test_telegram_model_picker_switches_the_chat_session_from_an_inline_button`, `test_telegram_model_picker_pages_through_more_than_eight_models`, `test_telegram_model_picker_does_not_let_an_unauthorized_user_switch_the_owner_session`). Belum terhadap Telegram sungguhan: F1-T3 |
| Penjadwal cron di dalam gateway | ✅ | |
| Adapter Discord | 🟡 | Diuji terhadap WebSocket Gateway v10 dan REST API tiruan; token rahasia terdaftar; thread dan mention kanal ditangani; sambung ulang saat heartbeat terlewat. Belum dicoba terhadap server Discord sungguhan: F4-T1 |
| Adapter Slack | 🟡 | Socket Mode dan Web API diuji terhadap server tiruan lokal; event diakui (ack), deduplikasi event ganda, balasan di thread. Belum terhadap ruang kerja Slack sungguhan: F4-T2 |
| Adapter email | 🟡 | Plugin platform bawaan memakai polling IMAP dan SMTP pustaka standar. Hanya pengirim pada `allowed_users` yang diteruskan; `References` menjadi `thread_id` sesi. Diuji terhadap server IMAP dan SMTP tiruan lokal (`tests/gateway/test_email.py`); belum diuji terhadap layanan email asli: F4-T3 |
| Adapter Matrix | 🟡 | Plugin platform bawaan memakai Client-Server API `/sync` dengan long polling dan mengirim `m.room.message`. Hanya pengirim pada `allowed_users` yang diteruskan. E2EE sengaja belum didukung: event atau room terenkripsi tidak dibaca maupun dibalas. Diuji terhadap server Client-Server tiruan lokal (`tests/gateway/test_matrix.py`); belum diuji terhadap homeserver Matrix asli: F4-T3 |
| Adapter Signal | 🟡 | Plugin platform bawaan berbicara ke REST `signal-cli` yang dijalankan pengguna: polling `GET /v1/receive/<akun>` dan kirim DM melalui `POST /v2/send`. Hanya pengirim pada `allowed_users` yang diteruskan; tidak ada alur pairing. Diuji terhadap server REST tiruan lokal (`tests/gateway/test_signal.py`); belum diuji terhadap layanan Signal atau `signal-cli` asli: F4-T3 |
| Adapter WhatsApp | 🟡 | Plugin platform bawaan memakai webhook Cloud API resmi untuk pesan masuk yang diverifikasi dengan `X-Hub-Signature-256`, dan Graph API untuk balasan teks. Hanya pengirim pada `allowed_users` yang diteruskan. Diuji terhadap webhook dan Graph API tiruan lokal (`tests/gateway/test_whatsapp.py`); layanan WhatsApp Cloud API asli belum diverifikasi: F4-T3 |
| Lampiran masuk dan keluar (gambar, suara, dokumen) | 🟡 | `gateway/media.py` menyimpan lampiran ke `<home>/gateway/media/<sesi>`: jenis ditentukan dari isi berkas (bukan nama), batas ukuran ditolak sebelum ditulis, direktori dibersihkan saat sesi tutup. Gambar masuk ke permintaan model sebagai bagian konten; dokumen diberitahukan sebagai path yang bisa dibaca. `send_file` membatasi path ke direktori kerja + media sesi dan tetap lewat `read_denied_reason`. Telegram menerima foto/dokumen/suara/video (`fetch_attachment`) dan mengirim lewat `sendDocument`. Dijaga `tests/gateway/test_gateway.py`. Belum diuji terhadap Telegram sungguhan: F4-T4 |
| Pesan suara masuk, jawaban bersuara | 🟡 | Pesan suara ditranskripsi sebelum menjadi giliran lewat `TranscriptionProvider` (plugin bawaan `speech-openai`; backend tiruan di tes); batas `speech.max_bytes` / `speech.max_seconds` diperiksa lebih dulu dan kegagalan apa pun berakhir sebagai pemberitahuan, bukan giliran yang hilang. Jawaban bersuara hanya untuk platform di `speech.reply_with_voice`, lewat `SpeechProvider` dan `send_file`. Dijaga `tests/gateway/test_gateway.py`. Uji tangan di Telegram belum dijalankan (tidak ada kredensial): F6-T7 |
| Jawaban streaming (menyunting pesan), progres tool | ✅ | Adapter yang bisa menyunting (`can_edit`/`edit`) mendapat jawaban bertahap: `gateway/stream.py` mengirim satu pesan lalu menyuntingnya dengan batas laju, dan satu pesan status yang diperbarui untuk progres tool (`display.tool_progress`; level `message` mengirim satu pesan terpisah per tool call berisi emoji tool dan preview argumennya). Suntingan yang ditolak platform tidak kehilangan jawaban (sisa dikirim sebagai pesan baru). Adapter tanpa `edit` tetap seperti semula. Dijaga `tests/gateway/test_gateway.py`: F4-T5 |
| Layanan sistem (systemd, launchd), restart dengan drain | ✅ | `clite gateway install`, `uninstall`, `start`, `stop`, `restart`, `status`, dan `logs`; unit user systemd/LaunchAgent dibuat per profil, kunci menolak instance kedua dalam home yang sama, dan SIGTERM menghentikan pesan baru lalu menunggu giliran aktif. Dijaga `tests/gateway/test_service.py`: F4-T6. Verifikasi manual systemd Linux belum dilakukan. |
| Kebijakan reset sesi (menganggur, harian), home channel | ✅ | `gateway.session_reset` (`idle`, `daily`), notifikasi reset sesi satu kali; `/sethome` menetapkan home channel; cron `deliver: <platform>` mengirim ke home channel platform tersebut. Dijaga `tests/gateway/test_gateway.py`: F4-T7 |
| Tool `send_message` | ✅ | Agent mengirim ke chat lain lintas platform; hanya ditawarkan saat gateway berjalan, tujuan dibatasi (chat asal, home channel, `gateway.send_targets`). Dijaga `tests/gateway/test_gateway.py`: F4-T8 |
| Endpoint API kompatibel OpenAI, webhook masuk | ✅ | API opt-in memakai token server dan toolset `api`; webhook opt-in memverifikasi HMAC SHA-256 konstan-waktu, membungkus body sebagai data tak tepercaya, lalu mengirim jawaban ke tujuan yang dikonfigurasi. Dijaga `tests/server/test_server.py`: F4-T10 |

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
