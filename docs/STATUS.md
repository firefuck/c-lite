# Status

Diperbarui 5 Oktober 2026. Halaman ini memisahkan tiga hal yang mudah tertukar: apa yang
**dijaga tes**, apa yang **ditulis tetapi belum pernah bertemu hal yang sebenarnya**, dan apa
yang **belum ada**.

## Dijaga tes

Dijalankan di mesin pembuatan: Linux, Python 3.13, Node 22.22.

| Pemeriksaan | Hasil |
|---|---|
| `ruff check src tests scripts` | Bersih |
| `mypy` (159 file sumber) | Bersih |
| Tes Python (`pytest tests`) | 662 lulus |
| Tes TypeScript `apps/shared` | 21 lulus; `tsc --noEmit` bersih |
| Tes TypeScript `ui-tui` | 18 lulus; `tsc --noEmit` bersih |
| Tes TypeScript `apps/desktop` | 7 lulus; type check dilewati (Electron tidak terpasang) |
| Rujukan ke file Hermes di semua dokumen | Semuanya ada di clone pada commit rujukan (skrip pemeriksanya ada di bagian "Menjalankan pemeriksaan") |

Yang tercakup tes Python itu, selain perilaku tiap modul:

- **Ujung jauh ditiru dengan server sungguhan, bukan tambalan.** Provider diuji terhadap server
  HTTP lokal, Telegram terhadap Bot API tiruan, MCP terhadap proses server (termasuk server
  dari SDK MCP resmi), dashboard di Chromium lewat Playwright. Di mesin tanpa Playwright atau
  SDK MCP, tes itu dilewati, tidak gagal.
- **Bentuk kode.** Arah import antar-lapisan, pembaca untuk setiap kunci config, tidak ada
  nama vendor di luar profilnya, nama direktori home hanya dieja di satu tempat, pembacaan
  variabel lingkungan hanya di file yang terdaftar, tidak ada `print` di luar CLI.
- **File turunan.** Kontrak TypeScript, halaman referensi, dan bundle TUI sama dengan
  sumbernya.
- **Dokumen.** Tautan, path, nama modul, nama tes, dan nomor task yang disebut dokumen
  semuanya ada.

Spesifikasi tiap modul (`docs/spesifikasi/`) menandai fitur yang dijaga tes dengan ✅.

## Ditulis, belum diverifikasi

Semua butir ini punya kode, dan sebagian punya tes terhadap tiruan, tetapi belum pernah
dijalankan terhadap hal yang sebenarnya. Anggap belum berfungsi sampai terbukti.

| Hal | Keadaan | Task |
|---|---|---|
| `pip install -e ".[dev]"` dari PyPI | Belum pernah dijalankan (registry tidak terjangkau saat pembuatan). Yang sudah dicoba: membangun wheel dan memasangnya ke lingkungan virtual | F1-T1 |
| `npm install` dan skrip `npm` di root | Belum pernah dijalankan; `package-lock.json` belum ada. Tes TypeScript dijalankan langsung dengan `node --test` memakai TypeScript 6.0, esbuild 0.28, dan `@types/node` 26 yang sudah terpasang | F1-T1 |
| `.github/workflows/ci.yml` | Belum pernah berjalan di GitHub Actions | F1-T1 |
| Panggilan ke provider sungguhan | Belum pernah. Transport `anthropic_messages` dan `chat_completions` hanya diuji terhadap server tiruan. Ini termasuk pemutaran ulang blok penalaran bertanda tangan pada model Claude generasi 5, yang aturannya diambil dari dokumentasi, bukan dari pengamatan | F1-T2 |
| Teks penalaran model generasi 5 (`thinking.display`) | Belum diterapkan; `display.show_reasoning` kemungkinan tidak menampilkan apa pun pada model itu | F1-T2 |
| Persetujuan `smart` dengan model sungguhan | Hanya diuji dengan model berskrip | F1-T2 |
| Adapter Telegram | Hanya terhadap Bot API tiruan | F1-T3 |
| Pengiriman cron ke `<platform>:<chat id>` | Jalurnya ada, belum punya tes | F1-T3 |
| Pasang skill dari GitHub | Belum pernah diuji ke jaringan | F1-T4 |
| Windows | Belum pernah dijalankan. Kunci file memori dan penyimpanan job tidak mengunci di sana | F1-T5 |
| macOS | Belum pernah dijalankan | F1-T1 |
| Plugin lewat entry point pip | Jalur muatnya ada; belum diuji dengan paket yang benar-benar terpasang | F6-T5 |
| Cangkang Electron (`apps/desktop/src/main.ts`, `preload.ts`, `build.mjs`) | Ditulis tanpa Electron terpasang; belum pernah dijalankan | F5-T1 |
| Skill dan subagent Claude Code di `.claude/`, dan pemuatan `CLAUDE.md` per direktori | Ditulis mengikuti dokumentasi Claude Code; belum pernah dimuat oleh Claude Code | Coba dengan `/orientasi` |

Hal lain yang perlu diketahui:

- **Beban dan skala belum diuji.** Tidak ada tes untuk sesi yang sangat panjang, banyak sesi
  gateway bersamaan, atau database yang besar.
- **Bedah Hermes** (`docs/hermes/`) ditulis dari membaca kode pada satu commit. Keberadaan
  setiap file yang dirujuk sudah diperiksa mesin; uraian perilakunya tidak diperiksa ulang
  satu per satu.
- **Ukuran task di roadmap adalah perkiraan.**

## Belum ada

Yang ada di Hermes dan belum ada di sini didaftar di
[arsitektur/07-beda-dengan-hermes.md](arsitektur/07-beda-dengan-hermes.md#yang-belum-dibawa),
dan setiap butirnya punya task di [roadmap](roadmap/README.md). Yang paling terasa bagi
pemakaian harian: pencarian web, backend terminal bersandbox, render Markdown, TUI layar
penuh, dan platform pesan selain Telegram.

Celah keamanan yang diketahui didaftar tersendiri di
[arsitektur/06-keamanan.md](arsitektur/06-keamanan.md#celah-yang-diketahui). Yang terpenting:
**tidak ada sandbox**. Perintah yang lolos gerbang persetujuan berjalan dengan hak penuh
pengguna.

## Menjalankan pemeriksaan

```bash
pip install -e ".[dev]"
npm install                                                  # opsional: type check dan build TypeScript
scripts/run_tests.sh                                         # lint, mypy, tes Python, tes TypeScript
python scripts/check_hermes_refs.py --hermes ../hermes-ref   # butuh clone Hermes
```

## Catatan verifikasi

| Tanggal | Yang diverifikasi | Di mana |
|---|---|---|
| 5 Oktober 2026 | Seluruh tabel "Dijaga tes" di atas | Linux, Python 3.13, Node 22.22 |
| 5 Oktober 2026 | Wheel dibangun dan dipasang ke lingkungan virtual bersih; dari sana `clite --version`, `clite doctor`, satu giliran dengan provider `mock`, `clite tui --help`, dan satu giliran lewat TUI | Linux, Python 3.13, Node 22.22 |
| 5 Oktober 2026 | `scripts/rename_project.py` pada salinan repositori: tidak ada nama lama yang tersisa, dan seluruh tes Python lulus setelah langkah lanjutannya | Linux, Python 3.13 |

Setiap task yang memverifikasi sesuatu menambah baris di tabel ini dan memindahkan butirnya
dari "belum diverifikasi".
