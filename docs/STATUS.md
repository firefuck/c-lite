# Status

Diperbarui 7 Oktober 2026. Halaman ini memisahkan tiga hal yang mudah tertukar: apa yang
**dijaga tes**, apa yang **ditulis tetapi belum pernah bertemu hal yang sebenarnya**, dan apa
yang **belum ada**.

## Dijaga tes

Pemeriksaan terbaru F1-T7 dijalankan runner di Linux, Python 3.11.16, Node 26.7.0.

| Pemeriksaan | Hasil |
|---|---|
| `ruff check src tests scripts` | Bersih |
| `mypy` (173 file sumber) | Bersih |
| Tes Python (`pytest tests`) | 1092 lulus, 29 terlewati (jaringan, Windows, Docker, paket opsional), 1 gagal yang sudah ada sebelum F2-T10 (`tests/server`, `websockets`) |
| Tes TypeScript `apps/shared` | 21 lulus; `tsc --noEmit` bersih |
| Tes TypeScript `ui-tui` | 18 lulus; `tsc --noEmit` bersih |
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

Setiap task yang memverifikasi sesuatu menambah baris di tabel ini dan memindahkan butirnya
dari "belum diverifikasi".