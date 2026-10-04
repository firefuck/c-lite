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
| Prompt | `prompt/` | Tiga tingkat prompt, file konteks, penanda cache |
| Konteks | `context/` | `ContextEngine` dan kompresor bawaan |
| Memori | `memory/` | `MemoryStore` bawaan, `MemoryProvider` eksternal, `MemoryManager` |
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
3. Masalah kredensial: ganti ke kunci lain milik provider yang sama, ulangi langsung.
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
- Langkah: pangkas keluaran tool lama, tentukan batas tanpa memisahkan tool call dari hasilnya,
  ringkas bagian tengah dengan model bantu, sambung dengan peran yang tetap berselang.
- Ringkasan lama diperbarui, bukan diringkas ulang. Peringkas yang gagal tetap membuang bagian
  tengah dan meninggalkan penanda.
- Kompresi menulis ulang riwayat di sesi yang sama: baris lama diarsipkan (`active=0`), tetap
  bisa dicari.

**Memori**
- `MEMORY.md` dan `USER.md` dibatasi karakter (2200 dan 1375). Entri dipisah `§`.
- Isi memori di prompt adalah potret saat sesi dimulai. Tulisan di tengah sesi langsung ke
  disk tetapi tidak mengubah prompt sesi itu.
- Entri yang lolos pemindaian ancaman saja yang disimpan. Duplikat ditolak.
- Provider memori eksternal yang gagal tidak pernah menggagalkan giliran.
- Setiap `memory.nudge_interval` giliran tanpa tulisan memori, satu pengingat ditempel ke
  pesan pengguna (hanya bila tool `memory` tersedia).

**Delegasi**
- Subagent mulai dengan percakapan kosong, tanpa memori, dan tanpa tool `delegate_task`,
  `clarify`, `memory`, `cronjob`. Induk hanya menerima laporan akhir.
- Toolset anak tidak pernah melebihi milik induk. Kedalaman dibatasi
  `delegation.max_spawn_depth` (1).
- Anak yang gagal melaporkan gagal tanpa menggagalkan induk atau saudaranya.

## Status fitur

| Fitur | Status | Catatan |
|---|---|---|
| Loop berfase, pemulihan galat, fallback provider | ✅ | |
| Prompt tiga tingkat, cache, file konteks | ✅ | |
| Kompresor bawaan dan registry `ContextEngine` | ✅ | Peningkatan: F2-T11 |
| Memori bawaan, provider eksternal, pengingat | ✅ | Provider contoh: F6-T3 |
| Delegasi sinkron | ✅ | Model per anak, progres rinci, delegasi asinkron: F2-T13 |
| Judul sesi otomatis | ✅ | |
| Estimasi token | 🟡 | Perkiraan karakter/4 di `context/tokens.py`. Angka dari provider dipakai bila ada |
| Estimasi biaya | ⬜ | Kolom `estimated_cost_usd` ada, belum diisi: F2-T3 |
| Input gambar | ⬜ | Konten berstruktur sudah lolos ke transport, belum ada jalur masuknya: F2-T6 |
| Review latar belakang (memori dan skill) | ⬜ | F2-T12 |
| Checkpoint dan rollback file | ⬜ | F2-T8 |
| Kunci file memori di Windows | ⬜ | `fcntl` saja: F1-T5 |

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

- Penghitung pengingat memori dimulai dari nol setiap kali agent dibuat (juga saat sesi
  dilanjutkan).
- Perkiraan token tidak memakai tokenizer provider, jadi kompresi pra-terbang bisa sedikit
  terlalu cepat atau terlambat sebelum respons pertama memberi angka sebenarnya.
