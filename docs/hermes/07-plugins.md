# 07. Plugins

Plugin adalah cara utama Hermes tumbuh tanpa membesarkan inti. Aturan dasarnya satu:
**plugin tidak pernah menyentuh inti**. Plugin hidup di foldernya sendiri dan bekerja di
dalam ABC, hook, dan permukaan `ctx` yang disediakan. Bila plugin butuh kemampuan yang
belum ada, yang dilebarkan adalah permukaan plugin yang **generik**, bukan logika khusus
plugin itu di dalam inti.

## Bentuk sebuah plugin

```text
~/.hermes/plugins/disk-cleanup/
├── plugin.yaml      manifest
├── __init__.py      memuat fungsi register(ctx)
└── disk_cleanup.py  modul pendukung, bebas
```

`plugin.yaml`:

```yaml
name: disk-cleanup
version: 2.0.0
description: "Auto-track and clean up ephemeral files created during sessions."
author: "..."
provides_hooks:
  - pre_tool_call
  - post_tool_call
  - on_session_end
```

`__init__.py`:

```python
def register(ctx):
    ctx.register_hook("pre_tool_call", _on_pre_tool_call)
    ctx.register_hook("post_tool_call", _on_post_tool_call)
    ctx.register_hook("on_session_end", _on_session_end)
    ctx.register_command("disk-cleanup", _slash_handler, description="...")
```

### Field manifest

| Field | Arti |
|---|---|
| `name`, `version`, `description`, `author`, `license`, `homepage`, `tags` | Identitas |
| `kind` | `standalone` (bawaan), `backend`, `exclusive`, `platform`, `model-provider` |
| `requires_env` | Variabel lingkungan yang dibutuhkan |
| `provides_tools`, `provides_hooks` | Deklarasi untuk tampilan dan audit |
| `requires_hermes` | Syarat versi, misalnya `">=0.19"`. Tidak terpenuhi berarti dilewati sebelum diimpor |
| `requires_plugins` | Ketergantungan antar-plugin. Bersifat anjuran: yang hilang hanya diperingatkan, tetapi menentukan urutan muat |
| `python_dependencies` | Divalidasi dan ditampilkan saja, **tidak pernah dipasang otomatis** |
| `config_schema` | Skema `plugins.entries.<id>.settings`. Ketidakcocokan hanya memperingatkan |
| `capabilities` | Kemampuan yang dideklarasikan. Deklarasi bukan izin |
| `manifest_version` | Versi format file. Tanpa field ini berarti v1, yang didukung selamanya |
| `provides_locales` | Paket bahasa yang didaftarkan otomatis |

Field yang tidak dikenal **diabaikan** dengan peringatan. Validasi manifest tidak pernah
menggagalkan pemuatan.

## Jenis plugin dan sistem discovery-nya

| Jenis | Lokasi | Discovery | Aturan tabrakan nama |
|---|---|---|---|
| Umum | `plugins/<nama>/`, `~/.hermes/plugins/`, `./.hermes/plugins/`, entry point pip | `PluginManager` di `hermes_cli/plugins.py` | Yang belakangan menang: proyek, lalu pengguna, lalu bawaan |
| Penyedia memori | `plugins/memory/<nama>/` | `plugins/memory/__init__.py` | **Bawaan dulu**, supaya folder yang dijatuhkan tidak membayangi yang resmi |
| Penyedia model | `plugins/model-providers/<nama>/` | `providers/__init__.py`, malas | Penulis terakhir menang |
| Mesin konteks, pembuat gambar, pencarian web, browser, TTS | `plugins/context_engine/`, `plugins/image_gen/`, `plugins/web/`, ... | ABC ditambah orkestrator | Satu yang aktif |
| Adapter platform | `plugins/platforms/<nama>/adapter.py` | Gateway | Lihat [12-gateway-cron.md](12-gateway-cron.md) |

Arti `kind`:

- `standalone`: harus dinyalakan lewat `plugins.enabled`.
- `backend`: backend pengganti untuk tool inti. Yang bawaan dimuat otomatis; yang dipasang pengguna harus dinyalakan.
- `exclusive`: hanya satu penyedia aktif, dipilih lewat `<kategori>.provider`. Punya discovery sendiri; pemindai umum melewatinya.
- `platform`: adapter gateway. Yang bawaan dimuat otomatis; yang dipasang pengguna dianggap kode tak tepercaya dan harus dinyalakan.
- `model-provider`: dicatat `PluginManager` tetapi **tidak diimpor** olehnya. Daur hidupnya milik registry provider.

## Alur muat

`PluginManager.discover_and_load()`:

1. Kumpulkan manifest dari folder: bawaan, pengguna, proyek. Plugin proyek hanya bila `HERMES_ENABLE_PROJECT_PLUGINS` disetel.
2. Tambahkan entry point pip dari grup `hermes_agent.plugins`. Plugin folder menang atas entry point bernama sama.
3. Tentukan pemenang per kunci.
4. Saring lewat `plugins.enabled` dan `plugins.disabled`. **Bawaannya opt-in**: tidak ada yang menyala sampai didaftarkan. `disabled` selalu menang.
5. Muat sesuai urutan ketergantungan (`resolve_plugin_load_order`, urutan topologis; siklus jatuh ke urutan abjad).
6. Tiap plugin diimpor ke namespace `hermes_plugins.<nama>`, lalu `register(ctx)` dipanggil. Pemuatan dibatasi `plugins.load_timeout_seconds`.

Kegagalan satu plugin dicatat sebagai error plugin itu dan tampil di `hermes plugins list`.
Plugin lain tetap dimuat.

**Jebakan waktu discovery**: `discover_plugins()` berjalan sebagai efek samping impor
`model_tools.py`. Kode yang membaca keadaan plugin tanpa mengimpor modul itu harus
memanggil `discover_plugins()` sendiri (idempoten).

## `PluginContext`

Objek `ctx` yang diterima `register()`. Method yang paling banyak dipakai:

```python
# Tool
ctx.register_tool(name, toolset, schema, handler, check_fn=None, requires_env=None,
                  is_async=False, description="", emoji="", override=False)
ctx.dispatch_tool(tool_name, args, **kwargs) -> str

# Hook dan middleware
ctx.register_hook(hook_name, callback)
ctx.register_middleware(kind, callback)

# Perintah
ctx.register_command(name, handler, description="", args_hint="")       # slash command /nama
ctx.register_cli_command(name, help, setup_fn, handler_fn=None)         # hermes <nama>

# Konten
ctx.register_skill(...)                      # skill bawaan plugin, dimuat sebagai plugin:skill
ctx.register_system_prompt_section(...)      # bagian di ekor volatile system prompt
ctx.register_locale_dir(...)

# Penyedia
ctx.register_memory_provider(provider)
ctx.register_context_engine(engine)
ctx.register_platform(...)
ctx.register_auxiliary_task(...)

# Lain-lain
ctx.get_config(key, default=None)            # dari plugins.entries.<id>.settings
ctx.set_config(key, value)
ctx.state                                    # penyimpanan milik plugin
ctx.llm                                      # akses LLM untuk plugin, dengan gerbang izin
ctx.call_mcp(server, tool, arguments)        # butuh plugins.entries.<id>.mcp_allowlist
ctx.inject_message(content, role="user", session_key=None)
ctx.emit(event, payload) / ctx.subscribe(event, callback)   # bus event antar-plugin
ctx.on_unload(callback)
ctx.has_plugin(plugin_id) / ctx.has_capability(capability)
```

Setiap pendaftaran dilacak dalam buku besar per plugin, sehingga plugin bisa dilepas
atau dimuat ulang dengan bersih: tool yang tertimpa dipulihkan ke pendaftaran
sebelumnya, hook dicabut, perintah dihapus.

### Izin yang perlu disetujui operator

Deklarasi di manifest bukan izin. Hal sensitif diberikan lewat `config.yaml`:

```yaml
plugins:
  enabled: [disk-cleanup, my-plugin]
  disabled: []
  entries:
    my-plugin:
      allow_tool_override: true        # boleh menimpa tool bawaan
      mcp_allowlist: [github]          # server MCP yang boleh dipanggil
      allow_gateway_injection: true    # boleh memicu giliran di sesi gateway
      settings:
        threshold: 5
```

Bila pembacaan izin gagal, jawabannya selalu "tidak".

## Hook

Daftar lengkap ada di `VALID_HOOKS` (`hermes_cli/plugins.py`). Yang inti:

| Hook | Kapan | Nilai balik |
|---|---|---|
| `pre_tool_call` | Sebelum tool dijalankan | `{"action": "block", "message"}` memveto; `{"action": "approve", "message", "rule_key"}` meminta persetujuan manusia; `{"action": "modify", "args": {...}}` mengubah argumen |
| `post_tool_call` | Sesudah tool | Pengamat. Menerima `result`, `duration_ms`, `status` |
| `transform_tool_result` | Sebelum hasil masuk konteks | String pengganti; string pertama menang |
| `transform_terminal_output` | Keluaran terminal | String pengganti |
| `pre_llm_call` | Sebelum panggilan model per giliran | `{"context": "..."}` atau string, ditempelkan ke pesan pengguna |
| `post_llm_call` | Sesudah giliran | Pengamat |
| `transform_llm_output` | Jawaban model | String pengganti atau `None` |
| `pre_api_request`, `post_api_request`, `api_request_error` | Tiap permintaan fisik ke penyedia | Pengamat |
| `pre_auxiliary_call`, `post_auxiliary_call` | Panggilan model pembantu | Pengamat |
| `on_stream_start`, `on_stream_delta`, `on_stream_end` | Streaming | Pengamat, di luar jalur token |
| `on_session_start`, `on_session_end`, `on_session_reset`, `on_session_finalize` | Batas sesi | Pengamat |
| `subagent_start`, `subagent_stop` | Delegasi | Pengamat |
| `pre_approval_request`, `post_approval_response` | Gerbang persetujuan | Pengamat; tidak bisa memveto |
| `pre_gateway_dispatch` | Tiap `MessageEvent` masuk, sebelum otorisasi | `{"action": "skip"}` membuang; `{"action": "rewrite", "text"}` mengganti teks |
| `pre_command` | Sebelum handler slash command | Diabaikan pada versi ini |
| `pre_verify` | Agent selesai mengubah kode dan hendak berhenti | `{"action": "continue", "message"}` menyuruh lanjut |
| `transform_api_error_classification` | Sebelum klasifikasi error bawaan | `{"reason": ..., "retryable": ...}` |

Prioritas `pre_tool_call`: `block` mengalahkan `approve`, bukan urutan pendaftaran.
Direktif `modify` digabung dangkal ke argumen asli dan diproses lebih dulu.

### Cara hook dipanggil

`PluginManager.invoke_hook(hook_name, **kwargs)`:

- Payload berkembang secara **aditif**. Callback dengan `**kwargs` menerima semuanya; callback bertanda tangan sempit hanya menerima field yang dideklarasikannya. Inilah yang membuat plugin lama tidak rusak ketika payload bertambah.
- Tiap callback **diisolasi**: exception dicatat sekali per kombinasi hook, callback, dan error, lalu callback lain tetap jalan.
- Hook berbatas waktu memakai `plugins.hook_callback_timeout`. Pekerja yang melewati batas ditinggalkan.
- `pre_tool_call` **gagal tertutup**: bila callback-nya melewati batas waktu atau melempar exception, hasilnya direktif blokir. Penjaga yang gagal tidak boleh berarti "silakan".
- Nilai balik selain `None` dikumpulkan dan dikembalikan sebagai daftar.

Selain hook plugin Python, ada **hook shell** (`agent/shell_hooks.py`) yang dikonfigurasi
di `hooks:` pada `config.yaml`: perintah shell yang menerima payload JSON di stdin.

## Katalog plugin

`plugin-catalog/` adalah satu-satunya sistem penemuan plugin luar repo. Satu file YAML
per entri, dengan pin SHA 40 heksadesimal wajib, digabung manual lewat PR. Ada lebih dari
400 entri pada commit rujukan.

```text
hermes plugins search <kueri>
hermes plugins install <nama | url git>
hermes plugins update | remove | enable | disable | list | show | validate | doctor
```

- `removed.yaml` adalah daftar bunuh: setiap jalur pemasangan menolak entri yang cocok.
- Asal-usul katalog disimpan di `.install-metadata.json` milik pemasang, tidak pernah dipercaya dari dalam pohon plugin.
- Hermes memutuskan tidak lagi menerima plugin produk pihak ketiga ke dalam repo. Semuanya dikirim sebagai repo plugin mandiri dan didaftarkan di katalog. Alasannya beban pemeliharaan, bukan mutu.

## Isolasi

`plugins.isolation` bernilai `in_process` (bawaan) atau `host`. Dalam mode `host`,
setiap plugin non-bawaan berjalan di proses host terpisah per profil, berkomunikasi
lewat protokol JSON berbingkai, dan menerima `RemotePluginContext`. Yang tidak bisa
menyeberang (objek gateway dan adapter yang hidup) didaftar di satu tabel
(`HOST_UNSUPPORTED_CTX_METHODS`).

## Kontrak kompatibilitas

Kompatibilitas adalah **kontrak perilaku**, bukan satu angka `PLUGIN_API_VERSION`:

- Data payload hook ditambahkan sebagai field kata kunci. Callback diperiksa tanda tangannya.
- Method `PluginContext` tidak pernah dihapus atau diganti nama. Parameter baru opsional dengan nilai bawaan.
- Field manifest yang tidak dikenal diabaikan.
- Method penyedia baru mendapat implementasi bawaan.
- Deprekasi: peringatan sekali per proses, pengganti terdokumentasi, dan minimal dua rilis minor sebelum dihapus.
- Test kompatibilitas memuat **plugin beku lewat jalur discovery sungguhan** dan menegaskan hasilnya.

**Path impor internal bukan API.** Plugin membangun di atas `ctx` dan ABC yang
terdokumentasi. Hermes tidak menyediakan shim ekspor ulang untuk perpindahan internal.

## Hook spekulatif ditolak

Hook atau titik perluasan tanpa konsumen nyata ditolak. Menambah hook itu mudah;
mencabutnya setelah plugin bergantung padanya sulit. Hook dengan kasus pakai yang nyata
dan dinyatakan tidak dianggap spekulatif walau konsumennya dikirim terpisah.

## Yang perlu ditiru persis

1. Manifest ditambah `register(ctx)`, tanpa menyentuh inti.
2. Opt-in secara bawaan; `disabled` selalu menang.
3. Payload hook aditif dengan pemeriksaan tanda tangan.
4. Isolasi kegagalan per callback, dan `pre_tool_call` yang gagal tertutup.
5. Buku besar pendaftaran supaya plugin bisa dilepas dengan bersih.
6. Izin sensitif lewat konfigurasi operator, bukan deklarasi plugin.
7. Test yang memuat plugin lewat discovery sungguhan.

## Rujukan di Hermes

`hermes_cli/plugins.py`, `hermes_cli/plugins_manifest.py`, `hermes_cli/plugins_loader.py`,
`hermes_cli/plugins_dispatch.py`, `hermes_cli/plugins_discovery.py`,
`hermes_cli/plugins_ledger.py`, `hermes_cli/plugins_cmd*.py`, `hermes_cli/plugin_catalog.py`,
`plugins/`, `plugin-catalog/`, `agent/shell_hooks.py`, `plugins/AGENTS.md`,
`website/docs/developer-guide/plugins/index.md`.
