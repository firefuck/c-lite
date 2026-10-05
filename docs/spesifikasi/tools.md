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
| Lingkungan | `environments/` | `BaseEnvironment`, backend `local` |
| Tool bawaan | `builtin/` | 16 tool (lihat [katalog](../referensi/katalog.md)) |
| MCP | `mcp/client.py` | Klien MCP stdio tanpa SDK |

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
- Urutan satu panggilan: cek tool dikenal dan diizinkan sesi, paksa tipe argumen sesuai skema,
  hook `pre_tool_call` (bisa memblokir atau mengubah argumen), handler,
  `transform_tool_result`, batas ukuran hasil (kepala dan ekor dipertahankan),
  `post_tool_call`.
- Hook `pre_tool_call` yang melempar atau kehabisan waktu berarti **blokir**.

**Persetujuan perintah** (urutan pemeriksaan, yang paling mutlak dulu)
1. Yang terlarang mutlak ditolak di semua mode: pola di `HARDLINE_PATTERNS`, dan `rm`
   rekursif yang targetnya root, direktori home (atau direktori di atasnya), atau direktori
   sistem (`SYSTEM_DIRECTORIES`). Target dibaca seperti shell menyelesaikannya, dari direktori
   kerja bila diketahui.
2. Glob `approvals.deny` ditolak di semua mode, termasuk `--yolo`.
3. Mode `off` meloloskan sisanya.
4. Perintah tanpa pola berbahaya langsung jalan.
5. Pola yang sudah disetujui untuk sesi ini atau ada di `command_allowlist` langsung jalan.
6. Mode `smart`: model bantu menilai. `APPROVE` jalan, `DENY` ditolak, selain itu (termasuk
   galat dan jawaban tak terduga) lanjut ke langkah 7. Putusannya tidak diingat.
7. Tanya pengguna: `once`, `session`, `always`, `deny`. Tanpa pengguna (cron, `-q`),
   kebijakan non-interaktif yang memutuskan; defaultnya tolak.
- Perintah dinormalkan dulu (escape ANSI, byte NUL, huruf lebar penuh), lalu setiap pendeteksi
  membacanya dua kali: seperti tertulis, dan seperti shell membacanya (`shell_plain`: tanpa
  tanda kutip, garis miring terbalik, `${NAMA}`, `$IFS`, dan garis miring berulang).
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
- Satu lingkungan per `task_id`. `cd` bertahan antar-panggilan, dan tool file menyelesaikan
  path relatif terhadap direktori kerja yang sama.
- Kredensial yang dikenal dibuang dari lingkungan perintah kecuali terdaftar di
  `terminal.env_passthrough`: setiap nama dari `.env`, dan setiap kunci provider atau
  platform (`core.env.secret_names`) juga bila ia di-`export` di shell pengguna. Keluaran
  diredaksi (`core.redact`).
- Batas waktu mematikan seluruh grup proses. Interupsi menghentikan perintah yang berjalan.
- Keluaran panjang dipotong dengan kepala dan ekor dipertahankan.

**Tool file**
- `read_file` mengembalikan baris bernomor, berhalaman, dan menolak biner, direktori, serta
  yang bukan file biasa (pipa, perangkat), supaya tidak pernah menggantung.
- Yang dibaca model dikirim ke provider dan disimpan di database sesi. Karena itu file
  kredensial tidak bisa dibaca (`.env` dan `auth.json` milik agent, `~/.ssh`, `~/.aws`, dan
  sejenisnya), pencarian isi melewatinya, dan kredensial di file lain diredaksi dari hasil
  `read_file`, `search_files`, dan diff `patch`. File di disk tidak diubah.
- `patch` mengganti tepat satu kecocokan (kecuali `replace_all`), mengembalikan diff, dan
  mentoleransi indentasi yang salah bila kecocokannya unik.
- `write_file` dan `patch` menolak `.env`, `config.yaml`, `auth.json`,
  `shell-hooks-allowlist.json` milik agent, direktori kredensial (`~/.ssh`, `~/.aws`, ...) dan
  direktori sistem.

**`web_fetch`**
- Hanya `http` dan `https`. Alamat loopback, privat, dan link-local ditolak kecuali
  `web.allow_private_urls: true`.
- Setiap lompatan redirect tunduk pada dua aturan yang sama. Halaman publik tidak bisa
  memantulkan agent ke alamat internal atau ke skema lain.

**MCP**
- Tiap server menjadi toolset `mcp-<server>` dengan tool `mcp_<server>_<tool>`.
- Server yang rusak dilewati, bukan fatal. Server yang mati melapor, tidak menggantung.
- Lingkungan proses server tidak memuat rahasia dari `.env` kecuali disebut di `env`.

## Status fitur

| Fitur | Status | Catatan |
|---|---|---|
| Registry, toolset, dispatch, hook | ✅ | |
| Persetujuan `manual`, `smart`, `off` | ✅ | |
| Backend terminal `local` | ✅ | |
| Backend terminal Docker, SSH, lainnya | ⬜ | Antarmukanya ada (`register_environment_backend`): F2-T7 |
| `terminal`, `process` | ✅ | |
| `read_file`, `write_file`, `patch`, `search_files` | ✅ | Patch toleran dan patch multi-file: F2-T4 |
| `web_fetch` | ✅ | |
| `web_search` | ⬜ | F2-T5 |
| `todo`, `memory`, `clarify`, `session_search` | ✅ | |
| `skills_list`, `skill_view`, `skill_manage` | ✅ | |
| `delegate_task`, `cronjob` | ✅ | |
| MCP stdio (tools) | ✅ | Diuji juga terhadap server dari SDK MCP resmi |
| MCP HTTP, resources, prompts, sampling, OAuth | ⬜ | F2-T10 |
| Analisis gambar, pembuatan gambar | ⬜ | F2-T6 |
| Eksekusi kode (`execute_code`) | ⬜ | F2-T9 |
| Checkpoint sebelum menulis file | ⬜ | F2-T8 |
| Otomasi browser | ⬜ | Belum dijadwalkan |
| `send_message` lintas platform | ⬜ | F4-T8 |
| Windows | 🟡 | Kode jalurnya ada (`taskkill`, `cmd.exe`), belum pernah dijalankan: F1-T5 |

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
  sandbox. Deteksi yang lebih dalam: F2-T15.
- Persetujuan yang diingat (`session`, `always`) berlaku untuk seluruh pola, bukan untuk
  perintah yang ditanyakan saja.
- Tool file tidak dibatasi ke direktori kerja. Yang dibatasi hanya daftar path terlarang.
- `web_fetch` memeriksa alamat dengan me-resolve nama host lebih dulu, lalu pustaka HTTP
  me-resolve lagi saat menyambung. Server DNS yang menjawab berbeda di antara keduanya (DNS
  rebinding) bisa lolos.
