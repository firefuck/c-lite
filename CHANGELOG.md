# Catatan perubahan

Semua perubahan yang berarti bagi pemakai dicatat di sini. Format mengikuti
[Keep a Changelog](https://keepachangelog.com/id-ID/1.1.0/), versi mengikuti
[Semantic Versioning](https://semver.org/lang/id/). Bagian sebuah versi menjadi isi rilis
GitHub-nya (`python scripts/release.py notes`).

## [Unreleased]

### Direncanakan (v1.0.1)
- Refactor arsitektur dan perapihan modul kode.

## [1.0.0] - 2026-10-13

Rilis versi 1.0.0 resmi menandai penyelesaian penuh 67/67 task pada roadmap pengembangan
(Fase 1 sampai Fase 6) secara 100% lengkap dan terverifikasi.

### Ditambahkan & Diselesaikan
- Inti agent stabil dan lengkap dengan plugin `claude-compat` bawaan.
- Dashboard web modern berbasis Vite + React 18 + TypeScript dengan server fallback.
- Seluruh 6 fase roadmap selesai: Fondasi, Inti Agent, CLI & TUI, Gateway, Desktop, dan Ekosistem.
- Pengujian menyeluruh pada suite Python (1.600+ tes), Node workspaces, dan lint/mypy bersih.

## [0.1.0] - 2026-10-07

Rilis pertama, berlisensi MIT. Distribusi `c-lite` diterbitkan sebagai wheel dan sdist
untuk GitHub Releases saja, tanpa PyPI; perintah dan paket Python tetap `clite`.
Tag `v0.1.0` dan rilis GitHub telah terbit; wheel terbit sudah dipasang dengan pipx dan diuji.

### Ditambahkan

- Inti agent: loop giliran berfase, system prompt yang stabil per sesi, kompresi konteks,
  memori bawaan, delegasi ke subagent, pemulihan galat, dan fallback provider.
- Profil provider untuk Anthropic, OpenAI, OpenRouter, Gemini, DeepSeek, Ollama, endpoint
  kustom, dan provider `mock` untuk mencoba tanpa kunci API.
- Tool terminal dengan gerbang persetujuan, file, `web_fetch`, memori, skill, daftar tugas,
  pencarian sesi, delegasi, penjadwalan, dan klien MCP.
- Skill berformat `SKILL.md`, termasuk pemasangan dari GitHub; plugin Python dengan hook
  siklus hidup; shell hook dari config.
- Antarmuka: REPL klasik, TUI (butuh Node 22), dashboard web, cangkang Electron, protokol
  JSON-RPC bersama, gateway pesan dengan adapter Telegram, dan penjadwal cron.
- Sesi di SQLite dengan pencarian teks penuh; profil terpisah penuh.
- Penulisan `config.yaml` mempertahankan komentar dan format.
- Dukungan Windows yang diuji di CI (kunci file, `cmd.exe` dan Git Bash, home di
  `%LOCALAPPDATA%`).

### Diketahui

- Panggilan ke API provider sungguhan dan Telegram sungguhan belum diverifikasi penuh;
  aplikasi desktop belum pernah dijalankan. Rinciannya di `docs/STATUS.md`.
- Belum ada sandbox: perintah yang lolos gerbang persetujuan berjalan dengan hak penuh
  pengguna.
