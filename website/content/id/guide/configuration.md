# Konfigurasi

Semua pengaturan ada di satu berkas YAML di dalam home Anda, `~/.clite/config.yaml`. Tidak ada
bagian yang wajib ditulis tangan: `clite setup` mengisi yang pokok, dan `clite config set`
mengubah satu nilai tanpa mengusik komentar dan urutan berkasnya.

## Mengubah pengaturan

```console
$ clite config show            # hanya nilai yang Anda ubah, bukan seluruh berkas
$ clite config get model.default
$ clite config set agent.max_turns 25
agent.max_turns = 25
$ clite config unset agent.max_turns   # kembali ke nilai bawaan
$ clite config path            # lokasi berkasnya
$ clite config env             # rahasia tersimpan, nilainya disamarkan
$ clite config edit            # buka di $EDITOR
```

Beberapa kunci mengubah apa yang boleh dilakukan agent tanpa bertanya — `approvals`,
`plugins.enabled`, `hooks`, `command_allowlist`, `mcp_servers`, dan
`gateway.allow_all_users`. Menulisnya lewat `config.set` dari dashboard menuntut konfirmasi
eksplisit, karena itu sama dengan mengubah kebijakan keamanan.

Nilai yang Anda hapus dari berkas tetap punya bawaan: yang dibaca adalah berkas Anda yang
ditumpuk di atas bawaan, jadi menghapus sebuah kunci berarti "pakai bawaan", bukan
"mati". Daftar setiap kunci beserta bawaannya ada di [Rujukan konfigurasi](../reference/config.md).

Nilai boleh merujuk variabel lingkungan dengan `${NAMA}`; isinya diganti saat config dibaca.
Rahasia sebaiknya tidak ditulis di sini — lihat bagian `.env` di bawah.

Kalau berkasnya rusak, `clite` melaporkannya sebagai peringatan dan tetap bisa dijalankan,
supaya `clite config edit` dan `clite doctor` bisa dipakai untuk memperbaikinya. Berkas yang
rusak tidak pernah ditimpa sendiri.

## Rahasia

Kunci API dan rahasia lain hanya disimpan di `~/.clite/.env` (izin 0600), dan hanya dibaca
lewat jalur yang menandainya sebagai kredensial. Konsekuensinya Anda dapatkan tanpa
mengonfigurasi apa pun:

- perintah yang dijalankan agent tidak mewarisi kunci apa pun — termasuk kunci yang Anda
  `export` sendiri di shell;
- keluaran terminal diredaksi sebelum masuk percakapan;
- kunci provider hanya dikirim ke host asal kunci itu.

`.env` milik profil mengalahkan variabel lama yang masih ada di shell Anda. `clite config env`
memperlihatkan nama yang tersimpan tanpa nilainya.

## Profil

Profil adalah home terpisah penuh: config, `.env`, sesi, memori, skill, dan plugin sendiri.
Berguna untuk memisahkan pekerjaan dan pribadi, atau untuk mencoba model lain tanpa mengusik
yang sedang dipakai.

```console
$ clite profile create kerja     # home baru, salinan sekali dari yang sekarang
$ clite profile use kerja
$ clite -p kerja                 # satu kali jalan, tanpa mengubah profil aktif
$ clite profile list
```

Profil yang tidak ada adalah galat, bukan dibuat diam-diam. Profil tidak pernah mewarisi
rahasia dari profil lain: menyalin profil menyalin pengaturan, bukan kunci.

Direktori home juga bisa dipindahkan sekaligus:

```console
$ CLITE_HOME=/media/disk/clite clite
```

## Bagian-bagian penting

| Bagian | Isi |
|---|---|
| `model` | Model default, provider, `base_url` khusus, panjang konteks, batas token |
| `providers` | Provider buatan sendiri: `{base_url, api_key_env, api_mode, models}` |
| `fallback_providers` | Rute yang dicoba berurutan bila rute utama gagal |
| `toolsets`, `disabled_toolsets` | Toolset yang aktif; `platform_toolsets` mempersempit per platform |
| `agent` | Batas giliran, retry dan timeout panggilan API, `reasoning_effort`, anggaran waktu |
| `terminal` | Backend eksekusi (`local`, `docker`, `ssh`), batas waktu, kredensial yang diteruskan |
| `approvals` | Mode persetujuan perintah, batas waktu, dan pola yang selalu ditolak |
| `command_allowlist` | Pola perintah yang Anda setujui selamanya |
| `memory` | Memori jangka panjang dan profil pengguna, batas ukurannya |
| `compression`, `context` | Pemadatan percakapan panjang |
| `skills`, `plugins` | Skill dan plugin yang aktif, sumber indeksnya |
| `mcp_servers` | Server MCP: `command` untuk stdio, `url` untuk Streamable HTTP |
| `hooks` | Shell hook pada event siklus hidup; baru berjalan setelah Anda menyetujuinya |
| `gateway` | Platform chat, `allowed_users`, kebijakan reset sesi, tujuan kirim |
| `cron` | Penjadwal: job yang terlewat, batas percobaan pengiriman |
| `speech` | Transkripsi pesan suara dan jawaban bersuara |
| `sessions`, `checkpoints` | Pembersihan sesi otomatis, batas penyimpanan titik pulih |
| `display` | Streaming, progres tool, skin, antarmuka bawaan |
| `timezone`, `logging` | Zona waktu dan ukuran log |

## Contoh yang sering diubah

### Model dan provider

```console
$ clite model show
$ clite model list
$ clite model providers           # provider yang terpasang dan kunci yang dibutuhkannya
$ clite model set openrouter:anthropic/claude-sonnet-5
Model: anthropic/claude-sonnet-5 via openrouter (saved as default)
```

Bentuk `provider:model` mengganti provider sekaligus modelnya; `--provider` melakukan hal yang
sama bila modelnya ambigu. Nama model yang tersedia datang dari provider masing-masing, dan
`clite model list` menampilkan yang diketahuinya (daftarnya di-cache di dalam home).

### Rute cadangan

```yaml
model:
  provider: openrouter
  default: anthropic/claude-sonnet-5
fallback_providers:
  - provider: deepseek
    model: deepseek-chat
```

Bila rute utama gagal — batas laju, galat server, koneksi putus — permintaan yang sama dicoba
ke rute berikutnya, dan percakapan tetap berjalan.

### Provider yang tidak ada di daftar

```yaml
providers:
  kantor:
    base_url: https://llm.internal/v1
    api_key_env: KANTOR_API_KEY
    api_mode: chat_completions
model:
  provider: kantor
  default: model-dalam
```

Kuncinya tetap disimpan di `.env` sebagai `KANTOR_API_KEY`, bukan di config.

### Toolset

```console
$ clite tools list
$ clite tools disable web
$ clite tools enable web
```

Toolset menentukan tool apa yang ditawarkan kepada model. `clite tools list` memperlihatkan
berapa tool yang aktif di tiap toolset; daftar toolnya ada di [Tool](tools.md).

### Backend terminal

```yaml
terminal:
  backend: docker
  docker:
    image: python:3.12-slim
    network: none
```

Perintah dan eksekusi kode kemudian berjalan di dalam container, bukan di mesin Anda. Ini
sandbox yang sebenarnya: berkas di luar direktori kerja tidak terlihat. Rinciannya di
[Keamanan](security.md).

### Server MCP

```console
$ clite mcp add berkas --command npx --args "-y @modelcontextprotocol/server-filesystem /data"
Added MCP server 'berkas' (command npx).
$ clite mcp list
$ clite mcp test berkas
```

Tiap server menjadi toolset `mcp-<nama>` berisi toolnya, dan bisa dites sekali dengan
`clite mcp test` sebelum dipakai. `clite mcp add` menulis ke `config.yaml` tanpa menghapus
komentar Anda. Server HTTP jauh ditambahkan dengan `--url` dan header `--header NAMA=NILAI`,
yang nilainya boleh merujuk `${NAMA}` dari `.env`.

### Shell hook

```yaml
hooks:
  pre_tool_call:
    - command: /usr/local/bin/audit-tool.sh
      matcher: terminal
```

Hook baru berjalan setelah pasangan event dan perintah itu Anda setujui dengan
`clite hooks approve`. Lihat [Plugin](plugins.md) dan [Keamanan](security.md).

## Variabel lingkungan

| Variabel | Guna |
|---|---|
| `CLITE_HOME` | Lokasi home, menggantikan `~/.clite` |
| `CLITE_ENABLE_PROJECT_PLUGINS` | Izinkan plugin dari `./.clite/plugins/` di dalam proyek |
| `CLITE_ACCEPT_HOOKS` | Setujui shell hook tanpa pertanyaan (hati-hati) |
| `CLITE_SESSION_TOKEN` | Token dashboard; hanya boleh lewat lingkungan, tidak lewat argumen |
| `NO_COLOR` | Matikan warna di terminal |

## Memeriksa dan memutakhirkan

```console
$ clite doctor          # termasuk "config.yaml is valid"
$ clite config migrate  # naikkan berkas lama ke versi config sekarang
```

`clite config migrate` menjalankan transformasi yang mengubah bentuk berkas (mengganti nama
kunci, menyusun ulang bagian). Instalasi baru tidak pernah membutuhkannya.
