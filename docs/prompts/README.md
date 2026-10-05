# Prompt siap pakai

Kumpulan prompt untuk mengerjakan proyek ini sepenuhnya dengan AI. Prompt-prompt ini ditulis
untuk Claude Fable 5.1 di Claude Code, tetapi isinya tidak bergantung pada alat itu: bagian
"Prompt" di tiap file bisa ditempel ke harness mana pun.

## Daftar

| Prompt | Perintah di Claude Code | Kapan dipakai |
|---|---|---|
| [01-orientasi.md](01-orientasi.md) | `/orientasi` | Sesi pertama di mesin baru: memeriksa lingkungan dan melaporkan keadaan proyek. Tidak mengubah apa pun |
| [02-kerjakan-task.md](02-kerjakan-task.md) | `/kerjakan-task F2-T4` | Mengerjakan satu task roadmap sampai commit |
| [03-tinjau.md](03-tinjau.md) | `/tinjau F2-T4` | Meninjau hasil sebuah task di konteks yang bersih |
| [04-perbaiki-bug.md](04-perbaiki-bug.md) | `/perbaiki-bug <gejala>` | Memperbaiki bug: tes yang gagal dulu, akar masalah, lalu perbaikan |
| [05-tambah-provider.md](05-tambah-provider.md) | `/tambah-provider <nama>` | Menambah satu provider model |
| [06-tambah-tool.md](06-tambah-tool.md) | `/tambah-tool <nama dan gunanya>` | Menambah satu tool |
| [07-tambah-platform.md](07-tambah-platform.md) | `/tambah-platform <nama>` | Menambah satu platform pesan ke gateway |
| [08-porting-dari-hermes.md](08-porting-dari-hermes.md) | `/porting-dari-hermes <fitur>` | Membawa fitur Hermes yang belum ada di roadmap |
| [09-verifikasi-lingkungan.md](09-verifikasi-lingkungan.md) | `/verifikasi-lingkungan` | Membuktikan pemasangan dan seluruh pemeriksaan di mesin ini |
| [10-pecah-task.md](10-pecah-task.md) | `/pecah-task F3-T3` | Memecah task berukuran XL menjadi task yang bisa dikerjakan |

Perintah di kolom kedua adalah skill proyek di `.claude/skills/`. Tiap skill hanya menunjuk ke
file prompt di folder ini, sehingga isinya ditulis di satu tempat.

Memakai model atau harness selain Claude Code: lihat [PANDUAN-MODEL-LAIN.md](../PANDUAN-MODEL-LAIN.md).

## Menyiapkan Claude Code

Yang diperlukan sekali saja:

1. Pasang Claude Code versi 2.1.257 atau lebih baru. Fable 5.1 membutuhkannya.
2. Jalankan `claude --model fable` dari root repositori, atau `/model fable` di dalam sesi.
   Fable tidak pernah menjadi model default; ia harus dipilih.
3. Clone Hermes sebagai rujukan di samping repositori ini, pada commit yang dicatat di
   [bedah Hermes](../hermes/README.md):

   ```bash
   git clone https://github.com/NousResearch/hermes-agent ../hermes-ref
   git -C ../hermes-ref checkout 1298c8e74baa73e1a2b90124228d017261ac6bc4
   ```

4. Jalankan `/orientasi` satu kali. Bila perintah itu tidak dikenali, skill proyek tidak
   termuat: tempel bagian "Prompt" dari [01-orientasi.md](01-orientasi.md) sebagai gantinya.
   Skill di `.claude/skills/` belum pernah dicoba di Claude Code (lihat
   [STATUS.md](../STATUS.md)); file prompt-nya tidak bergantung pada skill itu.

Yang dimuat otomatis oleh Claude Code: `CLAUDE.md` di root (yang mengimpor `AGENTS.md`), dan
`CLAUDE.md` di sebuah direktori saat file di direktori itu dibaca. Aturan proyek tidak perlu
diulang di prompt.

## Alur kerja yang disarankan

```
pilih task di docs/roadmap  ─►  /kerjakan-task <nomor>  ─►  /clear  ─►  /tinjau <nomor>
                                        ▲                                    │
                                        └────── perbaiki temuan ◄────────────┘
```

- **Satu task per sesi** adalah default yang aman: riwayat sesi tetap relevan, dan hasilnya
  mudah ditinjau. Fable sanggup memegang sesi panjang, jadi task berukuran L boleh dikerjakan
  dalam satu sesi, dan beberapa task S yang berkaitan boleh digabung.
- **Tinjau di konteks bersih.** `/tinjau` berjalan di subagent yang tidak melihat percakapan
  pengerjaan, sehingga yang dinilai adalah hasilnya, bukan penalaran yang menghasilkannya.
  Untuk task besar, jalankan juga di sesi baru setelah `/clear`.
- **Biarkan berjalan tanpa ditunggu** dengan `/goal`. Kondisinya harus sesuatu yang bisa
  dibuktikan keluaran di percakapan, misalnya:

  ```text
  /goal setiap butir "Selesai bila" task F2-T4 terpenuhi, `scripts/run_tests.sh` keluar dengan 0, dan `git status` bersih; atau berhenti setelah 40 giliran
  ```

- **Rencanakan dulu untuk task M ke atas.** Masuk ke plan mode (Shift+Tab sampai bilah status
  menunjukkannya, atau `claude --permission-mode plan`), minta rencana, baca, lalu setujui.
- **Koreksi lebih dari dua kali untuk hal yang sama** berarti konteksnya sudah keruh: `/clear`
  dan mulai lagi dengan prompt yang memuat apa yang sudah dipelajari.

## Yang tetap butuh Anda

AI tidak bisa menyediakan ini sendiri. Setiap task roadmap yang membutuhkannya menyebutnya di
bagian "Butuh dari Anda".

- Kunci API provider dan anggaran untuk panggilan uji.
- Token bot dan akun uji untuk platform pesan.
- Mesin dengan layar untuk aplikasi desktop, dan mesin Windows bila ingin mencoba dengan
  tangan.
- Keputusan produk: nama paket, bahasa dokumentasi pengguna, provider mana yang didahulukan.
- Membaca laporan akhir setiap task. Laporan itu memuat bagian "tidak diverifikasi"; itulah
  yang paling perlu Anda perhatikan.

## Yang perlu diketahui tentang Fable 5.1

- **Beri hasil yang diinginkan, bukan langkahnya.** Prompt di folder ini menyebut tujuan,
  batasan, dan bukti selesai. Menambahkan langkah rinci biasanya memperburuk hasil.
- **Pengingat untuk menguji tidak perlu diulang.** Kriteria selesai cukup disebut sekali.
- **Pekerjaan pada kode keamanan bisa dialihkan ke model lain.** Proyek ini memuat pola
  perintah berbahaya dan pemindai injeksi prompt. Permintaan yang ditandai pengklasifikasi
  keamanan siber dijalankan ulang pada model Opus. Itu perilaku Claude Code, bukan galat.
- **Pemakaian Fable bisa ditagihkan ke kredit pemakaian**, tergantung paket Anda. Dalam mode
  non-interaktif (`claude -p`) tidak ada pertanyaan konfirmasi sebelum biaya berjalan.

Sumber: dokumentasi Claude Code tentang
[konfigurasi model](https://code.claude.com/docs/en/model-config),
[`/goal`](https://code.claude.com/docs/en/goal),
[praktik terbaik](https://code.claude.com/docs/en/best-practices), dan
[skill](https://code.claude.com/docs/en/skills), dibaca 5 Oktober 2026. Perintah dan nomor
versi di halaman ini berasal dari sana dan bisa berubah.

## Menulis prompt baru

Prompt yang bekerja baik di proyek ini punya empat bagian, dalam urutan ini:

1. **Hasil.** Apa yang harus benar setelah pekerjaan selesai.
2. **Yang dibaca dulu.** File yang memuat aturan dan konteksnya. Sebut path-nya.
3. **Batasan.** Apa yang tidak boleh berubah, dan kapan harus berhenti dan melapor.
4. **Bukti.** Apa yang harus ditunjukkan di laporan akhir.

Simpan prompt baru di folder ini, dan bila sering dipakai, buat skill tipis di `.claude/skills/`
yang menunjuk kepadanya.
