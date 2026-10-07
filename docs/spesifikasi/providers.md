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
  `resolve_api_mode`, `get_headers`, `prepare_messages`, `build_extra_body`, `wants_cache_markers`,
  `resolve_temperature`, `replay_is_prefix_bound`, `get_max_tokens`,
  `get_model_context_length`, `resolve_base_url`, `resolve_credential`, `prepare_request`,
  dan `authenticate_request`. Dua method terakhir berjalan pada permintaan akhir; origin
  diperiksa sebelum autentikasi dan diperiksa lagi sesudahnya.
- Lapisan registry, yang belakangan menang: bawaan paket, plugin umum
  (`ctx.register_provider`), `<home>/plugins/model-providers/` (per profil), bagian
  `providers:` di config (per profil).
- Satu profil rusak tidak menyembunyikan profil lain.
- Mendaftarkan profil juga mendaftarkan `env_vars`-nya sebagai kredensial
  (`core.env.register_secret`), sehingga kunci itu tidak pernah sampai ke perintah yang
  dijalankan agent dan nilainya diredaksi dari transkrip.

**Resolusi rute**
- Urutan: argumen eksplisit, lalu config, lalu deteksi otomatis (provider pertama yang punya
  kunci; provider lokal dan `custom` tidak pernah dipilih otomatis).
- `model.base_url`, `model.api_mode`, `model.default`, `model.context_length` milik provider
  yang disebut config. Bila pemanggil meminta provider lain, nilai itu tidak ikut.
- Kunci provider hanya dikirim ke origin asalnya (skema, host, dan port). Bila provider
  diarahkan ke origin lain, kuncinya tidak ikut dan galatnya menyebut `model.api_key_env`.
- Rute mengikat origin dan variabel kumpulan kunci saat resolusi. `model.api_key_env`
  memiliki kumpulan bernomor sendiri; rotasi tidak pernah mengambil kunci profil vendor.
  `LLMClient.complete` dan katalog model memeriksa kembali origin URL permintaan sebelum
  mengirim lewat HTTP, termasuk URL katalog khusus profil.
  Kunci eksplisit tidak diputar ke kumpulan lain. Perubahan origin membutuhkan resolusi baru.
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
- `responses`: pesan internal menjadi item `input`, tool menjadi fungsi Responses, dan stream
  dirakit dari event berindeks. Item `output` lengkap (penalaran terenkripsi, pesan, dan
  `function_call`) disimpan di `provider_data["responses_output"]`, lalu diputar ulang apa
  adanya tanpa `previous_response_id`; permintaan memakai `store: false`. Respons tidak lengkap
  tidak menjalankan argumen tool yang mungkin terpotong.
- Profil `openai` memilih `responses` untuk `gpt-5-codex` lewat `resolve_api_mode`.
  `model.api_mode` eksplisit tetap menang, juga sesudah `/model`.
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
- Kode galat Responses (`invalid_encrypted_content`, `invalid_api_key`, `rate_limit_exceeded`,
  `server_error`, dan kode yang sudah dikenali lewat frasa) diklasifikasikan meskipun `type`
  bersifat umum. Event `response.failed`, `error`, dan stream terputus menjadi galat.
- Pemeriksaan isi pesan didahulukan dari kode status, karena provider tidak sepakat status
  mana membawa masalah apa.

**Kredensial**
- Untuk variabel `X_API_KEY`, kumpulan kunci juga memuat `X_API_KEY_2` sampai `_9`. Kunci yang
  kena batas laju atau galat tagihan diistirahatkan selama masa jeda, kunci berikutnya maju.
- State masa jeda dipisahkan menurut home, provider, variabel kumpulan, dan origin endpoint.
- Regresi endpoint kustom untuk 401/403/429/402 dijaga di `tests/agent/test_loop.py`;
  penolakan origin sebelum HTTP dijaga di `tests/providers/test_client.py`.

**Katalog model**
- Daftar model: cache segar (6 jam), lalu ambil langsung, lalu cache basi, lalu
  `fallback_models` profil.
- Rute eksplisit tanpa kunci tidak meminjam kumpulan vendor untuk permintaan katalog.
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
| Teks penalaran | Disembunyikan secara default (`display: omitted`); C-lite mengirim `thinking.display: summarized` bila `display.show_reasoning` aktif (dokumentasi dibaca 6 Oktober 2026) | Ringkasan dikirim secara default |

Akibat untuk C-lite: riwayat yang dikirim tidak boleh berubah (lihat
[agent](agent.md), bagian Prompt dan cache), dan `provider_data` dibuang saat kompresi, saat
ganti model, dan saat provider menolaknya (`FailoverReason.THINKING_SIGNATURE`).

## Profil tambahan F2-T2: kontrak dan bukti API asli

Gelombang pertama memakai transport `chat_completions` yang ada. Endpoint dan model
cadangan diambil dari dokumentasi resmi yang dibaca 7 Oktober 2026; URL sumber ada di
docstring masing-masing profil. Ini bukan hasil panggilan API. Daftar pendek cadangan
bisa usang atau membutuhkan akses akun/deployment tertentu; pilih model dari katalog
langsung bila tersedia. Semua profil baru mempertahankan `default_model` kosong.

| Profil | Variabel kunci | Base URL | Diuji terhadap API asli pada tanggal |
|---|---|---|---|
| `xai` | `XAI_API_KEY` | https://api.x.ai/v1 | Belum pernah |
| `groq` | `GROQ_API_KEY` | https://api.groq.com/openai/v1 | Belum pernah |
| `mistral` | `MISTRAL_API_KEY` | https://api.mistral.ai/v1 | Belum pernah |
| `together` | `TOGETHER_API_KEY` | https://api.together.ai/v1 | Belum pernah |
| `fireworks` | `FIREWORKS_API_KEY` | https://api.fireworks.ai/inference/v1 | Belum pernah |
| `nvidia` | `NVIDIA_API_KEY` | https://integrate.api.nvidia.com/v1 | Belum pernah |
| `zai` | `ZAI_API_KEY` | https://api.z.ai/api/paas/v4 | Belum pernah |
| `moonshot` | `MOONSHOT_API_KEY` | https://api.moonshot.ai/v1 | Belum pernah |
| `lmstudio` | Tidak ada (lokal tanpa autentikasi) | http://localhost:1234/v1 | Belum pernah |
| `vllm` | Tidak ada (lokal tanpa autentikasi) | http://localhost:8000/v1 | Belum pernah |

- Masing-masing menyediakan variabel override dengan nama profil huruf besar diikuti
  `_BASE_URL` (misalnya `LMSTUDIO_BASE_URL`). Kunci vendor tidak ikut berpindah origin;
  endpoint lain yang berkunci membutuhkan `model.api_key_env` eksplisit.
- LM Studio/vLLM harus dipilih eksplisit (`auto_select=False`), lalu pilih ID model yang
  benar-benar dilayani. `env_vars`, `fallback_models`, dan `context_lengths` sengaja kosong:
  server lokal tidak punya katalog universal. Isi `model.context_length` sesuai konfigurasi
  server; jangan menganggap nilai fallback generik sebagai kemampuan deployment.
- Profil lokal ini khusus server tanpa autentikasi. Untuk server yang memakai token,
  gunakan profil kustom melalui bagian `providers:` dengan `api_key_env`; rahasia di `.env`.
- Z.ai memakai endpoint umum, bukan endpoint langganan Coding Plan. Base URL bisa diganti
  eksplisit mengikuti aturan origin dan kredensial di atas.
- Untuk `kimi-k2.6`, profil Moonshot tidak mengirim `temperature`; server menentukan nilai
  tetap berdasarkan mode thinking. Model lain tidak diubah. Pengaturan penalaran khusus dan
  replay reasoning per vendor tidak ditambahkan dalam gelombang deklaratif ini.
- Profil lama `anthropic`, `openai`, `openrouter`, `gemini`, `deepseek`, `ollama`, dan `custom`
  juga belum pernah diuji terhadap layanan asli dalam proyek ini; `mock` tidak memakai API.
  Gelombang cloud di bawah juga belum pernah dipanggil sungguhan, sehingga **F2-T2 tetap
  parsial** sampai bukti API asli tersedia.

### Gelombang cloud F2-T2

Sumber resmi dibaca 7 Oktober 2026 dan dicatat di docstring profil. Semua bukti di bawah
berasal dari HTTP loopback dan kredensial sintetis, bukan API asli.

| Profil | Rahasia | Endpoint | Autentikasi | Diuji terhadap API asli pada tanggal |
|---|---|---|---|---|
| `azure` | `AZURE_OPENAI_API_KEY` | `AZURE_OPENAI_ENDPOINT` atau `model.base_url`, root resource dengan `?api-version=` opsional | Header `api-key`; model adalah nama deployment | Belum pernah |
| `bedrock` | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN` opsional | `https://bedrock-runtime.REGION.amazonaws.com/openai/v1` lewat `model.base_url` | SigV4 layanan `bedrock` per permintaan; extra `c-lite[bedrock]` | Belum pernah |
| `vertex` | `GOOGLE_SERVICE_ACCOUNT_JSON` | Endpoint OpenAI-compatible regional Vertex lewat `model.base_url` | Token OAuth akun layanan, scope cloud-platform; extra `c-lite[vertex]` | Belum pernah |

- Azure membangun `/openai/deployments/<deployment>/chat/completions?api-version=...`,
  menghapus `model` dari body, dan memakai versi default `2024-10-21` bila URL tidak
  menyebutnya. URL dengan path, fragmen, parameter lain, atau versi kosong/ganda ditolak.
- Bedrock menandatangani byte UTF-8 yang sama dengan yang dikirim, termasuk token sesi.
  Kredensial dari lingkungan hanya diberikan ke host HTTPS `bedrock-runtime` resmi; endpoint
  lain membutuhkan JSON kredensial eksplisit. Profil ini hanya Chat Completions, bukan
  Converse/InvokeModel.
- Vertex memvalidasi JSON akun layanan dan token URI standar. Tukar token memakai seam
  `HttpClient` dan sinyal batal yang sama, dilakukan sebelum setiap permintaan inferensi, dan
  galatnya tidak memuat isi respons token. Tidak ada credential chain SDK atau file kunci
  eksternal.
- Ketiganya tidak dipilih otomatis, tidak mengambil katalog, dan tidak mengarang model atau
  ukuran konteks. Tanpa extra, profil tetap muncul di setup; pemakaian SigV4/token gagal
  sebelum HTTP dengan perintah instalasi extra.

## Status fitur

| Fitur | Status | Catatan |
|---|---|---|
| Profil, registry berlapis, provider dari config | ✅ | |
| Resolusi rute, fallback, kumpulan kredensial | ✅ | |
| Transport `chat_completions`, `anthropic_messages`, `mock` | ✅ | Diuji terhadap server HTTP tiruan lokal |
| Panggilan ke provider sungguhan | ⬜ belum diverifikasi | F1-T2 |
| Transport `responses` (OpenAI Responses API) | 🟡 | Streaming dan nonstreaming, replay dua ronde tool, awalan kawat, pemilihan profil, dan galat diuji terhadap `fake_api`. Tes jaringan ditulis, belum dijalankan: F2-T1 |
| Profil bawaan | 🟡 | 21 profil; tiga profil cloud F2-T2 dijaga `tests/providers/test_cloud_profiles.py`; sepuluh tambahan gelombang pertama F2-T2 dijaga tes rute/HTTP lokal dan discovery setup. API asli semua profil tersebut belum diuji |
| Harga dan estimasi biaya | ⬜ | F2-T3 |
| OAuth, `clite auth`, kredensial di luar `.env` | ⬜ | F2-T14 |
| Tampilan teks penalaran (`thinking.display`) | 🟡 | Profil `anthropic` meminta `summarized` bila `display.show_reasoning` aktif; dijaga `test_anthropic_asks_for_summarized_thinking_only_when_reasoning_is_shown`. Belum dicoba ke API asli: F1-T2 |
| Tes terhadap API asli (`tests/providers/test_live.py`) | 🟡 | Ditulis; dilewati tanpa kunci. Belum pernah dijalankan: F1-T2 |
| Bedrock, Vertex, Azure | ⬜ | Gelombang kedua F2-T2; task tetap parsial |

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
