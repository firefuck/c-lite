# Spesifikasi: agent

| | |
|---|---|
| Kode | `src/clite/agent/` |
| Tes | `tests/agent/` |
| Lapisan | 4. Boleh mengimpor `core`, `state`, `providers`, `plugins.hooks`, `skills`, `tools` |
| Bedah Hermes | [02-agent-loop](../hermes/02-agent-loop.md), [03-prompt-dan-cache](../hermes/03-prompt-dan-cache.md), [11-state-sesi-memori](../hermes/11-state-sesi-memori.md) |

## Tanggung jawab

Satu percakapan dari awal sampai akhir: menyusun system prompt, menjalankan giliran (panggil
model, jalankan tool, ulangi), menjaga percakapan tetap muat di jendela konteks, mengelola
memori, dan mendelegasikan pekerjaan ke subagent. Paket ini tidak tahu apa pun tentang
terminal, WebSocket, atau Telegram. Semua surface memakainya lewat `AIAgent` dan
`AgentCallbacks`.

## Bagian-bagian

| Bagian | File | Isi |
|---|---|---|
| Fasad | `agent.py` | `AIAgent`: state sesi dan operasi yang dibutuhkan surface |
| Loop | `loop.py`, `state.py` | `run_turn`, `TurnState`, `Verdict`, `TurnResult` |
| Fase | `turn/context.py`, `turn/iteration.py`, `turn/request.py`, `turn/response.py`, `turn/finalize.py` | Satu fungsi per fase giliran |
| Tool | `tool_executor.py` | Menjalankan satu ronde tool call, paralel bila aman |
| Pesan | `messages.py` | Membersihkan riwayat sebelum dikirim, mem-parse argumen tool |
| Lampiran | `attachments.py` | Gambar yang dilampirkan pengguna: muat, validasi, kecilkan, jadikan bagian konten |
| Prompt | `prompt/` | Tiga tingkat prompt, file konteks, penanda cache |
| Konteks | `context/` | `ContextEngine`, kompresor bawaan, dan kontrak yang dicek `check_context_engine` |
| Memori | `memory/` | `MemoryStore` bawaan, `MemoryProvider` eksternal, `MemoryManager` |
| Review | `review.py` | Review latar belakang: agent kecil yang membaca salinan giliran panjang dan menulis memori/skill |
| Lain-lain | `delegation.py`, `title.py`, `todo.py`, `budget.py`, `callbacks.py` | Subagent, judul sesi, daftar tugas, anggaran iterasi, callback |

## Alur satu giliran

`AIAgent.run_conversation(pesan)` membuat `TurnState` lalu memanggil `run_turn`. Setiap fase
adalah fungsi `(agent, state) -> Verdict`:

```
build_turn_context          sekali per giliran
ulangi:
  begin_iteration           interupsi? anggaran waktu? anggaran iterasi? lalu pasang /steer
  prepare_iteration         kompresi pra-terbang bila sudah dekat ambang
  call_model                kirim permintaan; tangga pemulihan saat gagal
  normalize_response        jawaban kosong diulang; jawaban terpotong dilanjutkan
  dispatch_response         ada tool call: jalankan, ulangi. Hanya teks: selesai
finalize_turn               selalu jalan, juga setelah galat atau interupsi
```

Verdict `next` lanjut ke fase berikutnya, `continue` memulai iterasi baru, `break` mengakhiri
giliran. `run_turn` tidak pernah melempar exception: bug di sebuah fase menjadi
`exit_reason="internal_error"`.

Tangga pemulihan di `call_model` (keputusan berasal dari `classify_api_error`, bukan dari
kode status):

1. Blok penalaran yang diputar ulang ditolak provider: buang `provider_data` dari riwayat,
   ulangi langsung (sekali per giliran).
2. Konteks meluap: kompres, lalu ulangi iterasi (iterasi dikembalikan ke anggaran).
3. Masalah kredensial: ganti ke kunci lain dari kumpulan yang terikat pada endpoint rute,
   ulangi langsung. Kunci vendor tidak dipakai sebagai pengganti kunci endpoint kustom.
4. Galat sementara: tunggu (menghormati `Retry-After`), ulangi sampai `agent.api_max_retries`.
5. Provider mati: pindah ke entri berikutnya di `fallback_providers` untuk sisa giliran.
6. Selain itu: giliran berakhir dengan pesan galat yang sudah diklasifikasi.

## Kontrak

Setiap butir dijaga oleh tes di `tests/agent/`.

**Prompt dan cache**
- System prompt dibangun sekali per sesi, disimpan bersama sesi, dan dipakai ulang byte demi
  byte di setiap permintaan dan saat sesi dilanjutkan. Daftar tool juga tetap sepanjang sesi.
- Hanya kompresi konteks dan pergantian model yang membangun ulang prompt.
- Urutan tingkat: `stable` (identitas, panduan, skill auto-load), `context` (pesan sistem
  pemanggil, instruksi proyek, direktori kerja, petunjuk platform), `volatile` (indeks skill,
  memori, bagian plugin, tanggal tanpa jam, model).
- **Setiap permintaan mengulang permintaan sebelumnya persis, lalu menambah di ujungnya.**
  Bentuk kawat dari pesan yang sudah pernah dikirim tidak pernah berubah, juga setelah sesi
  dilanjutkan. Cache prompt bergantung pada ini, dan model Claude terbaru menolak permintaan
  yang riwayatnya diubah (blok penalarannya ditandatangani terhadap percakapan sebelumnya).
- Konteks yang dikumpulkan untuk satu giliran (ingatan dari provider memori, hasil hook
  `pre_llm_call`, pengingat memori) ikut pesan pengguna giliran itu, tidak pernah masuk
  system prompt. Ia disimpan di samping pesan sebagai `turn_context`: teks pengguna tetap
  bersih untuk ditampilkan dan dicari, dan pesan itu dikirim ulang persis sama di giliran
  berikutnya.
- `provider_data` (data buram yang diminta kembali oleh provider, misalnya blok penalaran
  bertanda tangan) disimpan bersama pesan asisten dan dikirim ulang apa adanya. Ia dibuang
  ketika awalan percakapan sengaja diubah (kompresi pada provider yang mengikatnya ke awalan,
  pergantian model) atau ketika provider menolaknya.
- Penanda cache (`cache_control`) dipasang pada salinan saat mengirim: system prompt dan tiga
  pesan non-sistem terakhir. Riwayat tersimpan tidak pernah memuatnya.
- File konteks proyek dipindai (`core.threats`) dan dipotong ke anggaran karakter sebelum
  dimuat. Hanya satu jenis yang dimuat: `.clite.md`/`CLITE.md`, lalu rantai `AGENTS.md` dari
  root repositori ke direktori kerja, lalu `CLAUDE.md`, lalu `.cursorrules`.

**Transkrip**
- Pesan langsung tahan lama begitu `append_message` kembali. Pesan asisten yang berisi tool
  call disimpan sebelum tool dijalankan.
- Setiap tool call selalu punya hasil. `finalize_turn` menutup yang belum terjawab, dan
  `sanitize_for_api` memperbaiki salinan yang dikirim.
- Kunci berawalan `_` dan `timestamp` tidak pernah dikirim ke provider.

**Lampiran gambar**
- Pesan pengguna tetap berupa teks sampai gambar dilampirkan. Dengan gambar, `content` menjadi
  daftar bagian: `text` lalu satu `image_url` per gambar (data URL base64). Transport sudah
  meneruskan bentuk berstruktur ini, jadi tidak ada perubahan di sana.
- Batas: `attachments.max_bytes` per gambar dan `attachments.max_images` per pesan. Gambar
  yang melewati batas byte dikecilkan dulu (`attachments.max_edge`, butuh ekstra `images`);
  tanpa Pillow, gambar yang terlalu besar ditolak dengan pesan yang menyebut cara mengecilkannya.
- Model yang tidak menerima gambar tidak pernah dikirimi bagian `image_url`. Yang dikirim
  hanya teksnya, ditambah catatan bahwa gambar dilampirkan tetapi tidak terlihat. Riwayat
  tersimpan tetap memuat gambarnya, jadi giliran berikutnya pada model berpenglihatan
  mengirimnya lagi. Penentuan ini dari `ProviderProfile.supports_vision(model)` atau override
  `model.vision`.
- Karena riwayat tersimpan tidak berubah, pesan bergambar dikirim ulang persis sama di giliran
  berikutnya (aturan A2 tetap berlaku).

**Tool**
- Hasil tool kembali sesuai urutan model, apa pun urutan selesainya.
- Satu ronde berjalan paralel hanya jika semua tool di dalamnya `safe` atau `path`, dan tidak
  ada dua tool `path` yang menyentuh file yang sama. Selain itu berurutan.
- Argumen yang rusak diperbaiki bila bisa (code fence, koma di akhir, JSON ganda), kalau tidak
  dikembalikan ke model sebagai hasil galat. Tool tak dikenal juga menjadi hasil galat, dan
  giliran berlanjut.

**Jawaban model**
- Jawaban kosong diulang sampai dua kali, lalu giliran berakhir dengan penjelasan.
- Penolakan (`finish_reason: content_filter` tanpa teks) dilaporkan sekali dan tidak diulang.
- Jawaban yang terpotong batas keluaran dilanjutkan sampai tiga kali dan digabung menjadi
  satu jawaban akhir.

**Anggaran dan interupsi**
- Anggaran iterasi tidak terbatas secara default (`agent.max_turns: null`). Saat habis, ada
  satu panggilan terakhir tanpa tool agar pengguna mendapat status, bukan giliran yang
  berhenti begitu saja. Model diberi tahu di hasil tool terakhir ketika sisa anggaran tinggal
  sepersepuluh.
- `interrupt()` membatalkan panggilan model yang sedang berjalan, mematikan perintah yang
  sedang jalan, melewati tool yang belum mulai, dan menjalar ke subagent.
- `steer()` tidak menginterupsi: teksnya ditempel ke hasil tool terbaru di iterasi berikut.
- Hanya satu giliran berjalan per agent pada satu waktu.

**Kompresi**
- Ambang: `compression.threshold` (0,5) dari jendela, dengan batas bawah 0,75 untuk jendela di
  bawah 512 ribu token.
- Langkah: pangkas gambar lama lebih dulu, lalu keluaran tool lama; tentukan batas tanpa
  memisahkan tool call dari hasilnya; ringkas bagian tengah dengan model bantu; sambung dengan
  peran yang tetap berselang.
- Ringkasan berstruktur dengan lima bagian tetap: `Goal`, `Key Decisions`, `Files` (path
  beserta keadaannya), `Failed Commands` (perintah gagal dan sebabnya), `Unfinished Work`.
  Ringkasan lama diperbarui, bukan diringkas ulang. Prompt pembaruan menyebut bagian mana yang
  belum ada di ringkasan lama.
- Bila bagian tengah lebih besar dari jendela model bantu, ia diringkas bertahap: bagian demi
  bagian diringkas lalu digabung dalam satu ringkasan akhir, bukan dipotong. Peringkas yang
  gagal tetap membuang bagian tengah dan meninggalkan penanda.
- Gambar lama dibuang lebih dulu daripada teks: bagian `image_url` di luar jendela terlindung
  diganti penanda, teks sekitarnya tetap.
- Kompresi menulis ulang riwayat di sesi yang sama: baris lama diarsipkan (`active=0`), tetap
  bisa dicari.
- Engine dipilih lewat `context.engine`. Nama yang tidak dikenal bukan galat: ia jatuh ke
  kompresor bawaan dan mencatat peringatan, jadi salah ketik di config tidak menggagalkan
  pembuatan agent.
- Setiap engine yang terdaftar lulus tes kontrak yang sama (`check_context_engine` di
  `context/contract.py`): tidak mengubah daftar masukan, tidak memisahkan tool call dari
  hasilnya, menjaga peran tetap berselang, dan mengembalikan transkrip yang lebih pendek.

**Memori**
- `MEMORY.md` dan `USER.md` dibatasi karakter (2200 dan 1375). Entri dipisah `§`.
- Isi memori di prompt adalah potret saat sesi dimulai. Tulisan di tengah sesi langsung ke
  disk tetapi tidak mengubah prompt sesi itu.
- Entri yang lolos pemindaian ancaman saja yang disimpan. Duplikat ditolak.
- Provider memori eksternal yang gagal tidak pernah menggagalkan giliran.
- Provider memilih sendiri apa yang disimpannya lewat `prefetch`, `sync_turn` dan hook lain;
  contoh lengkapnya plugin bawaan `memory-sqlite` (SQLite + FTS5): fakta disimpan lewat tool
  milik provider, diingat kembali lewat `prefetch`, dan masuk ke `turn_context` seperti ingatan
  lain. `README.md` di direktori itu menjelaskan tiap method antarmuka dan kapan ia dipanggil.
- Setiap `memory.nudge_interval` giliran tanpa tulisan memori, satu pengingat ditempel ke
  pesan pengguna (hanya bila tool `memory` tersedia). Penghitung giliran tanpa tulisan disimpan
  per sesi di `<home>/memories/nudge.json`, jadi sesi yang dilanjutkan tidak memulai ulang
  hitungannya.

**Delegasi**
- Subagent mulai dengan percakapan kosong, tanpa memori, dan tanpa tool `clarify`, `memory`,
  `cronjob`. Induk hanya menerima laporan akhir.
- Nama tool anak selalu merupakan subset nama tool induk, termasuk permintaan alias semua,
  toolset komposit, toolset kustom parsial, dan MCP. Larangan toolset induk diwariskan,
  lalu larangan khusus anak diterapkan. Kedalaman dibatasi
  `delegation.max_spawn_depth` (1).
- Setiap tugas bisa memilih model lewat argumen `model`: sebuah nama model saja mempertahankan
  provider induk, sedangkan `provider:model` dan alias berpindah provider. Pilihannya dibatasi
  ke provider yang terkonfigurasi; provider yang tidak bisa diresolusi menjadi hasil galat
  untuk tugas itu saja, tanpa menggagalkan tugas lain.
- Progres: `on_subagent` membawa nama tool, pratinjau argumen yang diredaksi, jumlah iterasi,
  dan model anak. Event RPC `subagent.update` diperluas dengan bidang opsional `args`,
  `iteration`, `model`, dan `spawn_id`; klien lama tetap bekerja.
- Delegasi latar: `delegate_task(background=true)` langsung kembali dengan id per tugas.
  Laporan tiap tugas yang selesai disampaikan ke induk sebagai catatan pada hasil tool
  berikutnya (pola `/steer`), tidak pernah menyisipkan ke pesan yang sudah dikirim; bila tiba
  di antara giliran, ia menjadi pesan internal baru. Interupsi induk menjalar ke subagent latar.
- Peran pengatur: dengan `delegation.max_spawn_depth` lebih dari 1, anak di tingkat tengah
  boleh mendelegasikan lagi (mendapat toolset `delegation`), sedangkan cucu tidak.
- Anak yang gagal melaporkan gagal tanpa menggagalkan induk atau saudaranya.

**Review latar belakang**
- Setelah giliran yang selesai dan memakai setidaknya `background_review.min_tool_calls`
  tool call, sebuah agent review kecil berjalan di thread latar. Ia menerima salinan giliran
  itu sebagai satu pesan pengguna (teks saja: apa yang diminta, tool apa yang dipanggil, apa
  jawabannya) dan **tidak** mewarisi transkrip sesi utama.
- Review berjalan pada `AIAgent` terpisah dengan toolset sempit (`memory` dan `skills`) dan
  anggaran `background_review.max_turns`; ia menulis hanya lewat tool memori dan skill, dan
  `persist=False` sehingga tidak ada baris sesi yang ditulis. Riwayat dan system prompt sesi
  utama tidak pernah disentuh.
- Gate: `background_review.enabled`, giliran harus selesai dan tidak terinterupsi, bukan
  subagent (`depth > 0`), bukan platform `cron`, sesi tidak sedang sibuk, dan tidak ada review
  lain untuk sesi itu dalam `background_review.min_interval_seconds` terakhir.
- Review yang gagal atau melewati `background_review.timeout_seconds` menjadi `error` pada
  hasilnya dan catatan log; ia tidak pernah melempar ke giliran dan tidak memengaruhi giliran
  berikutnya.
- Hasilnya terlihat: baris status `on_status("review", …)` di surface dan catatan di log.

## Status fitur

| Fitur | Status | Catatan |
|---|---|---|
| Loop berfase, pemulihan galat, fallback provider | ✅ | |
| Prompt tiga tingkat, cache, file konteks | ✅ | |
| Kompresor bawaan dan registry `ContextEngine` | ✅ | Ringkasan berstruktur, peringkasan bertahap, gambar dibuang lebih dulu (F2-T11). Engine kedua, jendela geser sebagai plugin bawaan (tanpa model bantu), dan `context.engine` yang tidak dikenal jatuh ke kompresor dengan peringatan. Tes kontrak `check_context_engine` menguji setiap engine terdaftar. F6-T6 |
| Memori bawaan, provider eksternal, pengingat | ✅ | Provider contoh: plugin bawaan `memory-sqlite` (SQLite + FTS5, tool `memory_save`/`memory_search`, diingat lintas sesi lewat `turn_context`), dijelaskan method demi method di `README.md` plugin itu. F6-T3 |
| Delegasi sinkron | ✅ | Model per tugas (`model`, dibatasi ke provider terkonfigurasi), progres rinci (nama tool, pratinjau argumen, iterasi, model). F2-T13 |
| Delegasi latar | ✅ | `delegate_task(background=true)` kembali dengan id; laporan tiba sebagai catatan pada hasil tool berikutnya (pola `/steer`), interupsi induk menjalar. Dijaga `tests/agent/test_memory_and_delegation.py`. F2-T13 |
| Peran pengatur | ✅ | Dengan `delegation.max_spawn_depth > 1`, anak tingkat tengah mendelegasikan lagi dan cucu tidak. F2-T13 |
| Judul sesi otomatis | ✅ | |
| Estimasi token | ✅ | `context/tokens.py`: perkiraan karakter/4 untuk pesan sesudah jangkar, `prompt_tokens` dari provider sebagai jangkar untuk bagian yang sudah diukur (F2-T11) |
| Estimasi biaya | ⬜ | Kolom `estimated_cost_usd` ada, belum diisi: F2-T3 |
| Input gambar | ✅ | `attachments.py`: bentuk konten, batas ukuran/jumlah, pengecilan, penyaringan model tanpa penglihatan; `clite chat --image` dan `/image`. Dijaga `tests/agent/test_attachments.py`, `test_loop.py`, `tests/runtime/test_session_and_slash.py`. Model bantu untuk melihat ada sebagai tool `vision_analyze` (spesifikasi tools) |
| Review latar belakang (memori dan skill) | ✅ | `review.py`: agent fork terpisah (toolset `memory`+`skills`, `background_review.max_turns`) menerima salinan giliran sebagai pesan pengguna, tidak menyentuh riwayat/system prompt sesi utama; gate `enabled`/`min_tool_calls`/`min_interval_seconds`/subagent/cron/sibuk; gagal atau timeout hanya jadi catatan. Dijaga `tests/agent/test_review.py`. F2-T12 |
| Checkpoint dan rollback file | ✅ | `tools/checkpoints.py` menyimpan isi lama sebelum `write_file`/`patch` mengubah file, dikelompokkan per giliran di bawah `<home>/checkpoints/`. `/rollback [n]` mengembalikan perubahan giliran terakhir (atau `n` giliran); file yang dibuat agent dihapus, file yang dihapus dikembalikan. Perubahan lewat perintah `terminal` tidak terlihat. Dijaga `tests/tools/test_checkpoints.py`. F2-T8 |
| Kunci file memori di Windows | ✅ | `core.locking` memakai `fcntl`/`msvcrt`; tes dua proses dan mutasi memori lulus pada Linux/Windows. CI `37499972911`, F1-T5 |

## Yang sengaja berbeda dari Hermes

- **Fase sebagai fungsi kecil.** Hermes memecah loop ke banyak modul pembantu
  (`agent/conversation_loop.py`, `turn_context.py`, `turn_recovery.py`, dan lain-lain) yang
  saling berbagi state lewat objek agent. Di sini semua variabel giliran ada di `TurnState`
  dan urutan fase terbaca di `src/clite/agent/loop.py`.
- **Tidak ada tabel tool khusus di loop.** Tool tingkat agent (`todo`, `memory`,
  `delegate_task`, `clarify`) adalah tool biasa di registry yang menerima `ctx.agent`.
- **Kompresi di tempat.** Hermes membuat sesi anak saat kompresi. Di sini id sesi tetap, baris
  lama diarsipkan.
- **`run_turn` tidak melempar.** Surface selalu menerima `TurnResult`.
- **Konteks giliran disimpan.** Hermes menempelkan konteks sesaat ke pesan pengguna hanya pada
  saat panggilan, lalu mengirim pesan itu tanpa konteks di giliran berikutnya. Itu mengubah
  awalan percakapan. Di sini konteks disimpan sebagai `turn_context` dan dikirim ulang.

## Celah yang diketahui

- Perkiraan token tidak memakai tokenizer provider. Setelah respons pertama, angka
  `prompt_tokens` dari provider dipakai sebagai jangkar dan hanya pesan sesudahnya yang
  diperkirakan, jadi galatnya tidak menumpuk. Sebelum respons pertama (dan bila provider
  melaporkan angka yang tidak masuk akal untuk transkrip ini) kompresi pra-terbang masih bisa
  sedikit terlalu cepat atau terlambat.
- Peringkasan bertahap memanggil model bantu beberapa kali untuk satu kompresi; biayanya
  bertambah pada bagian tengah yang sangat besar, ditukar dengan detail yang tidak hilang.
