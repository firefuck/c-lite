# Fase 2: inti agent

Fase ini menambah kemampuan yang membuat agent layak dipakai untuk pekerjaan harian: lebih
banyak provider, tool yang belum ada, dan perbaikan pada loop. Hampir semuanya menempel di
tepi (profil provider, tool, backend lingkungan), sesuai aturan "inti sempit". Bila sebuah
task terasa menuntut perubahan besar di `src/clite/agent/agent.py` atau
`src/clite/agent/loop.py`, baca ulang
[invarian B5](../arsitektur/03-invarian.md#b5-fasad-tetap-fasad) lebih dulu.

Task di fase ini saling lepas, kecuali yang disebut di "Bergantung pada". Urutan yang
disarankan bila tidak ada kebutuhan khusus: F2-T4, F2-T5, F2-T8, F2-T3, F2-T2, F2-T11, lalu
sisanya.

Aturan yang berlaku untuk semua task ada di [README](README.md#selesai-itu-apa).

---

### F2-T1 Transport Responses API

**Tujuan.** Model yang hanya tersedia lewat OpenAI Responses API bisa dipakai, dengan
penalaran dan tool call yang diputar ulang dengan benar antar-iterasi.

**Lingkup.**
- Kelas `ProviderTransport` baru untuk `api_mode: responses`: konversi pesan internal ke
  daftar `input`, tool ke bentuk Responses, dan akumulator stream untuk event-nya.
- Item penalaran yang harus dikirim kembali disimpan di `provider_data`, mengikuti pola
  transport Anthropic. Aturan A2 berlaku: yang sudah dikirim tidak berubah.
- Profil `openai` memilih `responses` untuk model yang membutuhkannya lewat method profil,
  bukan lewat nama model di kode inti.
- Klasifikasi galat untuk bentuk galat Responses.

**File.** `src/clite/providers/transports/responses.py (baru)`, `src/clite/providers/base.py`,
`src/clite/providers/client.py`, `src/clite/bundled/plugins/model-providers/openai/__init__.py`,
`tests/providers/test_transports.py`, `tests/providers/test_client.py`.

**Rujukan Hermes.** `agent/transports/codex.py`, `agent/codex_responses_adapter.py`,
`agent/transports/base.py`, `agent/transports/types.py`.

**Selesai bila.**
- [ ] Giliran dengan dua ronde tool lewat `fake_api` yang berbicara Responses lulus, streaming
      dan tidak.
- [ ] Tes awalan kawat (`test_every_request_repeats_the_previous_one_and_adds_to_its_end`)
      punya padanan untuk transport ini.
- [ ] Satu tes `network` terhadap API asli.
- [ ] Baris "Transport `responses`" di spesifikasi providers menjadi ✅.

**Ukuran.** M

**Bergantung pada.** F1-T2

**Butuh dari Anda.** `OPENAI_API_KEY` untuk tes jaringan.

---

### F2-T2 Profil provider tambahan

**Tujuan.** Pengguna bisa memilih dari jauh lebih banyak provider tanpa menulis profil sendiri,
termasuk yang autentikasinya bukan kunci API biasa.

**Lingkup.**
- Gelombang pertama, profil kompatibel OpenAI yang hanya butuh deklarasi: xAI, Groq, Mistral,
  Together, Fireworks, NVIDIA, Z.ai, Moonshot, LM Studio, vLLM. Satu direktori per provider.
- Gelombang kedua, yang butuh kode: Azure OpenAI (nama deployment, versi API di URL), AWS
  Bedrock (tanda tangan SigV4, bisa sebagai transport sendiri), Google Vertex (token dari
  kredensial layanan). Dependensi tambahan masuk ke extra di `pyproject.toml`, bukan ke
  dependensi wajib.
- Setiap profil: `env_vars`, `base_url`, `fallback_models`, `context_lengths`, dan override
  hanya untuk keanehan yang terbukti ada.
- Halaman `docs/spesifikasi/providers.md` mendapat tabel "diuji terhadap API asli pada
  tanggal" per profil. Profil yang belum pernah dipanggil sungguhan ditandai demikian.

**File.** `src/clite/bundled/plugins/model-providers/ (direktori baru per provider)`,
`src/clite/providers/transports/bedrock.py (baru, bila perlu)`, `pyproject.toml`,
`tests/providers/test_registry_and_runtime.py`, `docs/spesifikasi/providers.md`.

**Rujukan Hermes.** `plugins/model-providers/` (satu direktori per provider; baca yang
sepadan), `providers/base.py`, `agent/bedrock_adapter.py`, `agent/vertex_adapter.py`,
`agent/azure_identity_adapter.py`, `website/docs/developer-guide/adding-providers.md`,
`website/docs/developer-guide/model-provider-plugin.md`.

**Selesai bila.**
- [ ] Setiap profil baru punya tes resolusi rute dan bentuk permintaan terhadap `fake_api`.
- [ ] `test_vendors_are_named_only_in_their_provider_profiles` tetap lulus: tidak ada nama
      provider baru di luar direktori profilnya.
- [ ] `clite setup` menampilkan provider baru tanpa perubahan di kode setup.
- [ ] Tabel status per profil jujur tentang mana yang sudah dipanggil sungguhan.

**Ukuran.** M

**Bergantung pada.** F1-T2

**Butuh dari Anda.** Kunci untuk provider yang ingin Anda tandai "sudah diuji".

---

### F2-T3 Harga dan estimasi biaya

**Tujuan.** `/usage`, `clite sessions list`, dan event `turn.complete` menunjukkan perkiraan
biaya dalam dolar, dihitung dari token yang benar-benar dilaporkan provider.

**Lingkup.**
- Sumber harga berlapis: override pengguna di config, lalu harga yang dideklarasikan profil
  provider, lalu katalog model yang di-cache bila provider melaporkannya (OpenRouter).
- Empat tarif per model: masukan, keluaran, baca cache, tulis cache.
- Kolom `estimated_cost_usd` di tabel `sessions` diisi oleh `record_usage`.
- Tanpa harga yang diketahui, biaya ditampilkan sebagai tidak diketahui, bukan nol.

**File.** `src/clite/providers/pricing.py (baru)`, `src/clite/providers/base.py`,
`src/clite/providers/models.py`, `src/clite/agent/agent.py`, `src/clite/state/db.py`,
`src/clite/runtime/slash.py`, `src/clite/rpc/contracts/schema.py`,
`src/clite/core/config_defaults.py`.

**Rujukan Hermes.** `agent/usage_pricing.py`, `hermes_cli/models_pricing.py`,
`agent/models_dev.py`.

**Selesai bila.**
- [ ] Tes: biaya satu giliran dengan cache baca dan tulis dihitung benar dari tarif profil.
- [ ] Tes: model tanpa harga menghasilkan "tidak diketahui" di `/usage` dan `null` di RPC.
- [ ] Harga profil `anthropic` diisi dari halaman harga resmi, dengan tanggal pengambilan di
      komentar.
- [ ] Baris "Estimasi biaya" di spesifikasi agent, state, dan providers menjadi ✅.

**Ukuran.** S

**Bergantung pada.** F1-T2

---

### F2-T4 Patch toleran dan patch multi-file

**Tujuan.** Model lebih jarang gagal menyunting file karena selisih spasi atau kutipan, dan
bisa mengubah beberapa file dalam satu panggilan.

**Lingkup.**
- Rantai pencocokan untuk `old_string` yang tidak ditemukan persis: spasi di ujung baris,
  indentasi, kutipan tipografis, baris kosong. Setiap tingkat hanya diterima bila hasilnya
  unik. Hasil tool menyebut tingkat mana yang dipakai.
- Mode kedua pada tool `patch`: satu teks patch berformat V4A (`*** Update File`, `*** Add
  File`, `*** Delete File`) yang menyentuh beberapa file. Diterapkan seluruhnya atau tidak
  sama sekali.
- Semua path tetap melewati `write_denied_reason`, dan diff yang dikembalikan tetap diredaksi.

**File.** `src/clite/tools/builtin/file_tools.py`, `src/clite/tools/patching.py (baru)`,
`tests/tools/test_file_tools.py`.

**Rujukan Hermes.** `tools/fuzzy_match.py`, `tools/patch_parser.py`,
`tools/file_operations.py`.

**Selesai bila.**
- [ ] Tes per tingkat pencocokan, masing-masing dengan kasus "cocok unik" dan "ambigu ditolak".
- [ ] Tes: patch multi-file yang gagal di file ketiga tidak mengubah file pertama dan kedua.
- [ ] Tes: patch multi-file yang menyebut `.env` milik agent ditolak seluruhnya.
- [ ] Baris tool file di spesifikasi tools diperbarui.

**Ukuran.** M

**Bergantung pada.** -

---

### F2-T5 Pencarian web

**Tujuan.** Model bisa mencari di web, bukan hanya mengambil URL yang sudah diketahui.

**Lingkup.**
- Antarmuka `WebSearchProvider` dengan registry, mengikuti pola `register_context_engine`, dan
  `ctx.register_web_search_provider` di `PluginContext`.
- Tool `web_search` di toolset `web`. `check_fn`-nya lulus hanya bila ada provider yang
  terkonfigurasi, sehingga tool tidak ditawarkan tanpa backend.
- Dua provider bawaan sebagai plugin berjenis `backend`: satu tanpa kunci (SearXNG yang
  dihosting sendiri atau DuckDuckGo) dan satu berkunci (Tavily, Brave, atau Exa).
- Hasil: judul, URL, cuplikan. Cuplikan adalah teks tak tepercaya; ia masuk sebagai hasil
  tool, tidak pernah ke system prompt.
- Skill bawaan pengganti dengan `fallback_for_tools: [web_search]` yang menjelaskan cara
  bekerja tanpa pencarian.

**File.** `src/clite/tools/builtin/web.py`, `src/clite/tools/web_search.py (baru)`,
`src/clite/plugins/context.py`, `src/clite/bundled/plugins/ (plugin provider baru)`,
`src/clite/core/config_defaults.py`, `tests/tools/test_web.py`.

**Rujukan Hermes.** `tools/web_tools.py`, `agent/web_search_provider.py`,
`agent/web_search_registry.py`, `plugins/web/`,
`website/docs/developer-guide/web-search-provider-plugin.md`.

**Selesai bila.**
- [ ] Tes: `web_search` tidak ada di definisi tool tanpa provider, dan ada dengan provider.
- [ ] Tes terhadap server HTTP lokal yang meniru API pencarian.
- [ ] Kunci provider pencarian terdaftar sebagai kredensial (`register_secret`).
- [ ] Baris `web_search` di spesifikasi tools menjadi ✅.

**Ukuran.** M

**Bergantung pada.** -

---

### F2-T6 Gambar: masukan, analisis, pembuatan

**Tujuan.** Pengguna bisa melampirkan gambar ke pesannya, model tanpa penglihatan tetap bisa
"melihat" lewat model bantu, dan agent bisa membuat gambar.

**Lingkup.** Tiga langkah, masing-masing satu commit yang berdiri sendiri.
1. **Masukan.** `clite chat --image <path>`, `/image <path>` di semua surface, dan lampiran
   pada `prompt.submit` (bidang opsional baru). Gambar menjadi bagian konten pada pesan
   pengguna; transport sudah meneruskan konten berstruktur. Batas ukuran dan jumlah, pengecilan
   bila terlalu besar.
2. **Analisis.** Tool `vision_analyze` yang mengirim gambar ke rute `auxiliary.vision`, untuk
   model utama yang tidak menerima gambar. Profil provider menyatakan model mana yang menerima
   gambar.
3. **Pembuatan.** Antarmuka `ImageProvider` dengan registry, tool `image_generate`, dan satu
   plugin provider.
- Kompresi membuang gambar lama lebih dulu daripada teks (lihat F2-T11).

**Di luar lingkup.** Lampiran di platform pesan (F4-T4) dan di aplikasi desktop (F5-T5).

**File.** `src/clite/cli/subcommands/chat.py`, `src/clite/runtime/session.py`,
`src/clite/runtime/commands.py`, `src/clite/rpc/contracts/schema.py`,
`src/clite/rpc/methods.py`, `src/clite/agent/attachments.py (baru)`,
`src/clite/tools/builtin/vision.py (baru)`, `src/clite/tools/builtin/image_gen.py (baru)`,
`src/clite/providers/base.py`, `src/clite/core/config_defaults.py`.

**Rujukan Hermes.** `tools/vision_tools.py`, `agent/vision_message_prep.py`,
`agent/image_routing.py`, `tools/image_generation_tool.py`, `agent/image_gen_provider.py`,
`agent/image_gen_registry.py`, `plugins/image_gen/`, `tui_gateway/prompt_attachments.py`.

**Selesai bila.**
- [ ] Tes: giliran dengan gambar mengirim bagian konten yang benar di kedua transport, dan
      pesan itu dikirim ulang persis sama di giliran berikutnya.
- [ ] Tes: model yang dinyatakan tanpa penglihatan tidak pernah menerima bagian gambar.
- [ ] Tes: gambar tersimpan di database tanpa membengkakkan pencarian teks.
- [ ] Baris "Input gambar" dan "Analisis gambar, pembuatan gambar" di spesifikasi menjadi ✅.

**Ukuran.** L

**Bergantung pada.** F1-T2

---

### F2-T7 Backend terminal Docker dan SSH

**Tujuan.** Perintah dan operasi file agent bisa berjalan di dalam container atau di mesin
lain, sehingga ada batas nyata antara agent dan mesin pengguna.

**Lingkup.**
- `DockerEnvironment` dan `SSHEnvironment` sebagai turunan `BaseEnvironment`, didaftarkan
  dengan `register_environment_backend`, dipilih lewat `terminal.backend`.
- Tool file saat ini membaca dan menulis sistem file lokal secara langsung. Perluas
  `BaseEnvironment` dengan operasi file (baca, tulis, daftar, stat) dan arahkan
  `read_file`, `write_file`, `patch`, dan `search_files` lewat lingkungan sesi.
  `LocalEnvironment` mengimplementasikannya dengan kode yang sekarang.
- Docker: image dan mount dari config, satu container per `task_id`, dibersihkan saat sesi
  ditutup, direktori kerja di-mount, tanpa kredensial host kecuali yang disebut.
- SSH: host dan kunci dari config, satu koneksi per `task_id`.
- Gerbang persetujuan tetap berlaku di semua backend.

**Di luar lingkup.** Backend cloud (Modal, Daytona, dan sejenisnya); bisa menyusul sebagai
plugin.

**File.** `src/clite/tools/environments/base.py`, `src/clite/tools/environments/local.py`,
`src/clite/tools/environments/docker.py (baru)`, `src/clite/tools/environments/ssh.py (baru)`,
`src/clite/tools/builtin/file_tools.py`, `src/clite/tools/builtin/process.py`,
`src/clite/core/config_defaults.py`, `tests/tools/test_environments.py (baru)`.

**Rujukan Hermes.** `tools/environments/base.py`, `tools/environments/docker.py`,
`tools/environments/ssh.py`, `tools/environments/file_sync.py`, `tools/credential_files.py`,
`website/docs/developer-guide/terminal-environment-plugin.md`.

**Selesai bila.**
- [ ] Suite tool file dan terminal yang ada lulus terhadap `LocalEnvironment` lewat antarmuka
      baru, tanpa perubahan perilaku.
- [ ] Suite yang sama dijalankan terhadap Docker (tes bertanda khusus, terlewati tanpa
      Docker) dan lulus.
- [ ] Tes: file di luar mount tidak terbaca dari dalam container.
- [ ] Dokumen keamanan diperbarui: baris "Tidak ada sandbox" berubah menjadi penjelasan cara
      mengaktifkannya.

**Ukuran.** L

**Bergantung pada.** -

**Butuh dari Anda.** Docker di mesin pengembangan untuk menjalankan tesnya.

---

### F2-T8 Checkpoint dan rollback file

**Tujuan.** Setiap perubahan file oleh agent bisa dibatalkan dengan `/rollback`.

**Lingkup.**
- Sebelum `write_file` atau `patch` mengubah sebuah file, isi lamanya disimpan ke penyimpanan
  checkpoint milik sesi di `<home>/checkpoints/<id sesi>/`, dikelompokkan per giliran.
- `/rollback` mengembalikan perubahan giliran terakhir; `/rollback <n>` mundur beberapa
  giliran; `/checkpoints` mendaftarnya.
- Batas ukuran total dan pemangkasan mengikuti `sessions.retention_days`.
- File yang dibuat agent dihapus saat rollback; file yang dihapus dikembalikan.

**Di luar lingkup.** Perubahan yang dibuat perintah terminal. Itu tidak terlihat oleh tool
file; dokumentasikan batas ini dengan jelas.

**File.** `src/clite/tools/checkpoints.py (baru)`, `src/clite/tools/builtin/file_tools.py`,
`src/clite/runtime/commands.py`, `src/clite/runtime/slash.py`,
`src/clite/runtime/maintenance.py`, `src/clite/core/constants.py`,
`tests/tools/test_checkpoints.py (baru)`.

**Rujukan Hermes.** `tools/checkpoint_manager.py`, `tools/checkpoint_pruning.py`,
`hermes_cli/subcommands/checkpoints.py`.

**Selesai bila.**
- [ ] Tes: tulis, patch, dan buat file dalam satu giliran, lalu `/rollback` mengembalikan
      ketiganya.
- [ ] Tes: checkpoint tidak pernah menyimpan file yang ditolak `read_denied_reason`.
- [ ] Tes: pemangkasan menghapus checkpoint sesi yang sudah dipangkas.
- [ ] Baris checkpoint di spesifikasi agent, tools, dan runtime menjadi ✅.

**Ukuran.** M

**Bergantung pada.** -

---

### F2-T9 Eksekusi kode

**Tujuan.** Model bisa menjalankan skrip Python pendek untuk menghitung atau mengolah data,
tanpa merangkai banyak perintah shell.

**Lingkup.**
- Tool `execute_code`: menerima kode Python, menjalankannya di lingkungan eksekusi sesi dengan
  batas waktu dan batas keluaran, mengembalikan stdout, stderr, dan kode keluar.
- Kode berjalan lewat backend terminal yang aktif, jadi mewarisi sandbox bila backend-nya
  Docker.
- Kode adalah perintah: ia melewati `check_command` (teks kodenya dipindai dengan pola yang
  sama), kredensial dibuang dari lingkungannya, dan keluarannya diredaksi.
- Di backend `local` tool ini mengikuti `approvals.mode` seperti `terminal`.

**Di luar lingkup.** Memanggil tool agent dari dalam kode (jembatan RPC milik Hermes).

**File.** `src/clite/tools/builtin/code.py (baru)`, `src/clite/tools/toolsets.py`,
`src/clite/tools/approval.py`, `tests/tools/test_code.py (baru)`.

**Rujukan Hermes.** `tools/code_execution_tool.py`, `tools/code_execution_env.py`.

**Selesai bila.**
- [ ] Tes: kode yang melewati batas waktu dimatikan beserta proses anaknya.
- [ ] Tes: kode yang memuat pola berbahaya meminta persetujuan, sama seperti di `terminal`.
- [ ] Tes: variabel kredensial tidak terlihat dari dalam kode.
- [ ] Baris `execute_code` di spesifikasi tools menjadi ✅.

**Ukuran.** M

**Bergantung pada.** F2-T7

---

### F2-T10 MCP: HTTP, resources, prompts, `clite mcp`

**Tujuan.** Server MCP jarak jauh bisa dipakai, bukan hanya proses lokal, dan pengguna
mengelolanya tanpa menyunting YAML.

**Lingkup.**
- Transport Streamable HTTP di samping stdio, dengan header autentikasi dari `.env`.
- Resources dan prompts: tool `mcp_<server>_list_resources`, `mcp_<server>_read_resource`,
  dan prompt server sebagai slash command.
- `clite mcp add | list | remove | test`, dan `/mcp` untuk melihat status.
- Daftar tool server yang berubah (`notifications/tools/list_changed`) tidak mengubah daftar
  tool sesi yang sedang berjalan; perubahan berlaku di sesi berikutnya (aturan A1).
- Server yang mati dihidupkan ulang dengan jeda yang membesar.

**Di luar lingkup.** OAuth untuk server MCP dan sampling. Catat sebagai task baru bila
dibutuhkan.

**File.** `src/clite/tools/mcp/client.py`, `src/clite/tools/mcp/http.py (baru)`,
`src/clite/cli/subcommands/mcp.py (baru)`, `src/clite/cli/main.py`,
`src/clite/runtime/commands.py`, `src/clite/runtime/slash.py`, `tests/tools/test_mcp.py`.

**Rujukan Hermes.** `tools/mcp_tool.py`, `tools/mcp_tool_transport.py`,
`tools/mcp_tool_lifecycle.py`, `hermes_cli/mcp_config.py`, `hermes_cli/subcommands/mcp.py`.

**Selesai bila.**
- [ ] Tes terhadap server MCP HTTP sungguhan yang dijalankan lokal (dari SDK resmi, terlewati
      bila SDK tidak terpasang).
- [ ] Tes: perubahan daftar tool di tengah sesi tidak mengubah definisi tool sesi itu.
- [ ] Tes: `clite mcp add` menulis config lewat `atomic_config_update` dan `clite mcp test`
      melaporkan tool yang ditemukan.
- [ ] Baris MCP di spesifikasi tools dan cli diperbarui.

**Ukuran.** L

**Bergantung pada.** -

---

### F2-T11 Kompresi yang lebih baik

**Tujuan.** Percakapan panjang kehilangan lebih sedikit hal penting saat dikompres, dan
kompresi lebih jarang terjadi terlalu cepat atau terlambat.

**Lingkup.**
- Ringkasan berstruktur dengan bagian tetap: tujuan pengguna, keputusan, file yang disentuh
  beserta keadaannya, perintah yang gagal dan sebabnya, pekerjaan yang belum selesai.
- Peringkasan bertahap bila bagian tengah lebih besar dari jendela model bantu.
- Penghitung token yang lebih tepat: pakai angka `prompt_tokens` terakhir dari provider
  sebagai jangkar, dan perkiraan hanya untuk pesan sesudahnya.
- Gambar lama dibuang lebih dulu daripada teks.
- Penghitung pengingat memori bertahan saat sesi dilanjutkan (celah yang tercatat di
  spesifikasi agent).
- Pengukuran: skrip yang mengompres transkrip contoh dan melaporkan fakta mana yang hilang,
  supaya perubahan prompt ringkasan bisa dibandingkan.

**File.** `src/clite/agent/context/compressor.py`, `src/clite/agent/context/tokens.py`,
`src/clite/agent/context/engine.py`, `src/clite/agent/memory/manager.py`,
`scripts/eval_compression.py (baru)`, `tests/agent/test_compression.py`.

**Rujukan Hermes.** `agent/context_compressor.py`, `agent/context_compressor_summary.py`,
`agent/micro_compaction.py`,
`website/docs/developer-guide/context-compression-and-caching.md`.

**Selesai bila.**
- [ ] Semua tes kompresi yang ada tetap lulus, termasuk aturan `provider_data`.
- [ ] Tes: bagian tengah yang melebihi jendela model bantu diringkas bertahap, tidak dipotong.
- [ ] Tes: perkiraan token sesudah satu respons memakai angka provider sebagai jangkar.
- [ ] Skrip pengukuran berjalan dengan provider `mock` di CI.

**Ukuran.** M

**Bergantung pada.** F1-T2

---

### F2-T12 Review latar belakang dan kurator terjadwal

**Tujuan.** Agent belajar dari pekerjaannya tanpa diminta: fakta yang layak diingat masuk
memori, prosedur yang berhasil menjadi skill, dan skill yang tidak terpakai diarsipkan.

**Lingkup.**
- Setelah giliran yang cukup panjang (jumlah tool call melewati ambang), sebuah agent review
  berjalan di thread latar dengan toolset sempit (`memory` dan `skills`) dan anggaran kecil.
  Ia menerima salinan giliran itu sebagai masukan dan **tidak** menyentuh riwayat sesi utama.
- Review bisa dimatikan, punya batas frekuensi, dan tidak berjalan untuk subagent, cron, atau
  sesi yang sedang sibuk.
- Kurator dijalankan otomatis paling banyak sekali per selang waktu dari
  `run_startup_maintenance`, mengikuti pola auto-prune.
- Hasil review terlihat pengguna: baris status singkat, dan catatan di log.

**File.** `src/clite/agent/review.py (baru)`, `src/clite/agent/turn/finalize.py`,
`src/clite/runtime/maintenance.py`, `src/clite/skills/curator.py`,
`src/clite/core/config_defaults.py`, `tests/agent/test_review.py (baru)`.

**Rujukan Hermes.** `agent/background_review.py`, `agent/review_engine.py`,
`agent/review_idle_queue.py`, `agent/curator.py`.

**Selesai bila.**
- [ ] Tes: review menulis satu entri memori dari giliran yang dibuat-buat, dan riwayat serta
      system prompt sesi utama tidak berubah.
- [ ] Tes: review yang gagal atau kehabisan waktu tidak memengaruhi giliran berikutnya.
- [ ] Tes: kurator berjalan paling banyak sekali per selang, dan kegagalannya tidak
      menghalangi sesi.
- [ ] Baris "Review latar belakang" di spesifikasi agent dan baris kurator di spesifikasi
      skills menjadi ✅.

**Ukuran.** M

**Bergantung pada.** -

---

### F2-T13 Delegasi yang lebih kaya

**Tujuan.** Induk bisa memilih model per subagent, melihat kemajuan mereka dengan rinci, dan
tidak harus menunggu subagent yang lama.

**Lingkup.**
- Argumen `model` per tugas pada `delegate_task`, dibatasi ke provider yang terkonfigurasi.
- Kemajuan: `on_subagent` membawa nama tool, pratinjau argumen, dan jumlah iterasi; event
  `subagent.update` diperluas dengan bidang opsional.
- Delegasi latar: `delegate_task(background=true)` langsung kembali dengan id; hasilnya
  disampaikan ke induk sebagai catatan pada hasil tool berikutnya, mengikuti pola `/steer`
  (tidak pernah menyisipkan ke pesan yang sudah dikirim).
- Peran pengatur: dengan `delegation.max_spawn_depth` lebih dari 1, anak di tingkat tengah
  boleh mendelegasikan lagi dan cucu tidak.

**File.** `src/clite/agent/delegation.py`, `src/clite/tools/builtin/delegate.py`,
`src/clite/rpc/contracts/schema.py`, `src/clite/rpc/session.py`,
`src/clite/cli/repl.py`, `tests/agent/test_memory_and_delegation.py`.

**Rujukan Hermes.** `tools/delegate_tool.py`, `tools/delegate_tool_progress.py`,
`tools/async_delegation.py`, `agent/subagent_lifecycle.py`,
`website/docs/developer-guide/subagent-lifecycle-api.md`.

**Selesai bila.**
- [ ] Tes: tugas dengan `model` berjalan pada rute itu, dan model yang tidak terkonfigurasi
      menjadi hasil galat untuk tugas itu saja.
- [ ] Tes: hasil delegasi latar sampai ke induk tanpa melanggar aturan awalan kawat.
- [ ] Tes: interupsi induk menghentikan subagent latar.
- [ ] Baris delegasi di spesifikasi agent menjadi ✅ untuk ketiga butir.

**Ukuran.** M

**Bergantung pada.** -

---

### F2-T14 OAuth dan `clite auth`

**Tujuan.** Provider yang menyediakan OAuth untuk aplikasi pihak ketiga bisa dipakai dengan
masuk lewat browser, tanpa menyalin kunci.

**Lingkup.**
- `auth_type: oauth` pada `ProviderProfile`, dengan dua alur generik: device code dan PKCE.
- Token disimpan di `<home>/auth.json` (izin 0600; nama file ini sudah dilindungi dari tool
  file dan dari perintah shell), diperbarui otomatis sebelum kedaluwarsa, dan masuk ke
  kumpulan kredensial seperti kunci biasa.
- `clite auth login <provider>`, `clite auth status`, `clite auth logout <provider>`.
- Token akses terdaftar sebagai kredensial sehingga diredaksi dan tidak sampai ke perintah.
- Mulai dengan satu provider yang alurnya terdokumentasi resmi untuk aplikasi pihak ketiga
  (OpenRouter PKCE adalah kandidat). Jangan menerapkan alur masuk milik aplikasi resmi sebuah
  vendor tanpa izin tertulis vendor itu.

**File.** `src/clite/providers/oauth.py (baru)`, `src/clite/providers/credentials.py`,
`src/clite/providers/base.py`, `src/clite/providers/runtime.py`,
`src/clite/cli/subcommands/auth.py (baru)`, `src/clite/cli/main.py`,
`tests/providers/test_oauth.py (baru)`.

**Rujukan Hermes.** `hermes_cli/auth.py`, `hermes_cli/auth_commands.py`,
`hermes_cli/auth_device_flow.py`, `hermes_cli/auth_oauth_pkce_plugin.py`,
`agent/credential_pool.py`, `agent/credential_sources.py`.

**Selesai bila.**
- [ ] Tes kedua alur terhadap server otorisasi tiruan lokal, termasuk pembaruan token dan
      token yang dicabut.
- [ ] Tes: `auth.json` tidak pernah terbaca lewat `read_file` dan isinya tidak muncul di log.
- [ ] Satu provider sungguhan dicoba dengan tangan dan dicatat di `docs/STATUS.md`.
- [ ] Baris "OAuth, `clite auth`" di spesifikasi providers dan cli menjadi ✅.

**Ukuran.** L

**Bergantung pada.** F1-T2
