# website

Situs dokumentasi pengguna C-lite: pasang, mulai cepat, konfigurasi, tool, skill, plugin,
gateway, keamanan, dan halaman rujukan yang dihasilkan dari kode. Isinya untuk orang yang
memakai C-lite; dokumentasi untuk orang yang mengubah kodenya ada di `docs/`.

    python scripts/build_site.py                 # bangun ke website/build/
    python scripts/build_site.py --check         # periksa tanpa menulis
    python scripts/gen_docs.py --target site     # tulis ulang halaman rujukan
    python -m http.server -d website/build 8000  # pratinjau di localhost:8000

Situsnya diterbitkan ke GitHub Pages oleh `.github/workflows/docs.yml` setiap kali ada rilis;
alamatnya <https://dragovics.github.io/clite/>.

## Tata letak

| Path | Isi |
|---|---|
| `website/content/id/`, `website/content/en/` | Satu berkas Markdown per halaman, slug yang sama di kedua bahasa |
| `website/content/*/reference/` | **Dihasilkan** `scripts/gen_docs.py`; jangan disunting dengan tangan |
| `website/static/` | Stylesheet, disalin apa adanya ke akar hasil bangun |
| `website/build/` | Hasil bangun, tidak ikut git |

Pembangkit dan aturan penulisannya ada di `scripts/build_site.py` dan `website/AGENTS.md`.
Ringkasnya: dua pohon bahasa harus punya daftar slug yang sama, pagar `bash` hanya di halaman
mulai cepat (blok itu dijalankan oleh tes), dan halaman rujukan selalu datang dari kode.
