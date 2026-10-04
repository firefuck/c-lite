# Spesifikasi: state

| | |
|---|---|
| Kode | `src/clite/state/` |
| Tes | `tests/state/` |
| Lapisan | 1. Boleh mengimpor `core` saja |
| Bedah Hermes | [11-state-sesi-memori](../hermes/11-state-sesi-memori.md) |

## Tanggung jawab

Penyimpanan sesi dan pesan yang tahan lama: satu file SQLite per profil
(`<home>/state.db`) dengan pencarian teks penuh.

## Skema

| Tabel | Isi |
|---|---|
| `sessions` | Satu baris per sesi: sumber (platform), model, system prompt, induk, waktu, penghitung token, judul, bendera `archived` / `pinned` / `hidden` |
| `messages` | Pesan dalam bentuk internal. Kolom `active` dan `compacted` menandai baris yang diarsipkan kompresi |
| `messages_fts` | Indeks FTS5 atas `content`, `tool_name`, `tool_calls`, dijaga sinkron oleh trigger |
| `state_meta` | Pasangan kunci-nilai (misalnya waktu auto-prune terakhir) |
| `schema_version` | Versi skema |

Kunci pesan yang disimpan: `role`, `content` (string atau JSON), `tool_calls`,
`tool_call_id`, `name`, `reasoning`, `provider_data`, `turn_context`, `finish_reason`,
`display_kind`, `is_summary`, `timestamp`. Kunci lain dibuang saat menulis.

## Kontrak

- Pesan tahan lama begitu `append_message` kembali.
- **Riwayat hanya bertambah.** Satu-satunya penulisan ulang adalah kompaksi
  (`replace_active_messages`): baris lama menjadi `active=0, compacted=1` di sesi yang sama dan
  tetap bisa dicari. `deactivate_from` (dipakai `/undo`) menonaktifkan dari satu baris ke
  belakang tanpa menghapus. `clear_provider_data` hanya menghapus data putar ulang.
- Pesan pulang-pergi dalam bentuk internal, termasuk konten berstruktur.
- Id sesi unik dan bisa diurutkan (cap waktu UTC plus akhiran acak).
- `create_session` idempoten.
- Judul unik: bentrokan mendapat akhiran angka.
- `find_session` menerima id persis, judul persis, atau awalan id yang unik.
- `list_sessions` menyembunyikan sesi anak, tersembunyi, dan terarsip secara default.
- Pencarian memperlakukan masukan pengguna sebagai teks biasa (setiap kata dikutip), jadi
  operator FTS tidak bisa disuntikkan. Tanpa FTS5 di SQLite, pencarian jatuh ke `LIKE`.
- `update_session` menolak kolom di luar `UPDATABLE_SESSION_COLUMNS`.
- `prune_sessions` menghapus sesi tanpa aktivitas lebih lama dari batas, kecuali yang di-pin
  dan yang disebut di `keep`. Sesi anak dari sesi yang dihapus dilepas, tidak ikut dihapus.
- Kolom baru yang nullable ditambahkan lewat `COLUMN_ADDITIONS` dan direkonsiliasi saat
  database dibuka. `SCHEMA_VERSION` hanya dinaikkan bila data lama harus diubah.
- `SessionDB` aman dipakai dari banyak thread (satu koneksi, satu kunci). `get_session_db()`
  memberi satu instance per file database.

## Status fitur

| Fitur | Status | Catatan |
|---|---|---|
| Sesi, pesan, kompaksi di tempat, rewind | ✅ | |
| Pencarian FTS5 dengan cadangan `LIKE` | ✅ | |
| Penghitung token per sesi | ✅ | |
| Estimasi biaya | ⬜ | Kolom ada, tidak ada yang mengisi: F2-T3 |
| Pangkas sesi (`prune_sessions`) dan auto-prune | ✅ | Auto-prune ada di `runtime/maintenance.py` |
| Banyak proses menulis bersamaan | 🟡 | WAL dan `busy_timeout` 30 detik. Tidak ada kumpulan koneksi baca |
| Pemulihan database rusak | ⬜ | Hermes punya perangkat pemulihan lengkap (`hermes_state_repair.py`) |
| Ekspor dan impor sesi | 🟡 | Ekspor JSON di `clite sessions export`. Impor belum ada |

## Yang sengaja berbeda dari Hermes

- **Satu modul.** Hermes memecah state ke 30 lebih file `hermes_state_*.py`.
- **Kompaksi di tempat**, bukan sesi anak baru per kompresi.
- **`turn_context` sebagai kolom.** Lihat [agent](agent.md).

## Celah yang diketahui

- Tidak ada `VACUUM` terjadwal. File tidak menyusut setelah pemangkasan.
- Tes mengatur umur sesi dengan menulis langsung ke `db._conn`; tidak ada API publik untuk itu
  (dan tidak perlu di luar tes).
