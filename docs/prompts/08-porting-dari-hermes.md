# Porting fitur dari Hermes

**Kapan dipakai.** Ada fitur Hermes yang Anda inginkan dan belum ada di roadmap. Untuk fitur
yang sudah punya task, pakai [02-kerjakan-task.md](02-kerjakan-task.md).

**Di Claude Code:** `/porting-dari-hermes <fitur>`

**Isian.** `<FITUR>`: fitur Hermes yang dimaksud, sedekat mungkin dengan cara Hermes
menyebutnya (nama perintah, nama tool, atau nama file).

## Prompt

Bawa fitur Hermes berikut ke repositori ini: `<FITUR>`.

Kerjakan dalam dua tahap, dan berhenti di antara keduanya.

**Tahap 1: pahami dan tulis task-nya.** Tidak ada kode yang berubah di tahap ini.
- Temukan fiturnya di clone rujukan `../hermes-ref`. Mulai dari
  `docs/hermes/99-peta-file.md` dan bab bedah yang relevan di `docs/hermes/`, lalu baca kode
  dan **tesnya**: tes Hermes adalah daftar kasus tepi terbaik yang tersedia.
- Tulis apa yang dijanjikan fitur itu kepada pengguna, terpisah dari cara Hermes
  membangunnya.
- Tentukan bentuknya di sini dengan `docs/arsitektur/01-lapisan.md` (di lapisan mana) dan
  `docs/arsitektur/07-beda-dengan-hermes.md` (penyesuaian yang biasa diperlukan).
- Tulis blok task baru di file fase yang sesuai di `docs/roadmap/`, dengan nomor berikutnya
  dan semua bagian wajib, lalu daftarkan di indeks. Jalankan
  `python scripts/check_hermes_refs.py --hermes ../hermes-ref` untuk memastikan setiap rujukan
  ada.
- Laporkan: ringkasan fitur, ukuran task, hal yang sengaja tidak dibawa beserta alasannya,
  dan keputusan yang butuh jawaban pemilik proyek. **Berhenti di sini** dan tunggu
  persetujuan.

**Tahap 2: kerjakan.** Setelah disetujui, kerjakan task itu mengikuti
`docs/prompts/02-kerjakan-task.md`.

**Batasan.**
- Ambil perilakunya, bukan bentuknya. Cabang menurut nama provider menjadi method pada profil;
  state giliran masuk ke `TurnState`; konteks sesaat menjadi `turn_context` yang tersimpan.
- Bila ada potongan kode yang disalin langsung, pertahankan atribusi sesuai `NOTICE.md`.
- Jangan membawa ketergantungan baru tanpa menyebutnya di laporan tahap 1.
