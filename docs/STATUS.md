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
| Tes Python (`pytest tests`) | 694 lulus |
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
- **Penggantian nama.** `scripts/rename_project.py` dijalankan pada salinan repositori di
  setiap putaran suite: tidak ada ejaan nama lama yang tertinggal, program hasil ganti nama
  berjalan, dan bisa diganti nama lagi.
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
| `.github/workflows/ci.yml` | Terpicu di setiap push ke `main`, tetapi belum satu langkah pun berjalan: GitHub menolak semua job dengan pesan "account is locked due to a billing issue". File workflow-nya terurai (keempat job muncul); isinya belum teruji. Kunci akun itu hanya bisa dibuka pemilik akun | F1-T1 |
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
| Model atau harness selain Claude Code | Belum pernah ada yang mengerjakan repositori ini. Panduan peralihannya disusun dari isi repositori, belum dari sesi nyata ([PANDUAN-MODEL-LAIN.md](PANDUAN-MODEL-LAIN.md)) | Coba dengan satu task S |
| Skill dan subagent Claude Code di `.claude/` | Ditulis mengikuti dokumentasi Claude Code; belum pernah dipanggil di Claude Code. Bila `/orientasi` tidak dikenali, tempel bagian "Prompt" dari file di `docs/prompts/` | Coba dengan `/orientasi` |

Yang sudah teramati dari integrasi Claude Code, di sesi cloud tempat scaffolding ini dibuat
(Claude Code 2.1.289 terpasang di sana):

- `CLAUDE.md` di root dimuat bersama `AGENTS.md` yang diimpornya, dan `CLAUDE.md` sebuah
  direktori ikut dimuat saat file di direktori itu dibaca.
- Subagent `peninjau` dikenali, dengan nama, deskripsi, dan daftar tool yang benar.
- `claude --help` versi itu memuat `--model` dengan alias `fable`, `--effort` dengan lima
  tingkatnya, dan `--permission-mode plan`, sesuai yang ditulis di `docs/prompts/README.md`.

Kesepuluh skill di `.claude/skills/` sengaja disembunyikan dari model
(`disable-model-invocation`), jadi pemuatannya tidak bisa diamati dari sesi itu. Itu sebabnya
skill tetap ada di tabel di atas.

Hal lain yang perlu diketahui:

- **Beban dan skala belum diuji.** Tidak ada tes untuk sesi yang sangat panjang, banyak sesi
  gateway bersamaan, atau database yang besar.
- **Bedah Hermes** (`docs/hermes/`) ditulis dari membaca kode pada satu commit. Keberadaan
  setiap file yang dirujuk sudah diperiksa mesin; uraian perilakunya tidak diperiksa ulang
  satu per satu.
- **Ukuran task di roadmap adalah perkiraan.**

## Tinjauan pihak kedua

Pada 5 Oktober 2026 tiga peninjau independen (subagent yang tidak melihat proses pembuatan)
dijalankan. **Ketiganya terhenti oleh batas pemakaian sebelum menulis laporan.** Yang bisa
diselamatkan hanya percobaan peninjau keamanan:

| Tinjauan | Hasil |
|---|---|
| Gerbang persetujuan perintah | Ditemukan cara murah melewati dua janji: larangan mutlak (`rm -rf "$HOME"`, `rm -rf '/'`, `rm --recursive --force /`) dan pertanyaan untuk perintah yang menjangkau pengaturan agent (glob seperti `~/.clite/.e*`, `~//.clite`, CLI lewat path absolut). Semuanya diperbaiki dan dijaga tes. Sisa yang tidak terbaca gerbang didaftar di [celah yang diketahui](arsitektur/06-keamanan.md#celah-yang-diketahui) |
| Pemeriksa alamat `web_fetch` | Bertahan terhadap bentuk alamat yang dicoba (IPv4 terpetakan ke IPv6, alamat numerik) |
| Penjaga file | Saat memperbaiki gerbang di atas ditemukan dua celah lagi dan ditutup: `.env` profil lain bisa dibaca, dan `gateway/pairing.json` bisa ditulis |
| Kredensial dan redaksi, pemindai teks prompt, plugin dan shell hook, server, otorisasi gateway | **Belum ditinjau pihak kedua** |
| File instruksi (`AGENTS.md`, prompt, skill) terhadap kode | **Tidak ada laporan** |
| Uji petik uraian di `docs/hermes/` terhadap kode Hermes | **Tidak ada laporan** |

Mengulang ketiga tinjauan itu sampai selesai adalah pekerjaan pertama yang layak dilakukan
sebelum pagar keamanan diandalkan.

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
| 5 Oktober 2026 | Wheel dibangun dan dipasang ke lingkungan virtual bersih. Dari sana: `clite --version`, `clite doctor`, satu giliran dengan provider `mock`, `clite tui --help`, satu giliran lewat TUI, daftar plugin dan skill bawaan, dan `clite serve` (file dashboard, pemeriksaan token, satu giliran lewat WebSocket). Dependensi diambil dari paket sistem dan `websockets` dari clone, bukan dari PyPI | Linux, Python 3.13, Node 22.22 |
| 5 Oktober 2026 | `scripts/rename_project.py` pada salinan repositori, diikuti langkah lanjutan yang dicetaknya: `scripts/run_tests.sh` lulus seluruhnya dan program hasil ganti nama berjalan. Yang tersisa dari nama lama hanya URL repositori di README | Linux, Python 3.13, Node 22.22 |
| 5 Oktober 2026 | Workflow CI terpicu di GitHub pada setiap push; semua job ditolak sebelum berjalan karena akun terkunci masalah penagihan | GitHub Actions |

Setiap task yang memverifikasi sesuatu menambah baris di tabel ini dan memindahkan butirnya
dari "belum diverifikasi".
