# Kebijakan keamanan

C-lite menjalankan perintah, membaca dan menulis berkas, dan memegang kunci API atas nama
penggunanya. Celah di sini berarti seseorang bisa membuat agent melakukan sesuatu yang tidak
dikehendaki pemiliknya, jadi laporan keamanan diperlakukan lebih dulu dari pekerjaan lain.

## Versi yang didukung

| Versi | Didukung |
|---|---|
| 1.0.x (cabang `main`) | Ya |
| Di bawah 1.0 | Tidak |

Perbaikan keamanan masuk ke `main` dan ke rilis berikutnya. Tidak ada backport ke versi lama.

## Melaporkan celah

**Jangan buka issue publik untuk celah keamanan.**

Laporkan secara privat lewat tab **Security → Report a vulnerability** di repositori GitHub
proyek ini (fitur *private vulnerability reporting*). Bila tombol itu tidak ada, hubungi pemilik
repositori (`@dragovics`) lewat GitHub dan minta saluran privat sebelum mengirim rincian.

Sertakan:

- versi atau commit yang diuji, sistem operasi, dan provider yang dipakai;
- langkah untuk mereproduksi, sekecil mungkin, beserta config yang relevan (tanpa kunci asli);
- apa yang bisa dicapai penyerang, dan dari posisi mana (teks yang dibaca model, berkas di
  proyek, pesan dari platform chat, halaman web, plugin, dan seterusnya).

Pemilik proyek akan mengonfirmasi laporan, menilai dampaknya, dan memberi tahu pelapor saat
perbaikannya terbit. Pelapor disebut di catatan rilis bila menginginkannya.

## Yang sudah diketahui

Model ancaman, pagar yang ada, dan celah yang sudah diketahui ditulis di
[docs/arsitektur/06-keamanan.md](docs/arsitektur/06-keamanan.md). Hal yang sudah tercantum di
bagian "Celah yang diketahui" di sana bukan temuan baru, tetapi cara melewatinya yang lebih
murah dari yang tertulis tetap layak dilaporkan.

Yang terpenting untuk dipahami pemakai: backend terminal bawaan (`local`) **tidak
bersandbox**. Perintah yang lolos gerbang persetujuan berjalan dengan hak penuh pengguna;
isolasi hanya ada bila backend `docker` dipilih.

## Untuk kontributor

Aturan keamanan untuk kode baru (rahasia, kode dari luar, teks dari luar yang masuk prompt,
keputusan yang gagal ke "tidak") ada di `AGENTS.md` dan
[docs/arsitektur/06-keamanan.md](docs/arsitektur/06-keamanan.md). Perubahan yang menyentuh
gerbang persetujuan, penjaga berkas, redaksi, atau autentikasi server butuh tes yang
membuktikan serangannya gagal.
