# website: aturan kerja

    python scripts/build_site.py                 # tulis website/build/
    python scripts/build_site.py --check         # gagal bila ada halaman yang tidak bisa dibangun
    python scripts/gen_docs.py --target site     # tulis ulang halaman rujukan di sini
    python -m http.server -d website/build 8000  # pratinjau

Situs dokumentasi pengguna. Isinya untuk orang yang **memakai** C-lite, bukan yang mengubah
kodenya; dokumentasi pengembang tetap di `docs/`.

## Tata letak

| Path | Isi |
|---|---|
| `website/content/id/` | Halaman bahasa Indonesia, satu berkas per slug |
| `website/content/en/` | Halaman bahasa Inggris, slug yang persis sama |
| `website/static/` | Disalin apa adanya ke akar hasil bangun (stylesheet) |
| `website/build/` | Hasil bangun; tidak pernah disunting, dan tidak ikut git |

Pembangkitnya `scripts/build_site.py`, memakai pustaka standar saja. Alasannya tertulis di
docstring berkas itu: paket Python harus bisa dipasang tanpa Node, dan pekerjaan docs di CI
tidak boleh menuntut toolchain kedua.

## Aturan yang tidak boleh dilanggar

1. **Dua pohon bahasa harus punya daftar slug yang sama.** Tombol bahasa memetakan halaman ke
   `slug` yang sama di bahasa lain, dan tes memeriksa keduanya sama persis.
2. **Setiap halaman dimulai dengan satu heading `# `.** Judul itulah yang dipakai menu samping,
   jadi menu dan halaman tidak bisa berbeda.
3. **Halaman rujukan tidak pernah disunting dengan tangan.** `website/content/*/reference/`
   ditulis oleh `scripts/gen_docs.py` dari registry di kode; ubah kodenya, lalu jalankan
   skripnya. Tes membandingkan berkasnya dengan keluaran pembangkit.
4. **Pagar kode `bash` hanya boleh ada di `start/quickstart.md`.** Blok `bash` dijalankan apa
   adanya oleh `tests/test_website.py` terhadap provider `mock`, jadi setiap barisnya harus
   benar-benar jalan. Di halaman lain pakai `console` (transkrip terminal, dibaca saja) atau
   info string bahasa datanya (`yaml`, `json`, `markdown`, `text`).
5. **Tautan antar-halaman relatif dan berakhiran `.md`.** Pembangkit mengubahnya menjadi
   `.html`, dan `scripts/doc_refs.py` memeriksa bahwa berkas maupun anchor-nya ada. Jangan
   menautkan keluar dari `website/` ke `docs/`: halaman itu tidak ikut terbit — pakai URL
   GitHub absolut.
6. **Jangan mengklaim lebih dari yang sudah diverifikasi.** Kalau sesuatu belum pernah dicoba
   terhadap layanan sungguhan, tulis begitu, dan arahkan pembaca ke `docs/STATUS.md`.
7. **Perintah, path, dan keluarannya tidak diterjemahkan.** Nama program, subcommand, flag,
   path produk, dan keluaran perintah tetap sama di kedua bahasa. Yang ditulis dalam bahasa
   halamannya hanya prosa dan **teks contoh yang diketik pengguna** — prompt, nama profil,
   nama skill, nama berkas contoh. Tes membandingkan bentuk perintahnya (argumen berkutip
   dianggap contoh) supaya kedua halaman tetap menyuruh hal yang sama.

## Bahasa

Situs terbit dalam dua bahasa, dan keduanya setara: halaman baru ditulis di kedua pohon, bukan
salah satu lebih dulu. Prosa pengembang di `docs/` tetap berbahasa Indonesia; yang berbahasa
Inggris adalah halaman situs dan docstring di kode.
