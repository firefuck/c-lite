# core: aturan kerja

Lapisan daun: nama produk, home, config, rahasia, profil, logging. Spesifikasi:
`docs/spesifikasi/core.md`.

Tes: `pytest tests/core -q`

## Aturan yang tidak boleh dilanggar

1. **Tidak mengimpor apa pun dari `clite` selain `clite.core` sendiri.** Dijaga
   `test_core_imports_nothing_from_the_rest_of_the_package`.
2. **Tidak ada `~/.clite` harfiah, di mana pun di repositori.** Pakai `get_home()` untuk path
   dan `display_home()` untuk teks yang dilihat pengguna.
3. **Tidak ada path turunan home di konstanta tingkat modul.** Hitung saat dipanggil.
4. **Nama produk hanya dieja di `brand.py`.** Kode lain membaca konstanta dari sana.
5. **Rahasia dibaca dengan `get_secret`, bukan `os.getenv` atau `os.environ`.**
6. **Config ditulis hanya lewat `atomic_config_update` dan pembungkusnya.**
7. **Kunci config baru wajib punya pembaca**, dan komentar di `config_defaults.py` yang
   menjelaskan nilai default-nya.
8. **Thread yang bekerja untuk sebuah sesi dimulai dengan `core.threads.start_thread`**
   (giliran, tick penjadwal, polling platform). `threading.Thread` polos kehilangan profil
   yang sedang aktif.

## Resep

### Menambah kunci config

1. Tambahkan ke `DEFAULT_CONFIG` (`config_defaults.py`) dengan komentar alasan default.
2. Baca di tempat pemakaiannya dengan `get_path(config, "a.b.c", default)`. Di dalam agent
   pakai `agent.config`; di tool pakai `ctx.setting("a.b.c")`.
3. Jangan menaikkan `_config_version`: kunci baru otomatis tergabung ke instalasi lama.
4. `python scripts/gen_docs.py`, lalu `pytest tests/test_architecture.py -q`. Tes itu gagal
   bila kunci tidak dibaca di mana pun.

### Mengganti nama atau struktur kunci yang sudah ada

1. Naikkan `CONFIG_VERSION`.
2. Tambahkan fungsi ke `MIGRATIONS[versi_lama]` di `config.py` yang mengubah dokumen mentah.
3. Tes di `tests/core/test_config.py` dengan file versi lama.

### Mendaftarkan rahasia baru

`register_secret(SecretSpec(NAMA, deskripsi, category=..., url=...))` di modul yang
memakainya. Alur setup menampilkan daftar ini, dan `secret_names()` memakainya: nama yang
terdaftar dibuang dari lingkungan perintah yang dijalankan agent dan nilainya diredaksi dari
apa yang dibaca model. Kredensial yang tidak didaftarkan tidak mendapat perlindungan itu.

## Jebakan

- `load_config()` mengembalikan salinan. Mengubahnya tidak mengubah apa pun.
- `load_env()` menulis ke `os.environ`. Tes mengembalikan `os.environ` setelah tiap tes
  (`tests/conftest.py`).
- `apply_profile_override` harus dipanggil sebelum modul lain membaca home. Entry point baru
  wajib memanggilnya pertama kali (lihat `cli/main.py` dan `rpc/entry.py`).
