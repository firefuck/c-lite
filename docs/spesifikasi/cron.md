# Spesifikasi: cron

| | |
|---|---|
| Kode | `src/clite/cron/`, tool `src/clite/tools/builtin/cronjob.py`, CLI `src/clite/cli/subcommands/cron.py` |
| Tes | `tests/cron/` |
| Lapisan | 6. Boleh mengimpor `core`, `providers`, `skills`, `agent`. `scheduler.py` mengimpor `runtime.factory` di dalam fungsi |
| Bedah Hermes | [12-gateway-cron](../hermes/12-gateway-cron.md) |

## Tanggung jawab

Tugas agent terjadwal. Sebuah job adalah **prompt**, bukan perintah shell: ia dijalankan di
sesi baru tanpa ingatan percakapan yang membuatnya.

## Bagian-bagian

| File | Isi |
|---|---|
| `schedule.py` | Parse jadwal dan hitung waktu jalan berikutnya |
| `jobs.py` | `JobStore`: penyimpanan (`<home>/cron/jobs.json`) dan transisi state |
| `scheduler.py` | `tick`, `run_job`, `Scheduler` (ticker latar) |

## Jadwal

| Jenis | Contoh | Arti |
|---|---|---|
| `once` | `30m`, `2h`, `1d`, `2026-01-31T09:00` | Sekali: sekian lama dari sekarang, atau pada cap waktu ISO |
| `interval` | `every 30m`, `every 1d` | Berulang, minimal 60 detik |
| `cron` | `0 9 * * 1-5` | Lima bidang. Mendukung `*`, daftar, rentang, langkah, nama bulan dan hari |

Parser cron ditulis sendiri (tanpa `croniter`). Bila hari-dalam-bulan dan hari-dalam-minggu
sama-sama dibatasi, hari yang cocok dengan salah satunya berjalan, seperti cron klasik. Zona
waktu dari `timezone` di config, default zona sistem.

## Kontrak

- **Paling banyak sekali.** `next_run_at` dimajukan sebelum job dijalankan
  (`mark_dispatched`). Proses yang mati di tengah jalan tidak menyebabkan job dijalankan
  ulang: sebuah run bisa hilang, tidak pernah ganda.
- `tick()` menjalankan setiap job yang jatuh tempo, sekali. File kunci membuat tick yang
  tumpang-tindih tidak berbahaya: yang kedua langsung kembali. Kunci yang ditinggal tick yang
  crash diambil alih setelah dua jam.
- Setiap run adalah sesi baru di platform `cron` dengan toolset `clite-cron`: tanpa `clarify`
  (tidak ada pengguna untuk ditanya) dan tanpa `cronjob` (job tidak menjadwalkan job).
- Perintah berbahaya di dalam run mengikuti `approvals.cron_mode` (default tolak).
- Prompt job dipindai (`core.threats`) saat dibuat dan saat diubah: ia berjalan tanpa
  pengawasan dengan tool agent.
- Keluaran setiap run disimpan di `<home>/cron/output/<job>/<cap waktu>.md`.
- Pengiriman: `deliver: local` hanya menyimpan. `deliver: origin` mengirim balik ke chat asal
  job itu dibuat. `deliver: <platform>:<chat id>` mengirim ke chat tertentu. Dua yang terakhir
  hanya bekerja bila tick dijalankan oleh gateway yang platformnya tersambung. Jawaban yang
  diawali `[SILENT]` atau kosong tidak dikirim.
- Job yang gagal dicatat dan tidak menghentikan job lain dalam tick yang sama.
- Job yang tidak membuat kemajuan selama `cron.inactivity_timeout_seconds` diinterupsi.
- `repeat: N` mengakhiri job berulang setelah N kali. Job `once` selesai setelah satu kali.
- `cron.catch_up_missed: false` melewati run yang terlambat lebih dari lima menit (mesin mati),
  alih-alih menjalankannya saat hidup kembali.
- `skills` pada job dimuat ke dalam prompt run itu.
- `cron.enabled: false` mematikan semuanya.

Tick dipanggil oleh: gateway (ticker latar), `clite cron daemon`, atau timer luar yang
menjalankan `clite cron tick`.

## Status fitur

| Fitur | Status | Catatan |
|---|---|---|
| Tiga jenis jadwal, parser cron sendiri | ✅ | |
| Penyimpanan, jeda, lanjut, picu, ubah, hapus | ✅ | |
| Tick dengan kunci, paling banyak sekali | ✅ | |
| Tool `cronjob`, `clite cron`, `/cron` | ✅ | |
| Pengiriman ke chat asal | ✅ | Diuji dengan adapter `local` |
| Pengiriman ke `<platform>:<chat id>` | 🟡 | Jalurnya ada di `GatewayRunner.deliver`, belum punya tes; nilainya tidak divalidasi saat job dibuat |
| Home channel, pengiriman ke beberapa tujuan | ⬜ | F4-T9 |
| Skrip pra-jalan (data dikumpulkan skrip, lalu diberikan ke agent) | ⬜ | Hermes: `cron/scheduler_script.py`. F4-T9 |
| Riwayat eksekusi dan antrean pengiriman ulang | ⬜ | F4-T9 |
| Kunci file di Windows | ⬜ | `fcntl` saja: F1-T5 |

## Yang sengaja berbeda dari Hermes

- **Parser cron sendiri**, tanpa ketergantungan.
- **Satu file JSON** untuk job. Hermes juga JSON, tetapi dengan lapisan pelindung siklus hidup,
  insiden, dan blueprint yang tidak ada di sini.
- **Pengiriman lewat callback.** `tick(deliver=...)` menerima fungsi; penjadwal tidak tahu apa
  itu gateway.

## Celah yang diketahui

- Job dijalankan berurutan dalam satu tick. Job yang lama menunda job berikutnya.
- Tidak ada batas jumlah job atau kuota per pengguna.
