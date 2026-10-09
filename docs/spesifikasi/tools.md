# Spesifikasi: tools

| | |
|---|---|
| Kode | `src/clite/tools/` |
| Tes | `tests/tools/` |
| Lapisan | 3. Boleh mengimpor `core`, `state`, `providers`, `plugins.hooks`, `skills` |
| Bedah Hermes | [05-tools-dan-toolsets](../hermes/05-tools-dan-toolsets.md) |

## Tanggung jawab

Semua yang bisa dilakukan model terhadap dunia luar: registry tool, toolset, pintu masuk
dispatch, gerbang persetujuan perintah, lingkungan eksekusi, tool bawaan, dan klien MCP.

## Bagian-bagian

| Bagian | File | Isi |
|---|---|---|
| Registry | `registry.py` | `ToolRegistry`, `ToolEntry`, `tool_result`, `tool_error`, penemuan tool bawaan |
| Toolset | `toolsets.py` | Kelompok tool bernama yang bisa saling menyertakan |
| Dispatch | `dispatch.py` | `get_tool_definitions` dan `handle_function_call` |
| Konteks | `context.py` | `ToolContext`: apa yang boleh diketahui handler tentang panggilannya |
| Persetujuan | `approval.py` | Pola berbahaya, pola terlarang mutlak, mode `manual` / `smart` / `off` |
| Penjaga file | `file_safety.py` | Path yang tidak boleh ditulis atau dibaca tool file; `PROTECTED_PATHS` adalah daftar file terlindung di tiap home agent, dipakai juga oleh gerbang persetujuan |
| Lingkungan | `environments/` | `BaseEnvironment` + operasi file, backend `local`, `docker`, `ssh` |
| Tool bawaan | `builtin/` | 23 tool (lihat [katalog](../referensi/katalog.md)) |
| MCP | `mcp/client.py`, `mcp/http.py` | Klien MCP tanpa SDK: transport stdio dan Streamable HTTP, tools, resources, prompts |

## Kontrak

**Registry**
- Modul tool mendaftarkan dirinya saat diimpor dengan `registry.register(...)`.
  `discover_builtin_tools()` mengimpor setiap modul di `builtin/` yang berisi panggilan itu
  (dideteksi lewat AST, jadi modul pembantu tidak ikut diimpor).
- Handler menerima argumen model sebagai satu `dict` dan mengembalikan **string JSON**. Galat
  dikembalikan sebagai `{"error": ...}`, tidak dilempar. Exception di handler ditangkap dan
  menjadi hasil galat.
- Argumen kata kunci tambahan (`ctx`) hanya diberikan ke handler yang menamainya. Menambah
  argumen baru tidak mematahkan tool lama.
- `check_fn` menentukan apakah sebuah tool ditawarkan. Hasilnya di-cache 30 detik, dan check
  yang baru saja lolos bertahan 60 detik setelah satu kegagalan, supaya daftar tool (bagian
  dari awalan prompt) tidak berubah-ubah.
- Origin lain tidak bisa mengganti tool yang sudah terdaftar tanpa `override=True`.
- Handler `async` dijalankan di satu event loop latar (`get_background_loop`).

**Toolset**
- Toolset komposit (`clite-cli`, `clite-gateway`, `clite-cron`, `clite-subagent`) menyertakan
  toolset lain. Siklus `includes` berhenti dengan sendirinya.
- Toolset platform (`clite-*`) otomatis memuat semua toolset `mcp-*`.
- `disabled_toolsets` selalu menang, juga atas tool yang ditarik toolset komposit.
- Tool yang didaftarkan ke nama toolset baru tetap teresolusi tanpa mendeklarasikan toolset.

**Dispatch**
- Definisi tool diurutkan menurut nama dan berbentuk OpenAI. Yang dikembalikan selalu salinan.
- Daftar izin pada konteks membedakan `None` (pemanggilan internal tanpa batas sesi) dari
  himpunan kosong (sesi melarang semua tool). Tool call yang tidak ditawarkan ditolak juga
  ketika sesi tidak mempunyai satu tool pun.
- Urutan satu panggilan: cek tool dikenal dan diizinkan sesi, paksa tipe argumen sesuai skema,
  hook `pre_tool_call` (bisa memblokir atau mengubah argumen), handler,
  `transform_tool_result`, batas ukuran hasil (kepala dan ekor dipertahankan),
  `post_tool_call`.
- Hook `pre_tool_call` yang melempar atau kehabisan waktu berarti **blokir**.

**Persetujuan perintah** (urutan pemeriksaan, yang paling mutlak dulu)
1. Perintah yang melampaui batas penguraian ditolak di semua mode: lebih panjang dari
   `MAX_COMMAND_CHARS` (20.000 karakter), atau lebih bersarang dari `MAX_COMMAND_DEPTH` (12
   tingkat `$(`/subshell). Pesannya menyebut sebabnya (panjang atau kedalaman). Gerbang yang
   tidak sanggup membaca perintah gagal ke "tidak".
2. Yang terlarang mutlak ditolak di semua mode: pola di `HARDLINE_PATTERNS` (`rm` rekursif atas
   root/home/direktori sistem, `mkfs`, `dd` ke disk, tulis ke perangkat blok, fork bomb,
   `kill -1`/`kill -HUP`, `shutdown`/`reboot`/`halt`/`poweroff`/`init 0`/`init 6`), dan `rm`
   rekursif yang targetnya root, direktori home (atau direktori di atasnya), atau direktori
   sistem (`SYSTEM_DIRECTORIES`). Target dibaca seperti shell menyelesaikannya, dari direktori
   kerja bila diketahui.
3. Glob `approvals.deny` ditolak di semua mode, termasuk `--yolo`.
4. Mode `off` meloloskan sisanya.
5. Perintah tanpa pola berbahaya langsung jalan.
6. Pola yang sudah disetujui untuk sesi ini atau ada di `command_allowlist` langsung jalan.
7. Mode `smart`: model bantu menilai. `APPROVE` jalan, `DENY` ditolak, selain itu (termasuk
   galat dan jawaban tak terduga) lanjut ke langkah 8. Putusannya tidak diingat.
8. Tanya pengguna: `once`, `session`, `always`, `deny`. Tanpa pengguna (cron, `-q`),
   kebijakan non-interaktif yang memutuskan; defaultnya tolak.
- Perintah dinormalkan dulu (escape ANSI, byte NUL, huruf lebar penuh), lalu setiap pendeteksi
  membacanya dua kali: seperti tertulis, dan seperti shell membacanya (`shell_plain`: tanpa
  tanda kutip, garis miring terbalik, `${NAMA}`, `$IFS`, dan garis miring berulang).
- **Posisi perintah sadar tanda kutip.** Pendeteksi pola hanya menilai perintahnya, bukan teks
  yang menyebutnya. Kecocokan yang seluruhnya berada di dalam satu bagian berkutip hanyalah
  data: `git commit -m "buang rm -rf /"` dan `echo "rm -rf /"` tidak ditolak, sedangkan
  `rm -rf "/"` tetap hapus rekursif. Sebaliknya, bagian berkutip yang memuat **kode** dibaca
  ulang sebagai perintah: muatan `sh -c`/`bash -c`/`zsh -c`/`eval`, argumen `python -c`,
  `python3 -c`, `node -e`, `perl -e`, `ruby -e`, opsi `-c`/`-e`/`--command`/`--eval` sejenis
  (`psql -c`, `redis-cli -e`), dan teks yang diberikan ke `os.system`/`subprocess.*`. Jadi
  `bash -c "rm -rf /"` dan `python -c "import shutil; shutil.rmtree(chr(47))"` tetap ditolak.
- **Nama yang dirakit dari variabel di baris yang sama** diselesaikan lebih dulu: `c=clite; $c
  config set ...` dinilai sebagai `clite config set ...` (perintah pengelolaan agent sendiri,
  tidak pernah diingat), dan `d=/; rm -rf $d` sebagai `rm -rf /` (terlarang mutlak). Variabel
  yang nilainya tidak ada di baris itu tetap tidak terbaca.
- Teks kode `execute_code` masuk ke gerbang ini juga: panggilan merusak yang ditulis dalam
  Python (`shutil.rmtree(...)`, `os.remove`/`os.unlink`/`os.rmdir`, `File.delete`/`unlink`,
  `subprocess.run(["rm", …])`, `unlinkSync`/`rmSync`) ditandai oleh pola `script_delete`, sama
  seperti bentuk baris perintahnya.
- Callback persetujuan yang rusak atau jawaban tak dikenal berarti tolak.
- **Perintah yang menjangkau pengaturan atau kredensial agent sendiri**
  (`detect_self_access`) diperlakukan lebih ketat. Termasuk di dalamnya: path ke dalam salah
  satu home agent yang menunjuk, atau bisa mengembang menjadi, file di `PROTECTED_PATHS` atau
  direktori pemuatnya; perintah apa pun yang dijalankan dari dalam direktori semacam itu; dan
  CLI pengelolaan agent sendiri (`clite config`, `clite hooks`, `clite plugins`, dan
  seterusnya) dengan cara pemanggilan apa pun yang terbaca dari teksnya. Untuk perintah
  semacam ini langkah 5 dan 6 tidak berlaku: tidak pernah diingat, tidak pernah masuk
  `command_allowlist`, dan tidak pernah diloloskan peninjau `smart`. Pengguna ditanya setiap
  kali.

**Terminal dan lingkungan**
- Satu lingkungan per `task_id`, dibuat saat pertama dipakai dan dipilih lewat
  `terminal.backend`. Backend terdaftar dengan `register_environment_backend`: `local`
  (bawaan), `docker`, `ssh`. `cd` bertahan antar-panggilan, dan tool file menyelesaikan path
  relatif terhadap direktori kerja yang sama.
- `BaseEnvironment` punya empat operasi file — `read_file`, `write_file`, `list_dir`, `stat`
  — dan `spawn_background`. `read_file`, `write_file`, `patch`, dan `search_files`
  mengarahkan setiap pembacaan dan penulisan lewat sana, bukan lewat `pathlib` langsung, jadi
  perilakunya sama di semua backend. `LocalEnvironment` mengimplementasikannya dengan
  `pathlib` (perilaku lama, tak berubah). Penjaga file (`read_denied_reason`,
  `write_denied_reason`) dan redaksi berjalan sebelum operasi apa pun.
- Backend `docker`: satu container per `task_id` (`docker run -d`), direktori kerja
  di-bind-mount pada path yang sama, container dihapus saat sesi ditutup
  (`terminal.docker.keep_container` membiarkannya hidup). Container mulai tanpa variabel
  lingkungan host: tidak ada kunci provider atau isi `.env` yang diteruskan; yang masuk hanya
  apa yang disebut `terminal.docker.mounts`. Kunci config lain: `image` (wajib), `network`
  (bawaan `none`), `user`, `memory`.
- Backend `ssh`: satu koneksi per `task_id` (`ControlMaster`) ke `terminal.ssh.host`, dengan
  `key`, `port`, `known_hosts`, `cwd` dari config. Operasi file ditransportasi lewat `ssh`
  (`cat`, `tee`-style atomic write, `ls`, `stat`); tidak ada kredensial dari `.env` yang
  diteruskan.
- Kredensial yang dikenal dibuang dari lingkungan perintah kecuali terdaftar di
  `terminal.env_passthrough`: setiap nama dari `.env`, dan setiap kunci provider atau
  platform (`core.env.secret_names`) juga bila ia di-`export` di shell pengguna. Keluaran
  diredaksi (`core.redact`). `env_passthrough` berlaku untuk backend `local` saja: Docker dan
  SSH tidak mewarisi apa pun.
- Gerbang persetujuan (`check_command`) tetap dipanggil di semua backend sebelum perintah
  dijalankan, di `terminal_tool`, tidak di dalam backend.
- Batas waktu mematikan seluruh grup proses. Interupsi menghentikan perintah yang berjalan.
- Pembaca pipe memakai potongan berukuran tetap dan tetap menguras keluaran setelah batas
  penyimpanan tercapai. Foreground menyimpan paling banyak batas karakter yang diminta;
  proses latar menyimpan 200.000 karakter terakhir. Tanda pemotongan ditambahkan di luar
  batas isi itu. Dekode UTF-8 dan normalisasi newline tetap utuh antar-potongan.
- Semua aksi `process`, termasuk daftar, dibatasi oleh profil aktif dan `task_id` pemilik
  (atau `session_id` bila task kosong). Mengetahui id proses sesi lain tidak memberi izin
  membaca, menulis stdin, menunggu, atau mematikannya.
- Thread pembaca membawa konteks profil dan rahasia pemanggil. `process(wait)` menunggu
  proses keluar serta pipe selesai dikuras, dengan batas waktu dan interupsi.

**Tool file**
- `read_file` mengembalikan baris bernomor, berhalaman, dan menolak biner, direktori, serta
  yang bukan file biasa (pipa, perangkat), supaya tidak pernah menggantung.
- Yang dibaca model dikirim ke provider dan disimpan di database sesi. Karena itu file
  kredensial tidak bisa dibaca (`.env` dan `auth.json` milik agent, `~/.ssh`, `~/.aws`, dan
  sejenisnya), pencarian isi melewatinya, dan kredensial di file lain diredaksi dari hasil
  `read_file`, `search_files`, dan diff `patch`. File di disk tidak diubah.
- `patch` punya dua mode. Mode `replace` (default) mengganti tepat satu kecocokan
  (kecuali `replace_all`), mengembalikan diff, dan bila kecocokan persis tidak ada,
  mencoba rantai pencocokan toleran: spasi di ujung baris, indentasi, kutipan tipografis,
  baris kosong. Setiap tingkat hanya diterima bila hasilnya unik; hasil menyebut tingkat
  mana yang dipakai (`match_level`). Mode `patch` menerima teks berformat V4A
  (`*** Update File`, `*** Add File`, `*** Delete File`) yang menyentuh beberapa file,
  diterapkan seluruhnya atau tidak sama sekali (atomic: kegagalan di file ketiga mengembalikan
  file pertama dan kedua ke keadaan semula).
- `write_file` dan `patch` (kedua mode) menolak `.env`, `config.yaml`, `auth.json`,
  `shell-hooks-allowlist.json` milik agent, direktori kredensial (`~/.ssh`, `~/.aws`, ...) dan
  direktori sistem.

**`web_fetch`**
- Hanya `http` dan `https`. Alamat loopback, privat, dan link-local ditolak kecuali
  `web.allow_private_urls: true`.
- Setiap lompatan redirect tunduk pada dua aturan yang sama. Halaman publik tidak bisa
  memantulkan agent ke alamat internal atau ke skema lain.

**`web_search`**
- The tool is offered only when a web-search provider is configured. Its ``check_fn`` returns
  ``False`` when no provider is available (no registry entry, or a keyed provider whose API
  key is not in ``.env``), so the model is never told it can search the web when there is no
  backend to answer.
- Each result has a title, URL, and snippet. The snippet is untrusted text from the web: it
  arrives as a tool result, never in the system prompt. The tool does not sanitise or strip
  HTML in snippets; the model sees exactly what the search backend returned.
- Providers are pluggable (``WebSearchProvider`` in ``tools/web_search.py``); a plugin
  registers one with ``ctx.register_web_search_provider(name, factory)``. Two bundled
  ``kind: backend`` plugins ship: ``web-search-ddg`` (DuckDuckGo, no API key) and
  ``web-search-tavily`` (Tavily, needs ``TAVILY_API_KEY``).
- A keyed provider registers its API key with ``register_secret`` so it is stripped from
  commands the agent runs and redacted from what the model reads.

**`vision_analyze` dan `image_generate`**

- `vision_analyze` mengirim gambar ke rute `auxiliary.vision`, untuk model utama yang tidak
  menerima gambar. Model utama tidak pernah menerima bagian gambar; ia hanya menerima teks
  jawaban model bantu sebagai hasil tool. Rute itu memakai profil provider; modelnya harus
  menerima gambar (`ProviderProfile.supports_vision`). Bila rutenya buta, tool menolak dengan
  pesan yang menyebut cara mengarahkan `auxiliary.vision` ke model berpenglihatan, bukan
  mengirim gambar ke model yang akan menolaknya.
- `image_generate` membuat gambar lewat backend yang bisa dipasang (`ImageProvider` in
  ``tools/image_gen.py``); sebuah plugin mendaftarkannya dengan
  ``ctx.register_image_provider(name, factory)``. Tool hanya ditawarkan bila ada provider aktif
  (``check_fn``), jadi model tidak pernah diberi tahu ia bisa menggambar tanpa backend.
- Satu plugin bawaan berjenis ``backend``: ``image-gen-openai`` (OpenAI Images API, butuh
  ``OPENAI_API_KEY``). Kuncinya didaftarkan ``register_secret``. ``image.provider`` memilih
  backend saat lebih dari satu terpasang.
- Provider mengembalikan byte gambar dan media typenya. Tool menyimpannya di
  ``<cwd>/generated-images/`` dan mengembalikan path-nya (percakapan membawa teks, bukan
  gambar). Setiap path melewati ``write_denied_reason`` seperti tulisan file lain.

**`text_to_speech`**

- Mengubah teks menjadi berkas audio lewat backend yang bisa dipasang (`SpeechProvider` di
  `tools/speech.py`); sebuah plugin mendaftarkannya dengan
  `ctx.register_speech_provider(name, factory)`. Arah sebaliknya — pesan suara menjadi teks —
  memakai tabel kedua (`TranscriptionProvider`, `ctx.register_transcription_provider`).
- Tool hanya ditawarkan bila ada provider yang benar-benar bisa dipakai (`check_fn`), jadi model
  tidak pernah diberi tahu ia bisa bersuara di mesin yang tidak bisa. Provider yang butuh kunci
  tidak dihitung bila kuncinya tidak ada di `.env`.
- Tool berhenti di berkas; yang mengantarkannya ke pengguna adalah `send_file`. Jadi keluaran
  bersuara menempuh jalur yang sama, dan kena pemeriksaan yang sama, dengan berkas lain yang
  dibuat agent — dan permukaan tanpa chat pun tetap berakhir dengan berkas yang bisa diputar.
- Path keluaran (`<cwd>/spoken/<nama>.<format>`) melewati `write_denied_reason` lebih dulu.
  Teks yang melebihi `speech.max_chars` ditolak sebelum provider dipanggil, bukan dipotong.
- Satu plugin bawaan berjenis `backend`: `speech-openai` (OpenAI Audio API, butuh
  `OPENAI_API_KEY`). Kuncinya didaftarkan `register_secret`. `speech.speech.provider` dan
  `speech.transcription.provider` memilih backend saat lebih dari satu terpasang.

**`execute_code`**
- Menjalankan program Python pendek dan mengembalikan `stdout`, `stderr`, dan `exit_code`
  secara terpisah. Program dijalankan lewat lingkungan eksekusi sesi yang sama dengan
  `terminal` (`BaseEnvironment`), jadi di backend `docker` atau `ssh` ia berjalan di dalam
  container atau di host jauh, bukan di mesin pengguna. Di backend `local` ia mengikuti
  `approvals.mode` persis seperti `terminal`.
- Kode adalah perintah. Teksnya dikirim ke `check_command` yang sama sebelum dijalankan, jadi
  panggilan merusak yang ditulis dalam Python — `shutil.rmtree(...)`, `os.remove(...)`,
  `os.system("rm -rf …")`, `subprocess.run(["rm", …])` — ditandai sama seperti perintah yang
  dibungkusnya, dan pola terlarang mutlak ditolak di semua mode. Panggilan yang tidak menuju
  shell (`subprocess.run([...])` tanpa `shell=True`) juga terbaca, karena polanya membaca
  sintaks Python, bukan hanya bentuk baris perintah.
- Program menerima lingkungan yang sama bersihnya dengan perintah lain
  (`build_child_env`): setiap kredensial yang dikenal dibuang, jadi `os.environ` di dalam kode
  tidak memuat kunci provider maupun nama apa pun dari `.env`. Keluarannya diredaksi
  (`core.redact`) sebelum masuk transkrip.
- Program sampai ke interpreter lewat stdin (`python -`), sehingga teks model tidak masuk ke
  baris perintah sama sekali: tidak ada kutipan shell, tidak ada batas panjang baris perintah.
  Harganya: program tidak bisa membaca stdin.
- Runner kecil menandai setiap tulisan dengan stream asalnya dan membasuhnya saat itu juga,
  jadi keluaran mengalir, tidak dibuffer: program yang dimatikan karena batas waktu tetap
  memperlihatkan apa yang sempat tercetak. Tulisan proses anak yang langsung ke deskriptor
  berkas tidak bertanda dan dibaca sebagai stdout.
- Batas waktu mematikan program beserta proses anaknya (grup proses dimatikan lewat
  lingkungan, jadi ini berlaku di semua backend). Batas keluaran per stream mengikuti
  `tool_output.max_chars`, dengan catatan pemotongan yang menyebut batasnya. `code` dibatasi
  `MAX_CODE_CHARS` (100.000 karakter).
- Interpreter: `sys.executable` di backend `local`; `python3` di backend lain (container dan
  host jauh adalah mesin lain, di mana path host tidak berarti).

**MCP**
- Tiap server menjadi toolset `mcp-<server>` dengan tool `mcp_<server>_<tool>`. Dua transport:
  **stdio** (satu proses, satu pesan JSON-RPC per baris) dan **Streamable HTTP** (`url`,
  JSON-RPC dalam POST ke satu endpoint dengan header `Mcp-Session-Id`). Pemilihan transport
  dari spec: `command` memilih stdio, `url` memilih HTTP.
- Server yang mendeklarasikan kapabilitas `resources` juga mendapat tool
  `mcp_<server>_list_resources` dan `mcp_<server>_read_resource`. Prompt server menjadi slash
  command `mcp-<server>-<prompt>`; ia dikirim sebagai pesan pengguna, seperti skill, bukan
  dengan menyunting system prompt.
- Header autentikasi HTTP ditulis di `headers`, dengan `${NAMA}` merujuk `get_secret`. Nama
  yang diambil dari `.env` didaftarkan lewat `register_secret`, jadi nilainya diredaksi dari
  apa yang dibaca model. Variabel yang hilang adalah galat yang menyebut namanya, bukan header
  kosong yang berujung 401.
- **Daftar tool tetap selama sesi (A1).** `notifications/tools/list_changed` tidak menyentuh
  registry sesi yang berjalan: session menyimpan definisi tool yang dibangun saat ia dibuat.
  Perubahan diingat (`tools_changed`); sesi berikutnya membaca ulang daftarnya saat
  `connect_mcp_servers` dipanggil.
- Server yang rusak dilewati, bukan fatal. Server yang gagal start tidak dicoba ulang seketika:
  jeda membesar (eksponensial, `5s * 2^(n-1)`, batas 300 detik) sebelum percobaan berikutnya di
  sesi berikutnya. Server yang mati melapor, tidak menggantung.
- Lingkungan proses stdio tidak memuat rahasia dari `.env` kecuali disebut di `env`. Header
  HTTP yang berisi rahasia diredaksi dari transkrip.
- `clite mcp add | list | remove | test` mengelola `mcp_servers` lewat `atomic_config_update`,
  dan `/mcp` menampilkan status tiap server (transport, hidup/mati, jumlah tool/resources/prompts).

## Status fitur

| Fitur | Status | Catatan |
|---|---|---|
| Registry, toolset, dispatch, hook | ✅ | |
| Persetujuan `manual`, `smart`, `off` | ✅ | |
| Backend terminal `local` | ✅ | |
| Backend terminal Docker, SSH | 🟡 | Diimplementasikan dan diuji: Docker bertanda khusus (terlewati tanpa daemon), SSH lewat transport tiruan; keduanya belum dijalankan terhadap daemon/host sungguhan. F2-T7 |
| Backend terminal lainnya | ⬜ | Antarmukanya ada (`register_environment_backend`); cloud (Modal, Daytona) bisa menyusul sebagai plugin |
| `terminal`, `process` | ✅ | |
| `read_file`, `write_file`, `patch`, `search_files` | ✅ | Patch toleran (rantai pencocokan dengan cek unik per tingkat) dan patch multi-file V4A atomic |
| `web_fetch` | ✅ | |
| `web_search` | ✅ | Provider pluggable (``WebSearchProvider``); ``check_fn`` gates on provider availability; two bundled plugins (DDG keyless, Tavily keyed) |
| `todo`, `memory`, `clarify`, `session_search` | ✅ | |
| `skills_list`, `skill_view`, `skill_manage` | ✅ | |
| `delegate_task`, `cronjob` | ✅ | |
| MCP stdio (tools) | ✅ | Diuji juga terhadap server dari SDK MCP resmi |
| MCP HTTP, resources, prompts | ✅ | Streamable HTTP (header `${NAMA}` dari `.env`, didaftarkan `register_secret`), tool `mcp_<server>_list_resources`/`_read_resource`, prompt server sebagai slash command `mcp-<server>-<prompt>`, dan `clite mcp add\|list\|remove\|test` + `/mcp`. Perubahan daftar tool di tengah sesi menunggu sesi berikutnya (A1); server yang mati dicoba ulang dengan jeda membesar. Diuji terhadap server HTTP SDK resmi. F2-T10 |
| MCP sampling, OAuth | ⬜ | Di luar lingkup F2-T10 |
| Analisis gambar, pembuatan gambar | ✅ | `vision_analyze` (rute `auxiliary.vision`, model utama tanpa penglihatan tak pernah menerima gambar) dan `image_generate` (`ImageProvider` + registry, plugin bawaan `image-gen-openai`, `check_fn` tanpa provider). Dijaga `tests/tools/test_vision.py` dan `tests/tools/test_image_gen.py`. Uji terhadap API asli belum dijalankan |
| Eksekusi kode (`execute_code`) | ✅ | Program Python pendek lewat lingkungan eksekusi sesi; `stdout`/`stderr`/`exit_code` terpisah, batas waktu mematikan pohon proses, kredensial dibuang, keluaran diredaksi, dan teks kode lewat `check_command`. Dijaga `tests/tools/test_code.py`. F2-T9 |
| Checkpoint sebelum menulis file | ✅ | `write_file` dan `patch` menyimpan isi lama ke `<home>/checkpoints/<id sesi>/turn-<n>/` sebelum mengubah file; `/rollback [n]` dan `/checkpoints` ada di semua surface. Batasnya: perubahan lewat perintah `terminal` tidak terlihat (lihat "Celah yang diketahui"). Dijaga `tests/tools/test_checkpoints.py`. F2-T8 |
| Otomasi browser | ⬜ | Belum dijadwalkan |
| `send_message` lintas platform | ✅ | Hanya ditawarkan saat gateway berjalan (`check_fn`); tujuan dibatasi ke chat asal percakapan, home channel tiap platform, dan daftar `gateway.send_targets`. Dijaga `tests/gateway/test_gateway.py`: F4-T8 |
| Suara (`text_to_speech`) | 🟡 | Dua registry provider (`SpeechProvider`, `TranscriptionProvider`), plugin bawaan `speech-openai`, dan `check_fn` tanpa provider. Dijaga `tests/tools/test_speech.py` dan `tests/gateway/test_gateway.py`. Uji terhadap API asli belum dijalankan. F6-T7 |
| Windows | ✅ | cmd.exe dan Git Bash: cwd, exit code, stdin, timeout/interupsi pohon proses dan penjaga path lulus di Windows nyata. CI `37499972911`, F1-T5 |

## Yang sengaja berbeda dari Hermes

- **Kebijakan paralel dideklarasikan per tool** (`parallel="never" | "safe" | "path"`), bukan
  dalam daftar nama di executor.
- **Tool tingkat agent adalah tool biasa.** `todo`, `memory`, `delegate_task`, `clarify`
  menerima `ctx.agent`; loop tidak punya cabang khusus untuk nama tool.
- **`ToolContext` adalah satu objek.** Hermes meneruskan banyak kwargs lepas.
- **Klien MCP tanpa SDK.** Hermes memakai SDK `mcp`.
- **Pola berbahaya lebih sedikit.** Hermes punya deteksi yang jauh lebih luas
  (`tools/approval_detection.py`) dan pemindai eksternal opsional.

## Celah yang diketahui

- Gerbang persetujuan membaca teks satu perintah dan tidak menjalankan shell. Perintah yang
  menyembunyikan niatnya tidak tertangkap: skrip yang ditulis ke file lalu dijalankan
  terpisah, alias, nama yang dirakit dari variabel atau substitusi perintah, dan muatan
  interpreter (`python -c`). Gerbang ini sabuk pengaman terhadap kekeliruan model, bukan
  sandbox. Deteksi yang lebih dalam: F2-T15. Teks kode `execute_code` dibaca dengan pola yang
  sama, jadi ia mewarisi batas ini juga.
- Persetujuan yang diingat (`session`, `always`) berlaku untuk seluruh pola, bukan untuk
  perintah yang ditanyakan saja.
- Tool file tidak dibatasi ke direktori kerja. Yang dibatasi hanya daftar path terlarang.
  Backend `docker` dan `ssh` memberi batas nyata: berkas di luar mount tidak terlihat dari
  dalam container.
- Checkpoint file hanya mencatat tulisan lewat tool file (`write_file` dan `patch`). Perubahan
  yang dibuat lewat perintah `terminal` — misalnya `mv`, `sed -i`, atau skrip yang mengubah
  berkas — tidak terlihat oleh tool file, jadi tidak disimpan dan tidak bisa dikembalikan oleh
  `/rollback`. Batas ini sengaja: menyadap seluruh sistem file berada di luar lingkup, dan
  sandbox `docker`/`ssh` tetap cara yang benar untuk mengurung perubahan seperti itu.
- `web_fetch` memeriksa alamat dengan me-resolve nama host lebih dulu, lalu pustaka HTTP
  me-resolve lagi saat menyambung. Server DNS yang menjawab berbeda di antara keduanya (DNS
  rebinding) bisa lolos.
- `execute_code` memberi programnya kepada interpreter lewat stdin, jadi program itu tidak bisa
  membaca stdin. Ini pertukaran yang disengaja: teks model tidak pernah masuk ke baris
  perintah, jadi tidak ada yang perlu dikutip dan tidak ada batas panjang baris perintah.
- Proses anak dari `execute_code` yang menulis langsung ke deskriptor berkas tidak bertanda,
  jadi stderr-nya dilaporkan sebagai stdout. Program yang memakai `print()` biasa tidak
  terpengaruh.
