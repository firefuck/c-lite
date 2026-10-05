# Orientasi

**Kapan dipakai.** Sesi pertama di mesin baru, atau setelah lama tidak menyentuh proyek.
Hasilnya adalah laporan keadaan; tidak ada file yang berubah.

**Di Claude Code:** `/orientasi`

## Prompt

Periksa lingkungan kerja ini dan laporkan keadaan proyek C-lite. Jangan mengubah file apa pun
di sesi ini; bila ada yang gagal, laporkan saja.

**Yang dibaca.** `AGENTS.md`, `docs/README.md`, `docs/STATUS.md`,
`docs/arsitektur/README.md`, `docs/arsitektur/03-invarian.md`, dan `docs/roadmap/README.md`.

**Yang dijalankan.**
- `scripts/run_tests.sh`
- `python -m clite chat -q "halo" --provider mock` (satu giliran tanpa kunci API)
- `python scripts/check_hermes_refs.py --hermes ../hermes-ref`, bila clone rujukan Hermes ada

**Yang dilaporkan.**
- Versi Python dan Node, dan apakah dependensi terpasang.
- Hasil tiap pemeriksaan: lulus, gagal, atau dilewati. Untuk yang dilewati, sebabnya (misalnya
  `playwright` atau `typescript` tidak terpasang) dan cara memasangnya.
- Apakah clone rujukan Hermes ada di `../hermes-ref` pada commit yang dicatat di
  `docs/hermes/README.md`.
- Butir "belum diverifikasi" di `docs/STATUS.md` yang **bisa** diverifikasi di mesin ini.
- Task roadmap yang paling masuk akal dikerjakan berikutnya, dengan alasannya, dan apa yang
  dibutuhkan dari pemilik proyek untuk itu.

Tutup dengan daftar pendek hal yang Anda temukan tidak cocok antara dokumen dan kode, bila
ada. Sebut file dan barisnya.
