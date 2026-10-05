# Pecah task besar

**Kapan dipakai.** Sebuah task roadmap berukuran XL, atau task L yang ternyata lebih besar
dari perkiraan. Hasilnya adalah task-task baru; tidak ada kode yang berubah.

**Di Claude Code:** `/pecah-task F3-T3`

**Isian.** `<TASK>` adalah nomor task yang dipecah.

## Prompt

Pecah task roadmap `<TASK>` menjadi task yang masing-masing bisa dikerjakan dan ditinjau
sendiri. Jangan mengubah kode di sesi ini.

**Hasil yang diminta.** Task baru tertulis di file fase yang sama, terdaftar di indeks
`docs/roadmap/README.md`, dan `<TASK>` menjadi payung yang mendaftar anak-anaknya.

**Yang dibaca dulu.** Blok task `<TASK>`, spesifikasi modul yang disentuhnya, kode yang ada
di area itu, dan file "Rujukan Hermes" di `../hermes-ref` untuk menakar ukuran sebenarnya.

**Syarat pecahan yang baik.**
- Setiap pecahan berukuran M atau lebih kecil, dan meninggalkan repositori dalam keadaan
  lulus seluruh pemeriksaan. Tidak ada pecahan yang "setengah jalan".
- Setiap pecahan menghasilkan sesuatu yang bisa dilihat atau diuji sendiri. Pecahan yang
  hanya "menyiapkan" tanpa perilaku yang bisa diuji digabung ke pecahan yang memakainya.
- Urutannya memungkinkan pecahan pertama dikerjakan tanpa menunggu yang lain, dan
  ketergantungan antarpecahan ditulis di "Bergantung pada".
- Keputusan desain yang memengaruhi semua pecahan (pustaka mana, bentuk antarmuka mana)
  diambil sekarang dan ditulis di task payung beserta alasannya. Bila keputusan itu milik
  pemilik proyek, tulis pilihannya dan berhenti.

**Aturan penulisan.** Nomor berikutnya di fase itu; nomor tidak dipakai ulang. Setiap task
memuat semua bagian wajib (lihat "Bentuk sebuah task" di `docs/roadmap/README.md`). Path yang
belum ada diberi tanda `(baru)`. Jalankan `pytest tests/test_docs.py -q` dan
`python scripts/check_hermes_refs.py --hermes ../hermes-ref` sebelum commit.

**Laporan akhir.** Daftar task baru dengan ukuran dan ketergantungannya, keputusan desain yang
diambil, dan pertanyaan yang masih terbuka.
