# Log kerja otonom

Aturan dari Bos (2026-10-08):
- Kerja otonom sampai **80%** roadmap. Itu SATU-SATUNYA alasan berhenti.
- Tes gagal → catat, lanjut task berikutnya. Jangan berhenti.
- Butuh kunci/akun/platform → SKIP, lanjut. Jangan berhenti.
- Task mentok → catat, lanjut. Jangan berhenti.
- Wiring/debug detail boleh menyusul.
- Patokan: scaffold task di docs/roadmap/ + docs/prompts/ + AGENTS.md.

## Progres

Baseline: 11/55 (20%). Sekarang main `4aa9b98`.

Fase 2 kelar (T1-T15 selesai semua kecuali T14 OAuth di-skip: butuh akun).

| Task | Status | Commit/PR |
|---|---|---|
| F2-T6 l1 | ✅ | PR #8 |
| F2-T6 l2/3 | ✅ | PR #9 |
| F2-T7 | ✅ | 5f0ae24 (merge lokal) |
| F2-T8 | ✅ | PR #11 |
| F2-T9 | ✅ | PR #12 |
| F2-T10 | ✅ | PR #13 |
| F2-T11 | ✅ | PR #14 |
| F2-T12 | ✅ | PR #15 |
| F2-T13 | ✅ | PR #16 |
| F2-T15 | ✅ | PR #17 |
| F2-T14 OAuth | ⬜ SKIP | butuh akun |
| F2-T3 pricing | ⬜ SKIP | dibuang atas permintaan Bos |
| F3-T1 REPL saat sibuk/multi-baris | ✅ | kerja di branch `f3-t1-repl` (HEAD `4aa9b98`), belum di-commit |

### F3-T1 — Input REPL klasik (saat sibuk, multi-baris, riwayat)

- **Antrean bersama dipindah ke runtime.** `TurnQueue`/`Turn` + konstanta `BUSY_*`/`SUBMIT_*`
  kini di `runtime/session.py`; `RpcSession` dan `GatewayRunner` memakainya. REPL klasik juga.
- **REPL jalan di dua jalur.** Dengan `prompt_toolkit` (extra `clite[cli]`): giliran di thread
  pekerja, thread utama terus membaca, keluaran streaming lewat `patch_stdout` supaya tidak
  merusak baris yang diketik, multi-baris (Alt+Enter atau `\`), tempel berkurung, Tab completion.
  Tanpa `prompt_toolkit`: perilaku klasik yang sama seperti sebelumnya (jalur `StdlibReader`).
- **Tes.** `tests/runtime/test_session_and_slash.py` (mode sibuk queue/steer/reject/interrupt
  lewat `ChatSession`), `tests/cli/test_cli.py` (multi-baris, paste, completion, fallback tanpa
  `prompt_toolkit`, routing saat sibuk). Regresi: RPC 24 hijau, gateway+RPC 51 hijau, CLI 43
  hijau tanpa `prompt_toolkit`, suite penuh 1213 hijau (1 gagal di `tests/server` sudah gagal di
  tree bersih juga — tes DNS/hostname lingkungan, bukan regresi).
- **Docs.** `docs/spesifikasi/cli.md` (baris "Mengetik saat agent bekerja" dan "Input
  multi-baris" → ✅, bagian REPL, tabel bagian, catatan Hermes), `runtime.md` (TurnQueue),
  `rpc.md`, `docs/roadmap/fase-3-cli-tui.md` (checklist F3-T1), `docs/referensi/peta-modul.md`
  (generated).

Berikutnya: Fase 3 (CLI/TUI), Fase 5 (desktop), Fase 6 (ekosistem).
Skip otomatis: F1-T2, F1-T3 (kunci), F2-T14 (akun), Fase 4 (platform).

## Rencana lanjutan (arahan Bos 2026-10-08)
1. Selesaikan Fase 3 (T1-T8) dulu.
2. Setelah itu TAMBAL yang belum hijau: F1-T2, F1-T3, F2-T1, F2-T2, F2-T14, F2-T3.
3. Tes dengan TOKEN dan API KEY BENERAN (Bos kasih kuncinya).
