# state: aturan kerja

`SessionDB`: sesi dan pesan di SQLite. Spesifikasi: `docs/spesifikasi/state.md`.

Tes: `pytest tests/state -q`

## Aturan yang tidak boleh dilanggar

1. **Riwayat hanya bertambah.** Jangan menambah method yang mengubah atau menghapus isi pesan
   aktif. Tiga pengecualian yang ada (`replace_active_messages`, `deactivate_from`,
   `clear_provider_data`) masing-masing punya alasan tertulis di docstring-nya.
2. **Perubahan skema tidak boleh mematahkan database lama.** Kolom baru harus nullable atau
   punya default, dan didaftarkan di `COLUMN_ADDITIONS`. Menaikkan `SCHEMA_VERSION` hanya
   untuk mengubah data yang sudah ada, dengan SQL di `MIGRATIONS`.
3. **Semua akses lewat kunci `self._lock`.** Koneksi dipakai bersama antar-thread.
4. **Teks pengguna tidak pernah menjadi sintaks SQL atau FTS.** Pakai parameter dan
   `_fts_query`.
5. **Hanya mengimpor `core`.**

## Resep

### Menambah kunci pada pesan

1. Tambahkan kolom ke `SCHEMA_SQL` dan ke `COLUMN_ADDITIONS["messages"]` (`schema.py`).
2. Tulis di `_insert_message` dan baca di `_row_to_message` (`db.py`).
3. Bila kunci itu tidak boleh sampai ke provider, tambahkan ke `INTERNAL_MESSAGE_KEYS`
   (`providers/transports/base.py`) dan periksa `agent/messages.sanitize_for_api`.
4. Tes pulang-pergi, dan tes membuka database yang belum punya kolom itu (contoh:
   `test_a_database_from_before_a_column_existed_gains_it_on_open`).

### Menambah kolom pada sesi yang bisa diubah

Tambahkan ke `SCHEMA_SQL`, `COLUMN_ADDITIONS["sessions"]`, dan `UPDATABLE_SESSION_COLUMNS`.

## Jebakan

- `get_messages` mengembalikan `_row_id` dan `timestamp` di setiap pesan. Keduanya tidak boleh
  ditulis balik sebagai pesan baru.
- `append_message` memperbarui `last_activity_at`. Tes yang mengatur umur sesi harus
  melakukannya setelah menambah pesan.
- Trigger FTS berjalan pada `INSERT`, `DELETE`, dan `UPDATE` kolom terindeks saja.
