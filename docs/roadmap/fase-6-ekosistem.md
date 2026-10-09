# Fase 6: ekosistem

Fase ini membuka agent ke luar: skill dan plugin dari orang lain, editor, suara, dan
dokumentasi untuk pengguna. Hampir semua task di sini membawa kode atau teks pihak ketiga ke
dalam jangkauan agent, jadi dua aturan dari
[arsitektur/06-keamanan.md](../arsitektur/06-keamanan.md) berlaku lebih keras di sini:

- **Kode dari luar tidak berjalan tanpa tindakan eksplisit pengguna.** Memasang tidak pernah
  mengaktifkan, dan tidak ada yang memasang dependensi secara diam-diam.
- **Teks dari luar yang masuk system prompt dipindai dulu.** Itu termasuk deskripsi skill dari
  hub dan teks apa pun yang disumbang plugin.

Aturan yang berlaku untuk semua task ada di [README](README.md#selesai-itu-apa).

---

### F6-T1 Hub skill

**Tujuan.** Pengguna mencari skill dari sebuah indeks, memasangnya dengan satu perintah, dan
memperbaruinya, dengan pemindaian yang lebih dalam daripada sekarang.

**Lingkup.**
- **Indeks.** Satu file JSON yang dihasilkan dari repositori skill (nama, deskripsi, kategori,
  sumber, hash). Skrip pembuat indeks ada di repositori ini; lokasi indeks default bisa
  diganti di config.
- **Perintah.** `clite skills search <kata>`, `clite skills install <nama>`,
  `clite skills update [nama]`, `clite skills info <nama>`. `SkillSource.search` yang sekarang
  mengembalikan daftar kosong diimplementasikan.
- **Sumber tambahan** ("tap"): `clite skills tap add owner/repo`.
- **Pemindai yang lebih dalam** untuk skill dari luar: semua file teks, bukan hanya
  `SKILL.md`; skrip di `scripts/` dilaporkan per file beserta perintah yang dikandungnya; URL
  dan nama host yang dituju didaftar; file biner ditolak. Hasil pemindaian ditampilkan sebelum
  pemasangan dan pengguna mengonfirmasi.
- **Asal-usul.** File kunci mencatat sumber, hash, dan waktu pasang; `update` menunjukkan
  diff sebelum menimpa, dan tidak menimpa skill yang disunting pengguna tanpa konfirmasi.

**File.** `src/clite/skills/hub.py`, `src/clite/skills/scanner.py (baru)`,
`src/clite/cli/subcommands/skills.py`, `scripts/build_skills_index.py (baru)`,
`src/clite/core/config_defaults.py`, `tests/skills/test_hub.py (baru)`.

**Rujukan Hermes.** `tools/skills_hub.py`, `tools/skills_hub_search.py`,
`tools/skills_hub_sources.py`, `tools/skills_hub_install.py`, `tools/skills_guard.py`,
`tools/skills_ast_audit.py`, `scripts/build_skills_index.py`.

**Selesai bila.**
- [x] Tes terhadap indeks dan repositori tiruan lokal: cari, pasang, perbarui.
- [x] Tes: skill dengan skrip yang memuat perintah eksfiltrasi ditolak dengan laporan per file.
- [x] Tes: `update` atas skill yang disunting lokal tidak menimpa tanpa konfirmasi.
- [x] Baris hub dan pemindai di spesifikasi skills menjadi ✅.

**Catatan.** Indeks adalah berkas JSON biasa, bukan API: `scripts/build_skills_index.py`
membuatnya dari pohon direktori skill, dan paket membawa satu indeks bawaan yang dibangun dari
skill bawaan dengan awalan `dragovics/clite/src/clite/bundled/skills` — sehingga memasang nama
bawaan benar-benar mengunduh berkas yang sama dari repositori ini dan hashnya cocok. Registry
pihak ketiga yang punya API sendiri belum ada; `SkillSource.search` bawaan tetap kosong karena
pencarian dijawab indeks. Tap adalah lokasi indeks tambahan, bukan konsep baru.

**Ukuran.** L

**Bergantung pada.** F1-T4

---

### F6-T2 Porting skill bawaan dari Hermes

**Tujuan.** Instalasi baru membawa kumpulan skill yang berguna, bukan hanya empat.

**Lingkup.**
- Hermes mengirim skill bawaan dan skill opsional berlisensi MIT. Bawa per kategori, satu
  commit per kategori, dimulai dari `software-development`, `productivity`, dan `research`.
- Untuk setiap skill: periksa bahwa tool yang disebutnya ada di C-lite; ganti nama tool yang
  berbeda; buang bagian yang bergantung pada tool yang belum ada, atau tandai skill itu dengan
  `requires_tools` sehingga baru tampil ketika tool-nya tersedia; ganti penyebutan nama produk
  dan path home.
- Skill yang seluruhnya bergantung pada fitur yang belum ada (browser, suara) ditunda dan
  didaftar di task ini.
- Atribusi: setiap skill yang dibawa mencantumkan asalnya di frontmatter, dan `NOTICE.md`
  menyebut kumpulan itu.
- Pisahkan seperti Hermes: yang selalu ikut di `src/clite/bundled/skills/`, dan yang opsional
  di direktori yang bisa dipasang lewat hub (F6-T1).

**File.** `src/clite/bundled/skills/`, `NOTICE.md`, `tests/skills/test_skills.py`,
`docs/spesifikasi/skills.md`.

**Rujukan Hermes.** `skills/` (terutama `skills/software-development/`,
`skills/productivity/`, `skills/research/`), `optional-skills/`,
`website/docs/developer-guide/creating-skills.md`.

**Selesai bila.**
- [x] Tes: setiap skill bawaan lolos validasi format dan pemindaian ancaman.
      (`test_every_bundled_skill_passes_format_validation_and_the_threat_scan`)
- [x] Tes: tidak ada skill bawaan yang menyebut tool yang tidak terdaftar, kecuali lewat
      `requires_tools` atau `fallback_for_tools`.
      (`test_no_bundled_skill_names_a_tool_this_project_does_not_register`; frontmatter
      `requires_tools`/`requires_toolsets` divalidasi terhadap registry dan toolset,
      penyebutan tool yang tidak ada di C-lite ditolak)
- [x] Tes: tidak ada skill bawaan yang memuat nama produk atau path home Hermes.
      (tes yang sama, atas `~/.hermes`, `HERMES_HOME`, dan penyebutan produk)
- [x] Indeks skill tetap di bawah batas ukurannya dengan semua skill bawaan aktif.
      (`test_the_index_fits_every_bundled_skill`)

**Hasil porting (9 Oktober 2026).** Dua puluh lima skill dari Hermes pada commit
`1298c8e74baa73e1a2b90124228d017261ac6bc4`: 7 software-development, 14 productivity,
4 research. Adaptasinya: frontmatter `metadata.hermes` diganti `metadata.clite` dengan
`attributed_from`; nama tool Hermes dipetakan ke milik C-lite (`web_extract` →
`web_fetch`, `browser_*` dihapus); penyebutan helper yang tidak ada (rss-feeds,
blogwatcher, obsidian, xurl, himalaya) dialihkan ke `web_search`/`web_fetch` atau plugin
gateway bawaan; `airtable` dan `github` dibekali skrip pembantu stdlib
(`atr.py`, `ghapi.py`) karena pola curl + token pada baris perintahnya ditolak pemindai
sebagai `exfil_curl`; path `~/.hermes` menjadi `~/.clite`. `NOTICE.md` mendaftar
semuanya. Dua skill Hermes yang bergantung pada fitur yang belum ada ditunda:
`inspecting-hermes-desktop-dom` (DOM desktop Hermes, bukan C-lite) dan kategori web/media
yang menuntut tool browser serta suara. Skill opsional dari `optional-skills/` belum
dibawa; tinggal satu langkah manual bila dibutuhkan.

**Ukuran.** L

**Bergantung pada.** -

**Yang sudah dibawa** (10 Oktober 2026, 12 skill dalam tiga kategori). Setiap berkas ditulis
ulang mengikuti tool C-lite, menyebut asalnya di `metadata.clite.attribution`, dan didaftar di
`NOTICE.md`. Tesnya ada di `tests/skills/test_skills.py` (bagian "bundled skills").

- `software-development/`: `codebase-inspection`, `github`, `python-debugpy`,
  `requesting-code-review`, `simplify-code`, `spike`
- `productivity/`: `meeting-action-items`, `weekly-review-planning`
- `research/`: `arxiv`, `competitor-news-monitor`, `grounded-citations`, `llm-wiki`

**Yang ditunda, beserta alasannya.** Sisa kategori belum disentuh; ini daftarnya supaya tidak
hilang.

- Bergantung fitur yang belum ada: `dogfood`, `inspecting-hermes-desktop-dom` (butuh tool
  peramban dan DOM aplikasi desktop), `node-inspect-debugger` (butuh CLI `ndb`),
  `product-price-monitor` (butuh peramban).
- Bergantung layanan atau CLI pihak ketiga: `airtable`, `box`, `google-workspace`, `notion`,
  `teams-meeting-pipeline`, `maps`, `document-to-action-items`.
- Berat dan membawa skrip sendiri: `docx`, `xlsx`, `pdf`, `powerpoint`. Nilainya ada di skrip
  bawaan mereka; menulisnya ulang secara ringkas akan menghilangkan justru bagian yang berguna.
- Khusus Hermes: `hermes-agent-skill-authoring`, yang padanannya sudah ada di
  `meta/skill-authoring`.
- Kategori lain di Hermes, belum disentuh sama sekali: `apple`, `autonomous-ai-agents`,
  `creative`, `devops`, `email`, `media`, `note-taking`, `social-media`, `web`.
- Pemisahan "selalu ikut" dan "opsional" belum bisa dikerjakan: hub C-lite hanya punya
  `LocalDirSource` dan `GitHubSource`, belum ada sumber `optional-skills` seperti punya Hermes.
  Skill berat dan ceruk menunggu sumber itu.

---

### F6-T3 Plugin provider memori contoh

**Tujuan.** Ada satu provider memori eksternal yang benar-benar berguna, yang sekaligus
menjadi contoh lengkap untuk penulis plugin.

**Lingkup.**
- Plugin bawaan berjenis `backend` yang mengimplementasikan `MemoryProvider` dengan
  penyimpanan lokal: fakta disimpan di SQLite milik plugin, dicari dengan FTS5, dan diingat
  kembali lewat `prefetch` berdasarkan pesan pengguna.
- Tool milik provider (cari dan simpan) lewat `provider_tool_schemas`.
- Ingatan yang dikembalikan masuk ke `turn_context`, tidak pernah ke system prompt, dan
  dibungkus sebagai informasi latar.
- Dokumen singkat di direktori plugin yang menjelaskan tiap method antarmuka dan kapan
  dipanggil.
- Opsional, sebagai plugin kedua: satu provider yang dihosting. *(Ditunda: contoh lokal sudah
  menunjukkan seluruh antarmuka; provider terhosting menambah kredensial jaringan dan tidak
  bisa diuji tanpa layanan sungguhan.)*

**File.** `src/clite/bundled/plugins/ (direktori plugin baru)`,
`src/clite/agent/memory/provider.py`, `tests/agent/test_memory_and_delegation.py`,
`docs/spesifikasi/agent.md`.

**Rujukan Hermes.** `agent/memory_provider.py`, `plugins/memory/` (bandingkan dua
implementasi), `website/docs/developer-guide/memory-provider-plugin.md`.

**Selesai bila.**
- [x] Tes: fakta yang disimpan di satu sesi teringat di sesi lain lewat `turn_context`.
- [x] Tes: awalan kawat tetap stabil dengan provider aktif (ingatan giliran lama dikirim ulang
      persis sama).
- [x] Tes: plugin hanya mengimpor API plugin.
- [x] Baris "Provider contoh" di spesifikasi agent menjadi ✅.

**Ukuran.** M

**Bergantung pada.** -

---

### F6-T4 Server ACP

**Tujuan.** Editor yang berbicara Agent Client Protocol (Zed dan lainnya) bisa memakai C-lite
sebagai agent-nya.

**Lingkup.**
- `clite acp` menjalankan server ACP di atas stdio, di paket `src/clite/acp/` yang sekarang
  baru berupa penanda tempat.
- Method inti: inisialisasi dan negosiasi kemampuan, sesi baru, memuat sesi, prompt,
  pembatalan. Pembaruan sesi (potongan pesan, tool call dan statusnya, rencana dari `todo`)
  dikirim sebagai notifikasi.
- Permintaan izin ACP dipetakan ke callback `approve`; diam berarti tolak.
- Server dibangun di atas `ChatSession`, sama seperti RPC: tidak ada logika percakapan di
  dalamnya.
- Stdout adalah kawat; aturan yang sama dengan `src/clite/rpc/entry.py`.
- Periksa versi protokol ACP yang berlaku saat task ini dikerjakan; spesifikasinya masih
  bergerak.

**Di luar lingkup.** Kemampuan sisi klien (editor membaca file atau menjalankan terminal atas
nama agent). Catat sebagai task lanjutan.

**File.** `src/clite/acp/server.py (baru)`, `src/clite/acp/session.py (baru)`,
`src/clite/acp/__init__.py`, `src/clite/cli/subcommands/misc.py`,
`tests/acp/test_acp.py (baru)`, `docs/spesifikasi/acp.md (baru)`.

**Rujukan Hermes.** `acp_adapter/server.py`, `acp_adapter/session.py`,
`acp_adapter/events.py`, `acp_adapter/permissions.py`, `acp_adapter/tools.py`,
`website/docs/developer-guide/acp-internals.md`.

**Selesai bila.**
- [x] Tes dengan klien berskrip lewat pipa: satu giliran dengan tool call dan satu permintaan
      izin, dari inisialisasi sampai selesai.
- [x] Tes: `print` nyasar dari sebuah tool tidak merusak aliran protokol.
- [ ] Dicoba dengan tangan di satu editor dan dicatat di `docs/STATUS.md`.
- [x] `clite acp` tidak lagi mencetak penunjuk ke roadmap, dan baris ACP di spesifikasi cli
      menjadi ✅.

**Ukuran.** L

**Bergantung pada.** -

**Catatan.** Kemajuan per langkah:
1. Kawat, handshake, dan sesi — **selesai 9 Oktober 2026**. `initialize` (versi yang tidak
   dikenal dijawab dengan versi kita, bukan ditolak), `session/new` di atas `ChatSession`,
   tabel method berjalan di pool pekerja, permintaan ke klien dengan batas waktu, dan entry
   point `clite acp`/`python -m clite.acp.entry` yang memindahkan `sys.stdout` ke stderr.
   Kawatnya NDJSON `clite.rpc.transport` yang sama dengan TUI. 22 tes di
   `tests/acp/test_acp.py`, termasuk satu yang menjalankan proses sungguhan lewat pipa dan
   satu yang memastikan `print` nyasar tidak mendarat di kawat.
2. Giliran prompt — **selesai 9 Oktober 2026**. `session/prompt` menjawab dengan `stopReason`
   sementara teksnya mengalir sebagai `agent_message_chunk`/`agent_thought_chunk`;
   `session/cancel` dibaca di thread pembaca sehingga sampai saat giliran masih berjalan, dan
   prompt itu menjawab `cancelled`. Satu sesi satu giliran: prompt kedua dibalas `session busy`.
3. Tool call dan izin — **selesai 9 Oktober 2026**. `on_tool_start`/`on_tool_complete` menjadi
   `tool_call`/`tool_call_update` (kind dari apa yang dikerjakan tool, status `in_progress`
   lalu `completed`/`failed`, `rawInput`, `locations` untuk berkas, hasil dipotong 400
   karakter). Permintaan izin ACP dikirim ke klien lewat `session/request_permission` dan
   jawabannya menjadi pilihan `approve`; diam, `cancelled`, dan optionId yang tidak ditawarkan
   semuanya berarti tolak. Call yang sedang berjalan dilacak per thread, karena tool bisa
   berjalan paralel. Satu tes menjalankan proses sungguhan lewat pipa: `initialize`,
   `session/new`, satu giliran dengan tool call `chmod`, satu permintaan izin yang dijawab
   klien, dan perintahnya benar-benar jalan.
4. Rencana, perintah, dan memuat sesi — **selesai 9 Oktober 2026**. Daftar tugas (`todo`)
   dikirim utuh sebagai `plan` setiap kali tool itu selesai berjalan; butir `cancelled` tidak
   ikut karena ACP tidak punya kata untuk pekerjaan yang dibuang. `available_commands_update`
   dibangun dari `command_catalog` permukaan ini — perintah yang hanya ada di terminal tidak
   ditawarkan — dan dikirim **setelah** balasan `session/new`, karena id sesi baru berarti bagi
   klien setelah balasannya tiba; itu yang ditangani antrean kecil `after_reply`. Karena ACP
   menjalankan perintah sebagai prompt biasa, `session/prompt` lewat `handle_input`: teks yang
   berupa perintah dijawab perintahnya, dan model tidak dipanggil. `session/load` memutar ulang
   percakapan tersimpan sebagai `session/update` lalu menjawab `{}`; supaya itu bisa bekerja
   lintas proses, **id sesi ACP sekarang adalah id percakapan di penyimpanan**
   (`20261008_192945_4e3cc152`), bukan `sess_<uuid>` yang ditemukan untuk koneksi. Dua batasnya
   dicatat di spesifikasi: penalaran tidak diputar, dan sesi yang sudah terbuka ditolak.
5. Dokumentasi dan uji tangan di editor — halaman `docs/spesifikasi/acp.md` sudah ada; uji
   tangan di editor belum (tidak ada editor di lingkungan ini) dan dicatat apa adanya di
   `docs/STATUS.md`.
   Butir "`print` nyasar" ditutup dengan dua lapis: `entry.py` mengalihkan `sys.stdout` selama
   proses hidup (diuji lewat proses sungguhan) dan
   `tests/test_architecture.py::test_only_the_command_line_prints` melarang `print` di luar
   `clite/cli` — jadi tak ada tool kita yang bisa menulis ke kawat, dan print yang benar-benar
   berbahaya datang dari plugin atau pustaka pihak ketiga, yang justru ditangkap pengalihan itu.
   Isi tool yang dijalankan shell tidak bisa bocor ke stdout server karena keluarannya
   disalurkan lewat pipa oleh backend lingkungan.

---

### F6-T5 Ekosistem plugin

**Tujuan.** Plugin bisa ditemukan, diperbarui, dan diberi kemampuan lebih, tanpa melonggarkan
aturan opt-in.

**Lingkup.** Satu sub-langkah per butir.
1. **Asal-usul dan pembaruan.** Catat sumber dan commit saat memasang; `clite plugins update`
   menunjukkan apa yang berubah sebelum mengganti, dan plugin yang diperbarui kembali
   **nonaktif** sampai pengguna mengaktifkannya lagi.
2. **Katalog.** Indeks plugin dari sebuah repositori; `clite plugins search`.
3. **Dependensi.** `pip_dependencies` di manifest ditampilkan sebagai perintah yang harus
   dijalankan pengguna. Tidak ada pemasangan otomatis.
4. **Jenis `exclusive`.** Tegakkan "hanya satu aktif per kategori", yang sekarang baru
   dikenali.
5. **`ctx.llm`.** Akses plugin ke model bantu dengan anggaran per plugin dan tanpa akses ke
   riwayat percakapan.
6. **Hook tambahan** yang dibutuhkan plugin nyata, masing-masing dengan alasan tertulis dan
   keputusan gagal-terbuka atau gagal-tertutup.
7. **Halaman dashboard dari plugin**, dimuat dalam bingkai terisolasi dengan origin sendiri.

**File.** `src/clite/plugins/manager.py`, `src/clite/plugins/context.py`,
`src/clite/plugins/manifest.py`, `src/clite/plugins/hooks.py`,
`src/clite/cli/subcommands/plugins.py`, `src/clite/server/app.py`,
`tests/plugins/test_manager.py`.

**Rujukan Hermes.** `hermes_cli/plugins_cmd_update.py`, `hermes_cli/plugins_cmd_catalog.py`,
`hermes_cli/plugins_provenance.py`, `plugin-catalog/`, `agent/plugin_llm.py`,
`website/docs/developer-guide/plugin-llm-access.md`,
`website/docs/developer-guide/middleware.md`,
`website/docs/developer-guide/observer-hooks.md`.

**Selesai bila.**
- [x] Tes: plugin yang diperbarui tidak berjalan sampai diaktifkan lagi.
- [x] Tes: dua plugin `exclusive` dalam kategori yang sama tidak bisa aktif bersamaan.
- [x] Tes: `ctx.llm` berhenti pada anggarannya dan tidak pernah menerima pesan sesi.
- [x] Baris terkait di spesifikasi plugins menjadi ✅, satu per sub-langkah.

**Catatan.** Kemajuan per sub-langkah:
1. Asal-usul dan pembaruan — **selesai**. Modul baru `src/clite/plugins/hub.py`
   (bukan salah satu berkas yang didaftar di atas; `manager.py` sudah terlalu penuh),
   `scripts/build_plugins_index.py (baru)`, dan `tests/plugins/test_plugin_hub.py (baru)`
   menyertainya. `remove_plugin` juga diperbaiki: nama divalidasi dan symlink ditolak.
2. Katalog dan `clite plugins search` — **selesai**.
3. `pip_dependencies` ditampilkan sebagai perintah — **selesai**.
4. Jenis `exclusive` — **selesai**. Manifestnya wajib menyebut `category`; hanya satu plugin per
   kategori yang dimuat, yang lain berstatus `error` beserta alasannya.
5. `ctx.llm` — **selesai**. Modul baru `src/clite/plugins/llm.py` (bukan salah satu berkas yang
   didaftar di atas, seperti `hub.py`); anggaran per plugin lewat
   `plugins.entries.<id>.llm.calls` (bawaan 0), plafon `plugins.llm.max_tokens`, dan hanya
   prompt milik plugin yang pernah dikirim.
6. Hook tambahan — **selesai**. Dua hook, keduanya dengan alasan: `pre_memory_write` (menahan
   entri yang tidak lolos sebelum masuk ke system prompt setiap sesi berikutnya; **gagal
   tertutup**, masuk `FAIL_CLOSED_HOOKS`) dan `on_compaction` (pengamat setelah transkrip
   ditulis ulang, membawa `messages_before`/`messages_after`/`summary`; **gagal terbuka**).
   Keduanya dikecualikan dari `SHELL_HOOK_EVENTS` dengan alasan tertulis. `pre_verify` dan
   middleware permintaan tidak dibuat: belum ada plugin nyata yang membutuhkannya.
7. Halaman dashboard dari plugin — **selesai**. Manifest boleh mendeklarasikan
   `dashboard: {title, page}`; halaman dilayani **listener kedua di port sendiri**
   (`clite/plugins/pages.py` dan `create_plugin_pages_app` di `server/app.py`), jadi originnya
   sendiri: bingkai ber-sandbox di dashboard tidak berbagi DOM, `sessionStorage`, maupun token
   dengannya, dan WebSocket backend menolaknya lewat pemeriksaan origin. Hanya plugin yang
   aktif punya halaman, dan listener hanya menyerahkan aset web di dalam direktori plugin.

**Ukuran.** L

**Bergantung pada.** -

---

### F6-T6 Context engine alternatif

**Tujuan.** Ada lebih dari satu strategi untuk menjaga percakapan muat di jendela, dan penulis
plugin punya cara memastikan engine buatannya benar.

**Lingkup.**
- Engine kedua sebagai plugin bawaan: jendela geser tanpa peringkasan (murah, tanpa panggilan
  model bantu), untuk dibandingkan dengan kompresor bawaan.
- Engine ketiga bila provider mendukungnya: kompaksi di sisi provider. Perhatikan aturan A2:
  apa pun yang dilakukan provider terhadap riwayat harus tetap membuat permintaan berikutnya
  sah. *(Ditunda: belum ada provider terkonfigurasi yang menawarkan kompaksi sisi server.)*
- **Tes kontrak** yang bisa dipakai ulang: satu fungsi yang menerima sebuah `ContextEngine`
  dan memeriksa semua janji antarmukanya (tidak mengubah masukan, tidak memisahkan tool call
  dari hasilnya, peran tetap berselang, hasil lebih kecil dari masukan). Kompresor bawaan dan
  engine baru sama-sama dijalankan terhadapnya.

**File.** `src/clite/bundled/plugins/ (direktori plugin baru)`,
`src/clite/agent/context/engine.py`, `src/clite/agent/context/contract.py (baru)`,
`tests/agent/test_compression.py`, `docs/spesifikasi/agent.md`.

**Rujukan Hermes.** `agent/context_engine.py`, `plugins/context_engine/`,
`agent/native_compaction.py`,
`website/docs/developer-guide/context-engine-plugin.md`.

**Selesai bila.**
- [x] Tes kontrak lulus untuk setiap engine yang terdaftar.
- [x] Tes: engine dipilih lewat `context.engine`, dan nama yang tidak dikenal jatuh ke
      kompresor bawaan dengan peringatan.
- [x] Resep "Menambah context engine" di `src/clite/agent/AGENTS.md` merujuk tes kontrak.

**Ukuran.** M

**Bergantung pada.** F2-T11

---

### F6-T7 Suara

**Tujuan.** Pengguna bisa mengirim pesan suara di chat dan mendengar jawaban agent.

**Lingkup.**
- Registry `TranscriptionProvider` dan `SpeechProvider`, masing-masing dengan satu plugin
  provider.
- Masuk: pesan suara di gateway ditranskripsi sebelum menjadi giliran; transkripnya tampil
  sebagai teks pengguna.
- Keluar: tool `text_to_speech` yang menghasilkan file audio dan mengirimnya lewat
  `send_file`; opsi per platform untuk selalu membalas pesan suara dengan suara.
- Batas durasi dan ukuran; kunci provider terdaftar sebagai kredensial.

**Di luar lingkup.** Percakapan suara waktu nyata dan kata pemicu.

**File.** `src/clite/tools/builtin/speech.py (baru)`, `src/clite/gateway/media.py (dibuat F4-T4)`,
`src/clite/gateway/runner.py`, `src/clite/plugins/context.py`,
`src/clite/bundled/plugins/ (plugin provider baru)`, `tests/gateway/test_gateway.py`.

**Rujukan Hermes.** `tools/transcription_tools.py`, `tools/tts_tool.py`,
`agent/transcription_provider.py`, `agent/tts_provider.py`, `tools/voice_mode.py`.

**Selesai bila.**
- [x] Tes: pesan suara dari adapter `local` menjadi giliran dengan transkrip dari provider
      tiruan.
- [x] Tes: `text_to_speech` tidak ditawarkan tanpa provider yang terkonfigurasi.
- [ ] Dicoba dengan tangan di Telegram dan dicatat di `docs/STATUS.md`.

**Ukuran.** L

**Bergantung pada.** F4-T4

**Yang sudah dikerjakan** (10 Oktober 2026).

- Dua registry provider di `src/clite/tools/speech.py` (`TranscriptionProvider`,
  `SpeechProvider`), masing-masing memilih backend dari `speech.transcription.provider` /
  `speech.speech.provider`; nama yang tidak terdaftar, factory yang rusak, atau provider
  berkunci tanpa kunci di `.env` dilewati, bukan menggagalkan seluruh suara.
- Plugin bawaan `speech-openai` (`kind: backend`) mendaftarkan `openai-transcribe`
  (`POST /v1/audio/transcriptions`) dan `openai-speech` (`POST /v1/audio/speech`), keduanya
  memakai `OPENAI_API_KEY` yang didaftarkan sebagai kredensial. Bentuk permintaan dan batasnya
  dicatat di docstring plugin beserta tanggal pemeriksaannya.
- Pesan suara ditranskripsi di `gateway/runner.py` sebelum menjadi giliran; transkripnya masuk
  sebagai teks pengguna dan berkasnya tetap di direktori media sesi.
- Tool `text_to_speech` menulis berkas audio dan menyerahkan pengirimannya ke `send_file`;
  jawaban bersuara untuk platform di `speech.reply_with_voice`.
- Batas: `speech.max_bytes` dan `speech.max_seconds` menahan rekaman sebelum dikirim ke
  provider; `speech.max_chars` menahan teks yang akan diucapkan. Durasi dibaca dari header
  container (WAV lewat `wave`, Ogg Opus lewat granule position); container yang tidak
  menyebutkan durasinya hanya tunduk pada batas ukuran.
- Dijaga `tests/tools/test_speech.py` dan bagian "voice messages and spoken replies" di
  `tests/gateway/test_gateway.py`.

**Yang belum.** Uji tangan di Telegram belum dijalankan: tidak ada kredensial bot di mesin ini,
dan transkripsi sungguhan butuh `OPENAI_API_KEY`. Karena itu kotak ketiga tetap kosong dan
status di `docs/spesifikasi/gateway.md` tetap 🟡. Percakapan suara waktu nyata dan kata pemicu
tetap di luar lingkup.

---

### F6-T8 Batch runner dan ekspor lintasan

**Tujuan.** Banyak prompt bisa dijalankan tanpa pengawasan dengan hasil yang terekam, dan
percakapan bisa diekspor dalam format yang dipakai untuk evaluasi dan pelatihan.

**Lingkup.**
- `clite batch run <file.jsonl> --workers N --out <dir>`: tiap baris adalah satu prompt
  dengan pengaturannya, dijalankan di sesi baru pada platform `batch` (tanpa pengguna untuk
  ditanya; perintah berbahaya mengikuti kebijakan non-interaktif).
- Bisa dilanjutkan: baris yang sudah selesai dilewati saat perintah dijalankan ulang.
- Hasil per baris: jawaban akhir, alasan berakhir, pemakaian token, biaya, durasi.
  (Biaya ditunda: mesin biaya F2-T3 belum ada, jadi catatan hasil memuat token, bukan rupiah.)
- `clite sessions export --format trajectory`: pesan, tool call, dan hasilnya dalam satu
  format yang didokumentasikan, **diredaksi**, dan tanpa `provider_data`.

**File.** `src/clite/runtime/batch.py (baru)`, `src/clite/runtime/trajectory.py (baru)`,
`src/clite/cli/subcommands/batch.py (baru)`, `src/clite/cli/subcommands/sessions.py`,
`src/clite/runtime/factory.py`, `src/clite/providers/transports/base.py`,
`tests/runtime/test_batch.py (baru)`.

**Rujukan Hermes.** `batch_runner.py`, `agent/trajectory.py`, `trajectory_compressor.py`,
`website/docs/developer-guide/trajectory-format.md`.

**Selesai bila.**
- [x] Tes: batch tiga prompt dengan dua pekerja menghasilkan tiga hasil, dan menjalankan ulang
      tidak mengulang yang sudah selesai.
- [x] Tes: satu prompt yang gagal tidak menghentikan batch.
- [x] Tes: ekspor lintasan tidak memuat nilai kredensial yang dikenal.

**Catatan.** Batch runner memakai dua pekerja sekaligus dan menemukan balapan yang sudah ada
sebelum tugas ini: `_ensure_builtin` di `providers/transports/base.py` menandai registry
"sudah dimuat" sebelum impornya selesai, jadi thread kedua bisa melihat registry setengah
terisi (`no transport for api_mode 'mock'`). Kunci reentrant ditambahkan dan flag dipindah ke
akhir; dijaga `test_concurrent_first_use_of_the_transports_registry_finds_every_one` yang
menjalankan proses dingin bersamaan.

**Ukuran.** M

**Bergantung pada.** -

---

### F6-T9 Situs dokumentasi pengguna

**Tujuan.** Pengguna yang tidak akan pernah membuka kode punya dokumentasi: pasang, mulai
cepat, konfigurasi, tool, skill, plugin, gateway, keamanan.

**Lingkup.**
- Dokumen di `docs/` sekarang ditulis untuk orang yang **mengubah** kode. Dokumentasi pengguna
  adalah kumpulan terpisah, ditulis dari sudut pandang orang yang **memakai**.
- Putuskan bahasa (Indonesia, Inggris, atau keduanya) sebelum menulis.
- Pembangkit situs statis, diterbitkan lewat GitHub Pages pada setiap rilis.
- Halaman rujukan (perintah, slash command, kunci config, tool) dihasilkan dari kode oleh
  `scripts/gen_docs.py`, sehingga tidak pernah tertinggal.
- Setiap contoh perintah di dokumentasi dijalankan oleh tes terhadap provider `mock`.

**File.** `website/ (baru)`, `scripts/gen_docs.py`, `.github/workflows/docs.yml (baru)`,
`README.md`.

**Rujukan Hermes.** `website/docs/`, `website/docusaurus.config.ts`, `website/sidebars.ts`.

**Selesai bila.**
- [ ] Situs terbit di GitHub Pages. Tautannya sudah ada di `README.md`, dan
      `.github/workflows/docs.yml` sudah menulis dan mengunggah artefaknya seperti yang
      dijalankan di sini, tetapi workflow-nya belum pernah berjalan di GitHub.
- [x] Tes: halaman rujukan pengguna sama dengan keluaran pembangkitnya.
- [x] Tes: contoh perintah di halaman mulai cepat berjalan apa adanya.

**Ukuran.** M

**Bergantung pada.** F1-T7

**Butuh dari Anda.** Keputusan bahasa dan nama domain bila tidak memakai alamat GitHub Pages
bawaan. Dijawab: **keduanya**, dan alamat bawaan `https://dragovics.github.io/clite/` dipakai
apa adanya, jadi tidak ada keputusan domain.

**Catatan.** Situs ditulis dalam dua bahasa karena jawabannya "keduanya": setiap halaman ada
di `website/content/id/` dan `website/content/en/` dengan slug yang sama persis, sehingga
tombol bahasa selalu menemukan padanannya; tes pertama di `tests/test_website.py` gagal bila
kedua pohon tidak lagi sama.

Pembangkitnya `scripts/build_site.py`, memakai pustaka standar saja, bukan Docusaurus seperti
Hermes: paket Python harus bisa dipasang tanpa Node, dan pekerjaan docs di CI tidak boleh
menuntut toolchain kedua. `website/docusaurus.config.ts` dan `website/sidebars.ts` tetap
menjadi rujukan strukturnya (pohon halaman, menu samping, tombol bahasa).

`scripts/gen_docs.py` sekarang punya tiga sasaran: `--target docs` (dua halaman pengembang di
`docs/referensi/`, keluarannya tidak berubah sama sekali oleh tugas ini), `--target site`
(enam halaman rujukan situs, tiga per bahasa), dan `--target all`. Datanya satu: fungsi
`catalog_sections(language)` membaca registry yang sama. Halaman rujukan yang dihasilkan
tidak pernah disunting dengan tangan, dan `test_the_generated_pages_are_the_only_ones_in_the_reference_tree`
menjaga itu.

**Belum diverifikasi.** Penerbitannya sendiri belum pernah berjalan di GitHub:
`.github/workflows/docs.yml` membangun dan mengunggah artefaknya apa adanya, dan hal yang sama
sudah dijalankan di sini pada 2026-10-10, tetapi "situs terbit" baru terbukti setelah rilis
pertama yang memicunya. Tercatat juga di [STATUS.md](../STATUS.md), bukan diberi ✅ penuh.
