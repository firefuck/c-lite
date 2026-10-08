# Spesifikasi: plugins

| | |
|---|---|
| Kode | `src/clite/plugins/`, plugin bawaan di `src/clite/bundled/plugins/` |
| Tes | `tests/plugins/` |
| Lapisan | `hooks.py` di lapisan 1 (hanya mengimpor `core`). Sisanya di lapisan 5 |
| Bedah Hermes | [07-plugins](../hermes/07-plugins.md) |

## Tanggung jawab

Cara menambah kemampuan tanpa menyentuh kode inti: bus hook yang ditembakkan inti, plugin
Python yang mendaftarkan kemampuan lewat `PluginContext`, dan shell hook dari `config.yaml`.

## Bagian-bagian

| File | Isi |
|---|---|
| `hooks.py` | `HookBus` per home, `invoke_hook`, bagian prompt dari plugin |
| `manifest.py` | `plugin.yaml` dan validasinya |
| `context.py` | `PluginContext`: API yang diterima `register(ctx)` |
| `manager.py` | Penemuan, gerbang opt-in, muat, bongkar, pasang |
| `hub.py` | Asal-usul pemasangan, katalog plugin, pencarian, pembaruan |
| `shell_hooks.py` | Perintah shell pada event siklus hidup, dengan persetujuan per perintah |

## Kontrak

**Hook**
- Nama hook yang sah ada di `VALID_HOOKS` (lihat [katalog](../referensi/katalog.md)). Nama lain
  ditolak saat mendaftar.
- `invoke_hook(nama, **kwargs)` mengembalikan hasil bukan-`None` sesuai urutan pendaftaran.
- Kwargs bersifat aditif. Callback hanya menerima kwargs yang ia namai (atau semuanya bila
  memakai `**kwargs`), jadi inti boleh menambah kwarg tanpa mematahkan plugin lama.
- Callback yang gagal atau kehabisan waktu (`plugins.hook_callback_timeout`) tidak
  memengaruhi callback lain maupun pemanggil. Pengecualian: `pre_tool_call`, yang gagal
  tertutup. Guard yang melempar atau kehabisan waktu berarti **blokir**.
- Tiap home (profil) punya bus sendiri.
- Arahan yang dipahami inti: `pre_tool_call` boleh mengembalikan
  `{"action": "block", "message": ...}` atau `{"action": "modify", "args": {...}}`;
  `pre_llm_call` boleh mengembalikan `{"context": "..."}`; hook `transform_*` mengembalikan
  string pengganti (yang pertama menang).
- Bagian prompt dari plugin dirender sekali saat sesi dimulai, dibatasi 2000 karakter per
  bagian dan 8000 total.

**Plugin**
- Sumber, yang belakangan mengganti plugin bernama sama: bawaan paket, `<home>/plugins/`,
  `./.clite/plugins/` (hanya dengan `CLITE_ENABLE_PROJECT_PLUGINS=1`), paket pip dengan entry
  point `clite.plugins`.
- **Opt-in.** Plugin hanya berjalan bila namanya ada di `plugins.enabled`. `plugins.disabled`
  selalu menang. Pengecualian: plugin bawaan berjenis `platform`, `backend`, dan
  `model-provider`, yang tidak melakukan apa pun sampai dikonfigurasi.
- `requires_env` diperiksa sebelum kode plugin dijalankan.
- Plugin yang gagal dimuat dilaporkan (`status: error`) dan tidak meninggalkan apa pun:
  semua yang sempat ia daftarkan dibatalkan lewat ledger.
- Membongkar plugin membatalkan semua pendaftarannya. Tool bawaan yang ia timpa kembali.
- Plugin tidak bisa mengganti tool bawaan tanpa `plugins.entries.<id>.allow_tool_override: true`.
- **Jenis `exclusive`.** Manifestnya wajib menyebut `category`; tanpa itu manifestnya ditolak
  saat pemindaian dan plugin itu dilewati. Di antara plugin `exclusive` yang aktif, hanya
  yang pertama (urutan nama) yang dimuat — yang berikutnya berstatus `error` dengan alasan
  yang menyebut plugin dan kategori yang menang, dan semua yang sempat ia daftarkan dibatalkan.
  Menonaktifkan yang aktif membuat yang berikutnya naik saat `load_all` berikutnya.
- Memasang (`clite plugins install`) hanya menyalin. Pengguna membaca isinya dulu, lalu
  mengaktifkan sendiri. Sumbernya sebuah direktori, URL git, atau nama dari katalog.
- `remove_plugin` hanya menyentuh satu direktori langsung di bawah `<home>/plugins/`: nama
  divalidasi sebagai satu nama direktori, dan direktori bersymlink ditolak, bukan diikuti.
- Tiap profil punya kumpulan plugin sendiri.

**Asal-usul dan pembaruan**
- Pemasangan mencatat sumber (`local`/`git`), identifier, commit (bila sumbernya checkout
  git), versi, waktu pasang, dan hash isi di `<home>/plugins/.hub/provenance.json`.
- `clite plugins update [nama]` mengambil versi terbaru dari sumber yang sama, menampilkan
  ringkasan dan satu baris per berkas (`added`/`removed`/`changed`), lalu menggantinya setelah
  pengguna mengonfirmasi (`-y` melewati pertanyaan). Tanpa nama, semua yang punya asal-usul
  diperiksa.
- Plugin yang disunting pengguna (hash direktori berbeda dari yang dicatat) **tidak** ditimpa
  tanpa `--force`. Suntingan tidak pernah digabung.
- Setelah diperbarui, plugin kembali **nonaktif** (`plugins.disabled`): kode baru belum dibaca,
  jadi ia tidak berjalan sampai pengguna mengaktifkannya lagi.
- Bila penggantian gagal, salinan lama dipasang kembali.

**Katalog**
- Satu berkas JSON: `{"version": 1, "plugins": [{"name", "description", "version", "kind",
  "source", "identifier", "hash"}]}`. `scripts/build_plugins_index.py` membuatnya dari pohon
  direktori plugin (direktori yang dicadangkan, seperti `model-providers/`, dilewati); versi
  bawaan ada di dalam paket (`bundled/plugins-index.json`), dibangun dari plugin bawaan dengan
  awalan `dragovics/clite/src/clite/bundled/plugins`, dan dijaga tes agar tetap sama.
- Lokasi: `plugins.hub.index` (kosong berarti katalog bawaan). Katalog yang tidak terbaca
  dilaporkan sebagai peringatan, bukan menghentikan pencarian.
- `clite plugins install <nama>` memakai entri katalog, mengunduh identifier-nya, dan menolak
  hasil unduhan yang hashnya tidak sama dengan yang dijanjikan katalog. Nama yang tidak ada
  disebutkan beserta nama yang ada.
- `clite plugins search [kata]` dan `clite plugins info <nama>` membaca katalog yang sama.

**Dependensi**
- `pip_dependencies` di manifest tidak pernah dipasang otomatis. `clite plugins install` dan
  `clite plugins info` menampilkannya sebagai perintah `pip install ...` yang harus dijalankan
  pengguna sendiri.

**`PluginContext`** menyediakan: `register_tool`, `register_toolset`, `register_environment`,
`register_hook`, `register_prompt_section`, `register_command`, `register_cli_command`,
`register_provider`, `register_transport`, `register_memory_provider`,
`register_context_engine`, `register_web_search_provider`, `register_platform`,
`register_skills_dir`, `register_skill_source`, serta `settings`, `home`, `plugin_dir`,
`logger`.

**Shell hook**
- Konfigurasi: `hooks: {event: [perintah | {command, matcher, timeout, fail_closed}]}`.
- Kawat: stdin satu objek JSON `{hook_event_name, tool_name, tool_input, session_id, cwd,
  extra}`. Stdout opsional: `{"decision": "block", "reason": ...}`,
  `{"decision": "modify", "tool_input": {...}}`, atau `{"context": ...}`. Kode keluar 2 pada
  `pre_tool_call` berarti blokir dengan stderr sebagai alasan.
- **Persetujuan.** Hook hanya berjalan setelah pasangan `(event, perintah)` yang persis sama
  disetujui dengan `clite hooks approve` (atau `CLITE_ACCEPT_HOOKS=1`). Daftar persetujuan
  (`<home>/shell-hooks-allowlist.json`) tidak bisa ditulis lewat tool file.
- Gagal terbuka secara default. `fail_closed: true` hanya berlaku di `pre_tool_call`.
- Batas waktu hook dijaga di bawah batas waktu bus, supaya kebijakan gagal milik hook itu
  sendiri yang memutuskan.
- Memuat ulang plugin mengganti pendaftaran shell hook, tidak menumpuknya.
- Hook `transform_*` dan `pre_gateway_dispatch` tidak tersedia untuk shell hook.

## Status fitur

| Fitur | Status | Catatan |
|---|---|---|
| Bus hook, 19 hook | ✅ | |
| Plugin direktori dan entry point pip | ✅ | Entry point pip belum diuji dengan paket terpasang sungguhan |
| Ledger pembatalan | ✅ | |
| Shell hook dengan persetujuan | ✅ | |
| Plugin bawaan contoh (`audit-log`) | ✅ | |
| Plugin bawaan backend (`web-search-ddg`, `web-search-tavily`, `image-gen-openai`, `context-sliding-window`, `memory-sqlite`) | ✅ | DDG tanpa kunci; Tavily berkunci, `TAVILY_API_KEY` terdaftar sebagai kredensial. `context-sliding-window` dan `memory-sqlite` adalah contoh titik perluasan: context engine (F6-T6) dan provider memori (F6-T3) |
| `pip_dependencies` di manifest | ✅ | Ditampilkan sebagai perintah `pip install ...` oleh `install` dan `info`; tidak ada pemasangan otomatis. F6-T5 |
| `provides_tools`, `provides_hooks` di manifest | 🟡 | Diparse, belum dipakai (informasi saja) |
| Asal-usul pemasangan dan `clite plugins update` | ✅ | F6-T5: sumber, commit, versi, dan hash dicatat; `update` menampilkan diff per berkas, menolak menimpa plugin yang disunting tanpa `--force`, dan meninggalkan plugin **nonaktif** sesudah diperbarui. Dijaga `tests/plugins/test_plugin_hub.py` |
| Katalog plugin dan `clite plugins search` | ✅ | F6-T5: indeks JSON (`plugins.hub.index`, bawaan dari plugin bawaan), `clite plugins search`/`info`/`install <nama>` dengan hash yang diverifikasi |
| Jenis `exclusive` (satu aktif per kategori) | ✅ | F6-T5: manifest tanpa `category` ditolak; hanya satu plugin per kategori yang dimuat, yang lain berstatus `error` beserta alasannya. Dijaga `tests/plugins/test_manager.py` |
| Halaman dashboard dari plugin | ⬜ | F6-T5 |
| Akses LLM untuk plugin (`ctx.llm`) | ⬜ | Hermes: `agent/plugin_llm.py`. F6-T5 |
| Hook tambahan (`pre_verify`, middleware permintaan) | ⬜ | F6-T5 |

## Yang sengaja berbeda dari Hermes

- **Lebih sedikit titik ekstensi.** `PluginContext` Hermes (`hermes_cli/plugins.py`) punya
  jauh lebih banyak method `register_*` (halaman dashboard, penyedia autentikasi, bahasa,
  penyedia gambar dan suara, dan lainnya). Yang sama: ledger pembatalan per plugin, sehingga
  bongkar dan muat ulang bersih tanpa memulai ulang proses.
- **Penyedia model bukan plugin biasa.** Direktori `model-providers/` dimuat oleh registry
  provider sendiri, lebih awal dan tanpa gerbang opt-in.
- **Persetujuan shell hook lewat perintah eksplisit**, bukan prompt saat pertama dipakai, dan
  tidak ada kunci config yang menyetujui otomatis (config adalah file yang bisa diubah agent
  lewat terminal).

## Celah yang diketahui

- Plugin berjalan dalam proses yang sama dengan hak penuh. Opt-in dan "pasang tidak berarti
  aktif" adalah satu-satunya penghalang.
- Katalog plugin tidak punya konsep "tap" seperti hub skill: satu lokasi, `plugins.hub.index`.
- Entri katalog berjenis `git` belum ada; yang didukung baru `local` dan `github` (untuk
  `github`, identifier menunjuk satu direktori di dalam repositori).
- `clite plugins update` membandingkan berkas, bukan menyimpan riwayat: tidak ada cara kembali
  ke versi sebelumnya selain memasang ulang.
- `register_provider` dari plugin menulis ke lapisan dasar registry, bukan ke lapisan milik
  profil.
