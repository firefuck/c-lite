# cron: aturan kerja

Tugas agent terjadwal. Spesifikasi: `docs/spesifikasi/cron.md`.

Tes: `pytest tests/cron -q`

## Aturan yang tidak boleh dilanggar

1. **Majukan dulu, baru jalankan.** `mark_dispatched` harus dipanggil sebelum `run_job`.
   Urutan sebaliknya membuat job berjalan ganda setelah crash.
2. **Satu job gagal tidak boleh menghentikan tick.** Semua pengecualian di `run_job` ditangkap
   dan dicatat ke job itu.
3. **Run cron tidak punya pengguna.** Jangan memberi toolset cron tool yang bertanya
   (`clarify`) atau yang menjadwalkan (`cronjob`).
4. **Prompt job diperlakukan sebagai masukan tak tepercaya**: dipindai saat dibuat dan diubah.
5. **Penjadwal tidak mengimpor gateway.** Pengiriman adalah fungsi yang diteruskan pemanggil.
6. **Waktu disuntikkan.** Fungsi yang bergantung pada waktu menerima `now`. Tes tidak pernah
   tidur menunggu jadwal.

## Resep

### Menambah bidang pada job

1. Tambahkan parameter di `JobStore.create` dan, bila boleh diubah, ke `UPDATABLE_FIELDS`.
2. Pakai di `scheduler.run_job` atau `build_job_prompt`.
3. Buka di tool `cronjob` (`tools/builtin/cronjob.py`), di `clite cron add`, dan di kontrak
   RPC `cron.create` bila UI perlu mengaturnya.
4. Job lama tidak punya bidang itu: baca dengan `job.get(...)`.

### Menambah jenis jadwal

Tambahkan cabang di `parse_schedule` dan `next_run` (`schedule.py`), dengan baris baru di tes
`test_delay_interval_cron_and_timestamp_forms` dan `test_next_run_for_each_kind`.

## Jebakan

- `JobStore.list` didefinisikan paling akhir di kelas dengan sengaja: method bernama `list`
  menutupi builtin `list` di anotasi yang ditulis setelahnya.
- `get_job_store()` memberi satu store per home. Jangan menyimpannya di tingkat modul.
- Id job boleh disingkat menjadi awalan yang unik (`store.get`).
