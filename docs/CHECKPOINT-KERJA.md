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

### F2-T2 — gelombang pertama teruji lokal, task tetap parsial

- Branch `f2-t2-providers`, titik awal `49eecd7`; tanpa commit/push/merge dan tanpa API asli.
- Lingkup: sepuluh profil kompatibel OpenAI, tes rute/HTTP lokal dan discovery setup;
  Azure, Bedrock, Vertex tetap gelombang berikutnya. F2-T2 tetap parsial.
- Langkah: tes merah → deklarasi profil minimum → tes hijau → dokumen dan turunannya.
- Clone rujukan Hermes di direktori saudara tidak tersedia. Log worker sebelumnya hanya
  memuat cuplikan riset; sumber resmi endpoint/model diperiksa ulang pada 7 Oktober 2026.
- Sepuluh direktori profil ditambahkan; inti, transport, setup, dan dependensi tidak diubah.
  Hanya Moonshot K2.6 membutuhkan override suhu, sesuai batas resmi server. Profil lokal
  tanpa autentikasi, tanpa katalog/konteks rekaan; model selalu dipilih pengguna.
- Merah awal: 21 gagal sebelum profil ada (/tmp/clite-f2t2-red.log); regresi suhu gagal
  terpisah (/tmp/clite-f2t2-sampling-red.log). Snapshot terpisah `49eecd7` dengan timeout
  menggagalkan seluruh 23 kasus baru/diperluas (/tmp/clite-f2t2-baseline-red.log).
- Hijau: 22 kasus baru lulus (/tmp/clite-f2t2-green.log); suite terarah providers,
  arsitektur, docs, rilis dan rename 197 lulus, 15 terlewati (/tmp/clite-f2t2-targeted.log).
- Suite penuh: 870 lulus, 28 terlewati; Node shared 21, TUI 18, desktop 8 lulus dan ketiga
  typecheck lulus. Mypy 161 file bersih. Run pertama mendeteksi satu pemformatan import
  Moonshot; diperbaiki tanpa perubahan perilaku. Run final seluruh suite lulus, Ruff bersih:
  /tmp/clite-f2t2-full-final.log (run awal: /tmp/clite-f2t2-full.log).
- Handoff: patch belum di-commit; parent runner meninjau hasil verifikasi dan diff.
  Tidak ada API asli atau CI lintas platform baru. F2-T2 tetap 🟡: Azure/Bedrock/Vertex
  belum dikerjakan dan semua profil baru belum diuji terhadap layanan sungguhan.

### F2-T1 — implementasi lokal, API asli ditunda

- Branch `f2-t1-responses`, titik awal `12a8dbe`. Tanpa commit/push/tag/merge.
- Lingkup: transport Responses streaming/nonstreaming, replay `provider_data`, pemilihan
  protokol oleh profil, klasifikasi galat, tes HTTP lokal dua ronde tool dan awalan stabil.
- Langkah: tes merah → implementasi minimum → tes terarah hijau → regenerasi dokumen.
  Suite penuh diserahkan kepada runner; layanan asli tidak dipanggil atas instruksi pemilik.
- Clone rujukan Hermes di direktori saudara tidak tersedia; file rujukan belum dibaca.
  Kontrak kawat diperiksa dari dokumentasi resmi OpenAI pada 7 Oktober 2026.
- Bukti merah: tes baru dijalankan pada salinan `12a8dbe` tanpa implementasi: 28 gagal,
  2 tes jaringan dilewati (/tmp/clite-f2t1-red.log). Hijau sesudah implementasi: 28 lulus,
  2 dilewati (/tmp/clite-f2t1-green.log).
- Verifikasi terarah: tes docs, arsitektur, providers, dan agent 286 lulus, 15 dilewati;
  Ruff dan mypy 161 file bersih. Suite penuh dan TypeScript diserahkan kepada runner.
- Status F2-T1 🟡: tes `network` Responses ditulis tetapi tidak dijalankan; tidak ada API asli,
  biaya, atau provider pengganti yang dipakai.

### F1-T7 — selesai, rilis v0.1.0 terbit

- Pembaruan penerbitan: branch dan tag sudah didorong, tag tetap di `e65bb0c`.
  Workflow `37563420757` hijau; wheel/sdist tersedia pada
  https://github.com/dragovics/clite/releases/tag/v0.1.0. Unduhan terautentikasi
  dan digest SHA-256 cocok; instalasi pipx aset terbit lulus versi/doctor mock/smoke test.
  Main belum merge. Catatan persiapan sebelum penerbitan di bawah bersifat historis.

- Branch `f1-t7`, titik awal `0df6d09`. Melanjutkan patch worker yang terhenti HTTP 502;
  tidak memulai ulang. Patch diverifikasi runner untuk commit lokal; belum push/tag/merge.
- Keputusan pemilik: distribusi `c-lite`, import/CLI `clite`, MIT, GitHub Releases saja,
  tanpa PyPI. Versi tunggal berasal dari `src/clite/__init__.py`; skrip build memeriksa
  isi wheel dan menyediakan validasi versi/changelog/tag serta kenaikan versi.
- Bukti runner: /tmp/clite-f1t7-runner.log (820 lulus, 26 terlewati, Ruff dan mypy 160
  file bersih); /tmp/clite-f1t7-node.log (21+18+8 tes, tiga typecheck lulus).
- Wheel/sdist lokal dibuat, dipasang ke lingkungan terpisah di /tmp/f1t7-rel.
  Runner membangun ulang wheel dan memasangnya ulang; pemeriksa instalasi dengan `-I`
  lulus di luar checkout. CLI/doctor pipx juga lulus dengan config `mock`; metadata pipx
  menunjuk URL HTTP lokal. Tidak ada bukti pemasangan melalui URL GitHub privat.
- Regresi baru: /tmp/clite-f1t7-red.log; pada salinan terpisah dengan timeout, metadata
  lama menyebabkan dua tes gagal, dan empat pelepasan perilaku rilis masing-masing
  menyebabkan satu tes gagal. Pemulihan kode membuat sembilan tes rilis kembali lulus.
- README kini memakai pemasangan file wheel lokal dan menjelaskan unduhan terautentikasi
  setelah rilis terbit. Changelog ditandai belum diterbitkan; STATUS, spesifikasi CLI,
  indeks roadmap, dan kriteria F1-T7 membedakan bukti lokal dari rilis sungguhan.
- Tidak ada dependensi runtime baru. Build backend menjadi `setuptools>=77,<90` agar
  metadata lisensi SPDX didukung; alat build terpisah memakai `build>=1.2,<2`.
- Verifikasi sesudah edit dokumen: 22 tes dokumen/rilis/rename lulus; `git diff --check`
  bersih. Skrip pembuktian regresi lokal: /tmp/clite-f1t7-regression.py.
- Verifikasi final runner: 820 lulus, 26 terlewati; Ruff/mypy bersih. Wheel dan sdist
  dibangun ulang lalu masing-masing dipasang dan lulus pemeriksa instalasi di luar checkout.
  Log: /tmp/clite-f1t7-final.log. Jangan terbitkan atau tutup F1-T7 sebelum ada izin,
  workflow rilis hijau, wheel/sdist terlampir, dan instalasi
  dari aset tersebut terbukti. F1-T2 masih parsial; jangan mengklaim provider asli teruji.

### F1-T6 — selesai lokal

- Branch `f1-t6-config-comments`, titik awal `57c5794`; commit lokal, belum push/merge.
- Penulis config memakai `ruamel.yaml>=0.18.6,<0.19`, mempertahankan komentar, baris
  kosong, urutan, dan gaya kutip; resolver YAML 1.1 menjaga string seperti `yes` dan `012`.
- Bukti merah: 3 tes round-trip gagal pada salinan `57c5794` (`/tmp/clite-f1t6-red.log`);
  5 tes kompatibilitas skalar gagal sebelum resolver disamakan.
- Bukti hijau: `pytest tests/core tests/tools/test_approval.py -q` 146 lulus; Ruff dan mypy
  `src/clite/core/config.py` bersih. Suite penuh Linux: 811 lulus, 26 skip; Ruff dan mypy
  160 file bersih; tes Node 47 lulus dan tiga typecheck hijau. CI belum jalan (belum push).

### Pembaruan F1-T5 — 6 Oktober 2026

- F1-T5 selesai di branch `f1-t5-windows`, draft PR #1; belum merge ke `main`.
- Commit kode: `f884c73`, `b6c7288`, `6360a9a`. CI `37499972911` pada
  `6360a9a` hijau di semua job: Windows 765 lulus/59 skip; Linux Python 3.11–3.13
  masing-masing 798 lulus/26 skip; Node dan wheel hijau. Ruff dan mypy bersih.
- Terverifikasi Windows nyata: kunci dua proses serta integrasi memori/job, cmd.exe/Git
  Bash, cwd, stdin, exit code, timeout/interupsi pohon proses, home/path dan ACL `.env`.
- Tambahan dependensi: `tzdata>=2024.1,<2027` hanya Windows. REPL manual belum dicoba.
- F1-T2/F1-T3 tetap parsial menunggu layanan asli sesuai penundaan pemilik; F1-T4 selesai.
  Jangan merge PR tanpa perintah pemilik.

### Riwayat status sebelumnya

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
