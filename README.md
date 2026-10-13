# C-lite

C-lite adalah agent AI pribadi dengan satu inti percakapan yang dilayani banyak antarmuka:
CLI, TUI, dashboard web, aplikasi desktop, dan gateway pesan. Arsitekturnya diturunkan dari
[Hermes Agent](https://github.com/NousResearch/hermes-agent) milik Nous Research.

**Status: v1.0.0.** Seluruh task roadmap awal selesai dan dijaga tes, tetapi sebagian belum pernah
dijalankan terhadap hal yang sebenarnya (API provider asli, Telegram asli, Electron, Windows).
Daftar pastinya ada di [docs/STATUS.md](docs/STATUS.md). Ukurannya kira-kira dua persen dari
Hermes; yang ada di sini adalah fondasi dan peta kerja untuk menumbuhkan sisanya.

## Yang sudah ada

- **Inti agent**: loop giliran berfase, system prompt yang stabil per sesi (ramah cache
  prompt), kompresi konteks, memori bawaan, delegasi ke subagent, pemulihan galat dan
  fallback provider.
- **Provider**: profil deklaratif untuk Anthropic, OpenAI, OpenRouter, Gemini, DeepSeek,
  Ollama, endpoint kustom, dan provider `mock` untuk mencoba tanpa kunci.
- **Tool**: terminal dengan gerbang persetujuan, file (baca, tulis, patch, cari), `web_fetch`,
  memori, skill, daftar tugas, pencarian sesi, delegasi, penjadwalan, dan klien MCP.
- **Skill dan plugin**: format `SKILL.md` yang kompatibel dengan agentskills.io, plugin Python
  dengan hook siklus hidup, dan shell hook dari config.
- **Antarmuka**: REPL klasik, TUI (Node), dashboard web, cangkang Electron, protokol JSON-RPC
  bersama, gateway pesan dengan adapter Telegram, dan penjadwal cron.
- **Penyimpanan**: sesi di SQLite dengan pencarian teks penuh; profil terpisah penuh.

Daftar lengkap yang dihasilkan dari kode ada di
[docs/referensi/katalog.md](docs/referensi/katalog.md).

## Dokumentasi pengguna

Untuk yang memakai C-lite tanpa pernah membuka kodenya, ada situs terpisah dalam dua bahasa:
<https://dragovics.github.io/clite/>. Isinya pasang, mulai cepat, konfigurasi, tool, skill,
plugin, gateway, dan keamanan; halaman rujukannya dihasilkan dari kode oleh
`scripts/gen_docs.py`, dan situsnya dibangun ulang setiap rilis. Dokumentasi di `docs/`
tetap untuk yang mengubah kodenya.

## Memasang

Butuh Python 3.11 atau lebih baru. Node 22 hanya diperlukan untuk TUI. Distribusi bernama
`c-lite`, dengan lisensi MIT; paket Python dan perintah tetap `clite`. Tujuan penerbitan
adalah [GitHub Releases](https://github.com/dragovics/clite/releases), bukan PyPI.
**Rilis `v0.1.0` sudah terbit.** Wheel sudah diuji dengan pipx dan virtualenv:

```bash
pipx install ./dist/c_lite-0.1.0-py3-none-any.whl
clite --version     # C-lite 0.1.0
clite setup         # pilih provider, simpan kunci, pilih model
clite doctor        # periksa instalasi
```

Wheel tersebut dibuat dengan `python scripts/release.py build` (pasang alat build lewat
`python -m pip install 'build>=1.2,<2'`). Tanpa pipx, gunakan
`pip install ./dist/c_lite-0.1.0-py3-none-any.whl` di dalam virtualenv.
Pemasangan pipx lewat URL HTTP lokal juga sudah diuji; itu bukan bukti URL GitHub bekerja.
Unduh aset dengan akun GitHub yang punya akses ke repositori privat:

```bash
gh release download v0.1.0 --repo dragovics/clite --pattern '*.whl' --dir dist
pipx install ./dist/c_lite-0.1.0-py3-none-any.whl
```

Unduhan GitHub terautentikasi dan instalasi pipx telah diverifikasi. URL aset privat tidak bisa dipasang
secara anonim; login GitHub di browser tidak otomatis mengautentikasi pip/pipx.

Membuat rilis: naikkan versi berikutnya dengan `python scripts/release.py bump patch`
(atau `minor`/`major`), lalu isi bagian versinya di [CHANGELOG.md](CHANGELOG.md).
Untuk rilis pertama, pertahankan versi `0.1.0` yang sudah ada. Jalankan pemeriksaan dan build,
commit, lalu `python scripts/release.py tag` dan dorong tag hanya setelah mendapat izin.
Workflow `.github/workflows/release.yml` membangun wheel dan sdist,
mengujinya di virtualenv bersih, lalu menerbitkan rilis GitHub dengan keduanya terlampir.

## Mencoba dari source

```bash
git clone https://github.com/dragovics/clite && cd clite
pip install -e ".[dev]"

python -m clite chat -q "halo" --provider mock   # satu giliran tanpa kunci API
clite setup                                      # pilih provider, simpan kunci, pilih model
clite                                            # REPL klasik
clite tui                                        # antarmuka terminal (butuh Node)
clite dashboard                                  # dashboard web di browser
clite doctor                                     # periksa instalasi
```

Pemasangan dari registry dan tes sudah lulus di CI Linux pada Python 3.11–3.13 dan Node 22.
Untuk dependensi pengembangan Node, jalankan `npm ci` di root. Batas verifikasi lainnya
tercatat di [docs/STATUS.md](docs/STATUS.md).

## Peta repositori

| Path | Isi |
|---|---|
| `src/clite/` | Paket Python: `core`, `state`, `providers`, `plugins`, `skills`, `tools`, `agent`, `cron`, `runtime`, `rpc`, `gateway`, `server`, `cli` |
| `src/clite/bundled/` | Profil provider, plugin, dan skill bawaan |
| `apps/shared/` | Klien protokol TypeScript |
| `ui-tui/` | TUI |
| `web/` | Dashboard web (React) |
| `apps/desktop/` | Cangkang Electron |
| `tests/` | Tes Python, termasuk penjaga arsitektur dan penjaga dokumen |
| `scripts/` | Pemeriksaan, pembangkit file turunan, dan penggantian nama proyek |
| `website/` | Situs dokumentasi pengguna (Indonesia dan Inggris), dibangun oleh `scripts/build_site.py` |
| `docs/` | Arsitektur, spesifikasi, roadmap, prompt, dan bedah Hermes. Mulai dari [docs/README.md](docs/README.md) |

## Mengganti nama proyek

Nama "C-lite" dan `clite` bisa diganti di seluruh repositori dengan satu perintah:

```bash
python scripts/rename_project.py --name namabaru --display "Nama Baru" --dry-run
```

Buang `--dry-run` untuk menerapkannya, lalu ikuti langkah lanjutan yang dicetak skrip itu
(membuat ulang kontrak TypeScript, halaman referensi, dan bundle TUI, lalu mengurutkan ulang
import) sebelum menjalankan `scripts/run_tests.sh`. URL repositori di README tidak ikut
diganti.

## Berkontribusi

Mulai dari [CONTRIBUTING.md](CONTRIBUTING.md). Celah keamanan dilaporkan secara privat mengikuti
[SECURITY.md](SECURITY.md), dan semua yang terlibat mengikuti [kode etik](CODE_OF_CONDUCT.md).

## Lisensi

MIT, lihat [LICENSE](LICENSE). Atribusi untuk Hermes Agent ada di [NOTICE.md](NOTICE.md).
