# Verifikasi lingkungan

**Kapan dipakai.** Untuk membuktikan bahwa proyek ini bisa dipasang dan seluruh pemeriksaannya
lulus di mesin ini, lalu mencatat hasilnya. Berbeda dari [orientasi](01-orientasi.md), prompt
ini boleh memperbaiki yang rusak karena lingkungan.

**Di Claude Code:** `/verifikasi-lingkungan`

## Prompt

Buktikan bahwa repositori ini bisa dipasang dari nol dan lulus seluruh pemeriksaannya di mesin
ini, lalu catat hasilnya.

**Hasil yang diminta.** `docs/STATUS.md` mencerminkan apa yang benar-benar terbukti di mesin
ini pada tanggal hari ini, dan setiap perbaikan yang diperlukan sudah di-commit.

**Yang dikerjakan.**
- Lingkungan Python bersih, lalu `pip install -e ".[dev]"`.
- `npm install` di root, lalu `npm run typecheck`, `npm test`, dan `npm run build`.
- `scripts/run_tests.sh` tanpa variabel lingkungan tambahan.
- Bangun wheel, pasang ke lingkungan bersih lain, lalu jalankan `clite --version`,
  `clite doctor`, `clite chat -q "halo" --provider mock`, dan `clite tui --help`.
- Bila ada browser untuk `playwright`: jalankan juga tes dashboard.
- Bila ada layar: coba `npm run start` di `apps/desktop/` dan lalui daftar periksa di
  `apps/desktop/README.md`.

**Batasan.**
- Perbaiki hanya yang rusak karena lingkungan: batas versi dependensi, skrip, konfigurasi
  build. Bug pada perilaku produk dicatat di laporan dan tidak diperbaiki di sini.
- Tes yang gagal tidak dilewati atau dilemahkan supaya hijau.
- Setiap butir yang dipindah dari "belum diverifikasi" di `docs/STATUS.md` menyebut sistem
  operasi, versi Python dan Node, dan tanggalnya.

**Laporan akhir.** Tabel: pemeriksaan, hasil (lulus, gagal, dilewati), dan keterangan. Lalu
daftar perbaikan yang dibuat, dan daftar yang masih belum bisa diverifikasi di mesin ini
beserta apa yang dibutuhkan.
