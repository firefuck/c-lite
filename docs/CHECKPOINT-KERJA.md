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
- `package-lock.json` sudah diperiksa, di-commit, dan dipakai `npm ci` di CI.
- Backup fase audit berhasil: snapshot source di `main` dan
  `codex/checkpoint-2026-10-05` pada GitHub commit `a9f7b550c4d86f29624cef23f0a3b40f3ae5d66c`.
  Tree `4b3ef181801b77a16f4032e1fb931622a80b531f` identik dengan commit lokal `9ac1d63`.
  Branch `codex/history-2026-10-06` pada `af63a5fdf15ab9ee1ced779f26668e528b233073`
  menyimpan bundle seluruh riwayat asli dan petunjuk pemulihan. Blob bundle cocok dengan
  hasil lokal. Git CLI tidak mempunyai kredensial, sehingga snapshot dikirim melalui
  koneksi GitHub; SHA commit berbeda, tree sama.
- Tugas aktif berikutnya: F1-T1. Commit awal `9ac1d63`; periksa lockfile lama,
  jalankan pemasangan bersih, tambahkan job wheel, dan pakai `npm ci` di CI. CI pertama
  repo tujuan (run `37355514348`) sudah hijau: Python 3.11/3.12/3.13 dan Node 22.
  Billing blocker dari repo upstream tidak berlaku pada repo tujuan ini. Jangan menandai
  F1-T1 selesai sampai job wheel dan instalasi lockfile juga benar-benar hijau.
- Hasil lokal F1-T1: `pip install -e ".[dev]"` dan `npm ci` berhasil di lingkungan
  baru dari registry; `scripts/run_tests.sh` lulus dan kedua build Node berhasil.
  Smoke wheel di luar checkout lulus, serta menolak salinan instalasi dengan satu aset
  skill dihilangkan. Lockfile lama telah diperiksa dan cocok dengan ketiga workspace.
  CI run `37356398420` pada `6e6669c` hijau di semua job, termasuk `npm ci` dan wheel.
  F1-T1 selesai. Tugas berikutnya menurut urutan: F1-T2 (butuh kunci API dari pemilik);
  bila belum tersedia, F1-T4.

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
| 6 Oktober 2026 | F1-T1: pasang dan CI | CI run `37356398420` hijau: Python 3.11–3.13, Node, wheel | Lihat log Git |
