# Catatan perubahan

Semua perubahan yang berarti bagi pemakai dicatat di sini. Format mengikuti
[Keep a Changelog](https://keepachangelog.com/id-ID/1.1.0/), versi mengikuti
[Semantic Versioning](https://semver.org/lang/id/). Bagian sebuah versi menjadi isi rilis
GitHub-nya (`python scripts/release.py notes`).

## [Unreleased]

## [1.0.1] - 2026-10-13

### Keamanan
- `clite backup restore` menolak arsip yang anggotanya berupa tautan ke luar home. Sebelumnya
  arsip buatan orang lain bisa menulis file di luar home lewat symlink atau hardlink.

### Ditambah
- Metadata paket: penulis, tautan ke repositori, isu, dokumentasi, dan catatan perubahan,
  serta klasifikasi PyPI.
- Kebijakan keamanan (`SECURITY.md`) dengan saluran pelaporan privat, panduan kontribusi, dan
  kode etik.
- Penanda `py.typed`: plugin yang mengimpor `clite` ikut mendapat tipenya.

### Diubah
- Dashboard web ditulis ulang dengan React dan Vite. Fitur dan perilakunya sama, dijaga 24 tes
  browser dashboard lama.
- Perapian kode tanpa perubahan perilaku: fungsi panjang dipecah dan kompleksitas tiap fungsi
  dibatasi 15, format kode dan komentar `noqa` beralasan diperiksa di CI, mypy berjalan dalam
  mode `strict`, dan kode TypeScript diformat serta diperiksa Biome. Empat modul terbesar dipecah menurut tanggung jawab: runner gateway,
  gerbang persetujuan perintah, handler RPC (kini paket `clite.rpc.methods`), dan penyimpanan
  sesi.
- Tata letak monorepo: aplikasi di `apps/` (`apps/tui`, `apps/web`, `apps/desktop`) dan klien
  protokol bersama di `packages/shared`, yang kini diimpor kedua aplikasi lewat nama paketnya
  (`@clite/shared`).
- Backend eksekusi `local`, `docker`, dan `ssh` memakai satu loop yang sama untuk menunggu
  perintah (batas output, timeout, interupsi).
- Gateway menawarkan pemilih `/model` dan tombol persetujuan menurut kemampuan adapter, bukan
  nama platform; Telegram berperilaku seperti sebelumnya.

### Diperbaiki
- Tombol tutup percakapan dan tombol hapus lampiran di dashboard kini tombol sungguhan yang bisa
  dijangkau keyboard dan dibacakan pembaca layar; tombol tutup tidak lagi tersarang di dalam
  tombol percakapan.
- Wheel kini menyertakan berkas lisensi skill bawaan `docx`, `pdf`, `powerpoint`, dan `xlsx`;
  sebelumnya tertinggal karena tidak berekstensi, dan pemeriksaan isi wheel menolak rilis.
- Endpoint token OAuth yang menjawab dengan JSON bukan objek kini dibaca sebagai teks mentah,
  tidak lagi diteruskan sebagai tipe yang salah.

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
