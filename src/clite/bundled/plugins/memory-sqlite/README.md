# memory-sqlite

Provider memori eksternal: fakta disimpan di SQLite milik plugin, dicari dengan FTS5.

```yaml
memory:
  provider: sqlite-memory
```

Tanpa baris itu plugin dimuat tetapi tidak dipakai. Jenisnya `backend`, jadi pemasangan
biasa memuatnya otomatis (`_AUTO_LOAD_KINDS`).

Data ada di `<home>/memories/sqlite-memory.sqlite3`. Tool bawaan `memory` tetap bekerja
seperti biasa; keduanya berdiri sendiri.

## Antarmuka `MemoryProvider`

Hanya `name` dan `is_available` yang wajib. Sisanya punya default kosong, jadi provider
menulis hanya yang ia dukung.

| Method | Kapan dipanggil | Di sini |
|---|---|---|
| `name` | Saat registrasi dan di tiap log | `"sqlite-memory"` |
| `is_available()` | Sekali, saat `MemoryManager` dibuat | true bila SQLite punya FTS5 |
| `initialize(session_id, **context)` | Awal sesi, juga sesi yang dilanjutkan | membuka database |
| `system_prompt_block()` | Saat system prompt dibangun sekali per sesi | tidak dipakai: teks tetap per sesi tidak ada gunanya di sini |
| `prefetch(query, session_id=)` | Setiap giliran, sebelum panggilan model | cari fakta yang cocok dengan pesan pengguna |
| `queue_prefetch(query, session_id=)` | Sesudah giliran selesai | tidak dipakai: indeks lokal, tidak ada yang perlu dipanaskan |
| `sync_turn(user, assistant, session_id=)` | Sesudah giliran selesai | tidak dipakai: provider ini menyimpan yang dipilih model, bukan seluruh percakapan (riwayat sudah ada di database sesi) |
| `get_tool_schemas()` | Saat agent dibuat; daftar tool tetap sepanjang sesi | `memory_save` dan `memory_search` |
| `handle_tool_call(name, args, **context)` | Saat model memanggil salah satu tool itu | menyimpan dan mencari |
| `on_memory_write(action, target, content)` | Sesudah tulisan berhasil ke `MEMORY.md`/`USER.md` | tidak dipakai: isi store bawaan sudah ada di system prompt tiap giliran |
| `on_pre_compress(messages)` | Sebelum bagian tengah riwayat diringkas | tidak dipakai |
| `on_session_end(messages)` | Sesi ditutup | tidak dipakai |
| `shutdown()` | Agent ditutup | menutup koneksi |

## Yang perlu diperhatikan penulis provider

- **Semua kegagalan ditelan manager.** `MemoryManager._guard` menangkap exception dan
  melanjutkan tanpa provider. Kegagalan di sini tidak pernah menggagalkan giliran, jadi
  jangan menangkap sendiri lalu mengembalikan teks kosong: log-nya hilang.
- **`prefetch` ikut ke pesan pengguna, bukan ke system prompt.** Teks yang dikembalikan
  dibungkus `<memory-context>` dan disimpan sebagai `turn_context` pesan itu, lalu dikirim
  ulang apa adanya di giliran berikutnya. Jangan mengembalikan teks yang berubah tiap
  panggilan: awalan percakapan harus stabil.
- **`is_available` tidak boleh menyentuh jaringan.** Ia dipanggil saat agent dibuat.
- **Tool dapat berjalan di thread pekerja.** Ronde tool paralel memanggil
  `handle_tool_call` dari thread lain, jadi koneksi dibuka `check_same_thread=False` dan
  tiap pemakaian dikunci.
- **Awalan yang dikembalikan model.** `memory_save` mengembalikan JSON
  (`{"success": true, ...}`), sama seperti tool bawaan.

## Batas yang diketahui

- FTS5 adalah pencarian kata, bukan makna: pertanyaan "kapan saya pindah?" hanya cocok bila
  ada kata yang sama di fakta tersimpan.
- Deduplikasi memindai tabel (FTS5 tidak punya indeks unik). Untuk ratusan fakta lokal ini
  tidak terasa.
- Satu penulis, satu proses: tidak ada penguncian antar-proses.
