# Spesifikasi: providers

| | |
|---|---|
| Kode | `src/clite/providers/`, profil bawaan di `src/clite/bundled/plugins/model-providers/` |
| Tes | `tests/providers/` |
| Lapisan | 1. Boleh mengimpor `core` saja |
| Bedah Hermes | [04-provider-dan-model](../hermes/04-provider-dan-model.md) |

## Tanggung jawab

Mengubah "pengguna ingin model X" menjadi satu panggilan HTTP yang benar ke provider mana pun,
dan mengubah jawabannya ke satu bentuk yang sama untuk loop agent. Paket ini tidak tahu apa
itu tool, sesi, atau giliran.

## Bagian-bagian

| Bagian | File | Isi |
|---|---|---|
| Profil | `base.py` | `ProviderProfile`: deklarasi satu provider (endpoint, auth, protokol, keanehan) |
| Registry | `registry.py` | Empat lapis penemuan profil |
| Resolusi | `runtime.py` | `resolve_runtime_provider` menghasilkan `RuntimeRoute` |
| Kredensial | `credentials.py` | Kumpulan kunci per provider dan rotasinya |
| Transport | `transports/` | Satu kelas per protokol kawat (`api_mode`) |
| HTTP | `http.py` | `HttpClient` dari pustaka standar, bisa dibatalkan, sadar proxy |
| Klien | `client.py` | `LLMClient.complete`: satu panggilan, streaming atau tidak |
| Galat | `errors.py` | `classify_api_error` menghasilkan `ClassifiedError` dengan petunjuk pemulihan |
| Katalog | `models.py` | Daftar model (langsung, cache, cadangan) dan panjang konteks |
| Lain-lain | `auxiliary.py`, `model_switch.py`, `testing.py` | Tugas sampingan, pergantian model, klien uji |

## Kontrak

**Profil dan registry**
- Menambah provider adalah menambah satu direktori berisi profil. Tidak ada
  `if provider == ...` di kode inti. Keanehan provider masuk ke method yang di-override:
  `get_headers`, `prepare_messages`, `build_extra_body`, `wants_cache_markers`,
  `resolve_temperature`, `replay_is_prefix_bound`, `get_max_tokens`,
  `get_model_context_length`.
- Lapisan registry, yang belakangan menang: bawaan paket, plugin umum
  (`ctx.register_provider`), `<home>/plugins/model-providers/` (per profil), bagian
  `providers:` di config (per profil).
- Satu profil rusak tidak menyembunyikan profil lain.

**Resolusi rute**
- Urutan: argumen eksplisit, lalu config, lalu deteksi otomatis (provider pertama yang punya
  kunci; provider lokal dan `custom` tidak pernah dipilih otomatis).
- `model.base_url`, `model.api_mode`, `model.default`, `model.context_length` milik provider
  yang disebut config. Bila pemanggil meminta provider lain, nilai itu tidak ikut.
- Kunci provider hanya dikirim ke host asal kunci itu. Bila provider diarahkan ke host lain,
  kuncinya tidak ikut dan galatnya menyebut `model.api_key_env`.
- Base URL yang berakhiran `/anthropic` dianggap proxy kompatibel Anthropic.
- Tanpa provider yang terkonfigurasi, galatnya menjelaskan apa yang harus dilakukan.
- `RuntimeRoute.describe()` tidak pernah memuat kunci.

**Transport**
- Format internal adalah gaya OpenAI. Transport mengonversi pada salinan dan tidak mengubah
  riwayat. Kunci internal (`_row_id`, `timestamp`, `reasoning`, `provider_data`,
  `turn_context`, dan lain-lain) tidak pernah sampai ke kawat.
- `chat_completions`: tool call yang terpecah di stream dirakit ulang; `stream_options`
  meminta usage; penanda cache dipindah ke bagian konten.
- `anthropic_messages`: system dipisah, hasil tool dibungkus, pesan berperan sama yang
  berurutan digabung, blok penalaran bertanda tangan diputar ulang apa adanya dari
  `provider_data["anthropic_blocks"]`, tool memakai `input_schema`.
- `mock`: jawaban deterministik tanpa jaringan untuk demo dan tes ujung ke ujung.

**Panggilan**
- `cancel` (sebuah `threading.Event`) membatalkan panggilan dari thread lain dengan menutup
  soket. Pemanggil menerima `InterruptedError`.
- Batas waktu sambung (30 detik) terpisah dari batas waktu baca (`agent.api_timeout`).
- Alamat loopback tidak pernah lewat proxy.

**Galat**
- Loop tidak pernah melihat kode status. Ia menerima `ClassifiedError` dengan petunjuk:
  `retryable`, `should_compress`, `should_rotate_credential`, `should_fallback`,
  `should_drop_replay`, `retry_after`.
- Pemeriksaan isi pesan didahulukan dari kode status, karena provider tidak sepakat status
  mana membawa masalah apa.

**Kredensial**
- Untuk variabel `X_API_KEY`, kumpulan kunci juga memuat `X_API_KEY_2` sampai `_9`. Kunci yang
  kena batas laju atau galat tagihan diistirahatkan selama masa jeda, kunci berikutnya maju.

**Katalog model**
- Daftar model: cache segar (6 jam), lalu ambil langsung, lalu cache basi, lalu
  `fallback_models` profil.
- Panjang konteks: override pengguna, lalu profil (awalan terpanjang yang cocok), lalu
  katalog cache, lalu 128 ribu.

**Tugas sampingan**
- `call_auxiliary(task, ...)` tidak pernah melewati riwayat percakapan, jadi tidak mengganggu
  cache. Rutenya dari `auxiliary.<task>`; `provider: main` memakai rute utama dengan model
  murah milik profil bila ada. Rute yang tidak bisa dipakai jatuh ke rute utama.

## Aturan model Claude yang sudah diverifikasi

Dari dokumentasi Anthropic (model overview dan panduan migrasi Fable 5.1), dibaca 5 Oktober
2026. Semua ada di `bundled/plugins/model-providers/anthropic/__init__.py`.

| Hal | Model 5-series (Fable 5.x, Opus 5.x, Sonnet 5.5) | Generasi 4.5 dan sebelumnya |
|---|---|---|
| Penalaran | `thinking: {type: adaptive}` + `output_config: {effort}` | `thinking: {type: enabled, budget_tokens}` |
| Mematikan penalaran | Ditolak (400) di Fable dan Opus 5.5 | Bisa |
| `temperature` | Tidak dikirim (ditolak di Fable) | Dikirim bila penalaran mati |
| Jendela konteks | 1 juta token | 200 ribu token |
| Keluaran maksimum | 128 ribu token | 64 ribu (Haiku 4.5) |
| Blok penalaran | Terikat ke model dan ke percakapan sebelumnya | Tidak terikat ke awalan |
| `tool_choice` paksa, prefill asisten | Ditolak (400). C-lite tidak memakai keduanya | - |

Akibat untuk C-lite: riwayat yang dikirim tidak boleh berubah (lihat
[agent](agent.md), bagian Prompt dan cache), dan `provider_data` dibuang saat kompresi, saat
ganti model, dan saat provider menolaknya (`FailoverReason.THINKING_SIGNATURE`).

## Status fitur

| Fitur | Status | Catatan |
|---|---|---|
| Profil, registry berlapis, provider dari config | ✅ | |
| Resolusi rute, fallback, kumpulan kredensial | ✅ | |
| Transport `chat_completions`, `anthropic_messages`, `mock` | ✅ | Diuji terhadap server HTTP tiruan lokal |
| Panggilan ke provider sungguhan | ⬜ belum diverifikasi | F1-T2 |
| Transport `responses` (OpenAI Responses API) | ⬜ | Konstanta `API_MODE_RESPONSES` sudah ada: F2-T1 |
| Profil bawaan | 🟡 | 8: anthropic, openai, openrouter, gemini, deepseek, ollama, custom, mock. Tambahan: F2-T2 |
| Harga dan estimasi biaya | ⬜ | F2-T3 |
| OAuth, `clite auth`, kredensial di luar `.env` | ⬜ | F2-T14 |
| Tampilan progres penalaran (`thinking.display`) | ⬜ | Model 5-series menyembunyikan teks di antara tool call secara default: F1-T2 |
| Bedrock, Vertex, Azure | ⬜ | F2-T2 |

## Yang sengaja berbeda dari Hermes

- **HTTP dari pustaka standar.** Hermes memakai SDK `openai` dan `anthropic` serta `httpx`. Di
  sini satu `HttpClient` di atas `http.client`, supaya pembatalan lewat soket bisa diandalkan
  dan ketergantungan tetap sedikit.
- **Satu jalur kode per protokol.** Hermes punya adapter khusus per vendor (Codex, Bedrock,
  Gemini native). Di sini hanya transport per `api_mode`; vendor yang berbeda adalah profil.
- **Provider `mock` bawaan** supaya setiap surface bisa dijalankan dan diuji tanpa kunci.

## Celah yang diketahui

- `default_model` kosong di semua profil bawaan kecuali `mock`: pengguna harus memilih model
  lewat `clite setup` atau `clite model`.
- `fallback_models` dan `context_lengths` adalah daftar tangan yang akan usang. Katalog
  langsung adalah sumber kebenaran; daftar itu hanya cadangan.
- Tidak ada pengukuran token dengan tokenizer provider.
