# Lapisan

Paket `clite` tersusun berlapis. Setiap area punya peringkat, dan import hanya boleh mengarah
ke peringkat yang lebih rendah. Aturan ini dijalankan oleh `tests/test_architecture.py`, jadi
pelanggaran menggagalkan suite, bukan menunggu ketahuan saat review.

## Tabel lapisan

Sumber kebenarannya adalah `LAYER_RANK` di `tests/test_architecture.py`. Tabel ini
menjelaskannya.

| Peringkat | Area | Peran | Tidak tahu apa pun tentang |
|---:|---|---|---|
| 0 | `core` | Home, config, rahasia, profil, logging, redaksi, pemindaian teks | Semua paket lain |
| 1 | `state` | Sesi dan pesan di SQLite | Model, tool, agent |
| 1 | `providers` | Profil provider, transport, satu panggilan model, klasifikasi galat | Tool, sesi, giliran |
| 1 | `plugins.hooks` | Bus hook | Plugin manager, agent |
| 2 | `skills` | Menemukan, memvalidasi, menulis, dan memasang skill | Tool, agent |
| 3 | `tools` | Registry tool, dispatch, persetujuan, lingkungan eksekusi, tool bawaan, MCP | Loop agent, surface |
| 4 | `agent` | Satu percakapan: prompt, loop, kompresi, memori, delegasi | Surface, cron, plugin manager |
| 5 | `plugins` | Manifest, manager, `PluginContext`, shell hook | Surface (kecuali satu import ke `gateway`, lihat di bawah) |
| 6 | `cron` | Job terjadwal | Surface (kecuali satu import ke `runtime`, lihat di bawah) |
| 7 | `runtime` | `build_agent`, `ChatSession`, slash command | Surface mana yang memakainya |
| 8 | `rpc` | Server JSON-RPC | `gateway`, `server`, `cli` |
| 8 | `gateway` | Gateway pesan dan adapter platform | `rpc`, `server`, `cli` |
| 9 | `server` | HTTP + WebSocket di atas `rpc`, dashboard statis | `cli` |
| 9 | `acp` | Server ACP (baru penanda tempat) | `cli` |
| 10 | `cli` | Perintah `clite`, REPL klasik; merangkai semuanya | - |
| 11 | `__main__` | `python -m clite` | - |

## Aturan

1. **Import tingkat modul hanya ke peringkat yang lebih rendah.** `agent` boleh mengimpor
   `tools`; `tools` tidak boleh mengimpor `agent`.
2. **Dua area berperingkat sama tidak saling mengimpor.** `state` dan `providers` tidak saling
   kenal. `rpc` dan `gateway` tidak saling kenal: keduanya bertemu di `runtime`.
3. **`core` adalah daun.** Ia tidak mengimpor apa pun dari paket lain di `clite`
   (`test_core_imports_nothing_from_the_rest_of_the_package`).
4. **`plugins.hooks` adalah daun di peringkat 1**, terpisah dari sisa `plugins` (peringkat 5),
   supaya setiap lapisan bisa menembakkan hook tanpa menarik plugin manager.
5. **Blok `if TYPE_CHECKING:` tidak dihitung**, karena import di dalamnya tidak pernah
   dijalankan. Saat ini semuanya dipakai untuk memutus siklus di dalam satu area (fase di
   `agent/turn/` menyebut `AIAgent`, handler di `runtime/slash.py` menyebut `ChatSession`).
   `ToolContext.agent` sengaja bertipe `Any` supaya `tools` tidak perlu mengenal `agent`.
6. **Plugin bawaan hanya memakai API plugin.** Kode di `src/clite/bundled/` hanya boleh
   mengimpor `clite.core.*`, `clite.providers.base`, `clite.providers.registry`,
   `clite.providers.transports`, dan `clite.plugins.hooks`. Selebihnya datang lewat `ctx`.
   Alasannya: plugin bawaan adalah contoh yang akan disalin penulis plugin pihak ketiga
   (`test_bundled_plugins_use_only_the_plugin_api`).

## Import ke atas yang diizinkan

Empat tempat mengimpor ke peringkat yang lebih tinggi. Semuanya dilakukan **di dalam fungsi**
(tidak ada siklus saat modul dimuat) dan semuanya tercatat di `ALLOWED_UPWARD_LAZY_IMPORTS`.
Tes juga gagal bila sebuah entri di daftar itu sudah tidak dipakai.

| Dari | Ke | Alasan |
|---|---|---|
| `clite.tools.builtin.delegate` | `agent` | Tool `delegate_task` adalah pembungkus tipis `agent.delegation` |
| `clite.tools.builtin.cronjob` | `cron` | Tool `cronjob` menyunting penyimpanan job |
| `clite.plugins.context` | `gateway` | `ctx.register_platform()` mendaftarkan adapter |
| `clite.cron.scheduler` | `runtime` | Sebuah job dijalankan lewat `runtime.factory.build_agent` |

Menambah entri kelima butuh alasan yang setara: sebuah **tool atau titik ekstensi** yang
memang harus menjangkau lapisan di atasnya. Kebutuhan biasa diselesaikan dengan memindahkan
kode ke lapisan yang benar atau dengan callback.

## Cara lapisan atas dipanggil dari bawah tanpa import

Tiga mekanisme dipakai, dan kode baru sebaiknya memilih salah satunya sebelum
mempertimbangkan import ke atas.

| Mekanisme | Contoh |
|---|---|
| **Callback yang diserahkan dari atas** | `AgentCallbacks` (surface ke agent), `tick(deliver=...)` (gateway ke cron), `ToolContext.callbacks` |
| **Registry yang diisi dari atas** | `registry.register` (tool), `register_provider`, `register_platform`, `register_context_engine`, `register_memory_provider`, `register_environment_backend`, `register_skill_source` |
| **Hook** | `invoke_hook("pre_tool_call", ...)` di `tools`, didengar plugin di lapisan 5 |

## Di mana kode baru diletakkan

| Yang ditambahkan | Tempat | Catatan |
|---|---|---|
| Kemampuan baru untuk model (membaca, menulis, memanggil sesuatu) | `tools/builtin/<nama>.py` | Lihat resep di `src/clite/tools/AGENTS.md` |
| Pengetahuan atau prosedur untuk model | Skill di `src/clite/bundled/skills/` | Tidak menyentuh kode |
| Provider model baru | `src/clite/bundled/plugins/model-providers/<nama>/` | Satu direktori; tidak ada `if provider ==` di inti |
| Protokol kawat baru (`api_mode`) | `providers/transports/<nama>.py` | Satu kelas `ProviderTransport` |
| Perilaku baru pada loop giliran | Fase di `agent/turn/` | `loop.py` dan `agent.py` tetap pendek |
| Platform chat baru | `gateway/platforms/<nama>.py` atau plugin berjenis `platform` | Adapter hanya menerima, mengirim, memutus |
| Slash command | `runtime/commands.py` + `runtime/slash.py` | Otomatis tersedia di semua surface |
| Sub-perintah `clite` | `cli/subcommands/<nama>.py` | Punya `register(subparsers)` |
| Method atau event RPC | `rpc/contracts/schema.py` + `rpc/methods.py` | Lalu `scripts/gen_rpc_contracts.py` |
| Sesuatu yang dipakai dua surface | `runtime/` | Bukan di salah satu surface |
| Pengaturan | `core/config_defaults.py` | Harus punya pembaca, kalau tidak suite gagal |
| Reaksi atas event siklus hidup | Hook di plugin, atau shell hook | Bukan cabang baru di inti |
| Pembantu yang dipakai semua lapisan | `core/` | Hanya bila benar-benar tanpa ketergantungan |

Pertanyaan penguji: bila dua surface membutuhkan kode yang sama, kode itu milik `runtime`.
Bila sesuatu hanya dibutuhkan satu provider, itu milik profil provider tersebut. Bila sesuatu
bisa menjadi tool atau skill, ia tidak masuk ke `agent`.

## Mengapa `cron` di bawah `runtime`

`cron` terasa seperti surface (ia memulai giliran sendiri), tetapi `runtime` membutuhkannya
untuk perintah `/cron`, dan tool `cronjob` membutuhkannya untuk menyunting job. Karena itu
penyimpanan dan jadwal (`cron.jobs`, `cron.schedule`) berada di peringkat 6, dan satu-satunya
bagian yang membutuhkan `runtime`, yaitu menjalankan job, mengimpor `build_agent` di dalam
fungsi.

## Menambah area baru

1. Buat paketnya di `src/clite/<area>/`.
2. Tambahkan peringkatnya ke `LAYER_RANK`. Tanpa itu `test_every_package_has_a_layer` gagal.
3. Tulis `AGENTS.md` dan `CLAUDE.md` area itu (salin dari area tetangga).
4. Tambahkan barisnya ke tabel di dokumen ini dan spesifikasinya di `docs/spesifikasi/`.

## Bagian yang bukan Python

Front-end berbahasa TypeScript dan JavaScript tidak ikut dalam peringkat di atas. Mereka
terhubung ke backend **hanya** lewat protokol JSON-RPC ([05-protokol-rpc.md](05-protokol-rpc.md)).

| Bagian | Bergantung pada | Tidak boleh |
|---|---|---|
| `apps/shared/` (klien protokol, reducer transkrip) | Kontrak hasil generate | Mengimpor dari `ui-tui` atau `apps/desktop` |
| `ui-tui/` (TUI) | `apps/shared` | Membaca file di home secara langsung |
| `apps/desktop/` (cangkang Electron) | `clite serve` sebagai proses anak | Punya UI sendiri: jendelanya memuat dashboard backend |
| `src/clite/server/static/` (dashboard) | `rpc.js` di direktori yang sama | Langkah build |

Front-end tidak pernah membaca `config.yaml`, `state.db`, atau `.env`. Bila sebuah front-end
membutuhkan data, tambahkan method RPC.
