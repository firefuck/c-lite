# Tool

Tool adalah satu kemampuan konkret yang bisa dipanggil model: menjalankan perintah, membaca
berkas, mencari di web, mengirim pesan. Anda tidak memilihnya satu per satu untuk tiap tugas —
agent memutuskan sendiri tool mana yang perlu, dan menyebutkan apa yang sedang dikerjakannya di
terminal.

Tool dikelompokkan menjadi **toolset**. Yang aktif pada sebuah sesi menentukan apa yang bisa
dipanggil model; yang tidak aktif tidak pernah ditawarkan, jadi model tidak bisa "salah ingat"
bahwa ia punya kemampuan itu.

## Apa yang tersedia

```console
$ clite tools list
on   clarify          1/1  Ask the user a question
part clite-cli        19/23  Everything, for the interactive terminal
part clite-cron       17/18  Scheduled runs
part clite-gateway    19/23  Messaging platforms
on   clite-subagent   14/14  Delegated workers
on   cronjob          1/1  Schedule recurring or one-off agent tasks
on   delegation       1/1  Spawn subagents with isolated context
on   file             4/4  Read, write, patch and search files
on   memory           1/1  Persistent notes across sessions
off  messaging        0/3  Send messages and files to connected chat platforms, and speak
on   session_search   1/1  Search past conversations
on   skills           3/3  List, read and maintain skills
on   terminal         3/3  Run shell commands, Python snippets and background processes
on   todo             1/1  Task list for multi-step work
part vision           1/2  Look at images through a helper model
on   web              2/2  Search and fetch web pages as text
```

Angka `aktif/jumlah` memperlihatkan berapa tool di toolset itu yang benar-benar bisa dipanggil
saat ini; `part` berarti sebagian toolnya menunggu syarat yang belum terpenuhi (kunci API,
penyedia, atau platform yang tersambung). Daftar lengkap setiap tool beserta deskripsinya ada di
[Rujukan tool](../reference/tools.md).

| Toolset | Isinya |
|---|---|
| `terminal` | `terminal` (perintah shell), `execute_code` (program Python pendek), `process` (proses latar) |
| `file` | `read_file`, `write_file`, `patch`, `search_files` |
| `web` | `web_fetch`, `web_search` |
| `vision` | `vision_analyze`, `image_generate` |
| `memory`, `todo`, `skills`, `session_search`, `clarify` | Satu tool masing-masing |
| `delegation` | `delegate_task` — menjalankan subagent untuk tugas yang berdiri sendiri |
| `cronjob` | Menjadwalkan tugas |
| `messaging` | `send_message`, `send_file`, `text_to_speech` |

Empat toolset `clite-*` adalah kelompok siap pakai untuk tiap permukaan — `clite-cli` untuk
terminal, `clite-gateway` untuk chat, `clite-cron` untuk tugas terjadwal, `clite-subagent` untuk
pekerja yang didelegasikan. Isinya toolset di atas, disusun menurut apa yang masuk akal di
permukaan itu: `clite-cron` tidak punya `clarify` (tidak ada yang bisa ditanya) dan
`clite-subagent` tidak bisa mendelegasikan lagi.

## Mengubah toolset yang aktif

```console
$ clite tools disable web
$ clite tools enable web
```

Untuk mengubah bawaan bagi semua sesi, sunting `toolsets` dan `disabled_toolsets` di config.
`disabled_toolsets` selalu menang, termasuk atas tool yang ikut lewat toolset gabungan.

Antarmuka tertentu punya toolset sendiri. Chat memakai `clite-gateway`, cron memakai
`clite-cron`; `platform_toolsets` mempersempitnya lagi per platform. Jadi Anda bisa, misalnya,
memberi Telegram akses baca-saja sementara REPL di mesin Anda tetap punya `terminal`.

## Persetujuan perintah

Setiap perintah shell yang dijalankan agent melewati gerbang persetujuan sebelum berjalan.
Mode-nya satu pengaturan, `approvals.mode`:

| Mode | Artinya |
|---|---|
| `manual` | Bawaan. Perintah yang cocok pola berbahaya ditanyakan kepada Anda |
| `smart` | Model bantu menilai lebih dulu; yang jelas aman jalan, yang jelas berbahaya ditolak, sisanya ditanyakan |
| `off` | Tidak ada pertanyaan, kecuali dua lapis yang tidak bisa dimatikan |

Jawaban Anda bisa berlaku untuk perintah itu saja (`once`), untuk seluruh pola selama sesi
(`session`), atau selamanya lewat `command_allowlist` (`always`). Ingat bahwa `session` dan
`always` berlaku untuk **pola**-nya, bukan perintah persis itu: menjawab "always" untuk
`rm -rf build/` juga meloloskan hapus rekursif lain yang mirip. Untuk sesuatu yang tidak ingin
Anda umumkan, jawab `once`.

Dua lapis tidak pernah bisa dinyalakan: perintah yang terlarang mutlak (hapus rekursif atas
root, direktori home, atau direktori sistem; `mkfs`; `dd` ke disk; fork bomb; mematikan mesin)
selalu ditolak, dan glob yang Anda tulis sendiri di `approvals.deny` selalu ditolak, termasuk
saat mode `off`.

Di dalam REPL, `/yolo` mematikan pertanyaan untuk sesi itu; `/config` memperlihatkan mode yang
berlaku.

## Di mana perintah berjalan

```yaml
terminal:
  backend: local        # bawaan: langsung di mesin Anda
```

`local` berarti perintah berjalan sebagai Anda, dengan hak penuh Anda. Pagar di atas mencegah
kekeliruan dan jalur eskalasi yang paling langsung, bukan model yang sudah dibujuk untuk bekerja
melawan Anda dalam beberapa langkah. Kalau Anda ingin batas yang sebenarnya, pilih `docker` atau
`ssh` — perintah dan tool file lalu berjalan di dalam container atau di mesin lain. Lihat
[Keamanan](security.md) untuk sandbox dan batasnya.

## Tool yang menunggu penyedianya

Beberapa tool hanya muncul kalau ada yang bisa menjawabnya. Ini disengaja: model tidak pernah
diberi tahu ia bisa melakukan sesuatu yang ujungnya akan gagal.

| Tool | Muncul bila |
|---|---|
| `web_search` | Ada penyedia pencarian: `web-search-ddg` (tanpa kunci) atau `web-search-tavily` (`TAVILY_API_KEY`) |
| `image_generate` | Ada penyedia gambar, misalnya `image-gen-openai` (`OPENAI_API_KEY`) |
| `text_to_speech` | Ada penyedia suara, misalnya `speech-openai` (`OPENAI_API_KEY`) |
| `vision_analyze` | Rute `auxiliary.vision` menunjuk model yang menerima gambar |
| `send_message`, `send_file` | Gateway sedang berjalan |

`vision_analyze` mengirim gambar ke model bantu dan hanya mengembalikan teks jawabannya ke model
utama, jadi model percakapan Anda tidak perlu bisa melihat. Kalau rutenya buta, tool menolak
dengan pesan yang menyebut cara mengarahkannya, bukan mengirim gambar ke model yang akan
menolaknya.

## Server MCP

Server [MCP](https://modelcontextprotocol.io) menambah tool dari luar proses C-lite. Tiap server
menjadi toolset `mcp-<nama>` berisi toolnya, dan ikut aturan yang sama: bisa dimatikan, dan
perintah yang dijalankannya tetap lewat gerbang persetujuan. Contoh penambahannya ada di
[Konfigurasi](configuration.md#server-mcp).

## Yang belum ada

Ditulis apa adanya supaya Anda tidak mencarinya:

- **Otomasi browser** belum ada. `web_fetch` mengambil halaman sebagai teks, bukan menjalankan
  halaman itu.
- **Sandbox bawaan** belum ada; `local` berjalan tanpa kurungan. Docker dan SSH sudah bekerja
  tetapi belum pernah diuji terhadap daemon dan host sungguhan.
- **MCP sampling dan OAuth** di luar lingkup saat ini.
