# Perbaiki bug

**Kapan dipakai.** Ada perilaku yang salah: tes gagal, crash, atau hasil yang tidak sesuai
spesifikasi.

**Di Claude Code:** `/perbaiki-bug <gejala>`

**Isian.** `<GEJALA>`: apa yang terjadi, apa yang seharusnya terjadi, dan cara memicunya bila
diketahui. Tempelkan pesan galat dan traceback apa adanya.

## Prompt

Perbaiki bug berikut di repositori ini:

`<GEJALA>`

**Hasil yang diminta.** Akar masalahnya diperbaiki, ada tes yang gagal sebelum perbaikan dan
lulus sesudahnya, dan seluruh pemeriksaan (`scripts/run_tests.sh`) lulus.

**Urutan yang diharapkan.**
1. Reproduksi dulu. Tulis tes yang gagal karena bug ini, lewat pintu publik modulnya. Bila
   bug tidak bisa direproduksi, berhenti dan laporkan apa yang sudah dicoba.
2. Cari akar masalahnya sebelum mengubah kode. Gejala dan sebab sering berada di lapisan yang
   berbeda; perbaikan ditaruh di tempat sebabnya.
3. Perbaiki, lalu cari tempat lain yang memakai pola keliru yang sama.

**Batasan.**
- Jangan menekan galat (menangkap exception lalu diam, melonggarkan tes, menambah
  pengecualian) sebagai pengganti perbaikan.
- Bila perbaikan mengubah perilaku yang dijanjikan di spesifikasi modul, itu perubahan
  kontrak: ubah spesifikasinya dalam commit yang sama dan sebutkan di laporan.
- Bila bug itu celah keamanan, periksa juga `docs/arsitektur/06-keamanan.md`: pagar yang
  terkait, dan apakah tabel "Celah yang diketahui" perlu diubah.

**Laporan akhir.** Akar masalah dalam dua atau tiga kalimat, tes yang ditambahkan, tempat lain
yang ikut diperbaiki, dan apa pun yang masih Anda ragukan.
