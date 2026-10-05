# Checkpoint kerja C-lite

Dokumen ini mencatat titik lanjut untuk pengerjaan C-lite lintas sesi. Baca dokumen ini,
`docs/STATUS.md`, dan `docs/roadmap/README.md` sebelum melanjutkan. Cocokkan selalu dengan
`git status` dan log commit; isi dokumen ini tidak menggantikan keadaan repositori.

## Aturan kerja

1. Pilih satu masalah atau task roadmap yang batas dan kriteria selesainya jelas. Dahulukan
   celah keamanan dan kegagalan yang telah direproduksi sebelum fitur baru.
2. Bila tugas dapat dibagi tanpa benturan file, delegasikan bagian yang terpisah ke subagent.
   Model subagent yang diizinkan pemilik: GPT-6.1 Sol dan GPT-6 Sol. Penanggung jawab utama
   memeriksa integrasi, tes, dan hasil akhir.
3. Sebelum pekerjaan panjang, tulis ID tugas, commit awal, temuan, rencana langkah kecil,
   dan pemeriksaan yang akan dijalankan di bagian "Status aktif". Perbarui setelah setiap
   langkah penting; jangan tandai selesai sebelum pemeriksaannya benar-benar lulus.
4. Buat satu commit lokal untuk setiap perubahan logis yang lengkap dan teruji. Jangan push
   tanpa instruksi pemilik. Jangan memasukkan rahasia atau hasil tes sementara ke commit.
5. Ketika batas pemakaian mendekat, hentikan pekerjaan baru. Simpan perubahan yang selesai
   dalam commit; catat perubahan belum selesai, hasil tes, hambatan, dan perintah lanjut di
   sini. Jangan menyebut pekerjaan belum teruji sebagai selesai.
6. Jika sesi berhenti mendadak sebelum catatan diperbarui, sesi berikutnya harus memeriksa
   `git status`, `git diff`, dan commit terakhir terlebih dahulu. Jangan menimpa perubahan
   yang sudah ada. Lanjutkan tugas yang sama dari titik aman, lalu verifikasi ulang.

Persetujuan rutin tidak diminta. Jika akun, kredensial, atau keputusan produk yang tidak
tersedia benar-benar diperlukan, catat hambatannya dan lanjutkan pekerjaan independen yang
masih mungkin. Jangan menganggap diamnya pemilik sebagai persetujuan untuk tindakan yang
membutuhkan otorisasi tersendiri.

## Status aktif

- Tanggal: 6 Oktober 2026.
- Tahap: audit F01–F10 selesai diuji. Batas F11 tetap gateway dengan pengguna tepercaya
  yang berbagi data profil; isolasi multi-tenant membutuhkan keputusan produk tersendiri.
- Titik awal sesi ini: `e281688` pada branch `codex/checkpoint-2026-10-05`; F08/F09
  sebelumnya disimpan sebagai WIP `ea375e3`. WIP itu telah diperiksa dan dilengkapi:
  propagasi home/rahasia ke worker RPC/HTTP dan cleanup WebSocket, isolasi model/database
  dua profil bersamaan, serta redaksi rahasia scope dan nilai yang berbagi awalan.
- Bukti regresi: sembilan tes baru gagal pada salinan `ef2a1ec` sebelum perbaikan;
  66 tes core/RPC/context HTTP lulus sesudahnya. Redaksi awalan yang tumpang tindih juga
  direproduksi gagal pada kode WIP sebelum diperbaiki.
- Pemeriksaan gabungan: 758 tes Python lulus, 2 skip karena Playwright dan SDK MCP tidak
  terpasang; Ruff bersih; mypy bersih pada 159 file dengan cache tersendiri; 47 tes Node
  lulus (21 shared, 18 TUI, 8 desktop) dan ketiga typecheck lulus. Linux, Python 3.12.14,
  Node 24.19.0. API provider sungguhan dan Windows tetap belum diverifikasi.
- Perbaikan harness: tes fallback katalog kini memakai server HTTP lokal dan rute eksplisit.
  Sebelumnya variabel endpoint tidak dibaca oleh jalur yang diuji sehingga suite mencoba
  menghubungi API publik; pemeriksa otomatis menghentikannya. Tes kegagalan startup TUI
  kini memakai profil yang tidak ada, tetap berlaku saat paket sudah terpasang, memiliki
  timeout dan cleanup. Kedua tes tetap memeriksa kontrak kegagalan aslinya.
- Berkas lama yang belum terlacak: `package-lock.json`; simpan untuk diperiksa pada F1-T1.
- Backup: tujuan pemilik `https://github.com/dragovics/clite` terkonfirmasi kosong di awal
  sesi. Selesaikan backup fase ini sebelum mengerjakan fase berikutnya. Kredensial Git CLI
  tidak tersedia; koneksi GitHub mempunyai izin tulis. Jangan mengaku backup berhasil
  sampai ref remote dan isi tree sudah terverifikasi.
- Langkah lanjut setelah backup: F1-T1, periksa lockfile, pemasangan bersih, job wheel,
  dan CI di repo tujuan. Jangan menandai F1-T1 selesai tanpa job CI yang benar-benar hijau.

## Riwayat checkpoint

| Tanggal | Tugas | Hasil | Commit |
|---|---|---|---|
| 5 Oktober 2026 | Siapkan mekanisme lanjut lintas sesi | Catatan dan aturan checkpoint dibuat | Lihat log Git |
| 5 Oktober 2026 | F03: tolak tool call saat izin sesi kosong | Tes regresi dan perbaikan dispatch | `f5886db` |
| 5 Oktober 2026 | F02: batasi tool subagent ke hak induk | Tujuh regresi dan perbaikan delegasi | `422816e` |
| 5 Oktober 2026 | F04: tolak penulisan skill lewat symlink | Penjaga path dan kebijakan tulis | `e3927d6` |
| 5 Oktober 2026 | F01: ikat rotasi kredensial ke endpoint | Pool route, origin, dan regresi sintetik | `f825bba` |
| 5 Oktober 2026 | F05: validasi tujuan pemasangan skill | Kategori aman dan validasi semua tujuan sebelum force replace | `64d8d56` |
| 5 Oktober 2026 | F06/F07: ownership process dan batas output | Isolasi profil/task, drain pipe, UTF-8/newline, dan regresi | `04333e9` |
| 5 Oktober 2026 | RPC, desktop, dan cron | Tipe handler, stderr startup, advisory lock | `5048066`, `e578c5d`, `239da31` |
| 5 Oktober 2026 | F11: batas privasi trusted gateway | Dokumentasi shared profile data | `c5b2d12` |
| 6 Oktober 2026 | F08/F09: scope dan redaksi | Sembilan regresi dibuktikan; suite Python, tipe, dan Node lulus | Lihat log Git |
