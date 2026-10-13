# C-lite

C-lite adalah agent AI pribadi dengan satu inti percakapan yang dilayani banyak antarmuka:
CLI, TUI, dashboard web, aplikasi desktop, dan gateway pesan. Arsitekturnya diturunkan dari
[Hermes Agent](https://github.com/NousResearch/hermes-agent) milik Nous Research.

**Status: v1.0.1.** Seluruh task roadmap awal selesai dan dijaga tes, tetapi sebagian belum pernah
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

Butuh Python 3.11 atau lebih baru; Node 22 hanya untuk `clite tui`. Distribusinya bernama
`c-lite` dengan lisensi MIT, sedangkan paket Python dan perintahnya tetap `clite`. Rilis
diterbitkan di [GitHub Releases](https://github.com/dragovics/clite/releases), bukan PyPI, dengan
wheel dan sdist terlampir:

```bash
gh release download v1.0.1 --repo dragovics/clite --pattern '*.whl' --dir dist
pipx install ./dist/c_lite-1.0.1-py3-none-any.whl
clite --version     # C-lite 1.0.1
clite setup         # pilih provider, simpan kunci, pilih model
clite doctor        # periksa instalasi
```

Tanpa pipx, pasang wheel yang sama dengan `pip install` di dalam virtualenv. Selama
repositorinya privat, unduh aset dengan akun GitHub yang punya akses: URL aset privat tidak bisa
dipasang secara anonim, dan login di browser tidak otomatis mengautentikasi pip atau pipx.

### Membuat rilis

1. `python scripts/release.py bump patch` (atau `minor`, `major`, `X.Y.Z`) menaikkan versi
   paket Python dan semua workspace Node sekaligus.
2. Pindahkan isi `## [Unreleased]` di [CHANGELOG.md](CHANGELOG.md) ke bagian versi baru;
   `python scripts/release.py check` memastikan versi dan catatannya cocok.
3. `scripts/run_tests.sh`, lalu `python scripts/release.py build` (alatnya:
   `python -m pip install 'build>=1.2,<2'`) membangun wheel dan sdist dan memeriksa isi wheel.
4. Commit, lalu `python scripts/release.py tag` dan dorong tag itu. Workflow
   `.github/workflows/release.yml` membangun ulang, menguji wheel di virtualenv bersih, dan
   menerbitkan rilis GitHub dengan wheel dan sdist terlampir.

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

Untuk dependensi pengembangan Node, jalankan `npm ci` di root. CI (`.github/workflows/ci.yml`)
menguji Python 3.11–3.13 dan Node 22; hook `pre-push` menjalankan pemeriksaan yang sama sebelum
setiap push (aktifkan dengan `git config core.hooksPath scripts/hooks`). Batas verifikasinya
tercatat di [docs/STATUS.md](docs/STATUS.md).

## Peta repositori

| Path | Isi |
|---|---|
| `src/clite/` | Paket Python: `core`, `state`, `providers`, `plugins`, `skills`, `tools`, `agent`, `cron`, `runtime`, `rpc`, `gateway`, `server`, `cli` |
| `src/clite/bundled/` | Profil provider, plugin, dan skill bawaan |
| `apps/tui/` | TUI (Ink dan React), dibundel ke `src/clite/tui_dist/` |
| `apps/web/` | Dashboard web (React dan Vite), dibangun ke `src/clite/server/static/` |
| `apps/desktop/` | Cangkang Electron yang memuat dashboard |
| `packages/shared/` | Klien protokol TypeScript (`@clite/shared`) yang dipakai TUI dan dashboard |
| `tests/` | Tes Python, termasuk penjaga arsitektur dan penjaga dokumen |
| `scripts/` | Pemeriksaan, pembangkit file turunan, dan penggantian nama proyek |
| `website/` | Situs dokumentasi pengguna (Indonesia dan Inggris), dibangun oleh `scripts/build_site.py` |
| `docs/` | Arsitektur, spesifikasi, roadmap, dan bedah Hermes. Mulai dari [docs/README.md](docs/README.md) |

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
