# 12. Gateway Pesan dan Cron

## Gateway pesan

Gateway adalah proses berumur panjang yang menghubungkan agent ke platform pesan.
Satu proses menangani banyak platform dan banyak percakapan, memakai kelas `AIAgent`
yang sama dengan CLI.

```text
hermes gateway setup     wizard: pilih platform, isi token
hermes gateway run       jalankan di latar depan
hermes gateway start     jalankan sebagai layanan (systemd, launchd, Scheduled Task)
hermes gateway stop | restart | status | install | uninstall
```

### Bentuk kode

`gateway/run.py` adalah fasad `GatewayRunner`. Fase-fasenya di `run_*.py`: `startup`,
`adapters`, `inbound`, `turn`, `busy`, `notifications`, `shutdown`. Sesi di `session*.py`.
Handler slash di mixin `slash_commands_*.py`. Otorisasi di `authz_mixin.py`. Adapter di
`gateway/platforms/<nama>.py` dan `plugins/platforms/<nama>/adapter.py`, di atas
`gateway/platforms/base.py`.

Adapter bawaan di `gateway/platforms/`: `signal`, `weixin`, `bluebubbles`, `qqbot`,
`whatsapp_cloud`, `yuanbao`, `webhook`, `api_server`. Adapter berupa plugin di
`plugins/platforms/`: `telegram`, `discord`, `slack`, `whatsapp`, `matrix`,
`mattermost`, `email`, `sms`, `dingtalk`, `feishu`, `wecom`, `irc`, `line`, `teams`,
`google_chat`, dan lainnya.

### Alur satu pesan

```text
Event platform
  → Adapter menormalkan menjadi MessageEvent
  → Penjaga 1 (adapter dasar): bila sesi sedang aktif, antrekan
  → GatewayRunner._handle_message()
      → hook pre_gateway_dispatch (plugin boleh membuang atau menulis ulang)
      → otorisasi pengirim
      → slash command? → dispatch lewat registry
      → tentukan kunci sesi → ambil sesi
      → kebersihan sesi (kompresi 85%)
      → ambil AIAgent dari cache, atau buat
      → AIAgent.run_conversation() di thread pekerja
      → kirim progres tool dan jawaban akhir lewat adapter
```

### `MessageEvent` dan `SessionSource`

Semua adapter menghasilkan bentuk yang sama (`gateway/platforms/event.py`,
`gateway/session.py`):

```python
@dataclass
class SessionSource:
    platform: Platform
    chat_id: str
    chat_name: str | None = None
    chat_type: str = "dm"            # "dm", "group", "channel", "thread"
    user_id: str | None = None
    user_name: str | None = None
    thread_id: str | None = None
    scope_id: str | None = None      # guild Discord, workspace Slack
    profile: str | None = None       # profil tujuan pada gateway multipleks

@dataclass
class MessageEvent:
    text: str
    message_type: MessageType = MessageType.TEXT   # TEXT, PHOTO, VOICE, DOCUMENT, COMMAND, ...
    source: SessionSource = None
    message_id: str | None = None
    media_urls: list[str] = ...      # path lokal lampiran
    media_types: list[str] = ...
    reply_to_message_id: str | None = None
    reply_to_text: str | None = None
    channel_prompt: str | None = None   # prompt sementara per kanal, tidak disimpan
    internal: bool = False              # event sintetis yang melewati otorisasi
    metadata: dict = ...
```

### Kunci sesi

`gateway/session.py::build_session_key()` adalah satu-satunya sumber kebenaran:

```text
<namespace>:<platform>:<chat_type>[:<scope>][:<chat_id>][:<thread_id>][:<user>]
```

- DM diisolasi per `chat_id`.
- Grup menambahkan id peserta bila `group_sessions_per_user` menyala.
- Thread dibagi bersama secara bawaan.
- Namespace adalah `agent:main` untuk profil default dan `agent:<profil>` untuk profil lain.

Kunci sesi memetakan ke id sesi di `state.db`. `/new` membuat id sesi baru di bawah kunci
yang sama.

### Antarmuka adapter

`BasePlatformAdapter` (ABC) di `gateway/platforms/base.py`. Yang wajib diimplementasikan:

```python
async def connect(self, *, is_reconnect: bool = False) -> bool
async def disconnect(self) -> None
async def send(self, chat_id: str, content: str, reply_to: str | None = None, ...) -> SendResult
```

Yang opsional: `edit_message`, `delete_message`, `send_typing`, `send_image`,
`send_voice`, `send_exec_approval` (tombol persetujuan), `send_clarify`, streaming draf.
Adapter menyetel handler pesan lewat `set_message_handler(handler)` dan memanggilnya
dengan `MessageEvent`.

Menambah platform mengikuti `gateway/platforms/ADDING_A_PLATFORM.md` langkah demi langkah.

### Dua penjaga pesan

Selagi agent berjalan, pesan masuk melewati dua penjaga berurutan:

1. **Adapter dasar** mengantrekan pesan ke `_pending_messages` bila `session_key` ada di `_active_sessions`.
2. **Runner** mencegat `/stop`, `/new`, `/queue`, `/status`, `/approve`, `/deny` sebelum pesan mencapai `running_agent.interrupt()`.

Perintah baru yang harus sampai ke runner selagi agent terblokir (misalnya menunggu
persetujuan) **wajib melewati kedua penjaga** dan dijalankan langsung. Field
`busy_policy` pada `CommandDef` mengatur ini.

Pesan biasa yang masuk selagi agent sibuk diperlakukan menurut `display.busy_input_mode`:
`interrupt` (bawaan), `queue`, atau `steer`.

### Otorisasi

- **Daftar izin** per platform lewat variabel rahasia seperti `TELEGRAM_ALLOWED_USERS`, atau `GATEWAY_ALLOW_ALL_USERS`.
- **Pemasangan DM** (`gateway/pairing.py`): pengguna tak dikenal menerima kode sekali pakai yang disetujui pemilik lewat `hermes pairing approve`. Kode 8 karakter dari alfabet 32 karakter tanpa huruf membingungkan, kedaluwarsa 1 jam, maksimum 3 tertunda per platform, 1 permintaan per pengguna per 10 menit, dan terkunci setelah 5 kegagalan.
- **Akses slash** (`gateway/slash_access.py`): perintah admin bisa dibatasi.
- **Kunci token**: adapter yang menyambung dengan kredensial unik mengambil kunci berlingkup (`acquire_scoped_lock`) agar dua profil tidak berbagi satu token bot.

### Cache agent

Gateway menyimpan `AIAgent` per sesi di antara giliran supaya system prompt dan cache
penyedia tetap hangat. Tanda tangan konfigurasi agent memaksa pembangunan ulang bila
rute model berubah. Pengusiran (TTL, LRU, tekanan memori) memicu `on_session_end` dan
penulisan memori **di bawah lingkup profil pemilik**.

Karena agent di-cache, semua keadaan per giliran harus direset di awal giliran. Lihat
daftar reset di `agent/conversation_loop.py::_run_conversation_turn`.

### Streaming dan progres

- Progres tool dikirim sebagai pesan singkat, dengan kebertelean dari `display.tool_progress`.
- Streaming jawaban memakai penyuntingan pesan berkala (`streaming.edit_interval`).
- Untuk adapter yang aliran drafnya *adalah* pesan akhir, berlaku empat invarian: frame draf stabil sebagai prefiks; konsumen yang menyatakan final; kiriman antara ditandai `_interim_send`; dan rekonsiliasi lewat penyuntingan, bukan kiriman baru. Masing-masing lahir dari insiden pesan akhir ganda.

### Proses latar dan pemberitahuan

`terminal(background=true, notify_on_complete=true)` memasang pengawas di loop gateway.
Saat proses selesai, pengawas memicu giliran agent baru. Kebertelean diatur
`display.background_process_notifications`: `concise`, `all`, `result`, `error`, `off`.

### Gateway multipleks

Satu proses gateway bisa melayani semua profil (`gateway.multiplex_profiles`, bawaan
menyala bila ada lebih dari satu profil). Ini sumber banyak kerumitan:

- `os.environ` memegang nilai profil **default**. Rahasia profil lain hanya ada di lingkup rahasia yang diikat per aktivitas.
- Pembacaan env berlingkup profil **harus gagal tertutup**: bila lingkup terpasang dan nilainya tidak ada, kembalikan bawaan, jangan pernah meminjam dari `os.environ`.
- Lingkup diikat per **aktivitas** profil (giliran, callback, pengusiran, detak), bukan hanya per giliran.

Untuk proyek baru, ini adalah fitur tahap akhir. Yang perlu dijaga sejak awal hanyalah
disiplin "jangan baca home atau rahasia dari konstanta modul".

### Adapter `api_server`

`gateway/platforms/api_server.py` mengekspos agent sebagai **API kompatibel OpenAI**
lewat HTTP. Ini membuat agent bisa dipakai dari klien OpenAI mana pun, dan berguna untuk
menguji gateway tanpa platform pesan sungguhan.

## Cron

Tugas terjadwal Hermes adalah **tugas agent**, bukan tugas shell: tiap eksekusi
menjalankan agent baru dengan sebuah prompt.

`cron/jobs.py` adalah penyimpan job; `cron/scheduler.py` adalah loop detak, dengan
saudara `scheduler_*.py`. Agent menjadwalkan lewat tool `cronjob_manage`; pengguna lewat
`hermes cron list|add|edit|pause|resume|run|remove` atau `/cron`.

### Format jadwal

`parse_schedule()` menghasilkan `{"kind": "once" | "interval" | "cron", ...}`:

| Bentuk | Contoh | Jenis |
|---|---|---|
| Durasi | `"30m"`, `"2h"`, `"1d"` | interval |
| Frasa "every" | `"every 2h"` | interval |
| Frasa hari dan jam | `"every monday 9am"`, `"weekdays at 9am"` | cron |
| Cron 5 kolom | `"0 9 * * *"` | cron (butuh `croniter`) |
| Stempel waktu ISO | `"2026-06-01T09:00:00Z"` | sekali |

Stempel waktu tanpa zona ditafsirkan dalam zona waktu Hermes yang dikonfigurasi, bukan
zona server.

### Field job

`prompt`, `schedule`, `name`, `repeat` (kosong berarti selamanya), `deliver` (tujuan
kirim; bawaan `"origin"` bila ada asal, kalau tidak `"local"`), `skills` (dimuat sebagai
konteks), `model` dan `provider` (penimpaan per job), `script` (skrip pra-jalan yang
stdout-nya disisipkan ke prompt; dengan `no_agent=True` skrip itulah job-nya),
`context_from` (rantai keluaran job lain), `workdir`, `enabled_toolsets`,
`monitor_script` atau `monitor_url` (sumber murah yang dijalankan dulu; keluaran yang
tidak berubah membatalkan jalan agent).

### Alur eksekusi

```text
Detak penjadwal → muat job yang jatuh tempo
  → majukan next_run_at SEBELUM dispatch dan simpan
  → buat AIAgent baru tanpa riwayat, skip_memory=True, platform "cron"
  → sisipkan skill terlampir dan keluaran skrip
  → jalankan prompt
  → kirim jawaban ke tujuan
  → catat eksekusi
```

### Invarian pengerasan

Tiap butir menjaga dari kegagalan nyata:

- **Paling banyak sekali.** `tick()` memajukan `next_run_at` sebelum dispatch dan menandai `pending_slot` dalam simpanan yang sama. Macet di tengah jalan tidak menyebabkan eksekusi ganda.
- **Tidak ada slot yang hilang diam-diam.** Slot yang terlewat dipulihkan sekali; buku besar eksekusi mencegah tembakan kedua.
- **Jendela kejar** separuh periode, dibatasi 120 detik sampai 2 jam. `cron.catch_up_missed: false` melewatkan yang terlewat dengan alasan tercatat.
- **Pengawas ketidakaktifan** 600 detik menganggur. Ini waktu menganggur, bukan waktu dinding: sesi macet diinterupsi, job panjang yang aktif tidak pernah dipotong.
- **Kunci detak per home** (`<home>/cron/.tick.lock`) mencegah detak ganda antar-proses.
- Sesi cron melewati memori dan memakai mode persetujuan `cron_mode` (bawaan `deny`).
- Jawaban cron punya sesinya sendiri agar tidak merusak selang-seling peran di percakapan pengguna.

Penjadwal berjalan **di dalam gateway**. Tanpa gateway, backend desktop yang
menjalankannya.

## Kanban

Papan kerja multi-agent berbasis SQLite yang tahan lama: beberapa profil atau pekerja
berkolaborasi pada tugas. Dispatcher mengambil tugas yang siap dan meluncurkan profil
yang ditugaskan sebagai pekerja. Pekerja mendapat toolset `kanban_*` khusus, sehingga
jejak skemanya nol di luar tugas kanban.

Ini fitur lanjutan, dicatat di sini sebagai contoh penerapan tangga jejak: kemampuan
besar ditambahkan sebagai perintah CLI, toolset bergerbang, dan plugin, tanpa menyentuh
loop inti.

## Yang perlu ditiru persis

1. `MessageEvent` dan `SessionSource` sebagai bentuk ternormalisasi semua adapter.
2. Satu fungsi pembangun kunci sesi.
3. ABC adapter dengan `connect`, `disconnect`, `send`.
4. Slash command gateway diturunkan dari registry yang sama dengan CLI, dengan `busy_policy`.
5. Otorisasi lewat daftar izin dan pemasangan DM.
6. Cron sebagai tugas agent dengan semantik paling-banyak-sekali.
7. Jawaban cron di sesinya sendiri.

## Rujukan di Hermes

`gateway/run.py`, `gateway/run_*.py`, `gateway/session.py`, `gateway/platforms/base.py`,
`gateway/platforms/event.py`, `gateway/platforms/ADDING_A_PLATFORM.md`,
`gateway/pairing.py`, `gateway/delivery.py`, `gateway/platform_registry.py`,
`plugins/platforms/`, `cron/jobs.py`, `cron/scheduler.py`, `tools/cronjob_tools.py`,
`gateway/AGENTS.md`, `cron/AGENTS.md`,
`website/docs/developer-guide/gateway-internals.md`,
`website/docs/developer-guide/cron-internals.md`.
