# Gateway

Gateway menghubungkan agent ke platform chat: Telegram, Discord, Slack, email, Matrix, Signal,
WhatsApp. Satu proses berumur panjang menerima pesan, memutuskan siapa yang boleh bicara,
mengarahkannya ke sesinya, menjalankan giliran, lalu mengirim jawabannya.

Yang penting dipahami: pesan dari chat masuk ke sesi yang **sama** dengan yang Anda pakai di
terminal — memori, berkas, skill, dan ingatan proseduralnya sama. Jadi agent yang Anda latih di
REPL langsung berguna di Telegram.

## Menyiapkan Telegram

Telegram adalah platform yang paling sederhana untuk dicoba: hanya butuh token bot, tanpa webhook.

1. Buat bot lewat [@BotFather](https://t.me/BotFather) dan salin tokennya.
2. Simpan token di `~/.clite/.env` sebagai `TELEGRAM_BOT_TOKEN=...`.
3. Aktifkan platformnya di `config.yaml`:

```yaml
gateway:
  platforms:
    telegram:
      allowed_users: [123456789]   # id Telegram Anda
```

4. Jalankan gateway:

```console
$ clite gateway run
```

Kirim pesan ke bot Anda, dan agent menjawab di sana. Untuk melihat id pengguna Anda, kirim pesan
dulu tanpa `allowed_users`; orang asing yang menulis secara langsung akan ditawari kode pairing,
dan kodenya muncul di log gateway.

Platform lain ditambahkan dengan pola yang sama. Discord dan Slack punya adapter bawaan; `email`,
`matrix`, `signal`, dan `whatsapp` adalah plugin platform yang sudah ada di paket.

## Siapa yang boleh bicara

Tidak ada yang diizinkan secara bawaan. Tiga cara memberi akses:

| Cara | Untuk |
|---|---|
| `allowed_users` per platform | Daftar tetap yang Anda tulis di config |
| Pairing | Orang tak dikenal ditawari kode delapan karakter; Anda menyetujuinya di mesin gateway |
| `gateway.allow_all_users: true` | Siapa pun yang menemukan bot. **Jangan dipakai di platform publik** |

```console
$ clite gateway pair approve telegram ABC-DEF-GH
```

Setiap pengguna yang Anda izinkan bisa menyuruh agent menjalankan perintah di mesin gateway, dan
dialah yang menjawab permintaan persetujuan. Mengizinkan seseorang sama dengan memberinya akses
setara shell di mesin itu.

Kunci sesi memisahkan konteks percakapan, bukan data: orang yang diizinkan dalam satu profil
berbagi database sesi, memori, dan berkas. C-lite saat ini ditujukan untuk satu pemilik atau
sekelompok orang yang saling percaya.

## Menjalankannya terus-menerus

```console
$ clite gateway install      # pasang sebagai layanan (systemd user / LaunchAgent)
$ clite gateway start
$ clite gateway status
$ clite gateway logs
```

`install` membuat unit layanan per profil, jadi beberapa profil bisa berjalan berdampingan. Sebuah
kunci menolak instance kedua di home yang sama. Saat dihentikan (SIGTERM), gateway berhenti
menerima pesan baru lalu menunggu giliran yang sedang berjalan selesai.

Cara manual tetap ada: `clite gateway run`, atau `clite dashboard` yang menjalankan backend dan
membuka dashboard web.

## Cara agent menjawab

- **Satu giliran per thread.** Satu tugas panjang tidak menghalangi chat lain.
- **Jawaban panjang dipotong** pada batas paragraf, lalu baris, lalu kata, lalu dikirim
  bertahap. Adapter yang bisa menyunting pesan (Telegram, Discord, Slack) memperbarui satu pesan
  sambil teksnya mengalir.
- **Saat Anda menulis lagi ketika agent masih bekerja**: `display.busy_input_mode` menentukan
  apa yang terjadi. `interrupt` (bawaan) menghentikan giliran berjalan dan memulai yang baru —
  rentetan pesan cepat digabung menjadi satu. `queue` menjalankannya berurutan. `steer`
  menyisipkan pesan Anda ke giliran yang sedang berjalan tanpa menghentikannya.
- **Persetujuan lewat chat.** Kalau agent butuh menjalankan perintah berbahaya, ia mengirim
  perintahnya dan menunggu `/approve`, `/approve session`, `/approve always`, atau `/deny`. Diam
  sampai `approvals.timeout` berarti tolak.
- **Lampiran.** Gambar masuk ke permintaan model; dokumen disebutkan sebagai berkas yang bisa
  dibaca. Jawaban bisa mengirim berkas kembali lewat `send_file`.
- **Pesan suara** ditranskripsi lebih dulu, dan untuk platform yang Anda daftarkan di
  `speech.reply_with_voice` jawabannya diucapkan kembali. Keduanya butuh penyedia suara; tanpa itu
  agent tetap menjawab, hanya dalam teks.

## Cron

Job cron adalah **prompt**, bukan perintah shell: ia dijalankan di sesi baru tanpa ingatan
percakapan yang membuatnya, lalu hasilnya dikirimkan ke tempat yang Anda tentukan. Inilah cara
membiarkan agent bekerja saat Anda tidak ada.

```console
$ clite cron add --name "ringkasan pagi" --schedule "0 9 * * 1-5" \
    --prompt "Ringkas surel dan berita penting semalam, lalu kirim daftar tindakan hari ini." \
    --deliver telegram
$ clite cron list
$ clite cron history "ringkasan pagi"
```

Tiga bentuk jadwal:

| Jenis | Contoh | Arti |
|---|---|---|
| Sekali | `30m`, `2h`, `1d`, `2026-01-31T09:00` | Sekian lama dari sekarang, atau pada cap waktu tertentu |
| Berulang | `every 30m`, `every 1d` | Minimal 60 detik |
| Cron | `0 9 * * 1-5` | Lima bidang, seperti cron klasik |

Zona waktunya dari `timezone` di config; bawaannya zona sistem.

Ke mana hasilnya dikirim:

| `deliver` | Artinya |
|---|---|
| `local` | Hanya disimpan di `~/.clite/cron/output/` |
| `origin` | Dikirim balik ke chat tempat job itu dibuat |
| `telegram:123456789` | Dikirim ke chat tertentu di sebuah platform |

Jawaban yang diawali `[SILENT]` atau kosong tidak dikirim, jadi job pemantau bisa diam ketika
tidak ada yang perlu dilaporkan.

Job berjalan tanpa pengawasan: ia tidak bisa bertanya kepada Anda, tidak bisa menjadwalkan job
lain, dan perintah berbahaya ditolak secara default (`approvals.cron_mode`). Prompt-nya dipindai
saat dibuat dan saat diubah, karena ia nanti berjalan dengan tool agent tanpa Anda menemaninya.

Siapa yang menjalankan penjadwalnya: gateway (ticker latar, selama gateway hidup),
`clite cron daemon`, atau timer luar yang memanggil `clite cron tick`. Sebuah job dijalankan
paling banyak sekali — proses yang mati di tengah jalan bisa kehilangan satu run, tapi tidak
pernah menggandakannya.

## Yang belum ada

- Tidak ada antrean kirim yang tahan lama: pesan yang gagal terkirim hanya dicatat di log.
- Tidak ada pembatasan laju per pengguna.
- Adapter selain `local` diuji terhadap server tiruan; Telegram, Discord, Slack, email, Matrix,
  Signal, dan WhatsApp belum dicoba terhadap layanan sungguhan. Rinciannya di
  [STATUS.md](https://github.com/dragovics/clite/blob/main/docs/STATUS.md).
