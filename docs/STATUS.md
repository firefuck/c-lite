# Status pengerjaan C-lite

Checkpoint: 2026-10-05. Dokumen ini mencatat apa yang sudah ada, apa yang sudah diuji, dan apa
yang belum, supaya sesi berikutnya (manusia atau AI) bisa langsung melanjutkan.

## Sudah ada dan lulus pemeriksaan

- **Backend Python** (`src/clite`): `core`, `state`, `providers`, `plugins` (termasuk shell
  hooks), `tools` (termasuk klien MCP stdio dan persetujuan `smart`), `skills`, `agent`,
  `cron`, `runtime`, `cli`, `rpc`, `server` (dashboard statis), `gateway` (adapter `local`
  dan `telegram`). 612 tes lulus, `ruff check` bersih, `mypy` bersih.
- **TypeScript**: `apps/shared` (klien protokol, 21 tes), `ui-tui` (TUI berbasis teks, 18
  tes), `apps/desktop` (logika peluncur backend, 7 tes). `tsc --noEmit` bersih untuk
  `apps/shared` dan `ui-tui`.
- **Penjaga arsitektur** (`tests/test_architecture.py`): arah import antar-lapisan, setiap
  kunci `DEFAULT_CONFIG` punya pembaca, kontrak TypeScript sama dengan kontrak Python, bundle
  TUI di dalam paket sesuai dengan source-nya.
- **Skrip**: `scripts/run_tests.sh` (semua pemeriksaan), `scripts/rename_project.py` (sudah
  dicoba dua kali berturut-turut pada salinan repositori, seluruh tes lulus setelahnya),
  `scripts/gen_rpc_contracts.py`.
- **Bedah Hermes**: `docs/hermes/01` sampai `13`.

## Belum selesai

- Dokumen kerja untuk AI: `AGENTS.md` (root dan per area), `docs/arsitektur/`,
  `docs/spesifikasi/`, `docs/roadmap/`, `docs/prompts/`, `docs/hermes/99-peta-file.md`,
  `README.md` yang sebenarnya, `NOTICE.md`.
- Server ACP (`src/clite/acp`) baru berupa paket kosong berisi penjelasan.

## Belum diverifikasi

- `apps/desktop/src/main.ts` dan `preload.ts`: ditulis tanpa Electron terpasang, belum pernah
  dijalankan. Lihat `apps/desktop/README.md`.
- `npm install` di root belum pernah dijalankan (registry npm tidak terjangkau saat
  pembuatan). Tes TypeScript dijalankan langsung dengan `node --test` (Node 22) memakai
  TypeScript 6.0, esbuild 0.28 dan `@types/node` 26 yang sudah terpasang di mesin pembuatan.
- `pip install -e ".[dev]"` belum pernah dijalankan (PyPI tidak terjangkau saat pembuatan).
  Yang sudah dicoba: build wheel, lalu memasang wheel itu ke venv.
- `.github/workflows/ci.yml` belum pernah berjalan di GitHub Actions.
- Adapter Telegram hanya diuji terhadap Bot API tiruan; provider sungguhan hanya diuji
  terhadap server HTTP tiruan lokal; `GitHubSource` (pasang skill dari GitHub) belum diuji ke
  jaringan.

## Menjalankan pemeriksaan

    pip install -e ".[dev]"
    npm install                 # opsional: untuk type check TypeScript
    scripts/run_tests.sh        # lint, mypy, tes Python, tes TypeScript

## Checkpoint 5 Oktober 2026, 03.30 WIB (pekerjaan terhenti di sini)

Sudah ditulis sejak checkpoint sebelumnya: `docs/arsitektur/` (lengkap, 8 dokumen),
`docs/hermes/99-peta-file.md`, `docs/roadmap/README.md` dan `docs/roadmap/fase-1-fondasi.md`,
`tests/test_docs.py`, `scripts/doc_refs.py`, `scripts/check_hermes_refs.py`, empat penjaga baru
di `tests/test_architecture.py`, dan pengerasan keamanan (redirect `web_fetch`, perintah yang
menjangkau pengaturan agent sendiri, baca dan redaksi kredensial di tool file, kunci provider
dari shell, pemindaian skill proyek, pemeriksaan origin dan host di server).

Yang tersisa, berurutan:

1. Roadmap fase 2 sampai 6 (lima file `fase-*.md`; nomor dan judul task sudah ada di indeks
   roadmap).
2. `docs/prompts/` (README dan prompt siap pakai).
3. `AGENTS.md` di root, `CLAUDE.md` di root dan di samping setiap `AGENTS.md`, `README.md`,
   `NOTICE.md`, peta dokumen di folder `docs`.
4. Tulis ulang halaman ini (angka tes, daftar belum diverifikasi), lalu hapus syarat sementara
   di awal `tests/test_docs.py` dan buat seluruh tesnya lulus.
5. Verifikasi akhir (`scripts/run_tests.sh`), bangun wheel, kirim.
