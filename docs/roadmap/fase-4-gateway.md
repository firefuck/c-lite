# Fase 4: gateway

Fase ini membuat agent hidup di aplikasi chat dan berjalan sebagai layanan. Tiga hal yang
perlu dipegang sebelum menulis adapter:

- **Adapter hanya menerima, mengirim, dan memutus.** Siapa yang diizinkan, sesi mana yang
  dituju, dan apa arti sebuah perintah diputuskan `GatewayRunner`. Resep lengkapnya ada di
  `src/clite/gateway/AGENTS.md`.
- **Runner sinkron dan berbasis thread.** Pustaka platform yang asinkron menjalankan event
  loop-nya sendiri di thread adapter.
- **Mengizinkan seorang pengguna chat berarti memberinya akses setara shell** ke mesin
  gateway. Baca [arsitektur/06-keamanan.md](../arsitektur/06-keamanan.md#gateway) sebelum
  menambah cara baru untuk mengizinkan pengguna.

Setiap adapter baru diuji dulu terhadap server tiruan lokal yang meniru API platformnya
(pola yang dipakai tes Telegram), lalu dicoba dengan tangan terhadap platform yang asli.
Adapter yang belum pernah dicoba sungguhan diberi status 🟡, bukan ✅.

Aturan yang berlaku untuk semua task ada di [README](README.md#selesai-itu-apa).

---

### F4-T1 Discord

**Tujuan.** Agent menjawab di Discord: pesan langsung, mention di kanal, dan thread.

**Lingkup.**
- Adapter di atas Gateway WebSocket dan REST Discord, memakai dependensi `websockets` yang
  sudah ada. Tanpa pustaka Discord pihak ketiga.
- Koneksi: identify, heartbeat, resume setelah putus, sambung ulang dengan jeda membesar.
- Pesan langsung selalu dijawab. Di kanal, hanya mention dan balasan ke pesan agent.
- Thread menjadi `thread_id` pada `SessionSource`, sehingga tiap thread punya sesinya sendiri.
- Batas 2000 karakter per pesan lewat `max_message_length`; indikator mengetik.
- `allowed_users` berisi id pengguna Discord. Peran (role) tidak dipakai untuk otorisasi di
  task ini.

**Di luar lingkup.** Suara, slash command native Discord, lampiran (F4-T4).

**File.** `src/clite/gateway/platforms/discord.py (baru)`, `src/clite/gateway/runner.py`,
`tests/gateway/test_discord.py (baru)`, `docs/spesifikasi/gateway.md`.

**Rujukan Hermes.** `plugins/platforms/discord/adapter.py`,
`gateway/platforms/ADDING_A_PLATFORM.md`,
`website/docs/developer-guide/adding-platform-adapters.md`.

**Selesai bila.**
- [ ] Tes terhadap server WebSocket lokal yang meniru Gateway Discord: pesan masuk, jawaban,
      heartbeat yang terlewat memicu sambung ulang.
- [ ] Tes: token bot terdaftar sebagai kredensial dan tidak muncul di log.
- [ ] Daftar periksa manual terhadap Discord asli dijalankan dan dicatat di `docs/STATUS.md`.

**Ukuran.** M

**Bergantung pada.** F1-T3

**Butuh dari Anda.** Token bot Discord dan satu server uji.

---

### F4-T2 Slack

**Tujuan.** Agent menjawab di Slack: pesan langsung, mention, dan balasan di thread.

**Lingkup.**
- Adapter Socket Mode (WebSocket keluar, tidak butuh URL publik) dan Web API untuk mengirim.
- Dua kredensial: token aplikasi dan token bot.
- Balasan selalu di thread pesan pemicunya; thread menjadi `thread_id`.
- Setiap event diakui (ack) sebelum giliran dimulai, supaya Slack tidak mengirim ulang.
  Event ganda dibuang berdasarkan id.
- Format teks Slack (mrkdwn) untuk jawaban; pemotongan sesuai batas blok.

**Di luar lingkup.** Slash command Slack, Block Kit interaktif, lampiran (F4-T4).

**File.** `src/clite/gateway/platforms/slack.py (baru)`, `tests/gateway/test_slack.py (baru)`,
`docs/spesifikasi/gateway.md`.

**Rujukan Hermes.** `plugins/platforms/slack/adapter.py`,
`plugins/platforms/slack/block_kit.py`.

**Selesai bila.**
- [ ] Tes terhadap server Socket Mode tiruan: event diakui, event ganda tidak memicu dua
      giliran, jawaban masuk ke thread yang benar.
- [ ] Daftar periksa manual terhadap Slack asli dijalankan dan dicatat.

**Ukuran.** M

**Bergantung pada.** F1-T3

**Butuh dari Anda.** Aplikasi Slack dengan Socket Mode aktif di ruang kerja uji.

---

### F4-T3 WhatsApp, Signal, Matrix, email

**Tujuan.** Empat platform lagi, masing-masing sebagai adapter yang berdiri sendiri.

**Lingkup.** Satu sub-langkah dan satu commit per platform. Urutan yang disarankan, dari yang
paling sedikit ketergantungannya:
1. **Email.** IMAP (IDLE atau polling) untuk masuk, SMTP untuk keluar, pustaka standar. Sesi
   per utas email (`References`). Hanya pengirim di `allowed_users` yang dijawab; email tidak
   punya alur pairing.
2. **Matrix.** API client-server dengan long polling `/sync`. Tanpa enkripsi ujung ke ujung
   di tahap ini, dan itu dinyatakan jelas di dokumentasi.
3. **Signal.** Lewat `signal-cli` dalam mode REST atau JSON-RPC yang dijalankan pengguna.
4. **WhatsApp.** Cloud API resmi. Pesan masuk datang lewat webhook, jadi sub-langkah ini
   bergantung pada F4-T10.

Setiap adapter dikirim sebagai plugin berjenis `platform` di `src/clite/bundled/plugins/`,
supaya dependensinya tidak membebani pemasangan dasar.

**File.** `src/clite/bundled/plugins/ (satu direktori plugin per platform)`,
`tests/gateway/ (satu file tes per platform)`, `docs/spesifikasi/gateway.md`.

**Rujukan Hermes.** `plugins/platforms/email/adapter.py`,
`plugins/platforms/matrix/adapter.py`, `gateway/platforms/signal.py`,
`gateway/platforms/whatsapp_cloud.py`, `plugins/platforms/whatsapp/adapter.py`.

**Selesai bila.**
- [ ] Tiap adapter punya tes terhadap server tiruan lokal untuk protokolnya.
- [ ] `test_bundled_plugins_use_only_the_plugin_api` tetap lulus: adapter mendaftar lewat
      `ctx.register_platform`.
- [ ] Tabel platform di spesifikasi gateway menyebut, per platform, apakah sudah dicoba
      terhadap layanan asli.

**Ukuran.** L

**Bergantung pada.** F1-T3

**Butuh dari Anda.** Akun uji untuk platform yang ingin Anda tandai "sudah dicoba".

---

### F4-T4 Lampiran masuk dan keluar

**Tujuan.** Pengguna chat bisa mengirim gambar dan dokumen ke agent, dan agent bisa mengirim
file kembali.

**Lingkup.**
- Masuk: adapter mengisi `MessageEvent.attachments` (jenis, nama, ukuran, cara mengunduh).
  Runner mengunduh ke direktori milik sesi di `<home>/gateway/media/`, dengan batas ukuran dan
  pemeriksaan jenis dari isi file, bukan dari nama.
- Gambar diteruskan ke model sebagai bagian konten (F2-T6). Dokumen diberitahukan ke model
  sebagai path yang bisa ia baca dengan tool file.
- Keluar: `BasePlatformAdapter.send_file`, dan tool `send_file` yang hanya ditawarkan di
  platform pesan. Path dibatasi ke direktori kerja dan direktori media sesi, dan tetap
  melewati `read_denied_reason`.
- Direktori media dibersihkan bersama sesi.

**File.** `src/clite/gateway/event.py`, `src/clite/gateway/runner.py`,
`src/clite/gateway/media.py (baru)`, `src/clite/gateway/platforms/base.py`,
`src/clite/gateway/platforms/telegram.py`, `src/clite/tools/builtin/send_file.py (baru)`,
`tests/gateway/test_gateway.py`.

**Rujukan Hermes.** `gateway/media_fetch.py`, `gateway/media_policy.py`,
`gateway/platforms/media_cache.py`.

**Selesai bila.**
- [ ] Tes: gambar dari adapter `local` sampai ke permintaan model sebagai bagian konten.
- [ ] Tes: file yang melebihi batas ditolak dengan pesan ke pengguna, tanpa mengunduh
      seluruhnya.
- [ ] Tes: `send_file` menolak `.env` milik agent dan path di luar direktori yang diizinkan.
- [ ] Baris "Lampiran masuk dan keluar" di spesifikasi gateway menjadi ✅ untuk Telegram.

**Ukuran.** M

**Bergantung pada.** F2-T6

---

### F4-T5 Jawaban streaming dan progres tool di chat

**Tujuan.** Di chat, jawaban muncul bertahap dan pengguna melihat apa yang sedang dikerjakan
agent, alih-alih menunggu dalam diam.

**Lingkup.**
- Kemampuan opsional pada adapter: `edit(chat_id, message_id, text)`. Runner mengirim satu
  pesan lalu menyuntingnya saat teks bertambah, dengan batas laju per platform.
- Progres tool mengikuti `display.tool_progress`: satu pesan status yang diperbarui, bukan
  satu pesan per tool.
- Adapter tanpa `edit` tetap berperilaku seperti sekarang: indikator mengetik, lalu jawaban
  utuh.
- Jawaban yang melewati `max_message_length` di tengah streaming dipecah ke pesan baru pada
  batas yang wajar.

**File.** `src/clite/gateway/runner.py`, `src/clite/gateway/stream.py (baru)`,
`src/clite/gateway/platforms/base.py`, `src/clite/gateway/platforms/telegram.py`,
`src/clite/gateway/platforms/local.py`, `tests/gateway/test_gateway.py`.

**Rujukan Hermes.** `gateway/stream_consumer.py`, `gateway/stream_dispatch.py`,
`gateway/stream_events.py`.

**Selesai bila.**
- [ ] Tes dengan adapter `local` yang mendukung `edit`: jumlah suntingan dibatasi lajunya dan
      isi akhirnya sama dengan jawaban utuh.
- [ ] Tes: suntingan yang gagal (batas laju platform) tidak menggagalkan giliran; jawaban
      akhir tetap terkirim.
- [ ] Baris "Jawaban streaming" di spesifikasi gateway menjadi ✅.

**Ukuran.** M

**Bergantung pada.** F1-T3

---

### F4-T6 Gateway sebagai layanan sistem

**Tujuan.** Gateway menyala saat mesin menyala, dimulai ulang bila mati, dan berhenti tanpa
memotong giliran yang sedang berjalan.

**Lingkup.**
- `clite gateway install | uninstall | start | stop | restart | status | logs`: unit pengguna
  systemd di Linux, LaunchAgent di macOS.
- Berhenti dengan tenang pada SIGTERM: tidak menerima pesan baru, menunggu giliran berjalan
  sampai batas waktu, memberi tahu chat yang gilirannya terpotong.
- Satu instance per home: file kunci dengan PID, dan pesan yang jelas bila sudah ada yang
  berjalan.
- `clite gateway status` menampilkan platform yang tersambung, jumlah sesi aktif, dan waktu
  tick cron terakhir.

**Di luar lingkup.** Layanan Windows.

**File.** `src/clite/cli/subcommands/gateway.py`, `src/clite/gateway/service.py (baru)`,
`src/clite/gateway/runner.py`, `tests/gateway/test_service.py (baru)`.

**Rujukan Hermes.** `hermes_cli/gateway.py`, `hermes_cli/gateway_launchd.py`,
`gateway/systemd_notify.py`, `gateway/drain_control.py`.

**Selesai bila.**
- [ ] Tes: isi unit systemd dan plist yang dihasilkan, untuk profil default dan profil bernama.
- [ ] Tes: SIGTERM saat giliran berjalan menunggu giliran itu selesai (dengan provider tiruan
      yang lambat) lalu keluar dengan kode 0.
- [ ] Tes: instance kedua untuk home yang sama menolak mulai.
- [ ] Dicoba dengan tangan di Linux dan dicatat di `docs/STATUS.md`.

**Ukuran.** M

**Bergantung pada.** F1-T3

---

### F4-T7 Kebijakan reset sesi dan home channel

**Tujuan.** Percakapan chat tidak tumbuh tanpa batas, dan agent tahu ke mana mengirim pesan
yang tidak berasal dari percakapan mana pun.

**Lingkup.**
- `gateway.session_reset`: `none`, `idle` (setelah sekian menit tanpa pesan), atau `daily`
  (pada jam tertentu). Saat kebijakan terpenuhi, pesan berikutnya memulai sesi baru, dan
  pengguna diberi tahu satu kali.
- Sesi lama tidak dihapus; ia tetap bisa dibuka dengan `/resume`.
- `/sethome` menandai chat itu sebagai home channel platformnya. Disimpan per home di
  `<home>/gateway/`.
- Cron menerima `deliver: <platform>` tanpa id chat, yang berarti home channel platform itu.

**File.** `src/clite/gateway/runner.py`, `src/clite/gateway/session.py`,
`src/clite/runtime/commands.py`, `src/clite/runtime/slash.py`,
`src/clite/core/config_defaults.py`, `tests/gateway/test_gateway.py`.

**Rujukan Hermes.** `gateway/session.py`, `gateway/config.py`,
`gateway/channel_directory.py`,
`website/docs/developer-guide/gateway-session-lifecycle.md`.

**Selesai bila.**
- [ ] Tes dengan waktu yang disuntikkan: kebijakan `idle` dan `daily` memulai sesi baru tepat
      pada batasnya, dan tidak sebelum itu.
- [ ] Tes: job cron dengan `deliver: telegram` sampai ke home channel, dan gagal dengan pesan
      yang jelas bila belum ada.
- [ ] Baris "Kebijakan reset sesi, home channel" di spesifikasi gateway dan cron menjadi ✅.

**Ukuran.** S

**Bergantung pada.** -

---

### F4-T8 Tool `send_message`

**Tujuan.** Agent bisa mengirim pesan ke chat lain atas permintaan pengguna, misalnya
"kabari saya di Telegram kalau build-nya selesai".

**Lingkup.**
- Tool `send_message(target, text)`. `target` adalah nama platform (home channel-nya) atau
  `platform:chat`.
- Tool hanya ditawarkan bila proses itu punya gateway dengan platform tersambung (`check_fn`).
- Tujuan dibatasi: chat asal percakapan, home channel, dan daftar eksplisit di
  `gateway.send_targets`. Model tidak bisa mengirim ke id chat sembarang.
- Tool berkebijakan paralel `never`, dan setiap pengiriman dicatat di log.

**File.** `src/clite/tools/builtin/send_message.py (baru)`, `src/clite/tools/toolsets.py`,
`src/clite/gateway/runner.py`, `src/clite/core/config_defaults.py`,
`tests/gateway/test_gateway.py`.

**Rujukan Hermes.** `tools/send_message_tool.py`, `tools/send_message_targets.py`.

**Selesai bila.**
- [ ] Tes: pengiriman ke home channel dan ke chat asal berhasil lewat adapter `local`.
- [ ] Tes: tujuan di luar daftar ditolak dengan hasil galat yang menyebut cara mengizinkannya.
- [ ] Tes: tanpa gateway, tool tidak ada di definisi tool.
- [ ] Baris `send_message` di spesifikasi tools dan gateway menjadi ✅.

**Ukuran.** S

**Bergantung pada.** F4-T7

---

### F4-T9 Cron lanjutan

**Tujuan.** Job terjadwal bisa mengumpulkan data dengan skrip sebelum agent berjalan, punya
riwayat eksekusi, dan tidak kehilangan keluaran saat pengiriman gagal.

**Lingkup.**
- **Skrip pra-jalan.** Job boleh menyebut skrip di `<home>/cron/scripts/`. Keluarannya
  ditempel ke prompt run itu. Skrip ditulis pengguna; agent tidak bisa menulis ke direktori
  itu (tambahkan ke `write_denied_reason`), dan tool `cronjob` tidak bisa memasang skrip.
- **Riwayat.** Setiap run dicatat: waktu, durasi, status, pemakaian token, lokasi keluaran.
  `clite cron history [job]` dan method RPC untuk dashboard.
- **Pengiriman.** Beberapa tujuan per job, dan antrean ulang untuk pengiriman yang gagal
  dengan batas percobaan.
- **Batas.** Batas waktu per job, dan batas jumlah job yang bisa dibuat lewat tool.
- Job berjalan bersamaan sampai batas tertentu, supaya satu job lama tidak menunda yang lain
  (celah yang tercatat di spesifikasi cron).

**File.** `src/clite/cron/jobs.py`, `src/clite/cron/scheduler.py`,
`src/clite/cron/history.py (baru)`, `src/clite/tools/file_safety.py`,
`src/clite/tools/builtin/cronjob.py`, `src/clite/cli/subcommands/cron.py`,
`src/clite/rpc/contracts/schema.py`, `tests/cron/test_cron.py`.

**Rujukan Hermes.** `cron/scheduler_script.py`, `cron/executions.py`,
`cron/delivery_queue.py`, `cron/scheduler_delivery.py`,
`website/docs/developer-guide/cron-internals.md`.

**Selesai bila.**
- [ ] Tes: keluaran skrip masuk ke prompt run; skrip yang gagal dicatat dan job tetap jalan
      atau dilewati sesuai pengaturannya.
- [ ] Tes: `write_file` ke direktori skrip ditolak, dan `cronjob` menolak argumen skrip.
- [ ] Tes: pengiriman yang gagal dicoba ulang pada tick berikutnya dan berhenti setelah batas.
- [ ] Jaminan "paling banyak sekali" tetap dijaga tes yang ada.

**Ukuran.** M

**Bergantung pada.** F4-T7

---

### F4-T10 Endpoint kompatibel OpenAI dan webhook masuk

**Tujuan.** Aplikasi lain bisa memakai agent lewat API yang sudah mereka kenal, dan layanan
luar bisa memicu agent lewat webhook.

**Lingkup.**
- `POST /v1/chat/completions` (streaming dan tidak) dan `GET /v1/models` di `clite serve`,
  dilindungi token yang sama, dikirim sebagai kunci API. Tiap permintaan adalah satu giliran;
  sesi dipilih dari header atau dari bidang `user`.
- Endpoint ini memakai toolset platform `api`, bukan toolset terminal pengguna, kecuali
  diatur lain di `platform_toolsets`.
- Webhook masuk: `POST /api/webhooks/<nama>` dengan tanda tangan HMAC per webhook. Isi
  permintaan dimasukkan ke templat prompt sebagai **data tak tepercaya** (dibungkus dan
  ditandai), lalu hasilnya dikirim ke tujuan yang dikonfigurasi.
- `clite webhook add | list | remove`. Rahasia webhook disimpan di `.env`.
- Webhook dan endpoint API mati secara default.

**File.** `src/clite/server/app.py`, `src/clite/server/openai_api.py (baru)`,
`src/clite/server/webhooks.py (baru)`, `src/clite/cli/subcommands/webhook.py (baru)`,
`src/clite/runtime/factory.py`, `src/clite/core/config_defaults.py`,
`tests/server/test_server.py`.

**Rujukan Hermes.** `gateway/platforms/api_server.py`,
`gateway/platforms/api_server_openai_routes.py`, `gateway/platforms/webhook.py`,
`hermes_cli/webhook.py`.

**Selesai bila.**
- [ ] Tes dengan klien HTTP biasa: jawaban tidak streaming dan streaming SSE berbentuk seperti
      API OpenAI.
- [ ] Tes: tanpa token, dan dengan header `Host` asing pada server loopback, permintaan
      ditolak.
- [ ] Tes: webhook dengan tanda tangan salah ditolak dalam waktu konstan; isi webhook tidak
      pernah masuk ke system prompt.
- [ ] Baris endpoint OpenAI dan webhook di spesifikasi server dan gateway menjadi ✅.

**Ukuran.** M

**Bergantung pada.** -
