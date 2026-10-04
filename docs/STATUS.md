# Status pengerjaan C-lite

Checkpoint: 2026-10-04. Dokumen ini mencatat apa yang sudah ada, apa yang sudah diuji, dan apa
yang belum, supaya sesi berikutnya (manusia atau AI) bisa langsung melanjutkan.

## Sudah ada dan lulus tes

- **Backend Python** (`src/clite`): `core`, `state`, `providers`, `plugins`, `tools` (termasuk
  klien MCP stdio), `skills`, `agent`, `cron`, `runtime`, `cli`, `rpc`, `server` (dashboard
  statis), `gateway` (adapter `local` dan `telegram`). Pada pengujian terakhir: 554 tes lulus.
- **TypeScript**: `apps/shared` (klien protokol, 21 tes), `ui-tui` (TUI berbasis teks, 16 tes),
  `apps/desktop` (logika peluncur backend, 7 tes).
- **Bedah Hermes**: `docs/hermes/01` sampai `13`.

## Belum selesai

- Dokumen kerja untuk AI: `AGENTS.md` (root dan per area), `docs/arsitektur/`,
  `docs/spesifikasi/`, `docs/roadmap/`, `docs/prompts/`, `docs/hermes/99-peta-file.md`,
  `README.md` yang sebenarnya, `NOTICE.md`.
- Perapian scaffolding: `tui_dist/*.mjs` belum masuk `package-data`; `apps/desktop/README.md`;
  `scripts/run_tests.sh`; `scripts/rename_project.py`; tes untuk
  `scripts/gen_rpc_contracts.py --check`; paket `src/clite/acp` masih kosong.
- Kunci `DEFAULT_CONFIG` yang belum punya pembaca: `display.interface`,
  `memory.nudge_interval`, `hooks`, `sessions.auto_prune`, `sessions.retention_days`,
  `auxiliary.approval`. Harus diimplementasikan atau dihapus.

## Belum diverifikasi

- `apps/desktop/src/main.ts` dan `preload.ts`: ditulis tanpa Electron terpasang, belum pernah
  dijalankan.
- `npm install` di root belum pernah dijalankan (registry npm tidak terjangkau saat pembuatan).
  Tes TypeScript dijalankan langsung dengan `node --test test/*.test.ts` (Node 22) dan `tsc`.
- `pip install -e ".[dev]"` belum pernah dijalankan (PyPI tidak terjangkau saat pembuatan).
  Yang sudah dicoba: build wheel, lalu memasang wheel itu ke venv.
- Adapter Telegram hanya diuji terhadap Bot API tiruan; provider sungguhan hanya diuji terhadap
  server HTTP tiruan lokal; `GitHubSource` (pasang skill dari GitHub) belum diuji ke jaringan.

## Menjalankan tes

    pip install -e ".[dev]"
    pytest tests -q
    # per paket TypeScript (apps/shared, ui-tui, apps/desktop), setelah paket Python terpasang:
    node --test test/*.test.ts
