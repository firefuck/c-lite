# Berkontribusi ke C-lite

Terima kasih sudah mau ikut membangun C-lite. Halaman ini adalah pintu masuk; aturan kerja
lengkapnya ada di [AGENTS.md](AGENTS.md) dan di `AGENTS.md` tiap area. Bila keduanya tampak
berbeda, `AGENTS.md` yang berlaku.

## Menyiapkan lingkungan

Butuh Python 3.11 atau lebih baru dan Node 22 atau lebih baru.

```bash
pip install -e ".[dev]"
npm install
git config core.hooksPath scripts/hooks   # semua pemeriksaan jalan sebelum setiap push
scripts/run_tests.sh                      # ruff, mypy, biome, pytest, tes TypeScript
npx biome check --write .                 # format TypeScript sebelum commit
python -m clite chat -q "halo" --provider mock
```

Tes browser dashboard butuh `playwright` dan Chromium; tanpa keduanya tes itu dilewati, bukan
gagal.

## Sebelum mulai

- Cari tahu apakah pekerjaannya sudah ada di [roadmap](docs/roadmap/README.md) atau di issue.
  Untuk perubahan besar, buka issue lebih dulu supaya arahnya disepakati.
- Baca `docs/arsitektur/01-lapisan.md` (di mana kode baru diletakkan) dan
  `docs/arsitektur/03-invarian.md` (aturan yang tidak boleh dilanggar, beserta tes penjaganya).

## Saat mengerjakan

- **Tes lebih dulu atau bersamaan.** Setiap perilaku baru punya tes yang gagal bila perilaku
  itu dilepas. Tes tidak memakai jaringan dan tidak menyentuh home asli.
- **Bangun ulang turunan.** Tabel "Sesudah mengubah sesuatu yang punya turunan" di `AGENTS.md`
  menyebut skrip yang harus dijalankan (dokumen referensi, kontrak RPC, bundle TUI, bundle
  dashboard). Suite gagal bila terlupa.
- **Dokumen berubah bersama kode**, di commit yang sama: spesifikasi modul, indeks roadmap,
  dan `docs/STATUS.md`. Status ditulis jujur: yang belum pernah dijalankan terhadap hal
  sebenarnya dicatat sebagai belum diverifikasi.
- **Bahasa.** Dokumen berbahasa Indonesia. Kode, nama, komentar, pesan log, keluaran CLI, dan
  pesan commit berbahasa Inggris.

## Commit dan pull request

- Pesan commit: kalimat perintah berbahasa Inggris yang menyebut apa dan mengapa, satu
  perubahan logis per commit.
- Jalankan `scripts/run_tests.sh` sampai hijau sebelum membuka pull request. Hook `pre-push`
  melakukannya otomatis bila sudah diaktifkan.
- Isi template pull request: apa yang berubah, mengapa, dan bagaimana membuktikannya.
- Setiap perubahan ditinjau pemilik kode (lihat `.github/CODEOWNERS`).

## Celah keamanan

Jangan laporkan celah keamanan lewat issue publik. Ikuti [SECURITY.md](SECURITY.md).

## Perilaku

Semua yang terlibat diharapkan mengikuti [kode etik](CODE_OF_CONDUCT.md).

## Lisensi

Dengan berkontribusi, Anda setuju kontribusi Anda dirilis di bawah [lisensi MIT](LICENSE)
proyek ini. Kode yang disalin dari Hermes Agent mempertahankan atribusinya sesuai
[NOTICE.md](NOTICE.md).
