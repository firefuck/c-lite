# gateway: aturan kerja

Gateway pesan dan adapter platform. Spesifikasi: `docs/spesifikasi/gateway.md`.

Tes: `pytest tests/gateway -q`

## Aturan yang tidak boleh dilanggar

1. **Kebijakan di runner, bukan di adapter.** Otorisasi, pengarahan sesi, slash command,
   kebijakan sibuk, persetujuan: semuanya di `runner.py`, sehingga setiap platform berperilaku
   sama. Adapter hanya menerjemahkan.
2. **Orang asing tidak pernah mencapai agent.** Setiap jalur pesan masuk melewati
   `is_authorized`. Di grup, orang asing diabaikan tanpa balasan.
3. **Diam berarti tolak** untuk persetujuan.
4. **`dispatch` kembali dengan cepat.** Ia dipanggil dari thread terima milik adapter; giliran
   berjalan di thread lain.
5. **Satu pesan buruk tidak boleh mematikan loop terima.** Bungkus pemrosesan per pesan.
6. **Tidak mengimpor `rpc`, `server`, atau `cli`.**
7. **Token platform dari `.env` lewat `get_secret`**, didaftarkan dengan `register_secret`.

## Resep

### Menambah platform

Contoh lengkap: `platforms/telegram.py` (143 baris). Panduan Hermes yang setara:
`gateway/platforms/ADDING_A_PLATFORM.md` di clone rujukan.

1. Buat `platforms/<nama>.py` dengan kelas turunan `BasePlatformAdapter`:
   - `connect()`: periksa kredensial (lempar bila salah), mulai loop terima dengan
     `core.threads.start_thread`, lalu kembali.
   - `to_event(...)`: ubah pesan platform menjadi `MessageEvent` dengan `SessionSource`
     (`chat_type` salah satu dari `CHAT_DM`, `CHAT_GROUP`, `CHAT_CHANNEL`). Kembalikan `None`
     untuk pesan yang bukan untuk agent (obrolan grup biasa, pesan bot).
   - `send(chat_id, text, reply_to=, thread_id=)`: kirim satu pesan, kembalikan `SendResult`.
     Jangan melempar.
   - `disconnect()`: hentikan loop.
   - `max_message_length` sesuai batas platform.
2. Di akhir modul: `register_secret(SecretSpec(...))` dan `register_platform("<nama>", Kelas)`.
3. Impor modul itu di `GatewayRunner.start` (bersama `local` dan `telegram`), dan di
   `scripts/gen_docs.py` supaya muncul di katalog.
4. Tes terhadap **server tiruan lokal** yang meniru API platform itu (lihat `FakeTelegram`
   di `tests/gateway/test_gateway.py`). Jangan menguji terhadap layanan sungguhan di suite.
5. Dokumentasikan konfigurasinya di docstring modul (blok `gateway.platforms.<nama>`).

Platform sebagai plugin (di luar repositori): sama, tetapi didaftarkan dengan
`ctx.register_platform("<nama>", factory)`.

## Jebakan

- Callback `approve` dan `clarify` memblokir thread giliran sampai pengguna menjawab atau
  batas waktu habis. Pesan jawaban datang lewat `dispatch` di thread lain dan melepaskannya.
- Kunci sesi memuat id pengguna di grup. Mengubah `build_session_key` memutus semua sesi yang
  tersimpan di `sessions.json`.
- `client_factory` di `GatewayRunner` hanya untuk tes (menyuntikkan `ScriptedClient`).
