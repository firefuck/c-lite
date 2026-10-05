# Tambah platform pesan

**Kapan dipakai.** Untuk menghubungkan gateway ke satu aplikasi chat lagi.

**Di Claude Code:** `/tambah-platform <nama>`

**Isian.** `<PLATFORM>`: nama platform, alamat dokumentasi API-nya, dan apakah Anda punya akun
uji.

## Prompt

Tambahkan adapter platform `<PLATFORM>` ke gateway di repositori ini.

**Hasil yang diminta.** Pengguna yang diizinkan bisa bercakap-cakap dengan agent di platform
itu: pesan masuk menjadi giliran, jawaban terkirim, persetujuan dan klarifikasi berjalan lewat
chat, dan gateway yang dimulai ulang melanjutkan percakapan.

**Yang dibaca dulu.** `src/clite/gateway/AGENTS.md` (resep "Menambah platform"),
`docs/spesifikasi/gateway.md`, `src/clite/gateway/platforms/telegram.py` sebagai contoh
lengkap, bagian Gateway di `docs/arsitektur/06-keamanan.md`, dan dokumentasi API platform
itu. Bila Hermes punya adapternya di clone rujukan (`plugins/platforms/`), baca untuk melihat
kasus tepi platform tersebut.

**Batasan.**
- Adapter melakukan tiga hal: tersambung dan menerima, mengirim, memutus. Ia menerjemahkan
  pesan platform menjadi `MessageEvent` dan tidak memutuskan siapa yang diizinkan atau apa
  arti sebuah perintah.
- Runner sinkron. Bila pustaka atau protokol platform asinkron, jalankan event loop-nya di
  thread adapter, dimulai dengan `core.threads.start_thread`.
- Token dan rahasia dibaca lewat `get_secret`, didaftarkan dengan `register_secret`, dan tidak
  pernah muncul di log, termasuk saat permintaan gagal.
- Aturan grup: di tempat ramai, agent hanya menjawab bila disapa. Orang asing di grup
  diabaikan.
- Adapter yang butuh dependensi tambahan dikirim sebagai plugin berjenis `platform`, bukan di
  dalam paket inti.

**Bukti.**
- Tes terhadap server tiruan lokal yang meniru API platform: pesan masuk, jawaban, pesan
  panjang yang dipecah, sambungan yang putus lalu pulih, dan kegagalan mulai yang tidak
  menghentikan platform lain.
- Daftar periksa manual untuk dicoba pemilik proyek terhadap platform yang asli, ditulis di
  laporan akhir.
- Baris platform di `docs/spesifikasi/gateway.md` dengan status 🟡 sampai daftar periksa itu
  benar-benar dijalankan.
- `python scripts/gen_docs.py` dijalankan, dan `scripts/run_tests.sh` lulus.
