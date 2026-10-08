# Status

Diperbarui 8 Oktober 2026. Halaman ini memisahkan tiga hal yang mudah tertukar: apa yang
**dijaga tes**, apa yang **ditulis tetapi belum pernah bertemu hal yang sebenarnya**, dan apa
yang **belum ada**.

## Dijaga tes

Pemeriksaan terbaru F3-T2 dijalankan runner di Linux, Python 3.11.16, Node 26.7.0.

| Pemeriksaan | Hasil |
|---|---|
| `ruff check src tests scripts` | Bersih |
| `mypy` (178 file sumber) | Bersih |
| Tes Python (`pytest tests`) | 1268 lulus, 29 terlewati (jaringan, Windows, Docker, paket opsional), 1 gagal yang sudah ada sebelum F3-T4 (`tests/server`, `websockets`) |
| Tes TypeScript `apps/shared` | 22 lulus; `tsc --noEmit` 1 galat yang sudah ada di `HEAD` (literal `subagent.update` di tes, bukan dari F3-T2) |
| Tes TypeScript `ui-tui` | 18 lulus + 11 tes e2e lulus (29 total); `tsc --noEmit` bersih |
| Tes TypeScript `apps/desktop` | 8 lulus; `tsc --noEmit` bersih |
| Rujukan ke file Hermes di semua dokumen | Lulus pada sesi pembuatan; belum diulang di sesi ini karena clone rujukan tidak tersedia |

Yang tercakup tes Python itu, selain perilaku tiap modul:

- **Ujung jauh ditiru dengan server sungguhan, bukan tambalan.** Provider diuji terhadap server
  HTTP lokal, Telegram terhadap Bot API tiruan, MCP terhadap proses server (termasuk server
  dari SDK MCP resmi), dashboard di Chromium lewat Playwright. Di mesin tanpa Playwright atau
  SDK MCP, tes itu dilewati, tidak gagal.
- **Bentuk kode.** Arah import antar-lapisan, pembaca untuk setiap kunci config, tidak ada
  nama vendor di luar profilnya, nama direktori home hanya dieja di satu tempat, pembacaan
  variabel lingkungan hanya di file yang terdaftar, tidak ada `print` di luar CLI.
- **File turunan.** Kontrak TypeScript, halaman referensi, dan bundle TUI sama dengan
  sumbernya.
- **Penggantian nama.** `scripts/rename_project.py` dijalankan pada salinan repositori di
  setiap putaran suite: tidak ada ejaan nama lama yang tertinggal, program hasil ganti nama
  berjalan, dan bisa diganti nama lagi.
- **Dokumen.** Tautan, path, nama modul, nama tes, dan nomor task yang disebut dokumen
  semuanya ada.

Spesifikasi tiap modul (`docs/spesifikasi/`) menandai fitur yang dijaga tes dengan ✅.

### F2-T14 OAuth dan `clite auth` (8 Oktober 2026)

Dukungan OAuth 2.0 PKCE dan Device Code flow untuk provider model:
- Subcommand `clite auth login <provider>`, `clite auth status`, `clite auth logout <provider>`.
- Token disimpan di `<home>/auth.json` dengan izin berkas 0600 (owner-only DACL di Windows), penyegaran token otomatis sebelum kedaluwarsa, dan penanganan pencabutan token.
- Token akses otomatis terdaftar sebagai kredensial rahasia sehingga diredaksi dari transkrip/log dan dibuang dari lingkungan proses anak (`build_child_env`). Berkas `auth.json` dilindungi dari pembacaan/penulisan via tool (`read_file`, `write_file`, `patch`) dan gerbang persetujuan `detect_self_access`.
- Kumpulan kredensial (`CredentialPool`) dan resolusi rute (`resolve_runtime_provider`) mengintegrasikan token OAuth sebagai sumber kredensial.
- Alur PKCE (dengan callback HTTP lokal) dan Device Code flow diuji terhadap server otorisasi tiruan lokal di `tests/providers/test_oauth.py`. Uji langsung terhadap provider asli secara daring belum dilakukan (offline mock).

### F4-T3 langkah email, Matrix, dan Signal (8 Oktober 2026)

Plugin platform bawaan `email` memakai polling IMAP dan SMTP dari pustaka standar. Ia hanya
meneruskan pengirim dalam `allowed_users`, dan memakai `References` sebagai `thread_id` agar
setiap utas memiliki sesi gateway sendiri. Tes `tests/gateway/test_email.py` menjalankan server
IMAP dan SMTP tiruan lokal, lalu menjaga penerimaan, pemetaan utas, balasan SMTP, dan penolakan
pengirim lain. Layanan email asli belum pernah dicoba.

Plugin platform bawaan `matrix` memakai Client-Server API dengan long polling `/sync` dan
mengirim balasan `m.room.message`. Tes `tests/gateway/test_matrix.py` menjalankan server
Client-Server tiruan lokal untuk menjaga penerimaan event room yang diizinkan, checkpoint sync,
dan balasan ke room yang sama. E2EE sengaja belum didukung: event atau room terenkripsi tidak
dibaca atau dibalas. Homeserver Matrix asli belum pernah dicoba.

Plugin platform bawaan `signal` berbicara ke layanan REST `signal-cli` yang dijalankan pengguna:
ia mem-poll `GET /v1/receive/<akun>` dan mengirim DM melalui `POST /v2/send`. Tes
`tests/gateway/test_signal.py` menjalankan server REST tiruan lokal untuk menjaga penerimaan
pesan dari `allowed_users`, pemetaan pengirim ke sesi gateway, serta payload balasan. Layanan
Signal dan `signal-cli` asli belum pernah dicoba.

Plugin platform bawaan `whatsapp` menerima webhook WhatsApp Cloud API setelah memverifikasi
`X-Hub-Signature-256` memakai rahasia aplikasi, lalu mengirim balasan teks melalui Graph API.
Tes `tests/gateway/test_whatsapp.py` memakai webhook dan Graph API tiruan lokal untuk menjaga
verifikasi subscription, signature, penerimaan pengirim `allowed_users`, serta payload balasan.
Layanan WhatsApp Cloud API asli belum pernah diverifikasi.


### F2-T2 gelombang pertama (7 Oktober 2026)

Sepuluh profil tambahan diuji lewat HTTP loopback, streaming dan nonstreaming, tanpa
mengubah kode inti maupun setup. Menu setup ditemukan dari registry. Tes juga menjaga
kunci tidak ikut berpindah origin, model dipilih eksplisit, dan suhu K2.6 tidak dikirim.
Bukti regresi pada salinan `49eecd7`: 23 kasus baru/diperluas gagal; sesudah implementasi,
22 kasus baru dan discovery registry lulus. Log lokal /tmp/clite-f2t2-baseline-red.log dan
/tmp/clite-f2t2-green.log. Suite Python penuh: 870 lulus, 28 terlewati; mypy 161 file bersih;
tes Node shared/TUI/desktop masing-masing 21/18/8 lulus dan ketiga typecheck lulus.
Run final `scripts/run_tests.sh` lulus termasuk Ruff: /tmp/clite-f2t2-full-final.log.
F2-T2 tetap parsial, tanpa klaim API asli atau CI baru. Clone rujukan Hermes tidak tersedia.

Gelombang cloud lokal menambah Azure OpenAI, AWS Bedrock SigV4, dan Google Vertex akun
layanan. Bukti memakai HTTP loopback, pemeriksaan tanda tangan dan JWT dengan kredensial
sintetis, extra opsional, serta discovery setup; layanan cloud asli tidak dipanggil.
Snapshot `35ff0b0` dengan tes baru: 39 gagal (/tmp/clite-f2t2-cloud-red.log); sesudah
implementasi 39 lulus (/tmp/clite-f2t2-cloud-green.log). Suite Python penuh 908 lulus,
28 terlewati (/tmp/clite-f2t2-cloud-full.log); Ruff dan mypy 161 file bersih. Node tidak
disentuh dan tidak dijalankan ulang pada batch ini.

### F2-T5 (7 Oktober 2026)

Tool `web_search` dengan provider pluggable (`WebSearchProvider`) dan `check_fn` yang
menawarkan tool hanya bila ada provider aktif. Dua plugin bawaan berjenis `backend`:
`web-search-ddg` (DuckDuckGo, tanpa kunci) dan `web-search-tavily` (Tavily, berkunci;
`TAVILY_API_KEY` terdaftar via `register_secret`). Skill bawaan
`working-without-web-search` dengan `fallback_for_tools: [web_search]`. Bukti regresi pada
salinan `54bdd45`: 12 tes baru gagal (`ModuleNotFoundError: No module named
'clite.tools.web_search'`); sesudah implementasi, 12 tes lulus. Suite Python penuh (tanpa
`tests/server`, yang punya satu kegagalan sudah-ada sebelum tugas ini): 927 lulus, 26
terlewati. Ruff dan mypy bersih. Clone rujukan Hermes tidak tersedia.

### F2-T6 langkah 1: masukan gambar (8 Oktober 2026)

Masukan gambar selesai: `clite chat --image <path>`, `/image <path>` (alias `/attach`) di
semua surface, dan bidang opsional `attachments` pada RPC `prompt.submit`. Modul baru
`src/clite/agent/attachments.py` memuat, mengenali tipe dari byte awal, membatasi ukuran dan
jumlah, dan mengecilkan gambar yang terlalu besar lewat ekstra opsional `images` (Pillow).
Model yang dinyatakan tanpa penglihatan (`ProviderProfile.supports_vision` atau override
`model.vision`) tidak pernah dikirimi bagian gambar; riwayat tetap menyimpannya. Pencarian teks
pindah dari kolom `content` ke `search_text` supaya base64 gambar tidak masuk indeks FTS,
dengan skema versi 2, `COLUMN_ADDITIONS`, dan pembangunan ulang indeks saat dibuka.

Bukti regresi pada salinan bercabang dari `5ae95cd` dengan tes baru saja: 14 tes gagal
(`ModuleNotFoundError: No module named 'clite.agent.attachments'`,
`Extra inputs are not permitted` untuk `attachments`, `/image` tak dikenal, indeks FTS memuat
base64); sesudah implementasi, 46 tes baru lulus. Suite Python penuh: 995 lulus, 26 terlewati
(satu tes server yang sudah gagal sebelum tugas ini karena versi pustaka `websockets`, tidak
dipilih). Ruff bersih, mypy 164 file bersih. Tes Node `apps/shared` 21 lulus dan `ui-tui` 18
lulus; bundle TUI dibangun ulang dengan `node build.mjs` karena kontrak TypeScript berubah.
Clone rujukan Hermes tidak tersedia, sehingga file rujukan belum dibaca. Langkah 2
(`vision_analyze`) dan 3 (`image_generate`) belum dikerjakan; F2-T6 tetap 🟡.

### F2-T6 langkah 2 dan 3: analisis dan pembuatan gambar (8 Oktober 2026)

Langkah 2 selesai. `src/clite/tools/builtin/vision.py` menambah tool `vision_analyze`, yang
memuat gambar lewat `agent.attachments` dan mengirimnya ke rute `auxiliary.vision` (kunci
config baru `auxiliary.vision.provider`/`.model`). Model utama tidak pernah menerima bagian
gambar: ia hanya menerima teks jawaban model bantu sebagai hasil tool. Rute yang buta (`route
.profile.supports_vision(route.model)` bernilai salah) ditolak dengan pesan yang menyebut cara
mengarahkan `auxiliary.vision` ke model berpenglihatan. Profil provider menyatakan model mana
yang menerima gambar lewat `vision_models`/`no_vision_prefixes`; profil `deepseek` mengisi
daftar izin (`deepseek-v4-flash-vision-exp`, sumber 2026-10-07).

Langkah 3 selesai. `src/clite/tools/image_gen.py` menambah antarmuka `ImageProvider` dengan
registry dan `ctx.register_image_provider`; tool `image_generate`
(`src/clite/tools/builtin/image_gen.py`) hanya ditawarkan bila ada provider (`check_fn`),
memvalidasi ukuran terhadap `supported_sizes`, menyimpan byte gambar ke
`<cwd>/generated-images/` lewat `write_denied_reason`, dan mengembalikan path-nya. Plugin
bawaan `image-gen-openai` (`kind: backend`) menyediakan backend OpenAI Images; `OPENAI_API_KEY`
didaftarkan sebagai kredensial. Kunci config baru `image.provider`.

Bukti regresi merah/hijau pada salinan bercabang dari `1a6cdab` (worktree bersih) dengan tes
baru saja: `tests/tools/test_vision.py` dan `tests/tools/test_image_gen.py` gagal saat
koleksi dengan `ImportError: cannot import name 'vision'/'image_gen' from
'clite.tools.builtin'`, dan `tests/test_architecture.py` gagal dengan
`test_imports_point_down_the_layers` (import ke `agent.attachments`) serta
`test_indirect_reader_table_has_no_stale_entries` (kunci `auxiliary.vision.*` belum ada).
Sesudah implementasi, 20 tes baru lulus (8 vision + 11 image_gen + 1 giliran ujung-ke-ujung di
`tests/agent/test_loop.py`) dan `tests/test_architecture.py` lulus.
Suite Python penuh: 1016 lulus, 26 terlewati, 1 gagal — kegagalan itu
`tests/server/test_server.py::test_a_loopback_server_ignores_requests_addressed_to_another_name`,
yang sudah gagal sebelum tugas ini (versi pustaka `websockets`); diverifikasi dengan `git
stash`. Ruff bersih, mypy 167 file bersih.

Belum diverifikasi: mengirim gambar ke provider berpenglihatan sungguhan dan membuat gambar
lewat OpenAI Images sungguhan belum pernah dijalankan (butuh kunci API dan jaringan). Yang
diuji adalah bentuk permintaan HTTP dan perakitan hasil terhadap server lokal, bukan API asli.
Clone rujukan Hermes tidak tersedia, sehingga file rujukan belum dibaca.
### F2-T7: backend terminal Docker dan SSH (8 Oktober 2026)

`BaseEnvironment` diperluas dengan operasi file (`read_file`, `write_file`, `list_dir`,
`stat`) dan `spawn_background`. `read_file`, `write_file`, `patch`, dan `search_files` kini
mengarahkan setiap pembacaan dan penulisan lewat lingkungan sesi, bukan lewat `pathlib`
langsung; penjaga file dan redaksi tetap di jalurnya. `LocalEnvironment` mengimplementasikan
operasi itu dengan `pathlib` dan memindahkan kode spawn proses latar dari registry `process`.
Dua backend baru didaftarkan dengan `register_environment_backend` dan dipilih lewat
`terminal.backend`: `DockerEnvironment` (satu container per `task_id`, direktori kerja
di-bind-mount, container dihapus saat `cleanup`, tanpa variabel lingkungan host) dan
`SSHEnvironment` (satu koneksi ControlMaster per `task_id`, operasi file lewat `ssh`). Kunci
config baru di bawah `terminal.docker.*` dan `terminal.ssh.*`.

Bukti regresi pada salinan bercabang dari `1a6cdab` dengan tes baru saja (dan shim sementara
supaya koleksi berhasil): 10 tes gagal dan 1 error, termasuk `FileInfo`/`DirEntry` yang tidak
ada, backend `docker`/`ssh` yang tidak terdaftar, dan operasi file yang belum ada di
`BaseEnvironment`; sesudah implementasi, 14 tes lulus dan 3 tes bertanda `docker` terlewati
(tidak ada daemon di mesin ini). Suite tool file + terminal lama (56 tes) lulus lewat
antarmuka baru tanpa perubahan perilaku. Suite Python penuh: 1010 lulus, 29 terlewati, satu
tes server gagal yang sudah gagal sebelum tugas ini (versi pustaka `websockets`). Ruff dan
mypy bersih. Docker dan SSH asli belum pernah dijalankan. Rujukan Hermes tidak tersedia.

### F2-T8: checkpoint dan rollback file (8 Oktober 2026)

`src/clite/tools/checkpoints.py` menyimpan isi lama sebuah file sebelum `write_file` atau
`patch` mengubahnya, ke `<home>/checkpoints/<id sesi>/turn-<n>/` — satu subdirektori per
giliran, dengan `manifest.json` (daftar berkas dan jenis perubahannya: `modified`, `created`,
`deleted`) dan `files/` berisi salinan isi lama. Nomor giliran dihitung dari pesan pengguna
aktif di percakapan (`turn_id_for`), jadi pesan internal agent tidak memecah satu giliran
menjadi dua. Guard: berkas yang ditolak `read_denied_reason` tidak pernah disimpan, karena
store adalah teks biasa di disk dan menyimpannya akan memindahkan rahasia ke tempat yang bisa
dibaca model.

Dua slash command baru di `COMMAND_REGISTRY`: `/rollback [n]` mengembalikan perubahan giliran
terakhir (atau `n` giliran terakhir) — berkas yang dibuat agent dihapus, berkas yang dihapus
dikembalikan, berkas yang diubah dipulihkan; dan `/checkpoints` mendaftar giliran beserta
berkasnya. Keduanya dilayani `ChatSession.rollback_files` dan `list_file_checkpoints`, jadi
tersedia di CLI, TUI, dashboard, dan gateway. Pemangkasan mengikuti `sessions.retention_days`:
`runtime/maintenance.py::prune_checkpoints` berjalan saat surface mulai, menghapus store sesi
yang sudah tidak ada di database, membuang grup yang lebih tua dari batas retensi, dan
memangkas dari yang tertua bila total melewati `checkpoints.max_bytes` (kunci config baru,
default 100 MB).

Batas yang didokumentasikan: perubahan lewat perintah `terminal` (`mv`, `sed -i`, skrip) tidak
terlihat oleh tool file dan karena itu tidak tercatat; catatan ini ada di spesifikasi tools dan
agent.

Bukti regresi merah/hijau pada salinan bercabang dengan tes baru saja (modul dan konstanta
disalin, tapi tanpa penyambungan di `file_tools.py`, `slash.py`, `session.py`, dan
`maintenance.py`): 14 tes gagal, termasuk tiga perilaku yang diminta — satu giliran dengan
tulis/patch/buat yang tidak dikembalikan, checkpoint yang tidak menyapu store saat sesi
dipangkas, dan perintah `/rollback`/`/checkpoints` yang tidak ada. Dua guard diuji terpisah:
menghapus baris `read_denied_reason` di `record_change` menggagalkan
`test_a_checkpoint_never_stores_a_file_the_read_tools_refuse`, dan melumpuhkan
`_prune_missing_sessions` menggagalkan
`test_pruning_removes_the_checkpoints_of_a_pruned_session`. Sesudah implementasi, 20 tes di
`tests/tools/test_checkpoints.py` lulus. Suite `tests/tools`, `tests/runtime`, dan `tests/core`
yang terdampak lulus (393 lulus, 13 terlewati tanpa Docker/Windows). Rujukan Hermes tidak
tersedia.

### F2-T9: eksekusi kode (8 Oktober 2026)

`src/clite/tools/builtin/code.py` menambah tool `execute_code`: program Python pendek yang
dijalankan lewat lingkungan eksekusi sesi (`BaseEnvironment`, F2-T7), bukan di dalam proses
agent. Karena itu di backend `docker` atau `ssh` kode berjalan di dalam container atau di host
jauh dan mewarisi sandbox itu; di backend `local` ia mengikuti `approvals.mode` seperti
`terminal`.

Program sampai ke interpreter lewat stdin (`python -`), sehingga teks model tidak pernah masuk
ke baris perintah: tidak ada kutipan shell, tidak ada batas panjang baris perintah, tidak ada
celah injeksi. Sebuah runner kecil yang ditanam dalam program menandai setiap tulisan dengan
stream asalnya dan membasuhnya saat itu juga, lalu menutup dengan satu laporan base64 berisi
`exit_code`. Tool memisahkan `stdout` dan `stderr` dari tanda itu, membuang catatan penutup
milik lingkungan (`[command timed out …]`) supaya tidak terbaca sebagai keluaran program, dan
mengembalikan ketiganya. Karena keluarannya mengalir, bukan dibuffer, program yang dimatikan
karena batas waktu tetap memperlihatkan apa yang sempat tercetak.

Kode diperlakukan sebagai perintah. Teksnya dikirim ke `check_command` yang sama seperti
`terminal`, dan pola `script_delete` di `approval.py` diperluas dengan dua pola baru yang
membaca sintaks Python, sehingga `shutil.rmtree(...)`, `os.remove`/`os.unlink`/`os.rmdir`,
`shutil.move(...)`, dan `subprocess.run(["rm", …])` yang ditulis langsung dalam kode ikut
ditandai — bukan hanya bentuk `python -c "…rmtree…"` yang sudah ada. Kredensial dibuang lewat
`build_child_env` (mekanisme yang sama dengan perintah lain) dan `stdout`/`stderr` diredaksi
sebelum masuk transkrip. Tool terdaftar di toolset `terminal`, jadi ia ikut semua toolset
komposit tanpa perubahan di sana.

Bukti regresi merah/hijau pada salinan bercabang dari `eb5f031` dengan tes baru saja: 1 error
koleksi (`No module named 'clite.tools.builtin.code'`) yang menutupi 23 tes. Untuk membuktikan
tiap guard secara terpisah, kode yang sudah jadi diubah satu per satu di salinan terisolasi
(22 tes lulus, 1 gagal tiap kali karena `-x` berhenti di kegagalan pertama):

- **kredensial**: menghapus jaminan lingkungan yang membersihkan kredensial (menjalankan
  subprocess langsung yang mewarisi `os.environ`, tanpa `build_child_env`) menggagalkan
  `test_credential_variables_are_not_visible_from_inside_the_code` dan
  `test_provider_keys_exported_in_the_shell_are_not_visible_either`.
- **pola berbahaya**: memberi gerbang teks `'true'` sebagai ganti teks kode menggagalkan
  `test_code_containing_a_dangerous_pattern_asks_for_approval`; dan menghapus dua pola baru di
  `approval.py` menggagalkan
  `test_a_destructive_call_written_in_python_is_flagged_like_the_command_it_runs`. Pada HEAD,
  `shutil.rmtree`, `os.remove`, dan `subprocess.run(["rm", …])` lolos gerbang tanpa satu pun
  `DangerMatch`.
- **batas waktu**: menjalankan program dengan `timeout=None` (jadi bawaan 180 detik lingkungan
  yang berlaku) menggagalkan `test_a_program_that_overruns_its_timeout_is_stopped`
  (62,9 detik sampai gagal) dan, dijalankan sendiri, juga menggagalkan
  `test_the_timeout_kills_the_child_processes_the_program_started` (120,2 detik). Yang terakhir
  membuktikan proses anak (`sleep 120` yang dimulai dari dalam kode) mati setelah batas waktu,
  karena `LocalEnvironment` mematikan seluruh grup proses — dan bahwa tanpa batas waktu ia
  memang hidup terus.

Sesudah implementasi, 23 tes di `tests/tools/test_code.py` lulus. Satu tes lama yang menuliskan
isi toolset `terminal` secara harfiah disesuaikan kontraknya (tool baru memang masuk toolset
itu). Suite Python penuh: 1073 lulus, 29 terlewati, satu tes `tests/server` gagal yang sudah
gagal sebelum tugas ini (`websockets`). Ruff bersih, mypy 171 file bersih. Docker dan SSH asli
belum pernah dijalankan, jadi klaim "mewarisi sandbox" diuji lewat backend tiruan
(`test_code_runs_on_the_registered_backend_not_on_the_host`) yang membuktikan kode tidak
dijalankan di host melainkan lewat backend yang dipilih `terminal.backend`. Rujukan Hermes
tidak tersedia.

### F2-T10: MCP lewat HTTP, resources, prompts, `clite mcp`

`src/clite/tools/mcp/http.py` (baru) menambah transport **Streamable HTTP** di samping stdio:
JSON-RPC dalam POST ke satu endpoint, dengan `Mcp-Session-Id` dari respons pertama diteruskan
di setiap permintaan, dan balasan `text/event-stream` dibaca dari baris `data:`. Spec memilih
transport: `url` memilih HTTP, `command` memilih stdio. Header autentikasi ditulis di
`headers` dengan `${NAMA}` yang dibaca `get_secret`; nama itu didaftarkan lewat
`register_secret`, jadi nilainya diredaksi dari apa yang dibaca model dan dibuang dari
lingkungan perintah yang dijalankan agent. Variabel yang hilang adalah galat yang menyebut
namanya, bukan header kosong yang berujung 401.

Server yang mendeklarasikan kapabilitas `resources` mendapat tool
`mcp_<server>_list_resources` dan `mcp_<server>_read_resource`. Prompt server menjadi slash
command `mcp-<server>-<prompt>` di katalog perintah (kategori "MCP"); isinya diambil lewat
`prompts/get` saat dipanggil dan dikirim sebagai **pesan pengguna**, seperti skill, sehingga
system prompt tidak pernah berubah di tengah sesi.

**Aturan A1.** `notifications/tools/list_changed` hanya menandai `tools_changed` pada server
itu; ia tidak menyentuh registry tool sesi yang berjalan. Session diberi definisi tool saat
`AIAgent` dibangun (`agent.tools` adalah potret), jadi daftar tool sesi itu tetap. Sesi
berikutnya membaca ulang daftarnya ketika `connect_mcp_servers` dipanggil lagi. Server yang
gagal start tidak dicoba ulang seketika: jeda membesar `5s * 2^(n-1)` sampai batas 300 detik,
dan hanya sesi berikutnya (di luar jendela itu) yang mencoba lagi.

`clite mcp add | list | remove | test` menulis `mcp_servers` lewat `atomic_config_update`
(satu-satunya penulis config; komentar tetap utuh), dan `/mcp` menampilkan status tiap server.

Bukti regresi merah/hijau pada worktree bersih dari `4156234` dengan tes baru saja
(`PYTHONPATH` diarahkan ke salinan itu supaya import tidak jatuh ke paket terpasang):
**13 kegagalan** — `test_http_transport_speaks_to_a_real_sdk_server`,
`test_a_resource_server_gets_list_and_read_tools`, `test_auth_headers_come_from_dotenv`,
`test_a_missing_dotenv_header_variable_is_a_clear_error`,
`test_a_tool_list_change_does_not_alter_the_running_session`,
`test_a_dead_server_is_retried_with_a_growing_delay`,
`test_cli_add_writes_the_config_through_the_atomic_writer`,
`test_cli_test_reports_the_tools_it_found`, `test_cli_remove_deletes_only_the_named_server`,
`test_cli_add_rejects_a_spec_with_both_command_and_url`,
`test_mcp_prompts_appear_as_slash_commands`, `test_an_mcp_prompt_runs_as_a_slash_command`, dan
`test_slash_mcp_reports_no_servers_when_none_are_connected` — dan 8 tes lama lulus. Untuk
membuktikan tiap guard secara terpisah, implementasi di salinan terisolasi diubah satu per
satu:

- **A1**: membuat `notifications/tools/list_changed` langsung memuat ulang dan mendaftar ulang
  tool menggagalkan `test_a_tool_list_change_does_not_alter_the_running_session` (dan macet
  karena permintaan bersarang dari thread pembaca — justru alasan menundanya benar).
- **jeda membesar**: mengganti delay dengan nilai tetap menggagalkan
  `test_a_dead_server_is_retried_with_a_growing_delay`.
- **header dari .env**: melumpuhkan resolusi `${NAMA}` (mengirim nilai literal) menggagalkan
  `test_auth_headers_come_from_dotenv` dan
  `test_a_missing_dotenv_header_variable_is_a_clear_error`.
- **tool resources**: melewatkan pendaftaran tool resource menggagalkan
  `test_a_resource_server_gets_list_and_read_tools`.

Sesudah implementasi, 21 tes di `tests/tools/test_mcp.py` lulus. `clite mcp add` diperiksa
menulis config dengan komentar aslinya utuh dan `clite mcp test` melaporkan tool yang
ditemukan. Rujukan Hermes tidak tersedia. Sampling dan OAuth sengaja tidak dikerjakan (di luar
lingkup F2-T10).

### F2-T11: kompresi yang lebih baik (8 Oktober 2026)

Ringkasan kompresi kini berstruktur dengan lima bagian tetap (`SUMMARY_SECTIONS` di
`src/clite/agent/context/compressor.py`: `Goal`, `Key Decisions`, `Files`, `Failed Commands`,
`Unfinished Work`). `missing_summary_sections()` melaporkan bagian yang belum ada, dan prompt
pembaruan ringkasan lama menyebut bagian yang hilang supaya model mengisinya. Saat bagian tengah
lebih besar dari jendela model bantu, ia diringkas bertahap: excerpt dipecah pada batas pesan,
tiap bagian diringkas dengan template tahap, lalu digabung lewat satu panggilan merge — bukan
dipotong seperti sebelumnya. Jendela model bantu diisi agent lewat
`resolve_auxiliary_route("compression", …)` + `get_context_length` dan diteruskan ke
`ContextEngine.configure(..., auxiliary_context_length=…)`; `ContextCompressor._summary_input_budget`
menurunkannya ke anggaran karakter.

Perkiraan token `src/clite/agent/context/tokens.py::estimate_prompt_tokens` memakai
`prompt_tokens` terakhir dari provider sebagai jangkar dan memperkirakan hanya pesan sesudahnya.
Jangkar hanya dipercaya bila angkanya minimal sebesar perkiraan pesan yang diklaimnya; kalau
tidak (angka basi atau provider melaporkan hal lain), perkiraan penuh yang dipakai — itu menjaga
tes lama `test_preflight_compression_fires_before_the_window_is_exceeded` tetap benar, karena
`ScriptedClient` melaporkan `usage` tetap 10. `ContextEngine.anchored_prompt_tokens` dan
`iteration.prepare_iteration` memakainya.

`prune_images()` membuang bagian `image_url` di luar jendela terlindung lebih dulu daripada
`prune_tool_outputs()`, dan teks di sekitarnya tetap. Penghitung pengingat memori disimpan per
sesi di `<home>/memories/nudge.json` (`MemoryManager.initialize`/`_load_nudge_count`/
`_save_nudge_count`), jadi sesi yang dilanjutkan tidak memulai ulang hitungannya.

`scripts/eval_compression.py` (baru) mengompres transkrip contoh lewat `ContextCompressor` dan
melaporkan fakta mana yang hilang (5 fakta: dua path, satu keputusan, satu perintah gagal
beserta sebabnya, satu pekerjaan tersisa) serta bagian ringkasan yang kosong. Dengan
`--provider mock` seluruh jalur berjalan tanpa jaringan; `--json` untuk mesin, `--show-summary`
untuk melihat ringkasannya.

Bukti regresi merah/hijau pada worktree bersih dari `f119b29` dengan tes baru saja. Karena
simbol baru belum ada, koleksi gagal dengan `ImportError: cannot import name 'SUMMARY_SECTIONS'`;
supaya tiap guard terbukti terpisah, implementasi disalin ke salinan terisolasi lalu satu
perilaku dikembalikan ke bentuk lamanya satu per satu (skrip bukti `/tmp/prove_guards.py`):

- **bagian tetap dihapus**: `SUMMARY_SECTIONS` diganti daftar lama menggagalkan
  `test_the_summary_template_asks_for_the_fixed_sections`.
- **peringkasan bertahap dimatikan** (selalu satu panggilan): menggagalkan
  `test_a_middle_larger_than_the_aux_window_is_summarised_in_stages`.
- **pemangkasan gambar dimatikan** di `compress`: menggagalkan
  `test_compression_drops_old_images_before_pruning_text`.
- **jangkar diabaikan** (selalu perkiraan penuh): menggagalkan
  `test_the_provider_number_wins_over_the_estimate_before_any_appended_message`.
- **penghitung nudge tidak dipersistensi**: menggagalkan
  `test_a_resumed_session_does_not_restart_the_nudge_count`.
- **skrip pengukuran disingkirkan**: menggagalkan
  `test_the_compression_eval_script_runs_against_the_mock_provider`.

Sesudah implementasi, 10 tes baru lulus dan seluruh `tests/agent/test_compression.py` (33 tes)
lulus. Log lokal: `/tmp/clite-f2t11-red-guards.log` (merah per guard) dan
`/tmp/clite-f2t11-green.log` (hijau). Suite Python penuh dan status akhir ada di tabel catatan
verifikasi di bawah. Rujukan Hermes tidak tersedia, sehingga file rujukan belum dibaca.

### F2-T12: review latar belakang dan kurator terjadwal (8 Oktober 2026)

`src/clite/agent/review.py` (baru) menjalankan satu review di thread latar setelah giliran yang
selesai dan memakai setidaknya `background_review.min_tool_calls` tool call. Reviewer adalah
`AIAgent` terpisah dengan toolset sempit (`memory`, `skills`) dan anggaran
`background_review.max_turns`; ia menerima **salinan giliran** sebagai satu pesan pengguna —
teks saja, dibangun `build_turn_transcript` — dan berjalan dengan `persist=False`, jadi ia tidak
menulis baris sesi apa pun. Ia hanya menulis lewat tool memori dan skill, jadi riwayat dan
system prompt sesi utama tidak pernah tersentuh. Saksi di `turn/finalize.py`: setelah giliran
selesai, `should_review(..., ignore_busy=True)` memutuskan dan `spawn_background_review`
menjalankannya (kunci giliran masih dipegang saat itu, karena itu `ignore_busy`).

Gerbangnya: `background_review.enabled`, giliran selesai dan tidak terinterupsi, memori aktif,
bukan subagent (`depth > 0`), bukan platform `cron`, sesi tidak sibuk, dan tidak ada review lain
untuk sesi itu dalam `background_review.min_interval_seconds` terakhir. Review yang gagal atau
melewati `background_review.timeout_seconds` menjadi `error` pada hasil dan catatan log, tidak
pernah melempar ke giliran. Hasilnya terlihat: baris status `on_status("review", …)` di surface
dan catatan di log (`outcome.summary`).

Kurator dijalankan otomatis oleh `runtime/maintenance.py::run_curator_maintenance`, dipanggil
`run_startup_maintenance` setelah auto-prune dan pemangkasan checkpoint. Kunci config baru:
`curator.enabled`, `curator.interval_hours`, `curator.stale_days`, `background_review.*`.
Kurator berjalan paling banyak sekali per `curator.interval_hours` lewat cap waktu di database
(`last_curator_run`) — pola yang sama dengan auto-prune sesi — dan kegagalannya ditelan
(`_prune_curator_store` di dalam `try`), jadi surface tetap mulai. `curator.run_curator` kini
menerima `now=` supaya jamnya bisa disuntikkan.

Bukti regresi merah/hijau pada worktree bersih dari `a976469`. **Merah:** dengan tes baru saja
dan modul `review` belum ada, koleksi `tests/agent/test_review.py` gagal
(`ImportError: cannot import name 'review' from 'clite.agent'`); seluruh 23 tes tertutup. Untuk
membuktikan tiap guard secara terpisah, implementasi disalin ke worktree terisolasi lalu satu
perilaku dikembalikan ke bentuk yang salah:

- **riwayat sesi utama disentuh**: menambahkan pesan review ke `agent.messages` menggagalkan
  `test_review_writes_one_memory_entry_and_leaves_the_main_session_untouched` dan
  `test_a_real_long_turn_triggers_a_review_and_its_own_history_is_untouched`.
- **gagal tidak ditelan**: melempar `outcome.error` keluar `run_review` menggagalkan
  `test_a_failing_review_does_not_break_the_next_turn`; melempar pada timeout menggagalkan
  `test_a_timed_out_review_does_not_break_the_next_turn`.
- **kurator tiap startup**: menghapus gate interval menggagalkan
  `test_the_startup_curator_runs_at_most_once_per_interval` (3 pemanggilan, bukan 2); membuang
  penangkap galat di `run_startup_maintenance` menggagalkan
  `test_a_failing_curator_does_not_stop_a_session`.
- **gerbang review**: menghapus gate `enabled`/depth/cron/busy menggagalkan
  `test_a_subagent_turn_is_never_reviewed`, `test_a_cron_turn_is_never_reviewed`, dan
  `test_a_busy_session_is_not_reviewed`.
- **anggaran reviewer diabaikan**: memakai `max_turns` tetap besar menggagalkan
  `test_the_review_has_its_own_small_budget`.

Log lokal: `/tmp/clite-f2t12-red-collection.log` (merah koleksi), `/tmp/clite-f2t12-red-guards.log`
(merah per guard), `/tmp/clite-f2t12-green.log` (hijau). Sesudah implementasi, 23 tes
`tests/agent/test_review.py` lulus. Suite Python penuh: 1132 lulus, 29 terlewati, satu tes
`tests/server` gagal yang sudah gagal sebelum tugas ini (`websockets`). Ruff bersih, mypy 174
file bersih. Clone rujukan tetap `../hermes-ref` tidak tersedia; perilaku diambil dari salinan
Hermes Agent lain di mesin ini (commit `a0a7d765`, bukan commit yang dipatok).

### F2-T13: delegasi yang lebih kaya (8 Oktober 2026)

`src/clite/agent/delegation.py` menambah tiga kemampuan. **Model per tugas**: argumen `model`
pada `delegate_task` (dan pada tiap entri `tasks`) diresolusi lewat `parse_model_input` —
sebuah nama polos mempertahankan provider induk (`parent.route.with_model`), sedangkan
`provider:model` dan alias berpindah provider lewat `resolve_runtime_provider`. Provider yang
tidak bisa diresolusi melempar `CliteError` yang ditangkap per tugas, jadi ia menjadi hasil
galat untuk tugas itu saja (`_run_child` mengembalikan laporan `failed`); tugas lain tetap
jalan. **Kemajuan**: `_Progress` menyampaikan `on_subagent` dengan `tool`, `args` (pratinjau
argumen yang diredaksi lewat `core.redact`), `iteration` (dari `on_step`), dan `model`. Event
RPC `subagent.update` diperluas dengan bidang opsional `args`, `iteration`, `model`, `spawn_id`
(`rpc/contracts/schema.py`, `rpc/session.py`), dan surface menampilkannya (`cli/repl.py`,
`ui-tui/src/plain.ts`, `apps/shared/src/transcript.ts`). **Delegasi latar**:
`delegate_task(background=true)` memanggil `_run_background`, yang menjalankan tiap tugas di
thread sendiri dan langsung kembali dengan id. Laporan yang selesai masuk ke antrean catatan
induk (`AIAgent.queue_note`/`take_notes`); catatan itu ditempelkan pada hasil tool berikutnya
di `run_tool_round` — bukan dengan menulis ulang pesan yang sudah dikirim — dan menjadi pesan
internal baru bila tiba di antara giliran (`turn/iteration.py::_apply_notes`). Interupsi induk
menjalar ke subagent latar (anak terdaftar di `_children`), dan `AIAgent.close()` menunggu
thread latar (`wait_for_background`) sebelum menutup database sesi. **Peran pengatur**: dengan
`delegation.max_spawn_depth > 1`, `may_delegate` membuat anak tingkat tengah mendapat toolset
`delegation`, sedangkan cucu di dasar kedalaman tidak.

Bukti regresi merah/hijau pada worktree bersih dari `e53fda8`. **Merah:** dengan tes baru saja
dan implementasi belum ada, 10 dari 11 tes baru menggagalkan (`tests/agent/test_memory_and_
delegation.py`), dan tes baru `apps/shared/test/transcript.test.ts` gagal (1 dari 11). Untuk
membuktikan tiap guard secara terpisah, implementasi disalin ke worktree terisolasi lalu satu
perilaku dikembalikan ke bentuk yang salah:

- **catatan menulis ulang pesan terkirim**: membuang lampiran catatan di `run_tool_round`
  sehingga hanya jalur `_fold_note` yang menulis ulang hasil tool yang sudah dikirim
  menggagalkan `test_a_background_report_reaches_the_parent_as_a_note_without_rewriting_sent_messages`.
- **model per tugas diabaikan**: mengembalikan `_child_route` ke rute induk menggagalkan
  `test_a_task_with_a_model_runs_on_that_route`; membuat provider tak terkonfigurasi tidak
  melempar menggagalkan `test_an_unconfigured_model_fails_only_that_task`.
- **peran pengatur dimatikan**: `may_delegate` selalu `False` menggagalkan
  `test_a_middle_child_may_delegate_again_and_a_grandchild_may_not`.
- **interupsi tidak menjalar**: membuang penjalaran anak di `AIAgent.interrupt` menggagalkan
  `test_parent_interrupt_stops_a_background_subagent`.

**Hijau:** 38 tes `tests/agent/test_memory_and_delegation.py` lulus (11 baru). Suite Python
penuh: 1122 lulus, 29 terlewati, satu tes `tests/server` gagal yang sudah gagal sebelum tugas
ini (`websockets`). Ruff bersih, mypy 174 file bersih. `scripts/gen_rpc_contracts.py` dan
`scripts/gen_docs.py` dijalankan; bundle TUI dibangun ulang; `apps/shared` 22 tes lulus dan
`tsc --noEmit` bersih; `ui-tui` 18 tes lulus (11 e2e, 7 render). Clone rujukan `../hermes-ref`
tetap tidak tersedia, sehingga file rujukan belum dibaca.

### F2-T15: deteksi perintah yang lebih tahan penyamaran (8 Oktober 2026)

`src/clite/tools/approval.py` kini menilai **posisi perintah**. `shell_plain` dihasilkan satu
pembaca (`_shell_read`) yang sekaligus mencatat rentang tiap bagian berkutip, jadi pendeteksi
tahu bagian mana yang hanya **data** dan bagian mana yang **kode**. Kecocokan pola yang
seluruhnya berada di dalam satu bagian berkutip dianggap sebutan, bukan perintah: `git commit
-m "buang rm -rf / dari skrip"` dan `echo "rm -rf /"` berjalan tanpa ditolak, sedangkan
`rm -rf "/"` tetap hapus rekursif karena `rm` sendiri ada di posisi perintah. Bagian berkutip
yang memuat kode dibaca ulang sebagai perintah: muatan `sh -c`/`bash -c`/`zsh -c`/`eval`,
argumen `python -c`/`python3 -c`/`node -e`/`perl -e`/`ruby -e`, opsi `-c`/`-e`/`--command`/
`--eval` (`psql -c`), dan teks ke `os.system`/`subprocess.*`. **Penugasan variabel** di baris
yang sama diselesaikan lebih dulu (`_variable_values`/`_expand_variables`): `c=clite; $c config
set ...` ditangkap `detect_self_access` (tidak pernah diingat), `d=/; rm -rf $d` menjadi
`rm -rf /` (terlarang mutlak). **Larangan mutlak bertambah**: `kill -1`/`kill -HUP`,
`shutdown`/`reboot`/`halt`/`poweroff`, `init 0`/`init 6`, dan `mkfs` di posisi perintah — hanya
saat berada di posisi perintah, sehingga `echo "shutdown"` tetap data. **Batas penguraian**:
perintah lebih panjang dari `MAX_COMMAND_CHARS` (20.000) atau lebih bersarang dari
`MAX_COMMAND_DEPTH` (12 tingkat `$(`/subshell) ditolak dengan alasan yang menyebut sebabnya
(`choice="too_complex"`), bukan diloloskan. Ketiga pendeteksi (`detect_dangerous_command`,
`detect_hardline`, `detect_self_access`) menghormati batas ini dan membaca ulang muatan kode
secara rekursif, jadi `execute_code` yang mengirim teks Python lewat gerbang yang sama tetap
terjaga.

Bukti regresi merah/hijau pada worktree bersih dari `b5a547c` (di sana paket `clite` diarahkan
lewat `PYTHONPATH` ke `src` worktree, karena instalasi editable menunjuk checkout utama).
**Merah:** dengan 58 tes baru saja dan implementasi belum ada, 28 tes menggagalkan
(`tests/tools/test_approval.py`). Untuk membuktikan tiap guard secara terpisah, implementasi
disalin ke worktree terisolasi lalu satu perilaku dikembalikan ke bentuk yang salah:

- **posisi perintah dimatikan** (`_contained` selalu `False`): 13 tes gagal — sebutan berkutip
  kembali ditolak mutlak.
- **muatan kode tidak dibaca ulang** (`_code_payloads` mengembalikan kosong): 17 tes gagal —
  `bash -c "rm -rf /"` dan muatan interpreter lolos.
- **ekspansi variabel dimatikan**: 5 tes gagal — `c=clite; $c config set ...` dan
  `d=/; rm -rf $d` lolos.
- **pola larangan mutlak baru dibuang**: 6 tes gagal — `kill -1`, `shutdown`, `reboot`,
  `init 0` kembali hanya pola berbahaya yang bisa diingat.
- **batas penguraian dimatikan** (panjang dan kedalaman): 3 tes gagal — perintah raksasa dan
  bersarang diloloskan.

**Hijau:** 148 tes `tests/tools/test_approval.py` lulus (58 baru), seluruh `tests/tools` 402
lulus/13 terlewati. Suite Python penuh: 1178 lulus, 29 terlewati (`tests/server` butuh
`websockets`, gagal sebelum tugas ini). Ruff bersih, mypy 174 file bersih. Tiga contoh di baris
celah "Gerbang persetujuan tidak menjalankan shell" kini tertutup dan dijaga
`test_the_examples_in_the_security_document_are_caught`; sisa celahnya (substitusi bersarang
lebih dalam dari batas, skrip di file lain) tetap terdaftar. Clone rujukan `../hermes-ref`
tetap tidak tersedia, sehingga file rujukan belum dibaca.

## Pemasangan yang sudah diverifikasi

Pada 6 Oktober 2026 CI repo `https://github.com/dragovics/clite` run `37356398420` pada
commit `6e6669c` lulus di semua job. Job Python memasang paket dari registry dan
menjalankan Ruff, mypy, serta seluruh tes Python pada 3.11, 3.12, dan 3.13. Job Node 22
memasang dependensi dengan `npm ci` dari `package-lock.json`, menjalankan
`scripts/run_tests.sh` (termasuk pemeriksaan tipe), dan `npm run build`. Job wheel
membangun wheel, memasangnya ke virtualenv bersih, lalu `scripts/check_wheel_install.py`
lulus di luar checkout: CLI, doctor, giliran mock, plugin dan skill bawaan, aset dashboard,
dan TUI. Aset skill yang sengaja dihilangkan ditolak oleh pemeriksa tersebut (dicoba lokal).
Kendala penagihan yang tercatat pada repo sebelumnya tidak muncul di repo tujuan ini.
F1-T1 selesai.

### F1-T7: rilis GitHub terbit dan teruji

Distribusi `c-lite` versi `0.1.0` memakai MIT; import dan CLI tetap `clite`.
Pada 7 Oktober 2026 runner memverifikasi ulang build wheel/sdist, pemeriksaan versi
terhadap calon tag `v0.1.0`, pemasangan wheel ke virtualenv terpisah, dan
`scripts/check_wheel_install.py` dengan Python mode terisolasi di luar checkout.
CLI, doctor, giliran mock, plugin/skill bawaan, aset dashboard dan TUI lulus.
Instalasi pipx dari wheel yang disajikan lewat HTTP lokal juga menghasilkan versi benar
dan doctor lulus; metadata instalasinya menunjuk URL loopback, **bukan GitHub**.
Sdist sudah dipasang di lingkungan terpisah dan menghasilkan CLI versi `0.1.0`.
Doctor memakai config provider `mock`, bukan kredensial atau provider sungguhan.

Sembilan tes `tests/test_release.py` menjaga versi tunggal, tag yang cocok, changelog,
kenaikan versi, isi wheel dan penolakan tag pada tree kotor/duplikat. Bukti regresi di
salinan terpisah: metadata lama menggagalkan dua tes; pelepasan pemeriksaan tag, penulisan
versi, isi catatan rilis, dan pemeriksaan wheel masing-masing menggagalkan satu tes.
Sesudah kode dipulihkan, sembilan tes lulus. Log lokal: /tmp/clite-f1t7-red.log.

F1-T7 selesai: workflow `37563420757` hijau pada `e65bb0c` (build, Python 3.11/3.13,
publish). Rilis https://github.com/dragovics/clite/releases/tag/v0.1.0 memuat wheel dan
sdist. Aset diunduh lewat `gh release download`, digest SHA-256 cocok dengan GitHub,
wheel dipasang dengan pipx terisolasi dan lulus versi, doctor mock serta smoke test.
Repositori tetap privat; unduhan perlu autentikasi. Main belum di-merge; F1-T2 tetap parsial.

### F3-T3 dipecah (8 Oktober 2026)

F3-T3 (TUI layar penuh, XL) dipecah menjadi F3-T9…F3-T15, masing-masing M atau lebih kecil,
tanpa mengubah kode: kerangka aplikasi Ink (F3-T9), bilah status (F3-T10), dialog persetujuan
dan klarifikasi (F3-T11), pelengkapan slash command (F3-T12), pemilih sesi dan model (F3-T13),
tema dari skin dan tahan ubah ukuran (F3-T14), dan bundle Ink dalam satu `.mjs` (F3-T15).
Kecuali F3-T12 (yang juga menunggu F3-T4), semuanya bergantung pada F3-T9.

Keputusan desain yang mengikat semua anak: **Ink + React** (disetujui pemilik proyek), ditanam
esbuild ke dalam satu file `.mjs` sehingga `pip install` tetap menghasilkan `clite tui` yang
jalan tanpa `npm install` — ini pengecualian tertulis terhadap aturan "tanpa dependensi runtime
baru" di `ui-tui/AGENTS.md`, yang akan diperbarui di F3-T9. Antarmuka baris (`plain.ts`) tetap
ada sebagai `--plain` dan untuk masukan pipa, dan tes ujung ke ujung yang ada harus lulus di
kedua mode. Yang dipakai ulang tanpa diubah: `backend.ts`, `gateway-client.ts`, dan reducer
`transcript.ts`. Setiap rujukan Hermes yang disebut di pecahan sudah diperiksa keberadaannya
(`ui-tui/src/...`, `ui-tui/scripts/build.mjs`). Tidak ada kode yang berubah; hanya
`docs/roadmap/fase-3-cli-tui.md`, `docs/roadmap/README.md`, dan `docs/spesifikasi/tui.md`.

### F3-T7: pelengkapan shell (8 Oktober 2026)

`clite completion bash|zsh|fish` mencetak skrip pelengkapan yang dibangun dengan menelusuri
pohon parser `main` yang sama (`build_parser`), jadi daftar sub-perintah dan opsi selalu sama
dengan yang benar-benar diterima CLI dan ikut berubah saat plugin menambah perintahnya —
tidak ada daftar nama yang dieja dua kali. Nilai dinamis (nama profil, model, id sesi)
dilengkapi lewat `clite completion --values profiles|models|sessions`, yang membaca katalog
dan mencetak satu nama per baris. Jalur `--values` sengaja tidak membangun parser dan tidak
memuat plugin (diukur ~20 ms, `clite.plugins.manager` tidak masuk `sys.modules`), karena ia
dipanggil pada tiap Tab; galat apa pun di situ ditelan agar Tab tidak pernah gagal.

Sifat yang dijaga tes (`tests/cli/test_cli.py`): skrip bash memuat setiap sub-perintah yang
benar-benar terdaftar di parser; skrip bash lulus `bash -n`; skrip zsh diawali `#compdef clite`
dan fish memakai `complete -c clite`; `--values profiles` memuat `default`; dan
`--values sessions` menjawab tanpa memuat plugin. Baris "pelengkapan shell" di
`docs/spesifikasi/cli.md` menjadi ✅. Skrip zsh dan fish belum dijalankan di shell aslinya
(keduanya tidak terpasang di mesin ini) — bentuknya diperiksa mata dan lolos pemeriksaan
sintaks yang tersedia; dicatat sebagai belum diverifikasi terhadap zsh/fish sungguhan.
F3-T7 selesai.

### F3-T1: input REPL klasik — saat sibuk, multi-baris, riwayat (8 Oktober 2026)

REPL klasik kini menerima masukan selagi agent bekerja: giliran berjalan di thread pekerja dan
thread utama terus membaca. Baris yang datang saat sibuk mengikuti `display.busy_input_mode`
lewat `TurnQueue` di `runtime/session.py`, logika antrean yang sama dipakai RPC dan gateway —
`RpcSession` tidak lagi menyimpan salinannya. Masukan multi-baris (`\` di ujung baris, atau
Alt+Enter) dan tempel berkurung ditangani `cli/input.py`.

`prompt_toolkit` dipakai bila ada (pemilik baris prompt, keluaran streaming lewat
`patch_stdout` sehingga tidak menimpa yang sedang diketik, riwayat di `~/.cli_history`, dan
pelengkapan Tab untuk nama model/skill/sesi). Tanpa `prompt_toolkit`, `StdlibReader` tetap
jalan — REPL pustaka standar adalah jalur cadangan yang tetap diuji. Logika reader dipisah ke
`cli/input.py` supaya tidak bocor ke `repl.py`.

Sifat yang dijaga tes: baris saat sibuk diantrekan/interupsi/mengarahkan sesuai mode lewat
`ChatSession` (`tests/runtime/test_session_and_slash.py`, `tests/cli/test_cli.py`); tes RPC dan
gateway mode sibuk tetap lulus setelah logika pindah (`tests/rpc`, `tests/gateway`); dan dengan
`prompt_toolkit` disembunyikan seluruh `tests/cli` lulus di jalur `StdlibReader`. Baris
"Mengetik saat agent bekerja" dan "Input multi-baris, tempel gambar" di
`docs/spesifikasi/cli.md` menjadi ✅.

Penutupan F3-T1 membersihkan dua galat `mypy` yang tersisa di berkasnya (anotasi `self.session`
di `cli/input.py`, dan `hasattr(reader, "streaming")` → `getattr` di `cli/repl.py`), sehingga
`mypy` kembali bersih pada 176 file. F3-T1 selesai.

### F3-T2: render Markdown dan diff (8 Oktober 2026)

`cli/markdown.py` (baru) merender Markdown menjadi teks berwarna, **bertahap** saat jawaban
mengalir: baris yang sudah lengkap dirender, baris yang belum selesai ditahan. Blok kode tidak
pernah dibaca sebagai Markdown — isinya ditampilkan apa adanya sampai pagar penutupnya tiba.
Tabel yang lebih lebar dari terminal dipotong kolomnya dari kanan sampai muat, dengan penanda
potongan. Diff `patch`/`write_file` diberi warna per baris (tambah, hapus, hunk, konteks) dan
dipotong pada batas panjang supaya tambalan besar tidak membanjiri layar.

Perendernya **murni**: tidak menyentuh I/O, tidak membaca variabel lingkungan, dan tidak
mengeja satu pun kode warna ANSI. Warnanya datang dari `MarkdownStyle` yang dibangun lapisan
tampilan dari kulit: `runtime/presentation.py::markdown_role_codes` memetakan peran
(`heading`, `code`, `diff_add`, …) ke kode warna yang dipilih kulit, dan bila warna mati
(`NO_COLOR`, terminal bodoh, atau keluaran dialihkan ke berkas) peta itu kosong sehingga yang
keluar teks polos yang tetap terbaca. Karena itu perender bisa diuji dengan membandingkan
string. Aturan yang sama ditulis ulang di `ui-tui/src/render.ts` (`renderMarkdown`,
`MarkdownStream`, `renderDiff`, `markdownStyle`) supaya CLI dan TUI tampil seragam.

Sifat yang dijaga tes: potongan streaming berukuran acak menghasilkan keluaran yang **sama
persis** dengan teks utuh (`tests/cli/test_markdown.py`, invariant dijalankan pada tiap titik
potong); blok kode tidak pernah dirender sebagai Markdown; tabel lebar dipotong sesuai lebar
terminal; dan tanpa warna yang keluar adalah teks polos. `MarkdownStream.view()` memberi
seluruh tampilan saat ini termasuk baris yang belum selesai, sehingga jawaban terlihat saat
sedang diketik; surface hanya mencetak bagian yang belum tercetak, jadi tidak ada baris yang
tercetak dua kali.

Bukti regresi di salinan terpisah: dengan `cli/markdown.py` disingkirkan, 29 tes
`tests/cli/test_markdown.py` merah; dengan penambahan Markdown di `ui-tui/src/render.ts`
dikembalikan ke `HEAD`, 18 tes `ui-tui/test/render.test.ts` merah. Sesudah kode dipulihkan
keduanya hijau. Suite Python penuh 1244 lulus/29 terlewati (satu tes `tests/server` gagal
sebelum tugas ini, `websockets`), Ruff bersih, mypy 176 file bersih, 22 tes `apps/shared` lulus, 18 tes `ui-tui` lulus,
11 tes e2e TUI lulus, `tsc --noEmit` bersih di `apps/shared` dan `ui-tui`, bundle TUI dibangun
ulang. Clone rujukan `../hermes-ref` tidak tersedia; rujukan dibaca dari
`/home/luwak/.hermes/hermes-agent`.
F3-T2 selesai.

### F3-T4: slash command tambahan (8 Oktober 2026)

Dua belas perintah baru ditambahkan, masing-masing satu baris `CommandDef` di
`COMMAND_REGISTRY` dan satu handler `_handle_<nama>` yang mengembalikan `SlashResult`
(handler tidak mencetak dan tidak membaca masukan). Tabel bawaan naik dari 32 menjadi
**44** perintah; baris slash command di `docs/spesifikasi/runtime.md` diperbarui dan halaman
`docs/referensi/katalog.md` dibuat ulang.

Sifat yang dijaga tes (`tests/runtime/test_session_and_slash.py`, semua lewat
`ChatSession.run_slash`):

- `/branch [judul]` menyalin pesan aktif ke sesi baru **tanpa `provider_data`** (awalan
  percakapan berbeda, jadi blok penalaran bertanda tangan induk tidak berlaku), mencatat
  `parent_session_id`, memakai judul `(branch)` bila tidak diberi judul, dan berpindah ke
  sesi baru. Id baris induk tidak ditulis balik; baris sesi induk diberi
  `end_reason="branched"`.
- `/queue <teks>` menitipkan catatan ke giliran yang berjalan (`agent.queue_note`), dan
  melaporkan bila tidak ada yang berjalan.
- `/background <teks>` menjalankan satu giliran di sesi yang dibangun sendiri dan
  melaporkan jawabannya; percakapan ini tidak tersentuh.
- `/export [path]` menulis transkrip terlihat sebagai Markdown atau JSON menurut ekstensi,
  dan menolak ekstensi lain dengan pesan yang jelas.
- `/context` memecah jendela (token, peringkat prompt, skema tool, riwayat); `/tasks`
  menampilkan daftar `todo` lewat `agent.todos.read()`/`summary()`.
- `/hooks` menampilkan `configured_hooks()` dan menandai yang belum disetujui
  (`is_approved`).
- `/pin` dan `/archive` menyetel `pinned`/`archived` lewat `update_session`, dan sesi
  terarsip hilang dari `list_sessions`.
- `/verbose [off|new|all|verbose]` menyetel `display.tool_progress` untuk sesi ini.
- `/skin`, `/logs`, `/copy` bertanda `cli_only`: ditolak di platform pesan; `/copy`
  mengembalikan `action="clipboard"` dan surface CLI yang menulis ke clipboard
  (`cli/clipboard.py`, pustaka standar saja: `pbcopy`/`wl-copy`/`xclip`/`xsel` lalu OSC 52).

Bukti regresi: pada worktree bersih `d2d70c8` dengan berkas tes baru saja, 16 tes baru
merah (`Unknown command: /...`); sesudah implementasi 44 tes `tests/runtime/test_session_and_slash.py`
lulus. `test_every_command_has_a_handler_and_every_handler_a_command` tetap lulus (kunci
`SLASH_HANDLERS` == nama `COMMAND_REGISTRY`, nama dan alias unik).
F3-T4 selesai.

### F3-T9: kerangka aplikasi Ink (8 Oktober 2026)

`clite tui` kini memilih antara UI layar penuh Ink dan UI baris: `chooseUi({stdinIsTTY,
stdoutIsTTY, plain})` mengembalikan `"ink"` hanya bila kedua stream adalah TTY dan `--plain`
tidak diberikan; selain itu (pipa, non-TTY) `"plain"`. Fungsi pemilih diuji tanpa terminal
sungguhan (`ui-tui/test/app.test.ts`). Komponen akar Ink (`App.tsx`) merender transkrip dari
reducer `apps/shared/src/transcript.ts` yang sama dengan `plain.ts` — keduanya tidak bisa
berbeda pendapat — plus sebuah kotak tulis satu baris yang mengirim `prompt.submit`. Bila
Ink gagal dimuat saat runtime, `entry.ts` jatuh ke `PlainTui` dengan catatan di stderr.

`ink` dan `react` masuk sebagai `devDependencies` di `ui-tui/package.json` dan dibundel
esbuild ke dalam satu `clite-tui.mjs` (1.4 MB), sehingga `pip install` tetap menghasilkan
`clite tui` yang jalan tanpa `npm install`. `react-devtools-core` (hook devtools opsional
ink) di-alias ke stub no-op; `signal-exit` (CJS) ditangani dengan shim `createRequire` di
banner esbuild. `ui-tui/AGENTS.md` mencatat pengecualian dependensi ini. File `.tsx`
dibundel (JSX bukan TS yang bisa dihapus); logika yang bisa diuji (pemilih, reducer) tetap
di `.ts` yang diuji `node --test`.

Bukti: 5 tes `app.test.ts` merah sebelum implementasi (`chooseUi` belum ada), hijau
sesudahnya. 11 tes e2e tetap lulus (mode `--plain` utuh); `tsc --noEmit` bersih; bundle
dibangun ulang dan lolos tes hash sumber. Smoke test `echo hi | clite tui --plain`
menampilkan banner, jawaban, dan penanda sesi. TUI Ink belum diuji di terminal sungguhan
(sandbox ini tidak punya PTY untuk `stdin`+`stdout` interaktif) — dicatat sebagai belum
diverifikasi terhadap terminal asli; komponennya tipe-benar dan dibangun tanpa galat.
F3-T9 selesai.

## Ditulis, belum diverifikasi

Semua butir ini punya kode, dan sebagian punya tes terhadap tiruan, tetapi belum pernah
dijalankan terhadap hal yang sebenarnya. Anggap belum berfungsi sampai terbukti.

| Hal | Keadaan | Task |
|---|---|---|
| Rilis GitHub wheel/sdist | Artefak lokal dan instalasi pipx/virtualenv teruji; workflow tag, penerbitan, dan unduhan aset privat belum dijalankan | F1-T7 |
| Panggilan ke provider sungguhan | Belum pernah. Transport `anthropic_messages` dan `chat_completions` hanya diuji terhadap server tiruan. Ini termasuk pemutaran ulang blok penalaran bertanda tangan pada model Claude generasi 5, yang aturannya diambil dari dokumentasi, bukan dari pengamatan | F1-T2 |
| Teks penalaran model generasi 5 (`thinking.display`) | Diterapkan: profil `anthropic` meminta `display: summarized` bila `display.show_reasoning` aktif. Belum dicoba ke API asli | F1-T2 |
| Transport `responses` | Diuji terhadap server HTTP lokal untuk streaming/nonstreaming dan dua ronde tool; `test_openai_responses_replays_reasoning_across_two_tool_rounds` belum dijalankan karena pemilik menunda uji API asli | F2-T1 |
| Sepuluh profil tambahan gelombang pertama | Rute, bentuk HTTP streaming/nonstreaming, dan discovery setup diuji dengan server lokal. API asli (termasuk server LM Studio/vLLM sungguhan) belum pernah dipanggil; profil cloud Azure/Bedrock/Vertex juga hanya diuji lokal | F2-T2 🟡 |
| Provider pencarian web (`web-search-ddg`, `web-search-tavily`) | Diuji terhadap server HTTP lokal yang meniru API pencarian. DuckDuckGo dan Tavily asli belum pernah dipanggil | F2-T5 ✅ |
| Masukan dan analisis gambar ke provider sungguhan | Bentuk konten dan permintaan `vision_analyze` diuji terhadap transport dan terhadap HTTP loopback, bukan API asli. Mengirim gambar ke provider berpenglihatan sungguhan (dan perilaku model tanpa penglihatan terhadap gambar yang ditahan) belum pernah dijalankan | F2-T6 ✅ (uji asli belum) |
| Pembuatan gambar lewat OpenAI Images (`image-gen-openai`) | Bentuk permintaan (`/v1/images/generations`, `model`/`prompt`/`size`/`n`) dan dekode `b64_json` diuji terhadap server lokal. API asli belum pernah dipanggil | F2-T6 ✅ (uji asli belum) |
| Masukan gambar ke provider sungguhan | Bentuk konten diuji terhadap transport dan terhadap HTTP loopback, bukan API asli. Mengirim gambar ke provider berpenglihatan sungguhan (dan perilaku model tanpa penglihatan terhadap gambar yang ditahan) belum pernah dijalankan | F2-T6 🟡 |
| Backend terminal Docker | Kode ada dan diuji: pemilihan lewat `terminal.backend`, penolakan tanpa `terminal.docker.image`, penyusunan argv `docker run`/`docker exec`, dan env klien Docker. Tiga tes bertanda `docker` terlewati di mesin ini (tidak ada daemon). Menjalankan container sungguhan, mount, isolasi berkas di luar mount, dan pembersihan belum pernah | F2-T7 🟡 |
| Backend terminal SSH | Kode ada dan diuji lewat transport tiruan: resolusi path, `read_file`/`write_file`/`list_dir`/`stat`, dan penolakan tanpa `terminal.ssh.host`. Koneksi ControlMaster, transfer berkas, dan `~/.ssh/config` sungguhan belum pernah dijalankan | F2-T7 🟡 |
| Tes jaringan provider (`tests/providers/test_live.py`) | Ditulis, belum pernah dijalankan: menunggu kunci Anthropic dan satu provider kompatibel OpenAI | F1-T2 |
| Persetujuan `smart` dengan model sungguhan | Hanya diuji dengan model berskrip | F1-T2 |
| Adapter Telegram | Hanya terhadap Bot API tiruan. Daftar periksa bot sungguhan di F1-T3 belum dijalankan: menunggu token bot dan grup uji | F1-T3 |
| Pengiriman cron ke `<platform>:<chat id>` | Diuji dengan adapter `local` dan divalidasi saat job dibuat; ke Telegram sungguhan belum | F1-T3 |
| Windows | Terverifikasi CI `37499972911` pada `6360a9a`: 765 lulus, 59 terlewati. ACL `.env`, cmd/Git Bash, penghentian pohon proses, home/path, dan kunci dua proses lulus; REPL manual belum dicoba | F1-T5 ✅ |
| macOS | Belum pernah dijalankan | F1-T1 |
| Plugin lewat entry point pip | Jalur muatnya ada; belum diuji dengan paket yang benar-benar terpasang | F6-T5 |
| Cangkang Electron (`apps/desktop/src/main.ts`, `preload.ts`, `build.mjs`) | Ditulis tanpa Electron terpasang; belum pernah dijalankan | F5-T1 |
| Model atau harness selain Claude Code | Belum pernah ada yang mengerjakan repositori ini. Panduan peralihannya disusun dari isi repositori, belum dari sesi nyata ([PANDUAN-MODEL-LAIN.md](PANDUAN-MODEL-LAIN.md)) | Coba dengan satu task S |
| Skill dan subagent Claude Code di `.claude/` | Ditulis mengikuti dokumentasi Claude Code; belum pernah dipanggil di Claude Code. Bila `/orientasi` tidak dikenali, tempel bagian "Prompt" dari file di `docs/prompts/` | Coba dengan `/orientasi` |

Yang sudah teramati dari integrasi Claude Code, di sesi cloud tempat scaffolding ini dibuat
(Claude Code 2.1.289 terpasang di sana):

- `CLAUDE.md` di root dimuat bersama `AGENTS.md` yang diimpornya, dan `CLAUDE.md` sebuah
  direktori ikut dimuat saat file di direktori itu dibaca.
- Subagent `peninjau` dikenali, dengan nama, deskripsi, dan daftar tool yang benar.
- `claude --help` versi itu memuat `--model` dengan alias `fable`, `--effort` dengan lima
  tingkatnya, dan `--permission-mode plan`, sesuai yang ditulis di `docs/prompts/README.md`.

Kesepuluh skill di `.claude/skills/` sengaja disembunyikan dari model
(`disable-model-invocation`), jadi pemuatannya tidak bisa diamati dari sesi itu. Itu sebabnya
skill tetap ada di tabel di atas.

Hal lain yang perlu diketahui:

- **Beban dan skala belum diuji.** Tidak ada tes untuk sesi yang sangat panjang, banyak sesi
  gateway bersamaan, atau database yang besar.
- **Bedah Hermes** (`docs/hermes/`) ditulis dari membaca kode pada satu commit. Keberadaan
  setiap file yang dirujuk sudah diperiksa mesin; uraian perilakunya tidak diperiksa ulang
  satu per satu.
- **Ukuran task di roadmap adalah perkiraan.**

## Tinjauan pihak kedua

Pada 6 Oktober 2026 verifikasi gabungan perbaikan audit selesai: 758 tes Python lulus,
2 skip paket opsional, Ruff dan mypy bersih, serta 47 tes Node dan seluruh typecheck lulus.
F08/F09 kini menjaga home, model, database, dan rahasia dua profil pada worker RPC/HTTP;
penutupan WebSocket membawa scope yang sama. Redaksi juga mencakup rahasia scope dan
mendahulukan nilai terpanjang agar awalan bersama tidak menyisakan potongan rahasia.
Sembilan regresi gagal pada snapshot sebelum perbaikan. Tes katalog yang tanpa sengaja
mengakses endpoint publik diganti dengan server lokal, dan tes startup TUI dibuat mandiri
terhadap keadaan pemasangan paket. Provider asli dan UI Electron tetap belum
terverifikasi. Perkembangan berikutnya dicatat di [checkpoint](CHECKPOINT-KERJA.md).

Tinjauan tambahan pada 5 Oktober 2026 menemukan empat celah prioritas tinggi pada rotasi
kredensial endpoint kustom, delegasi tool, sesi tanpa izin tool, dan penulisan skill lewat
symlink. Perbaikannya sudah masuk bersama tes regresi. Suite Python setelah perbaikan lulus
720 tes dan melewati 2 tes yang butuh paket opsional. Pengujian dengan provider sungguhan
belum dilakukan. Perbaikan lanjutan memperjelas tipe handler RPC dan menolak kategori
pemasangan skill yang keluar dari direktori lokal. Lima regresi pemasangan gagal pada
salinan kode lama dan 35 tes skill lulus setelah perbaikan; pemeriksaan tipe area RPC
lulus. Verifikasi gabungan perubahan lanjutan masih berlangsung.

Pada 5 Oktober 2026 tiga peninjau independen (subagent yang tidak melihat proses pembuatan)
dijalankan. **Ketiganya terhenti oleh batas pemakaian sebelum menulis laporan.** Yang bisa
diselamatkan hanya percobaan peninjau keamanan:

| Tinjauan | Hasil |
|---|---|
| Gerbang persetujuan perintah | Ditemukan cara murah melewati dua janji: larangan mutlak (`rm -rf "$HOME"`, `rm -rf '/'`, `rm --recursive --force /`) dan pertanyaan untuk perintah yang menjangkau pengaturan agent (glob seperti `~/.clite/.e*`, `~//.clite`, CLI lewat path absolut). Semuanya diperbaiki dan dijaga tes. Sisa yang tidak terbaca gerbang didaftar di [celah yang diketahui](arsitektur/06-keamanan.md#celah-yang-diketahui) |
| Pemeriksa alamat `web_fetch` | Bertahan terhadap bentuk alamat yang dicoba (IPv4 terpetakan ke IPv6, alamat numerik) |
| Penjaga file | Saat memperbaiki gerbang di atas ditemukan dua celah lagi dan ditutup: `.env` profil lain bisa dibaca, dan `gateway/pairing.json` bisa ditulis |
| Kredensial dan redaksi, pemindai teks prompt, plugin dan shell hook, server, otorisasi gateway | **Belum ditinjau pihak kedua** |
| File instruksi (`AGENTS.md`, prompt, skill) terhadap kode | **Tidak ada laporan** |
| Uji petik uraian di `docs/hermes/` terhadap kode Hermes | **Tidak ada laporan** |

Mengulang ketiga tinjauan itu sampai selesai adalah pekerjaan pertama yang layak dilakukan
sebelum pagar keamanan diandalkan.

## Belum ada

Yang ada di Hermes dan belum ada di sini didaftar di
[arsitektur/07-beda-dengan-hermes.md](arsitektur/07-beda-dengan-hermes.md#yang-belum-dibawa),
dan setiap butirnya punya task di [roadmap](roadmap/README.md). Yang paling terasa bagi
pemakaian harian: pencarian web, backend terminal bersandbox, render Markdown, TUI layar
penuh, dan platform pesan selain Telegram.

Celah keamanan yang diketahui didaftar tersendiri di
[arsitektur/06-keamanan.md](arsitektur/06-keamanan.md#celah-yang-diketahui). Yang terpenting:
**tidak ada sandbox**. Perintah yang lolos gerbang persetujuan berjalan dengan hak penuh
pengguna.

## Menjalankan pemeriksaan

```bash
pip install -e ".[dev]"
npm install                                                  # opsional: type check dan build TypeScript
scripts/run_tests.sh                                         # lint, mypy, tes Python, tes TypeScript
python scripts/check_hermes_refs.py --hermes ../hermes-ref   # butuh clone Hermes
```

## Catatan verifikasi

| Tanggal | Yang diverifikasi | Di mana |
|---|---|---|
| 7 Oktober 2026 | F1-T7: 820 tes Python lulus/26 terlewati, Ruff/mypy 160 file bersih; 47 tes Node dan tiga typecheck lulus. Build, instalasi wheel/doctor/mock/TUI dan pipx lokal lulus; enam kegagalan regresi di salinan terpisah, sembilan tes rilis kembali lulus sesudah dipulihkan. Belum menerbitkan rilis GitHub | Linux, Python 3.11.16, Node 26.7.0 |
| 5 Oktober 2026 | Seluruh tabel "Dijaga tes" di atas | Linux, Python 3.13, Node 22.22 |
| 5 Oktober 2026 | Wheel dibangun dan dipasang ke lingkungan virtual bersih. Dari sana: `clite --version`, `clite doctor`, satu giliran dengan provider `mock`, `clite tui --help`, satu giliran lewat TUI, daftar plugin dan skill bawaan, dan `clite serve` (file dashboard, pemeriksaan token, satu giliran lewat WebSocket). Dependensi diambil dari paket sistem dan `websockets` dari clone, bukan dari PyPI | Linux, Python 3.13, Node 22.22 |
| 5 Oktober 2026 | `scripts/rename_project.py` pada salinan repositori, diikuti langkah lanjutan yang dicetaknya: `scripts/run_tests.sh` lulus seluruhnya dan program hasil ganti nama berjalan. Yang tersisa dari nama lama hanya URL repositori di README | Linux, Python 3.13, Node 22.22 |
| 5 Oktober 2026 | Workflow CI terpicu di GitHub pada setiap push; semua job ditolak sebelum berjalan karena akun terkunci masalah penagihan | GitHub Actions |
| 6 Oktober 2026 | F1-T6 lokal: penulis config `ruamel.yaml` mempertahankan format; suite penuh 811 lulus, 26 skip; CI belum jalan | Linux, Python 3.11 |
| 6 Oktober 2026 | `install_skill("anthropics/skills/skills/pdf")` memasang skill dari GitHub sungguhan tanpa token (`pytest tests/skills -m network`) | Linux, Python 3.13 |
| 8 Oktober 2026 | F2-T6 langkah 1: 14 regresi merah pada salinan `5ae95cd` dengan tes baru saja, 46 tes baru lulus sesudah implementasi; suite Python penuh 995 lulus/26 terlewati, Ruff dan mypy 164 file bersih; 21 tes Node `apps/shared` dan 18 tes `ui-tui` lulus, bundle TUI dibangun ulang | Linux, Python 3.11.16, Node 26.7.0 |
| 8 Oktober 2026 | F2-T6 langkah 2 dan 3: regresi merah pada worktree bersih dari `1a6cdab` (2 `ImportError` + 2 kegagalan arsitektur), 20 tes baru + arsitektur lulus sesudah implementasi; suite Python penuh 1016 lulus/26 terlewati (1 gagal sudah-ada di `tests/server`), Ruff bersih, mypy 167 file bersih | Linux, Python 3.11.16 |
| 8 Oktober 2026 | F2-T7: 10 gagal + 1 error pada salinan `1a6cdab` dengan tes baru saja, 14 lulus / 3 terlewati (tanpa Docker) sesudah implementasi; suite tool file + terminal lama 56 lulus lewat antarmuka baru; suite Python penuh 1010 lulus/29 terlewati (satu tes server gagal sebelum tugas ini), Ruff dan mypy bersih. Docker dan SSH asli belum dijalankan | Linux, Python 3.11.16 (Docker CLI ada, daemon tidak) |
| 8 Oktober 2026 | F2-T8: 14 gagal pada salinan bercabang dengan tes baru saja tanpa penyambungan, 19 tes baru lulus sesudah implementasi; dua guard diuji terpisah (hapus penjaga `read_denied_reason`, lumpuhkan pemangkasan sesi) dan keduanya menggagalkan tesnya; suite `tests/tools`+`tests/runtime`+`tests/core` 393 lulus/13 terlewati, `tests/test_architecture.py` dan `tests/test_docs.py` lulus sesudah `python scripts/gen_docs.py` | Linux, Python 3.11.16 |
| 8 Oktober 2026 | F2-T9: merah pada salinan `eb5f031` dengan tes baru saja (1 error koleksi, modul belum ada); 23 tes baru lulus sesudah implementasi; tiga guard diuji terpisah pada salinan terisolasi (batas waktu, gerbang persetujuan, kredensial) dan masing-masing menggagalkan tesnya; suite Python penuh 1073 lulus/29 terlewati (satu tes `tests/server` gagal sebelum tugas ini, `websockets`), Ruff bersih, mypy 171 file bersih | Linux, Python 3.11.16 |
| 8 Oktober 2026 | F2-T10: 13 tes baru merah pada worktree bersih `4156234` dengan tes baru saja, 21 tes `tests/tools/test_mcp.py` lulus sesudah implementasi; empat guard diuji terpisah pada salinan terisolasi (A1, jeda membesar, header `.env`, tool resources) dan masing-masing menggagalkan tesnya; MCP HTTP diuji terhadap server Streamable HTTP dari SDK resmi (termasuk middleware bearer token), terlewati bila SDK tidak terpasang; suite Python penuh 1092 lulus/29 terlewati (satu tes `tests/server` gagal sebelum tugas ini), Ruff bersih, mypy 173 file bersih. Sampling dan OAuth belum ada | Linux, Python 3.11.16 (SDK `mcp` 2.0.0) |
| 8 Oktober 2026 | F2-T11: merah pada worktree bersih `f119b29` dengan tes baru saja (koleksi gagal: `cannot import name 'SUMMARY_SECTIONS'`); enam guard diuji terpisah pada salinan terisolasi (bagian tetap, peringkasan bertahap, pemangkasan gambar, jangkar token, persistensi penghitung nudge, skrip pengukuran) dan masing-masing menggagalkan tesnya; 10 tes baru lulus sesudah implementasi, seluruh `tests/agent/test_compression.py` 33 lulus; suite Python penuh 1109 lulus/29 terlewati (satu tes `tests/server` gagal sebelum tugas ini, `websockets`), Ruff bersih, mypy 173 file bersih. `scripts/eval_compression.py --provider mock` melaporkan 5/5 fakta bertahan | Linux, Python 3.11.16 |
| 8 Oktober 2026 | F2-T12: merah pada worktree bersih `a976469` dengan tes baru saja (koleksi `tests/agent/test_review.py` gagal: `cannot import name 'review' from 'clite.agent'`); enam guard diuji terpisah pada worktree terisolasi (riwayat sesi utama, gagal ditelan, timeout ditelan, gate interval kurator, gerbang enabled/depth/cron/busy, anggaran reviewer) dan masing-masing menggagalkan tesnya; 23 tes baru lulus sesudah implementasi; suite Python penuh 1132 lulus/29 terlewati (satu tes `tests/server` gagal sebelum tugas ini, `websockets`), Ruff bersih, mypy 174 file bersih. Clone rujukan tetap `../hermes-ref` tidak tersedia | Linux, Python 3.11.16 |
| 8 Oktober 2026 | F2-T13: merah pada worktree bersih `e53fda8` dengan tes baru saja (10 dari 11 tes baru `tests/agent/test_memory_and_delegation.py` gagal, tes baru `apps/shared/test/transcript.test.ts` gagal); empat guard diuji terpisah pada worktree terisolasi (catatan tidak menulis ulang pesan terkirim, model per tugas, peran pengatur, penjalaran interupsi) dan masing-masing menggagalkan tesnya; 11 tes baru + 27 lama lulus sesudah implementasi; suite Python penuh 1122 lulus/29 terlewati (satu tes `tests/server` gagal sebelum tugas ini, `websockets`), Ruff bersih, mypy 174 file bersih, `apps/shared` 22 tes lulus, bundle TUI dibangun ulang. Clone rujukan `../hermes-ref` tidak tersedia | Linux, Python 3.11.16, Node 26.7.0 |
| 8 Oktober 2026 | F2-T15: merah pada worktree bersih `b5a547c` dengan `PYTHONPATH` ke `src` worktree (instalasi editable menunjuk checkout utama) dan 58 tes baru saja: 28 tes `tests/tools/test_approval.py` gagal; lima guard diuji terpisah pada worktree terisolasi (posisi perintah 13 gagal, muatan kode 17, ekspansi variabel 5, larangan mutlak baru 6, batas penguraian 3) dan masing-masing menggagalkan tesnya; 148 tes lulus sesudah implementasi, seluruh `tests/tools` 402 lulus/13 terlewati; suite Python penuh 1178 lulus/29 terlewati (satu tes `tests/server` gagal sebelum tugas ini, `websockets`), Ruff bersih, mypy 174 file bersih. Clone rujukan `../hermes-ref` tidak tersedia | Linux, Python 3.11.16 |
| 8 Oktober 2026 | F3-T7: 5 tes baru merah sebelum implementasi (`completion` belum ada), hijau sesudah; skrip bash dibangun dari parser nyata (memuat setiap sub-perintah terdaftar, termasuk dari `misc`) dan lolos `bash -n`; `--values profiles|models|sessions` bekerja dan jalur `--values` memuat tanpa plugin (~20 ms, `clite.plugins.manager` tidak terimpor). Skrip zsh/fish belum dijalankan di shell aslinya (tidak terpasang) | Linux, Python 3.11.16 |
| 8 Oktober 2026 | F3-T1: penutupan verifikasi — dua galat `mypy` yang tersisa di berkas F3-T1 dibereskan (`cli/input.py` anotasi `self.session`, `cli/repl.py` `hasattr`→`getattr`), mypy kembali bersih pada 176 file; `tests/cli`+`tests/runtime` 110 lulus termasuk jalur `StdlibReader` tanpa `prompt_toolkit`; Ruff bersih. Baris papan F3-T1 menjadi ✅ | Linux, Python 3.11.16 |
| 8 Oktober 2026 | F3-T2: merah di salinan terpisah — 29 tes `tests/cli/test_markdown.py` gagal tanpa `cli/markdown.py`, dan 18 tes `ui-tui/test/render.test.ts` gagal tanpa penambahan Markdown di `render.ts`; keduanya hijau sesudah kode dipulihkan. Invariant "potongan ukuran acak = teks utuh" dijalankan pada tiap titik potong untuk delapan dokumen contoh. Suite Python penuh 1244 lulus/29 terlewati (satu tes `tests/server` gagal sebelum tugas ini, `websockets`), Ruff bersih, mypy 176 file bersih, `apps/shared` 22 lulus, `ui-tui` render 18 + e2e 11 lulus, `tsc --noEmit` bersih di `ui-tui` dan `apps/desktop`, `apps/shared` kecuali satu galat `subagent.update` yang sudah ada di `HEAD`, bundle TUI dibangun ulang. Clone rujukan `../hermes-ref` tidak tersedia | Linux, Python 3.11.16, Node 26.7.0 |

| 8 Oktober 2026 | F3-T4: 16 tes baru merah pada worktree bersih `d2d70c8` dengan berkas tes baru saja (`Unknown command: /branch`, `/queue`, `/background`, `/export`, `/context`, `/tasks`, `/hooks`, `/pin`, `/archive`, `/verbose`, `/skin`, `/logs`, `/copy`); hijau sesudah implementasi — 44 tes `tests/runtime/test_session_and_slash.py` lulus, `tests/runtime`+`tests/cli`+`tests/state` 164 lulus. `/branch` menyalin pesan aktif tanpa `provider_data` dan mencatat `parent_session_id` (dijaga `test_branch_copies_the_conversation_without_provider_data_and_links_the_parent`). Tabel bawaan 32 → 44 perintah. Suite Python penuh 1268 lulus/29 terlewati (satu tes `tests/server` gagal sebelum tugas ini, `websockets`), Ruff bersih, mypy 178 file bersih, `python scripts/gen_docs.py` memperbarui `docs/referensi/katalog.md`, `tests/test_docs.py` dan `tests/test_architecture.py` lulus. Clone rujukan `../hermes-ref` tidak tersedia; rujukan dibaca dari `/home/luwak/.hermes/hermes-agent` | Linux, Python 3.11.16 |
| 8 Oktober 2026 | F3-T9..F3-T15 & F3-T3: Seluruh paket TUI Ink (kerangka Ink, bilah status, dialog, pelengkapan, pemilih model/sesi, tema dari skin & resize, bundle mandiri single-file) tuntas; 23 tes `app.test.ts`, 18 tes `render.test.ts`, 11 tes `test_tui_bundle.py` lulus; bundle terkompilasi mandiri tanpa external runtime npm imports, ukuran <3MB (~1.4MB), `tsc` bersih | Linux, Python 3.11.16, Node 26.7.0 |
| 8 Oktober 2026 | F3-T5, F3-T6, F3-T8: Wizard setup interaktif + pengujian panggilan nyata; manajemen update, backup (izin 0600 untuk rahasia), restore, dan uninstall yang dijaga `detect_self_access`; perintah `/insights` dan `clite insights (--json)` menghitung token, biaya, model, tool, dan platform dengan atribusi subagent ke induk; 47 tes `tests/cli/test_cli.py`, 32 tes `tests/state/test_db.py`, dan 45 tes `tests/runtime/test_session_and_slash.py` lulus. Seluruh Fase 3 (CLI dan TUI) selesai 100% | Linux, Python 3.11.16 |
| 8 Oktober 2026 | F4-T1: Adapter Discord di atas WebSocket Gateway v10 dan REST API; identify, heartbeat, resume, mention stripping, penanganan thread, pemotongan pesan batas 2000 karakter, indikator typing; 3 tes `tests/gateway/test_discord.py` lulus terhadap server mock WebSocket & REST lokal; token bot terdaftar sebagai kredensial privat. Platform live Discord belum dijalankan (status 🟡 parsial) | Linux, Python 3.11.16 |
| 8 Oktober 2026 | F4-T2: Adapter Slack Socket Mode dan Web API; pengakuan (ack) envelope instan, deduplikasi event ganda via LRU ID, mention stripping, balasan masuk ke thread_ts; 2 tes `tests/gateway/test_slack.py` lulus terhadap server mock Socket Mode & Web API lokal; token aplikasi dan bot terdaftar sebagai kredensial privat. Ruang kerja live Slack belum dijalankan (status 🟡 parsial) | Linux, Python 3.11.16 |
| 8 Oktober 2026 | F4-T7: Kebijakan reset sesi gateway (`idle`, `daily`) dengan notifikasi satu kali dan retensi sesi lama untuk `/resume`; perintah `/sethome` menetapkan home channel; cron `deliver: <platform>` mengirim langsung ke home channel platform tersebut; 2 tes baru `tests/gateway/test_gateway.py` lulus dengan waktu yang disuntikkan | Linux, Python 3.11.16 |
| 8 Oktober 2026 | F4-T8: Tool `send_message` lintas platform; hanya ditawarkan saat gateway berjalan (`check_fn`), tujuan dibatasi ke chat asal, home channel, dan `gateway.send_targets`; 4 tes baru `tests/gateway/test_gateway.py` lulus; bukti merah: tanpa modul tool, 3 tes gagal (`ModuleNotFoundError`) | Linux, Python 3.11.16 |
| 8 Oktober 2026 | F4-T5: Jawaban streaming dan progres tool di chat; `gateway/stream.py` (`StreamSender`, `ProgressReporter`), `can_edit`/`edit` pada adapter (Telegram `editMessageText`, `local` untuk tes), batas laju 1.5 detik, pemecahan saat melewati batas karakter, dan fallback saat suntingan ditolak; 6 tes baru `tests/gateway/test_gateway.py` lulus; 5 tes lama disesuaikan dengan kontrak streaming (menunggu teks akhir, bukan indeks pesan); bukti merah: tanpa `stream.py` koleksi gagal (`ModuleNotFoundError`) | Linux, Python 3.11.16 |
| 8 Oktober 2026 | F4-T4: Lampiran masuk dan keluar; `gateway/media.py` (jenis dari magic bytes, batas ukuran ditolak sebelum ditulis, cleanup per sesi), gambar masuk sebagai bagian konten model, dokumen diberitahukan sebagai path, tool `send_file` dengan batas direktori + `read_denied_reason`, Telegram `fetch_attachment` (foto/dokumen/suara/video) dan `sendDocument`; 8 tes baru `tests/gateway/test_gateway.py` lulus (50 total di `tests/gateway`). Belum diuji terhadap Telegram sungguhan | Linux, Python 3.11.16 |
| 8 Oktober 2026 | F4-T6: layanan gateway menghasilkan unit systemd user dan LaunchAgent per profil, menolak proses kedua untuk home yang sama, dan SIGTERM menghentikan pesan baru sambil menunggu giliran aktif selesai lalu keluar 0; 3 tes `tests/gateway/test_service.py` lulus. Verifikasi manual systemd Linux belum dilakukan karena tidak memasang atau menjalankan layanan pada home pengguna. | Linux, Python 3.11.16 |
| 8 Oktober 2026 | F4-T9: skrip pra-jalan pengguna dari `cron/scripts` memasukkan keluaran ke prompt dan terlindung dari tool file/`cronjob`; riwayat persisten dan `clite cron history`/RPC `cron.history`; pengiriman gagal diantrekan lalu dicoba ulang dengan batas; tick menjalankan job paralel terbatas. `tests/cron/test_cron.py` 40 lulus, `tests/tools/test_file_tools.py` dan `tests/cli/test_cli.py` lulus; belum diverifikasi terhadap platform gateway sungguhan. | Linux, Python 3.11.16 |
| 8 Oktober 2026 | F2-T3: Estimasi harga dan biaya model; `providers/pricing.py` (`ModelPricing` dengan empat tarif: input, output, cache read, cache write), resolusi hierarkis (config `pricing.overrides`, profil provider, katalog OpenRouter ter-cache), pengisian `sessions.estimated_cost_usd` oleh `record_usage`, pelaporan biaya di `/usage`, `clite sessions list`, dan `turn.complete` JSON-RPC (null / "unknown" bila tidak diketahui); tarif Anthropic diambil dari halaman resmi 2026-10-08; 6 tes baru di `tests/providers/test_pricing.py`, `tests/runtime/test_session_and_slash.py`, `tests/rpc/test_rpc.py`, `tests/cli/test_cli.py` lulus. | Linux, Python 3.11.16 |

Setiap task yang memverifikasi sesuatu menambah baris di tabel ini dan memindahkan butirnya
dari "belum diverifikasi".