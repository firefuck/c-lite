# agent: aturan kerja

Satu percakapan: prompt, loop giliran, kompresi, memori, delegasi. Spesifikasi lengkapnya di
`docs/spesifikasi/agent.md`. Baca itu dulu.

Tes: `pytest tests/agent -q`

## Aturan yang tidak boleh dilanggar

1. **System prompt tidak berubah di tengah sesi.** Jangan menambahkan apa pun yang berubah
   antar-giliran ke `prompt/builder.py`. Informasi per giliran masuk ke `turn_context` pesan
   pengguna (`turn/context.py`) atau ke hasil tool. Tes penjaganya:
   `test_system_prompt_and_tools_are_byte_stable_across_turns_and_resume`.
2. **Yang sudah dikirim tidak pernah berubah.** Setiap permintaan harus sama dengan permintaan
   sebelumnya ditambah pesan baru di ujungnya. Jangan menyisipkan sesuatu ke pesan lama, dan
   jangan mengirim sesuatu yang tidak disimpan. `messages.sanitize_for_api` harus
   deterministik. Tes penjaganya:
   `test_every_request_repeats_the_previous_one_and_adds_to_its_end`.
3. **Riwayat hanya bertambah.** Yang boleh menulis ulang riwayat hanya
   `AIAgent.compress_context`, dan yang boleh membuang `provider_data` hanya
   `AIAgent.drop_replay_data`.
4. **`agent.py` tetap fasad.** Perilaku baru masuk sebagai fase, tool, atau plugin, bukan
   method baru di `AIAgent`.
5. **`loop.py` tetap pendek.** Mengubah perilaku loop berarti mengubah atau menyisipkan fase.
6. **Tidak ada import dari `runtime`, `cli`, `rpc`, `server`, `gateway`, `cron`.** Agent
   berbicara ke surface hanya lewat `AgentCallbacks`.
7. **Callback pengamat tidak boleh menggagalkan giliran.** Panggil lewat
   `agent.callbacks.emit(...)`, jangan langsung.

## Resep

### Menambah fase ke loop

1. Tulis fungsi `(agent, state) -> Verdict` di `turn/`. Kembalikan `PROCEED`, atau
   `Verdict(CONTINUE, alasan)`, atau `Verdict(BREAK, alasan)`.
2. Simpan variabel yang perlu hidup antar-fase di `TurnState` (`state.py`), bukan di agent.
3. Sisipkan ke `ITERATION_PHASES` di `loop.py` pada posisi yang benar.
4. Tulis tes di `tests/agent/test_loop.py` dengan `make_agent` dan `ScriptedClient`.

### Menambah teks panduan ke prompt

1. Tambahkan konstanta di `prompt/identity.py`.
2. Pasang di `_stable` (`prompt/builder.py`), dengan syarat tool yang relevan tersedia.
3. Teksnya harus sama untuk semua sesi dengan tool yang sama. Tanpa tanggal, tanpa path,
   tanpa nama pengguna.

### Menambah context engine

Turunkan `ContextEngine` (`context/engine.py`), implementasikan `compress`, daftarkan dengan
`register_context_engine`. Dari plugin: `ctx.register_context_engine`. Kontraknya: jangan
mengubah daftar masukan, dan jangan memisahkan tool call dari hasilnya (`repair_tool_pairs`
tersedia di `context/compressor.py`).

### Menambah provider memori

Turunkan `MemoryProvider` (`memory/provider.py`), daftarkan dengan `register_memory_provider`.
Semua method selain `name` dan `is_available` opsional. Kegagalan provider ditelan oleh
`MemoryManager._guard`, jadi provider tidak perlu menangkap galatnya sendiri.

## Jebakan

- `AIAgent.config` adalah potret saat agent dibuat. Membaca `load_config()` di tengah giliran
  memberi nilai yang bisa berbeda dari yang dipakai sesi itu. Gunakan `agent.config` atau
  `ctx.setting(...)`.
- Tool bisa dipanggil dari thread pekerja saat ronde berjalan paralel. Apa pun yang disentuh
  tool pada agent harus aman untuk itu (`TodoStore` dan `append_message` sudah memakai kunci).
- `ScriptedClient` melempar `AssertionError` saat skripnya habis. Itu berarti loop memanggil
  model lebih sering daripada yang tes harapkan, bukan bug di klien uji.
- Pesan di `agent.messages` membawa `_row_id` (id baris di database). Jangan menyalinnya ke
  pesan baru.
