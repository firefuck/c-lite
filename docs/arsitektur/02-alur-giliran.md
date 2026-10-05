# Alur satu giliran

Satu **giliran** adalah semua yang terjadi dari satu pesan pengguna sampai jawaban akhir
asisten. Di dalamnya bisa ada banyak **iterasi**: setiap iterasi adalah satu panggilan model,
diikuti satu ronde tool bila model memintanya.

Dokumen ini menelusuri giliran dari ujung ke ujung. Kontrak tiap bagian ada di
[spesifikasi agent](../spesifikasi/agent.md); di sini yang dijelaskan adalah urutannya dan
alasan di balik urutan itu.

## Dari surface ke loop

```
surface            runtime                 agent                    providers        tools         state
───────            ───────                 ─────                    ─────────        ─────         ─────
masukan ─────────► ChatSession
                   .handle_input
                     │ diawali "/" ? ──► run_slash (tanpa model, kecuali skill dan /retry)
                     │ bukan
                     ▼
                   .submit ─────────────► AIAgent
                                          .run_conversation
                                            │ kunci giliran (satu giliran per agent)
                                            ▼
                                          run_turn(agent, TurnState)
                                            │
                                            ├─ build_turn_context ───────────────────────────────► simpan pesan pengguna
                                            │
                                            │  ┌──────────── iterasi ────────────┐
                                            ├─►│ begin_iteration                 │
                                            │  │ prepare_iteration               │
                                            │  │ call_model ───────────────────────► LLMClient.complete ──► API
                                            │  │   ◄── delta teks ──────────────────
◄── on_delta ───── callbacks ◄──────────────│  │ normalize_response              │
                                            │  │ dispatch_response               │
                                            │  │   ├ ada tool call ──────────────────────────────► simpan pesan asisten
                                            │  │   │   run_tool_round ──────────────────► handle_function_call
◄── on_tool_* ──── callbacks ◄──────────────│  │   │                                               simpan hasil tool
                                            │  │   │   ulangi iterasi             │
                                            │  │   └ hanya teks ─────────────────────────────────► simpan jawaban
                                            │  └─────────────────────────────────┘
                                            ├─ finalize_turn
                                            ▼
◄───────────────── TurnResult ◄──────────── TurnResult
```

Tiga hal yang perlu dipegang:

- **Surface tidak pernah menyentuh loop.** Ia memanggil `ChatSession` dan mendengarkan
  `AgentCallbacks`. `ChatSession` dibuat lewat `runtime.factory.build_agent`, satu-satunya
  tempat `AIAgent` dibuat untuk sebuah surface.
- **Loop tidak pernah menyentuh surface.** Semua yang ingin ia sampaikan lewat callback.
- **`run_turn` tidak pernah melempar.** Bug di sebuah fase menjadi
  `exit_reason="internal_error"`, dan `finalize_turn` tetap jalan.

## `build_agent`: sekali per sesi

Sebelum giliran pertama, `build_agent` melakukan ini berurutan:

1. Memuat config sekali. Agent menyimpan potret config itu sepanjang sesi.
2. Menjalankan pekerjaan rumah startup (auto-prune sesi), sekali per proses dan home.
3. Memuat plugin, lalu menemukan tool bawaan. Urutan ini penting: plugin bisa menyumbang tool
   dan provider, dan keduanya harus sudah terdaftar sebelum daftar tool diresolusi.
4. Menyambungkan server MCP bila ada di config.
5. Meresolusi rute provider (`resolve_runtime_provider`) dan toolset platform.
6. Membuat `AIAgent`, yang langsung meresolusi daftar tool. Daftar itu tetap sepanjang sesi.

System prompt **belum** dibangun di sini. Ia dibangun saat giliran pertama dimulai
(`ensure_session`), disimpan di baris sesi, dan dipakai ulang byte demi byte sesudahnya.
Sesi yang dilanjutkan memuat prompt tersimpan, tidak membangun ulang.

## Fase demi fase

Setiap fase adalah fungsi `(agent, state) -> Verdict` di `src/clite/agent/turn/`. Verdict
`next` meneruskan ke fase berikutnya, `continue` memulai iterasi baru, `break` mengakhiri
giliran. Seluruh variabel giliran ada di `TurnState` (`agent/state.py`).

### `build_turn_context` (sekali per giliran)

1. Menghapus tanda interupsi dan mengisi ulang anggaran iterasi.
2. `ensure_session`: membuat baris sesi dan membangun system prompt bila belum ada.
3. Mengumpulkan **konteks giliran**: ingatan dari provider memori eksternal, pengingat memori,
   dan keluaran hook `pre_llm_call`.
4. Menyimpan pesan pengguna, dengan konteks giliran di kunci `turn_context` di sampingnya.

Konteks giliran tidak pernah masuk system prompt (itu akan mengubah awalan yang di-cache), dan
tidak dikirim sekali lalu dibuang (itu akan mengubah pesan yang sudah dikirim). Ia disimpan,
lalu `sanitize_for_api` menggabungkannya ke isi pesan pada **setiap** permintaan.

### `begin_iteration`

Urutan pemeriksaan: interupsi, anggaran waktu (`agent.run_budget_seconds`), anggaran iterasi
(`agent.max_turns`). Bila anggaran habis, giliran tidak berhenti begitu saja: lihat
[Akhir karena anggaran](#akhir-karena-anggaran). Sesudah itu teks `/steer` yang mengantre
ditempel ke pesan terbaru, yaitu pesan yang belum dijawab model.

### `prepare_iteration`

Kompresi pra-terbang. Bila perkiraan ukuran percakapan sudah melewati ambang, percakapan
dikompres **sebelum** memanggil model. Menunggu provider menolak berarti satu panggilan
terbuang.

### `call_model`

Menyusun permintaan lalu memanggil `LLMClient.complete`:

```
[ system prompt tersimpan ]
+ sanitize_for_api(riwayat)        salinan: turn_context digabung, tool call tanpa hasil diberi
                                   hasil pengganti, kunci internal dibuang
+ penanda cache                    hanya bila profil provider memintanya, dan hanya pada salinan
+ definisi tool                    tetap sepanjang sesi
```

Bila panggilan gagal, `classify_api_error` mengubah exception menjadi `ClassifiedError`, dan
tangga pemulihan dicoba berurutan. Yang pertama cocok menang:

| # | Kondisi | Tindakan | Batas |
|---:|---|---|---|
| 1 | Provider menolak data putar ulang (blok penalaran bertanda tangan) | Buang `provider_data`, ulangi langsung | Sekali per giliran |
| 2 | Konteks meluap | Kompres, mulai ulang iterasi. Iterasi dikembalikan ke anggaran | `compression.max_attempts` |
| 3 | Masalah kredensial | Ganti ke kunci lain milik provider yang sama, ulangi langsung | Sampai kumpulan kunci habis |
| 4 | Galat sementara | Tunggu (menghormati `Retry-After`), ulangi | `agent.api_max_retries` |
| 5 | Provider mati | Pindah ke entri berikutnya di `fallback_providers` untuk sisa giliran | Sampai daftar habis |
| 6 | Selain itu | Giliran berakhir dengan `exit_reason="api_error:<alasan>"` | - |

Loop tidak pernah melihat kode status HTTP. Semua keputusan berasal dari petunjuk di
`ClassifiedError`.

### `normalize_response`

| Jawaban model | Tindakan |
|---|---|
| Penolakan (`finish_reason: content_filter`, tanpa teks) | Dilaporkan sekali, tidak diulang. `exit_reason="refusal"` |
| Kosong (tanpa teks, tanpa tool call) | Diulang sampai dua kali, lalu berakhir dengan penjelasan. `exit_reason="empty_response"` |
| Terpotong batas keluaran (`finish_reason: length`) | Potongan disimpan, permintaan "lanjutkan" disimpan sebagai pesan internal, iterasi baru. Sampai tiga kali |
| Selain itu | Lanjut ke fase berikutnya |

### `dispatch_response`

**Ada tool call.** Pesan asisten disimpan **sebelum** tool pertama berjalan, supaya transkrip
tetap menunjukkan apa yang dicoba bila proses mati di tengah jalan. Lalu `run_tool_round`
menjalankan ronde itu, setiap hasil disimpan, dan loop memulai iterasi baru.

**Hanya teks.** Hook `transform_llm_output` boleh mengganti teksnya, pesan disimpan, dan
giliran selesai dengan `exit_reason="completed"`.

### `finalize_turn` (selalu jalan)

1. Menutup tool call yang belum punya hasil, supaya transkrip tersimpan selalu diterima
   provider di giliran berikutnya.
2. Mengisi jawaban akhir bila giliran berakhir karena galat.
3. Memberi tahu memori (`after_turn`) dan hook `post_llm_call`.
4. Memulai pembuatan judul sesi di latar belakang (hanya setelah giliran pertama yang sukses).
5. Mengembalikan `TurnResult`.

## Satu ronde tool

`run_tool_round` (`agent/tool_executor.py`) menerima daftar tool call dari satu jawaban model.

1. **Argumen di-parse.** JSON yang rusak diperbaiki bila bisa. Bila tidak, tool call itu
   langsung mendapat hasil galat dan model bisa memperbaikinya sendiri.
2. **Kebijakan paralel diputuskan per ronde.** Ronde berjalan paralel hanya bila semua tool di
   dalamnya dideklarasikan `safe` atau `path`, dan tidak ada dua tool `path` yang menyentuh
   file yang sama. Satu tool `never` membuat seluruh ronde berurutan, karena model mungkin
   mengurutkan panggilannya dengan sengaja.
3. **Setiap panggilan lewat `handle_function_call`**:

   ```
   tool dikenal dan diizinkan sesi ini?
   paksa tipe argumen sesuai skema
   hook pre_tool_call        boleh memblokir atau mengubah argumen; gagal = blokir
   handler                   untuk terminal: gerbang persetujuan perintah ada di sini
   hook transform_tool_result
   batas ukuran hasil        kepala dan ekor dipertahankan
   hook post_tool_call
   ```

4. **Hasil kembali sesuai urutan model**, apa pun urutan selesainya.
5. Bila anggaran iterasi tinggal sepersepuluh, peringatan ditempel ke hasil tool terakhir.

Handler tidak pernah melempar ke loop. Galat adalah hasil berbentuk `{"error": ...}` yang
dibaca model.

## Interupsi dan steer

| | `interrupt()` | `steer(teks)` |
|---|---|---|
| Panggilan model yang berjalan | Dibatalkan dengan menutup soket | Tidak diganggu |
| Perintah terminal yang berjalan | Dimatikan (seluruh grup proses) | Tidak diganggu |
| Tool yang belum mulai | Dilewati, diberi hasil "cancelled" | Tetap jalan |
| Subagent | Ikut diinterupsi | - |
| Efek pada transkrip | Tool call yang terbuka ditutup oleh `finalize_turn` | Teks ditempel ke pesan terbaru di iterasi berikut |
| `exit_reason` | `interrupted` | Tidak mengakhiri giliran |

Pesan baru yang datang saat giliran berjalan ditangani surface, bukan loop. Tiap surface
menerapkan kebijakan sibuknya (`interrupt`, `queue`, `steer`, atau `reject`) lalu memanggil
method di atas.

## Akhir karena anggaran

Saat anggaran iterasi atau waktu habis, `begin_iteration` tidak langsung berhenti:

1. Permintaan penutup disimpan sebagai pesan internal.
2. Satu panggilan terakhir dibuat **tanpa tool**, sehingga model hanya bisa menjawab dengan
   teks: apa yang sudah selesai, apa yang tersisa, apa yang menghalangi.
3. Jawaban itu menjadi jawaban akhir, dengan `exit_reason="budget_exhausted"`.

Bila panggilan penutup itu sendiri gagal, pengguna tetap mendapat kalimat pengganti.

## Kompresi

Kompresi adalah satu-satunya operasi yang menulis ulang riwayat dan membangun ulang system
prompt di tengah sesi. Ia dipicu dari tiga tempat: `prepare_iteration` (ambang),
`call_model` (provider menolak karena meluap), dan `/compress` (manual).

```
pangkas keluaran tool lama
tentukan batas kepala dan ekor      tanpa memisahkan tool call dari hasilnya
ringkas bagian tengah               dengan model bantu (call_auxiliary, di luar riwayat)
sambung: kepala + ringkasan + ekor  peran tetap berselang
arsipkan baris lama                 active=0, sesi yang sama, tetap bisa dicari
buang provider_data                 hanya bila provider mengikatnya ke awalan
muat ulang memori, bangun ulang system prompt
```

Sesudah kompresi, awalan percakapan baru. Cache prompt mulai dari nol sekali, lalu stabil
lagi.

## Alasan giliran berakhir

`TurnResult.exit_reason` selalu terisi:

| Nilai | Arti | `completed` |
|---|---|---|
| `completed` | Model menjawab dengan teks | ya |
| `interrupted` | Pengguna menghentikan giliran | tidak |
| `budget_exhausted` | Anggaran iterasi atau waktu habis; ada jawaban penutup | tidak |
| `refusal` | Model menolak menjawab | tidak |
| `empty_response` | Model terus mengembalikan jawaban kosong | tidak |
| `api_error:<alasan>` | Panggilan model gagal dan tangga pemulihan habis | tidak |
| `internal_error` | Bug di sebuah fase | tidak |

## Callback ke surface

`AgentCallbacks` (`agent/callbacks.py`) adalah seluruh antarmuka dari agent ke surface.
Pengamat dipanggil lewat `callbacks.emit`, jadi callback yang gagal hanya dicatat di log.

| Callback | Kapan | CLI klasik | RPC (event) | Gateway |
|---|---|---|---|---|
| `on_step` | Iterasi dimulai | - | `turn.step` | - |
| `on_delta` | Potongan teks jawaban | Dicetak langsung | `message.delta` | - |
| `on_reasoning` | Potongan teks penalaran | Bila `display.show_reasoning` | `reasoning.delta` | - |
| `on_message` | Pesan asisten lengkap | Menutup baris; mencetak teks yang tidak di-stream | `message.complete` | - |
| `on_tool_start` | Tool mulai | Baris progres | `tool.start` | - |
| `on_tool_complete` | Tool selesai | Baris hasil | `tool.complete` | - |
| `on_status` | Kompresi, coba ulang, fallback, peringatan | Baris status | `status.update` | Hanya `fallback` dan `compressed` dikirim ke chat |
| `on_subagent` | Kemajuan subagent | Baris progres | `subagent.update` | - |
| `approve` | Perintah berbahaya butuh keputusan | Prompt `[o/s/a/d]` | Permintaan `approval.request` | Pesan chat, menunggu `/approve` |
| `clarify` | Tool `clarify` bertanya | Prompt | Permintaan `clarify.request` | Pesan chat, menunggu jawaban |

Dua yang terakhir **memblokir** sampai pengguna menjawab. Tanpa callback (cron, `-q`),
kebijakan non-interaktif yang memutuskan, dan defaultnya tolak.

Callback bisa datang dari thread pekerja saat ronde tool berjalan paralel. Surface yang punya
thread UI memindahkannya sendiri.

## Subagent

Tool `delegate_task` memanggil `agent.delegation.delegate`, yang membuat `AIAgent` anak untuk
setiap tugas:

- Percakapan kosong dan tanpa memori. Tugas dan konteks yang ditulis induk menjadi pesan
  pengguna pertama; system prompt anak memuat panduan untuk subagent.
- Toolset anak adalah irisan dari yang diminta dan milik induk, dikurangi `delegate_task`,
  `clarify`, `memory`, dan `cronjob`.
- Anggaran iterasi sendiri (`delegation.max_iterations`).
- Perintah berbahaya tetap meminta persetujuan pengguna lewat callback `approve` milik induk.
- Sesi anak tersimpan dengan `parent_session_id`, sehingga tidak muncul di daftar sesi tetapi
  bisa dicari.
- Beberapa tugas dalam satu panggilan berjalan bersamaan, paling banyak
  `delegation.max_concurrent_children`.

Induk hanya menerima laporan akhir tiap anak sebagai hasil tool. Riwayat anak tidak pernah
masuk ke konteks induk: itulah gunanya delegasi.
