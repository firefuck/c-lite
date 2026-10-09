# Mulai cepat

Sepuluh menit, dimulai dari yang tidak butuh kunci API. Semua perintah di halaman ini bisa
disalin apa adanya; yang berada di blok `bash` dijalankan oleh suite tes proyek ini, jadi
keluarannya tidak akan pernah beda dari yang tertulis di sini.

## 1. Pastikan instalasinya hidup

Provider `mock` menjawab tanpa kunci API dan tanpa jaringan. Pakai untuk memastikan perintahnya
ada dan home-nya bisa ditulis:

```bash
clite --version
clite chat -q "sebutkan tiga hal yang bisa kamu lakukan" --provider mock
clite model list
clite tools list
clite skills list
clite doctor
```

Yang Anda lihat, berurutan: nomor versi; jawaban `mock` atas pertanyaan itu; daftar model yang
diketahui tiap provider; daftar toolset beserta jumlah tool yang aktif; daftar skill bawaan;
dan hasil pemeriksaan instalasi.

`clite doctor` akan melaporkan tepat satu masalah — provider belum dikonfigurasi — sampai
langkah berikutnya selesai. Sisanya sudah hijau sejak pemasangan. Kalau ada baris lain yang
merah, perbaikannya ada di [Memasang](install.md#kalau-ada-yang-salah).

## 2. Pilih provider dan model

```console
$ clite setup
Setting up /home/anda/.clite
...
$ clite config get model.provider
openrouter
```

`clite setup` menanyakan provider, kunci API, model (daftarnya diambil dari provider itu),
toolset, mode persetujuan, dan token Telegram. Kunci diuji dengan satu panggilan sungguhan;
kalau salah, langkah itu diulang alih-alih disimpan. Yang disimpan: kunci ke `.env` (izin
0600), sisanya ke `config.yaml`.

Pertanyaan itu bisa dilewati seluruhnya dengan flag, yang berguna untuk skrip:

```console
$ clite setup --provider openrouter --api-key "$OPENROUTER_KEY" --model anthropic/claude-sonnet-5
Saved: provider openrouter, model anthropic/claude-sonnet-5
```

Tanpa terminal (stdin bukan TTY), `clite setup` menolak berjalan dan menyebut bentuk flag itu.
Provider yang tersedia, variabel kunci tiap-tiapnya, dan model bawaannya ada di
[Konfigurasi](../guide/configuration.md).

Kalau Anda ingin memakai model lokal, Ollama dan LM Studio ada di daftar provider dan tidak
butuh kunci. Untuk endpoint yang tidak ada di daftar, daftarkan provider sendiri di bagian
`providers` pada config.

## 3. Ngobrol

```console
$ clite
> rangkum berkas catatan.md, lalu simpan ringkasannya sebagai ringkasan.md
…
> /help
```

`clite` tanpa argumen membuka REPL klasik. Tulis perintah seperti Anda menjelaskannya kepada
orang lain; agent memilih sendiri tool yang dipakai, dan setiap perintah shell yang berbahaya
akan meminta persetujuan Anda lebih dulu.

Beberapa perintah slash yang sering dipakai:

| Perintah | Guna |
|---|---|
| `/help` | Daftar lengkap perintah slash |
| `/new`, `/sessions`, `/resume` | Mulai sesi baru, pilih sesi lama, lanjutkan |
| `/model`, `/provider` | Ganti model atau provider untuk sesi ini |
| `/tools` | Lihat, aktifkan, matikan toolset |
| `/skills`, `/memory` | Skills dan memori jangka panjang |
| `/status`, `/compress` | Keadaan sesi, dan padatkan percakapan yang panjang |
| `/rollback`, `/checkpoints` | Batalkan suntingan berkas yang dilakukan agent |
| `/image` | Lampirkan gambar pada pesan berikutnya |
| `/stop` | Hentikan giliran yang sedang berjalan |
| `/quit` | Keluar |

## 4. Satu pertanyaan tanpa REPL

Untuk skrip dan pipa, `-q` menjalankan satu giliran lalu keluar. Hanya jawabannya yang ke
stdout; progres tool ke stderr, dan `--json` mencetak hasil gilirannya lengkap.

```bash
clite config get model.provider
clite chat -q "ringkas berkas catatan.md"
clite sessions list
```

Dalam skrip, jangan lupa bahwa tidak ada yang bisa menjawab pertanyaan persetujuan:
perintah berbahaya ditolak (`approvals.single_query_mode`). Lihat
[Keamanan](../guide/security.md).

## 5. Lanjut dari sini

| Kalau Anda ingin | Baca |
|---|---|
| Mengubah model, toolset, atau perilaku lain | [Konfigurasi](../guide/configuration.md) |
| Tahu tool apa saja yang ada | [Tool](../guide/tools.md) |
| Mengajari agent cara kerja Anda | [Skill](../guide/skills.md) |
| Menambah kemampuan dengan kode | [Plugin](../guide/plugins.md) |
| Memakai agent dari Telegram, Discord, Slack | [Gateway](../guide/gateway.md) |
| Membiarkan agent bekerja saat Anda tidak ada | [Gateway](../guide/gateway.md#cron) |
| Melihat dashboard di browser | `clite dashboard` |
| Memeriksa apa yang sudah dan belum diverifikasi | [STATUS.md](https://github.com/dragovics/clite/blob/main/docs/STATUS.md) |
