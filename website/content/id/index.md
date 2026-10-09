# C-lite

C-lite adalah agent AI pribadi: satu inti percakapan yang dipakai dari terminal, dashboard web,
aplikasi desktop, dan chat. Arsitekturnya diturunkan dari
[Hermes Agent](https://github.com/NousResearch/hermes-agent) milik Nous Research, lalu
ditumbuhkan tahap demi tahap di proyek ini.

Instalasi ini masih **scaffolding**: yang ada sudah berjalan dan dijaga tes, tetapi sebagian
belum pernah dijalankan terhadap hal yang sebenarnya (API provider asli, Telegram asli, aplikasi
desktop di Windows dan macOS). Apa yang sudah dan belum diverifikasi dicatat di
[STATUS.md](https://github.com/dragovics/clite/blob/main/docs/STATUS.md).

## Yang bisa dilakukan

- **Mengobrol dan mengerjakan tugas.** Agent menjalankan perintah shell, membaca dan menulis
  berkas, mencari di web, mengingat hal tentang Anda, dan memakai prosedur yang tersimpan.
- **Banyak antarmuka, satu percakapan inti.** REPL klasik, TUI, dashboard web, aplikasi
  desktop, dan gateway chat memakai sesi dan ingatan yang sama.
- **Chat.** Telegram, Discord, Slack, email, Matrix, Signal, dan WhatsApp; pesan suara
  ditranskripsi dan jawabannya bisa diucapkan kembali.
- **Terjadwal.** Job cron menjalankan tugas tanpa Anda, dan hasilnya dikirim ke chat.
- **Bisa diperluas.** Tool, skill (`SKILL.md`), plugin Python, server MCP, dan hook shell.

## Mulai dari mana

| Kalau Anda ingin | Baca |
|---|---|
| Memasangnya | [Memasang](start/install.md) |
| Mencobanya sekarang, tanpa kunci API | [Mulai cepat](start/quickstart.md) |
| Mengubah pengaturan | [Konfigurasi](guide/configuration.md) |
| Tahu apa yang bisa dilakukan agent | [Tool](guide/tools.md) |
| Menyimpan cara kerja Anda sendiri | [Skill](guide/skills.md) |
| Menambah kemampuan dengan kode | [Plugin](guide/plugins.md) |
| Memakainya dari Telegram atau Slack | [Gateway](guide/gateway.md) |
| Tahu apa yang dijaga dan apa batasnya | [Keamanan](guide/security.md) |
| Daftar perintah, kunci konfigurasi, dan tool | [Rujukan](reference/commands.md) |

## Bahasa

Situs ini ada dalam dua bahasa. Setiap halaman punya padanannya di bahasa lain; tombol di kanan
atas berpindah ke halaman yang sama dalam bahasa itu.

## Lisensi

MIT. Atribusi untuk Hermes Agent ada di
[NOTICE.md](https://github.com/dragovics/clite/blob/main/NOTICE.md).
