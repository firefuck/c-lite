# 05. Tools dan Toolsets

Tool Hermes adalah fungsi yang **mendaftarkan dirinya sendiri**, dikelompokkan ke
dalam toolset, dan dijalankan lewat satu registry dan satu jalur dispatch.

## Registry

`tools/registry.py` tidak bergantung pada modul lain dan diimpor oleh setiap file tool.
Isinya singleton `registry` bertipe `ToolRegistry`.

### Mendaftarkan tool

```python
registry.register(
    name="terminal",              # nama unik, dipakai di skema API
    toolset="terminal",           # toolset pemilik
    schema={...},                 # skema untuk model: description, parameters
    handler=handle_terminal,      # fungsi yang dijalankan
    check_fn=check_terminal,      # opsional: True bila tool tersedia
    requires_env=["SOME_VAR"],    # opsional: untuk tampilan UI
    is_async=False,               # handler berupa coroutine
    emoji="💻",                   # untuk spinner dan progres
)
```

Tiap pendaftaran membuat `ToolEntry`:

```python
@dataclass(eq=False, slots=True)
class ToolEntry:
    name: str; toolset: str; schema: dict; handler: Callable
    check_fn: Optional[Callable]; requires_env: list; is_async: bool
    description: str; emoji: str
    max_result_size_chars: int | float | None = None
    dynamic_schema_overrides: Optional[Callable] = None   # digabung ke skema tiap get_definitions()
```

Aturan pendaftaran:

- `schema` harus kamus dan `schema["parameters"]` harus objek JSON Schema. Skema cacat ditolak **saat pendaftaran**, karena kalau lolos ia merusak setiap permintaan ke penyedia dan errornya muncul jauh dari plugin yang salah.
- Pendaftaran yang akan menimpa tool dari **toolset lain** ditolak, kecuali `override=True`. Plugin yang menimpa tool bawaan juga butuh izin operator: `plugins.entries.<id>.allow_tool_override: true`.
- Pendaftaran ulang dalam toolset yang sama diizinkan (dipakai MCP saat menyambung ulang).
- `schema["description"]` adalah deskripsi yang dilihat model. Argumen `description=` hanya metadata registry.
- Registry menaikkan penghitung `_generation` di tiap mutasi. `get_tool_definitions` memakai angka itu untuk membatalkan memo.

**Semua handler mengembalikan string JSON.** Pembantu `tool_error(message, **extra)` dan
`tool_result(data)` menggantikan `json.dumps` berulang. Isi error dibatasi 2.048 karakter
supaya exception mentah tidak menggembungkan riwayat pada tiap retry.

### Discovery

`discover_builtin_tools()` memindai `tools/*.py` dan `tools/<paket>/tool.py`, mengurai
tiap file dengan **AST**, dan hanya mengimpor file yang memanggil `registry.register()`
di **badan modul** (atau di dalam `for` tingkat modul). Panggilan di dalam fungsi tidak
dihitung, sehingga modul pembantu tidak ikut diimpor.

- Hasil pindai AST disimpan di `~/.hermes/cache/tool_discovery_cache.json` dengan kunci `(mtime_ns, size)`, karena memindai sekitar 100 file memakan 145 ms.
- Kegagalan impor tool opsional dicatat sebagai peringatan dan tidak menghentikan tool lain.
- `model_tools.py` memanggil discovery saat diimpor, lalu memuat plugin. Discovery MCP **tidak** berjalan di sini karena bisa memblokir sampai 120 detik; tiap entry point menjalankannya sendiri saat mulai.

### Ketersediaan: `check_fn`

`check_fn` menjawab "apakah tool ini tersedia sekarang": kunci API ada, layanan
berjalan, biner terpasang. Saat `get_definitions()` merakit skema, tool yang `check_fn`-nya
`False` dilewati.

- Hasil di-cache sekitar 30 detik (`_CHECK_FN_TTL_SECONDS`), karena keadaan luar berubah dalam skala waktu manusia.
- Exception dianggap tidak tersedia.
- **Penahan kedipan**: kegagalan dalam 60 detik setelah keberhasilan terakhir dianggap sementara, dan tool tetap tersedia. Tanpa ini, satu probe yang lambat bisa melucuti seluruh toolset dari agent yang sedang dibangun.
- `check_fn` membaca kredensial lewat `agent.secret_scope.get_secret`, tidak pernah `os.getenv` polos, karena satu proses bisa melayani beberapa profil.
- `check_fn` menjawab keterjangkauan atau persetujuan pengguna, **tidak pernah** jenis permukaan. Hasilnya di-cache se-proses, jadi jawaban per sesi tidak boleh di sana.

### Dispatch

```python
def dispatch(self, name: str, args: dict, *, scope=None, **kwargs) -> str | dict
```

- Tool tak dikenal menghasilkan `{"error": "Unknown tool: ..."}`.
- `kwargs` konteks (`task_id`, `session_id`, `user_task`, `parent_agent`) **disaring berdasarkan tanda tangan handler**. Handler sempit `handle(args)` tidak rusak ketika dispatcher menambah field baru.
- Handler async dijembatani lewat `_run_async()`.
- Hasil dinormalkan: harus string, atau amplop multimodal `{"_multimodal": True, "content": [...]}`. Tipe lain menjadi error kontrak.
- Setiap exception menjadi `{"error": "Tool execution failed: <Tipe>: <pesan>"}`.

Jembatan async memakai loop yang **persisten**, tidak pernah `asyncio.run` per
panggilan, agar klien async yang di-cache tetap terikat pada loop yang hidup: satu loop
untuk thread utama, loop lokal per thread pekerja, dan thread sekali pakai bila sudah
ada loop yang berjalan (gateway).

## Toolsets

`toolsets.py` berisi satu kamus `TOOLSETS`. Tiap entri punya `description`, `tools`,
dan `includes` (toolset lain yang ikut dimasukkan).

```python
_HERMES_CORE_TOOLS = [
    "web_search", "web_extract",
    "terminal", "process_manage",
    "read_file", "write_file", "patch", "search_files",
    "vision_analyze", "image_generate",
    "skills_list", "skill_view", "skill_manage",
    "browser_navigate", ...,
    "text_to_speech", "todo_list", "memory", "session_search", "clarify",
    "execute_code", "delegate_task", "cronjob_manage", ...
]
```

Tiga macam toolset:

| Macam | Contoh | Arti |
|---|---|---|
| Dasar | `web`, `terminal`, `file`, `skills`, `todo`, `memory`, `delegation` | Satu kategori tool |
| Skenario | `debugging` (terminal ditambah `web` dan `file`), `safe` (tanpa terminal), `coding` | Gabungan untuk satu keperluan |
| Bundel platform | `hermes-cli`, `hermes-telegram`, `hermes-acp`, `hermes-api-server` | Tool inti ditambah ekstra platform |

`resolve_toolset(name)` menguraikan sebuah toolset beserta `includes`-nya menjadi daftar
nama tool terurut, dengan deteksi siklus. `"all"` dan `"*"` mencakup semuanya. Plugin
dan server MCP menambah toolset lewat registry, bukan dengan mengubah kamus.

**Pendaftaran saja tidak cukup.** Discovery mendaftarkan skema, tetapi tool baru
terekspos hanya bila sebuah toolset menyebut namanya.

### Dari toolset ke skema yang dikirim

`model_tools.get_tool_definitions(enabled_toolsets, disabled_toolsets, quiet_mode)`:

1. Bila `enabled_toolsets` diberikan, hanya tool dari toolset itu. Kalau tidak, semua toolset.
2. Toolset yang dicadangkan untuk peran profil tertentu dibuang.
3. `disabled_toolsets` **dikurangkan paling akhir**, sehingga tool dari toolset yang dimatikan tetap dibuang walau bundel menyalakannya lagi. Mematikan bundel hanya membuang ekstra non-intinya.
4. `registry.get_definitions()` menyaring dengan `check_fn` dan mengembalikan skema format OpenAI.
5. **Penulisan ulang skema dinamis**: deskripsi `execute_code`, `browser_navigate`, dan `delegate_task` disesuaikan agar hanya menyebut tool yang benar-benar lolos saringan.
6. Skema dibersihkan untuk backend yang ketat.
7. **Tool Search**: bila tool MCP dan plugin melebihi anggaran konteks, tool itu diganti jembatan `tool_search`, `tool_describe`, `tool_call`. Tool inti tidak pernah ditunda.

Hasil di-memo dengan batas 8 entri, dan pemanggil selalu menerima **salinan** supaya
mutasi di hilir tidak meracuni cache.

Aturan penulisan skema: **deskripsi tidak boleh menyebut tool dari toolset lain**. Tool
itu mungkin tidak tersedia, dan model akan mengarang panggilan ke sana. Rujukan silang
ditambahkan secara dinamis di langkah 5.

Per platform, toolset diatur lewat `hermes tools` (UI curses) atau
`tools.<platform>.enabled/disabled` di konfigurasi.

## Jalur dispatch lengkap

```text
tool_call dari model
   ▼
agent/tool_executor.py                    cegat tool tingkat agent (todo, memory, ...)
   ▼
model_tools.handle_function_call(name, args, task_id, ...)
   ├─ coerce_tool_args                    rapikan tipe argumen
   ├─ alias nama lama                     transkrip lama tetap jalan
   ├─ jembatan Tool Search                tool_call dibuka menjadi nama tool aslinya
   ├─ middleware tool_request
   ├─ hook pre_tool_call                  blokir, minta persetujuan, atau ubah argumen
   ├─ registry.dispatch(name, args, **kwargs)
   ├─ hook post_tool_call                 pengamat: durasi, status
   └─ hook transform_tool_result          plugin boleh mengganti hasil
   ▼
string JSON kembali ke loop
```

Error dibungkus di dua tingkat: `registry.dispatch()` menangkap exception handler, dan
`handle_function_call()` membungkus seluruh jalur. Model selalu menerima JSON yang
terbentuk baik. Teks error dibersihkan dari token pembingkai (tag peran, pagar kode)
sebelum dilihat model.

## Persetujuan perintah berbahaya

`tools/approval.py` dan `tools/approval_detection.py`.

1. **Deteksi**: `DANGEROUS_PATTERNS` adalah daftar `(regex, deskripsi)` untuk operasi merusak: hapus rekursif, format sistem file, SQL merusak, menimpa konfigurasi sistem, mematikan layanan, `curl | sh`, fork bomb, dan padanan Windows-nya.
2. **Mode** (`approvals.mode`): `manual` selalu bertanya; `smart` (bawaan) memakai LLM pembantu untuk menyetujui otomatis perintah berisiko rendah yang kebetulan cocok pola; `off` tidak bertanya.
3. **Prompt**: di CLI, prompt interaktif. Di gateway, permintaan dikirim ke platform pesan dan dijawab `/approve` atau `/deny`. Di TUI dan Desktop, server request `approval`.
4. **Pilihan**: sekali, untuk sesi ini, selalu, atau tolak.
5. **Keadaan sesi**: persetujuan dilacak per sesi dan per pola.
6. **Daftar izin permanen**: pilihan "selalu" ditulis ke `command_allowlist` di `config.yaml`.
7. **Daftar tolak** (`approvals.deny`): glob yang memblokir bahkan dalam mode YOLO.
8. **Tanpa pengawasan**: cron, satu-kueri (`-q`), dan platform tanpa kanal jawaban memakai `cron_mode`, `single_query_mode`, `unattended_mode`, semuanya bawaan `deny`.
9. Batas waktu bawaan 300 detik, karena persetujuan lewat pesan sering tidak langsung terlihat.

## Backend terminal

`tools/environments/` berisi backend di belakang tool `terminal`: `local`, `docker`,
`ssh`, `modal`, `daytona`, `singularity`, `vercel_sandbox`. `BaseEnvironment` adalah
ABC-nya; inti antarmukanya `execute(command, ...)` dan `cleanup()`.

Yang didukung: direktori kerja per tugas, proses latar (`background=true`) dengan
`process_manage` untuk memantau, mode PTY, dan pemberitahuan saat proses selesai.

Dua aturan penting:

- **Setiap proses anak lewat satu pembangun lingkungan** (`environments/local.py::build_subprocess_env`). Rahasia dari `.env` tidak diteruskan ke perintah yang dijalankan agent, kecuali yang didaftarkan di `terminal.env_passthrough`.
- **Mematikan proses latar memberi sinyal ke induk dulu**, menunggu, baru ke keturunannya.

Menambah backend berarti menambah file atau entri tabel penyedia, tidak pernah `elif`
pada nama backend.

## Tool inti dan parameternya

| Tool | Parameter utama |
|---|---|
| `terminal` | `command`*, `background`, `timeout`, `workdir`, `pty`, `notify` |
| `process_manage` | `action`* (`list`, `poll`, `log`, `wait`, `kill`, `write`, ...), `session_id` |
| `read_file` | `path`*, `offset` (baris, mulai 1), `limit` (bawaan dan maksimum 2000) |
| `write_file` | `path`*, `content`* |
| `patch` | `path`*, `old_string`*, `new_string`*, `replace_all` |
| `search_files` | `pattern`*, `target` (`content` atau `files`), `path`, `file_glob`, `limit`, `offset`, `output_mode`, `context` |
| `todo_list` | `todos` (larik), `merge` |
| `memory` | `target`* (`memory` atau `user`), `operations` (larik `add`, `replace`, `remove`) |
| `skills_list` | `category` |
| `skill_view` | `name`*, `file_path` |
| `skill_manage` | `operations`* (larik `create`, `patch`, `write_file`, `remove_file`, `delete`) |
| `session_search` | `query`, `limit`, `session_id`, `around_message_id`, `window` |
| `clarify` | `questions`* (larik berisi `question`, `choices`, `multi_select`) |
| `delegate_task` | `goal`, `context`, `toolsets`, atau `tasks` (larik) |
| `web_search` | `query`*, `limit` |
| `web_extract` | `urls`*, `char_limit` |

Tanda `*` berarti wajib. `patch` memakai pencocokan kabur dengan 9 strategi dan
mengembalikan diff. `read_file` membatasi hasil sekitar 100 ribu karakter dengan
`next_offset` untuk lanjutan.

Aturan penting: **tidak ada `offset` atau `limit` pada tool yang memuat isi instruksi**
(skill, prompt, playbook). Model membaca halaman pertama lalu melewatkan sisanya.

## MCP

Klien MCP ada di `tools/mcp_tool.py` beserta saudaranya (`config`, `discovery`,
`transport`, `registration`). Konfigurasinya:

```yaml
mcp_servers:
  time:
    command: uvx
    args: ["mcp-server-time"]
  notion:
    url: https://mcp.notion.com/mcp
  github:
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "..."
```

Tool dari server MCP didaftarkan ke toolset `mcp-<nama server>` dengan alias nama server
itu. Karena tidak ada jejak permanen di skema inti, MCP adalah anak tangga kelima pada
tangga jejak.

## Menambah tool

Untuk tool lokal atau khusus pengguna, **jangan ubah inti**. Buat plugin di
`~/.hermes/plugins/<nama>/` dan panggil `ctx.register_tool(...)`. Toolset plugin
ditemukan otomatis.

Untuk tool inti, dua file:

1. `tools/<nama_tool>.py` dengan `registry.register(...)` di tingkat modul.
2. `toolsets.py`: tambahkan nama ke `_HERMES_CORE_TOOLS` atau ke toolset baru.

## Yang perlu ditiru persis

1. Registry tanpa ketergantungan, pendaftaran saat impor, discovery lewat AST.
2. Semua handler mengembalikan string JSON; error selalu terbungkus.
3. `check_fn` dengan cache berbatas waktu dan penahan kedipan.
4. `kwargs` konteks disaring berdasarkan tanda tangan handler.
5. Toolset sebagai data, dengan pengurangan `disabled` di akhir.
6. Deskripsi skema tidak menyebut tool dari toolset lain.
7. Gerbang persetujuan dengan pola, keadaan per sesi, dan daftar izin permanen.
8. Rahasia tidak diteruskan ke proses anak.

## Rujukan di Hermes

`tools/registry.py`, `toolsets.py`, `model_tools.py`, `tools/approval.py`,
`tools/approval_detection.py`, `tools/environments/`, `tools/terminal_tool.py`,
`tools/file_tools.py`, `tools/process_registry.py`, `tools/delegate_tool.py`,
`tools/mcp_tool*.py`, `tools/tool_search.py`, `tools/AGENTS.md`,
`website/docs/developer-guide/tools-runtime.md`,
`website/docs/developer-guide/adding-tools.md`.
