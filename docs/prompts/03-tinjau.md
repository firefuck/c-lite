# Tinjau hasil sebuah task

**Kapan dipakai.** Setelah sebuah task dikerjakan, di konteks yang tidak memuat percakapan
pengerjaannya. Peninjau menilai hasil, bukan penalaran yang menghasilkannya.

**Di Claude Code:** `/tinjau F2-T4` (berjalan di subagent `peninjau`). Untuk task besar,
jalankan juga di sesi baru setelah `/clear`.

**Isian.** `<TASK>` adalah nomor task. Bila yang ditinjau bukan task roadmap, ganti dengan
rentang commit atau nama branch dan uraian singkat tentang apa yang seharusnya dicapai.

## Prompt

Tinjau perubahan yang mengerjakan task roadmap `<TASK>`. Anda tidak mengubah file; hasil Anda
adalah daftar temuan.

**Yang ditinjau.** Diff task itu: commit sejak task dimulai, atau perubahan yang belum
di-commit. Gunakan `git log` dan `git diff` untuk menemukannya.

**Terhadap apa.**
1. Butir "Selesai bila" pada blok task `<TASK>` di `docs/roadmap/`, dan daftar "Selesai itu
   apa" di `docs/roadmap/README.md`.
2. Invarian di `docs/arsitektur/03-invarian.md`.
3. Kontrak di spesifikasi modul yang disentuh (`docs/spesifikasi/`).
4. Aturan keamanan untuk kode baru di `docs/arsitektur/06-keamanan.md`, bila diff menyentuh
   tool, hook, server, gateway, atau apa pun yang menjalankan perintah, menulis file, atau
   menerima masukan dari luar.

**Cara memeriksa.**
- Jalankan `scripts/run_tests.sh`.
- Untuk setiap tes baru, pastikan tes itu gagal bila perubahan yang diujinya dilepas. Tes yang
  tidak bisa gagal adalah temuan. Lakukan ini di salinan terpisah (`git worktree add` ke
  direktori sementara), bukan di direktori kerja, dan jalankan dengan batas waktu: kode tanpa
  perbaikannya bisa saja menggantung.
- Baca kode yang berubah seutuhnya, bukan hanya baris diff-nya.
- Periksa bahwa dokumen ikut berubah: baris status di spesifikasi, indeks roadmap,
  `docs/STATUS.md`, dan file hasil generate.

**Yang dilaporkan sebagai temuan.** Hanya yang menyangkut kebenaran, keamanan, invarian, atau
kriteria task: kriteria yang belum terpenuhi, perilaku yang salah beserta cara memicunya,
kasus tepi tanpa tes, klaim ✅ tanpa bukti, dan perubahan di luar lingkup task. Preferensi
gaya, penamaan, dan usulan abstraksi tambahan bukan temuan.

**Bentuk laporan.** Satu baris putusan (layak diterima, atau belum), lalu temuan berurutan
dari yang paling berat. Tiap temuan: file dan baris, apa yang salah, bagaimana membuktikannya,
dan seberapa berat (menghalangi, perlu diperbaiki, atau catatan). Bila tidak ada temuan,
katakan demikian dan sebut apa saja yang sudah Anda periksa.
