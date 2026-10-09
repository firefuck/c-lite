# Memasang

## Yang dibutuhkan

| | |
|---|---|
| Python | 3.11 atau lebih baru |
| Node.js | 22, hanya untuk TUI dan aplikasi desktop. REPL klasik, dashboard, gateway, dan cron tidak butuh Node |
| Sistem | Linux, macOS, atau Windows |

Distribusi bernama `c-lite`; paket Python dan perintahnya tetap `clite`. Rilisnya diterbitkan
lewat [GitHub Releases](https://github.com/dragovics/clite/releases), bukan PyPI.

## Dari aset rilis

Rilis `v0.1.0` sudah terbit. Unduh wheel-nya (repositori masih privat, jadi unduhan butuh akun
yang punya akses), lalu pasang dengan pipx atau di dalam virtualenv:

```console
$ gh release download v0.1.0 --repo dragovics/clite --pattern '*.whl' --dir dist
$ pipx install ./dist/c_lite-0.1.0-py3-none-any.whl
$ clite --version
C-lite 0.1.0
```

Tanpa pipx, ganti baris keduanya dengan `pip install ./dist/c_lite-0.1.0-py3-none-any.whl`
setelah mengaktifkan virtualenv.

## Dari source

```console
$ git clone https://github.com/dragovics/clite && cd clite
$ pip install -e ".[dev]"
$ python -m clite chat -q "halo" --provider mock
You said: halo
```

`--provider mock` menjawab tanpa kunci API, jadi baris terakhir berguna untuk memastikan
instalasinya hidup sebelum Anda memilih provider sungguhan.

## Setelah dipasang

```console
$ clite setup        # pilih provider, simpan kunci API, pilih model
$ clite doctor       # periksa instalasi
$ clite              # REPL klasik
```

`clite setup` berjalan bertahap: provider, kunci (diuji dengan satu panggilan sungguhan dan
ditolak bila salah), model dari provider itu, toolset, lalu opsi keselamatan dan Telegram.
Semuanya bisa dilewati dengan flag, jadi skrip non-interaktif menghasilkan config yang sama.

`clite doctor` memeriksa versi Python, home yang bisa ditulis, config, pencarian penuh SQLite,
provider yang terkonfigurasi, backend terminal, plugin aktif, shell hook yang menunggu
persetujuan, dan Node.js. Selama provider belum dipilih, satu baris itu yang dilaporkannya —
sisanya sudah hijau sejak pemasangan.

## Di mana datanya

Semua keadaan ada di satu direktori, `~/.clite`:

| Path | Isi |
|---|---|
| `config.yaml` | semua pengaturan |
| `.env` | kunci API dan rahasia lain, izin 0600 |
| `state.db` | sesi dan pesan (SQLite, dengan pencarian teks penuh) |
| `memories/` | memori jangka panjang dan profil pengguna |
| `skills/`, `plugins/` | skill dan plugin milik Anda |
| `logs/` | `agent.log` dan `errors.log` |

Direktori itu bisa dipindahkan dengan variabel lingkungan `CLITE_HOME`. Profil memberi Anda
beberapa home yang terpisah penuh — config, rahasia, memori, sesi, skill, dan plugin sendiri —
lihat `clite profile --help` dan [Konfigurasi](../guide/configuration.md).

Cadangkan sebelum mengubah banyak hal:

```console
$ clite backup create              # arsip home, tanpa rahasia
$ clite backup create --include-secrets   # termasuk .env, izin 0600
```

## Memperbarui dan mencopot

```console
$ clite update          # mengenali cara pemasangan (git, pipx, pip) dan memasang yang lebih baru
$ clite update --check  # hanya memeriksa
$ clite uninstall       # mencopot paket; --purge menghapus data home juga
```

## Menjalankan tanpa memasang

Selama berada di dalam checkout, semua perintah bisa dijalankan sebagai modul:

```console
$ python -m clite doctor
```

Itu berguna saat mengembangkan C-lite sendiri; untuk pemakaian sehari-hari, pasang paketnya
supaya perintah `clite` selalu ada di PATH.

## Kalau ada yang salah

| Gejala | Yang bisa dicoba |
|---|---|
| `clite: command not found` | Perintahnya dipasang di dalam virtualenv atau direktori Scripts pipx, yang mungkin belum ada di PATH |
| `clite doctor` menyebut config tidak valid | `clite config path` menunjukkan berkasnya; `clite config edit` membukanya di editor Anda. Config yang rusak tidak pernah ditimpa sendiri |
| Tidak ada provider | `clite setup`, atau taruh kunci di `.env` lalu pilih model dengan `clite model` |
| TUI menolak jalan | Node.js 22 belum terpasang. REPL klasik tetap jalan; `clite` tanpa argumen membukanya |
