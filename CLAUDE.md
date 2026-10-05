@AGENTS.md

## Khusus Claude Code

- Aturan tiap area ada di `AGENTS.md` direktorinya dan dimuat lewat `CLAUDE.md` di sampingnya
  saat Anda membaca file di direktori itu. Bila Anda akan mengubah sebuah area tanpa membaca
  filenya lebih dulu, baca `AGENTS.md` area itu.
- Alur kerja yang sering dipakai tersedia sebagai skill proyek: `/orientasi`,
  `/kerjakan-task <nomor>`, `/tinjau <nomor>`, `/perbaiki-bug <gejala>`, `/tambah-provider`,
  `/tambah-tool`, `/tambah-platform`, `/porting-dari-hermes`, `/verifikasi-lingkungan`,
  `/pecah-task <nomor>`. Isinya ada di `docs/prompts/`.
- Subagent `peninjau` meninjau diff di konteks yang bersih. Pakai sebelum menganggap sebuah
  task selesai.
- Saat memadatkan percakapan, pertahankan: nomor task yang sedang dikerjakan, daftar file yang
  sudah diubah, perintah pemeriksaan dan hasil terakhirnya, keputusan yang sudah diambil
  beserta alasannya, dan hal yang masih menunggu jawaban pemilik proyek.
