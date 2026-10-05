# C-lite

C-lite adalah agent AI pribadi dengan satu inti percakapan yang dilayani banyak antarmuka:
CLI, TUI, dashboard web, aplikasi desktop, dan gateway pesan. Arsitekturnya diturunkan dari
[Hermes Agent](https://github.com/NousResearch/hermes-agent) milik Nous Research.

**Status: scaffolding.** Intinya berjalan dan dijaga tes, tetapi sebagian belum pernah
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

## Mencoba

Butuh Python 3.11 atau lebih baru. Node 22 hanya diperlukan untuk TUI.

```bash
git clone https://github.com/firefuck/c-lite && cd c-lite
pip install -e ".[dev]"

python -m clite chat -q "halo" --provider mock   # satu giliran tanpa kunci API
clite setup                                      # pilih provider, simpan kunci, pilih model
clite                                            # REPL klasik
clite tui                                        # antarmuka terminal (butuh Node)
clite dashboard                                  # dashboard web di browser
clite doctor                                     # periksa instalasi
```

`pip install` dari registry belum pernah dijalankan saat scaffolding ini dibuat; yang sudah
dicoba adalah membangun wheel lalu memasangnya. Lihat [docs/STATUS.md](docs/STATUS.md).

## Mengerjakan proyek ini dengan AI

Repositori ini disiapkan untuk dikerjakan sepenuhnya oleh AI, dengan Claude Fable 5.1 sebagai
sasaran utama.

1. Baca [docs/prompts/README.md](docs/prompts/README.md): cara menyiapkan Claude Code dan
   daftar prompt siap pakai.
2. Jalankan `/orientasi` sekali untuk memeriksa lingkungan.
3. Pilih task di [docs/roadmap/README.md](docs/roadmap/README.md), mulai dari fase 1, lalu
   `/kerjakan-task <nomor>` dan `/tinjau <nomor>`.

Aturan kerja untuk AI ada di [AGENTS.md](AGENTS.md) dan di `AGENTS.md` tiap direktori.
Sebagian besar aturan itu dijaga tes, sehingga pelanggaran menggagalkan suite.

## Peta repositori

| Path | Isi |
|---|---|
| `src/clite/` | Paket Python: `core`, `state`, `providers`, `plugins`, `skills`, `tools`, `agent`, `cron`, `runtime`, `rpc`, `gateway`, `server`, `cli` |
| `src/clite/bundled/` | Profil provider, plugin, dan skill bawaan |
| `apps/shared/` | Klien protokol TypeScript |
| `ui-tui/` | TUI |
| `apps/desktop/` | Cangkang Electron |
| `tests/` | Tes Python, termasuk penjaga arsitektur dan penjaga dokumen |
| `scripts/` | Pemeriksaan, pembangkit file turunan, dan penggantian nama proyek |
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

## Lisensi

MIT, lihat [LICENSE](LICENSE). Atribusi untuk Hermes Agent ada di [NOTICE.md](NOTICE.md).
