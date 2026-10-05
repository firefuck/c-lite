# Kerjakan satu task roadmap

**Kapan dipakai.** Untuk mengerjakan satu task dari `docs/roadmap/` sampai selesai dan
ter-commit.

**Di Claude Code:** `/kerjakan-task F2-T4`

**Isian.** `<TASK>` adalah nomor task, misalnya `F2-T4`.

## Prompt

Kerjakan task roadmap `<TASK>` di repositori ini sampai selesai.

**Hasil yang diminta.** Setiap butir "Selesai bila" pada task itu terpenuhi, begitu juga
daftar "Selesai itu apa" di `docs/roadmap/README.md`, dan perubahannya sudah di-commit.

**Yang dibaca dulu.**
- Blok task `<TASK>` di file fasenya, dan task yang disebut di "Bergantung pada". Bila ada
  ketergantungan yang belum ✅, berhenti dan laporkan.
- Spesifikasi modul yang disentuh di `docs/spesifikasi/`, dan `AGENTS.md` di direktori yang
  akan diubah.
- File di "Rujukan Hermes", dibaca langsung di `../hermes-ref`. Ambil perilaku dan kasus
  tepinya, lalu tulis mengikuti bentuk proyek ini; panduannya ada di
  `docs/arsitektur/07-beda-dengan-hermes.md`. Bila clone itu tidak ada, katakan, dan jangan
  mengandalkan ingatan tentang Hermes.

**Batasan.**
- Invarian di `docs/arsitektur/03-invarian.md` tidak dilanggar. Bila task tampak menuntutnya,
  berhenti dan jelaskan pertentangannya; jangan mencari jalan memutar.
- Kerjakan lingkup task itu saja. Hal lain yang Anda temukan dicatat di laporan akhir, tidak
  diperbaiki, kecuali bug yang menghalangi task atau celah keamanan.
- Tes yang gagal tidak diperbaiki dengan melemahkannya. Putuskan dulu mana yang salah: kode
  atau harapan tes.
- Yang membutuhkan sesuatu dari pemilik proyek (bagian "Butuh dari Anda") dikerjakan sejauh
  mungkin tanpanya, lalu dicatat sebagai belum diverifikasi. Jangan memberi tanda ✅ pada
  sesuatu yang belum pernah dijalankan terhadap hal yang sebenarnya.

**Sebelum menganggap selesai.** Minta subagent `peninjau` memeriksa diff terhadap kriteria
task (di harness tanpa subagent, lakukan sendiri dengan membaca ulang diff dari awal).
Perbaiki temuan yang menyangkut kebenaran atau kriteria task. Preferensi gaya boleh diabaikan.

**Commit.** Pesan dalam bahasa Inggris, kalimat perintah, menyebut apa yang berubah dan
mengapa. Satu perubahan logis per commit. Jangan push kecuali diminta.

**Laporan akhir.**
- Yang berubah, per file, dalam satu atau dua kalimat masing-masing.
- Bukti: perintah pemeriksaan yang dijalankan dan hasilnya, dan untuk tiap butir "Selesai
  bila", tes yang membuktikannya.
- Yang **tidak** diverifikasi, dan apa yang dibutuhkan untuk memverifikasinya.
- Penyimpangan dari lingkup task, dan temuan di luar lingkup.
