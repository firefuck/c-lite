# 08. CLI, Slash Command, Konfigurasi, dan Profil

## Entry point

`pyproject.toml` mendaftarkan tiga perintah:

```toml
[project.scripts]
hermes = "hermes_cli.main:main"
hermes-agent = "agent.legacy_cli:main"
hermes-acp = "acp_adapter.entry:main"
```

`hermes_cli/main.py` adalah pintu masuk. Urutannya penting:

1. **Penimpaan profil dulu.** `_apply_profile_override()` membaca `-p <nama>` dan menyetel `HERMES_HOME` **sebelum modul lain diimpor**, karena banyak modul membaca home saat diimpor.
2. Muat `.env` dari home.
3. Bangun parser argparse. Tiap subcommand punya file sendiri di `hermes_cli/subcommands/`, dan plugin menambah subcommand lewat `ctx.register_cli_command` tanpa mengubah `main.py`.
4. Jalankan handler. Tanpa subcommand, yang dijalankan adalah obrolan interaktif.

## Subcommand

Ada sekitar 60 subcommand tingkat atas. Dikelompokkan menurut guna:

| Kelompok | Subcommand |
|---|---|
| Obrolan | *(tanpa subcommand)*, `chat`, `resume` |
| Model dan auth | `model`, `auth`, `login`, `logout`, `fallback`, `usage` |
| Konfigurasi | `setup`, `config`, `tools`, `skin`, `profile`, `secrets`, `vault` |
| Skill dan plugin | `skills`, `curator`, `bundles`, `plugins`, `mcp`, `hooks` |
| Permukaan | `gateway`, `dashboard`, `serve`, `gui`, `acp`, `webhook`, `pairing`, `slack`, `whatsapp` |
| Otomasi | `cron`, `approvals`, `checkpoints`, `worktree` |
| Sesi dan data | `sessions`, `memory`, `insights`, `journey`, `backup`, `import`, `dump` |
| Pemeliharaan | `doctor`, `status`, `logs`, `debug`, `update`, `uninstall`, `completion`, `version` |

### Flag obrolan

| Flag | Arti |
|---|---|
| `-q`, `--query` | Satu pertanyaan lalu keluar |
| `--query-file` | Pertanyaan dari file |
| `-z`, `--oneshot` | Satu giliran tanpa hiasan, untuk skrip |
| `-m`, `--model`, `--provider`, `--reasoning` | Rute model untuk sesi ini |
| `-t`, `--toolsets` | Toolset yang dinyalakan |
| `-s`, `--skills` | Skill yang dimuat di awal |
| `-r`, `--resume <id>`, `-c`, `--continue` | Lanjutkan sesi tertentu atau yang terakhir |
| `-w`, `--worktree` | Bekerja di git worktree terisolasi |
| `--yolo` | Lewati semua persetujuan perintah berbahaya |
| `--max-turns`, `--run-budget` | Batas iterasi dan batas waktu |
| `--tui`, `--cli` | Paksa TUI Ink atau CLI klasik |
| `-p <profil>` | Profil yang dipakai |
| `--ignore-user-config`, `--ignore-rules`, `--safe-mode` | Jalankan tanpa konfigurasi atau aturan pengguna |
| `-v`, `-Q`, `--format` | Kebertelean dan format keluaran |

Aturan kecil yang menyelamatkan: `add_parser("list", aliases=["ls"])` menyetel `dest` ke
kata yang diketik pengguna (`"ls"`), jadi dispatch harus menerima keduanya.

## CLI klasik

`cli.py` berisi `HermesCLI`: loop REPL, konfigurasi, dan dispatch slash. Perilakunya
dipecah ke mixin di `hermes_cli/cli_*_mixin.py` (perintah, stream, bilah status, widget
TUI, fase inisialisasi, fase jalan). Pembantu tingkat modul ada di saudara topikal:
`cli_config_load.py`, `cli_render.py`, `cli_terminal_input.py`, `cli_shutdown.py`,
`cli_single_query.py`.

Pustaka:

- **Rich** menggambar banner dan panel.
- **prompt_toolkit** menangani input dan pelengkapan otomatis.
- **`KawaiiSpinner`** (`agent/display.py`) menganimasikan panggilan API dan mencetak umpan aktivitas tool.
- Semua pemilih menu interaktif memakai **curses** (`hermes_cli/curses_ui.py`).

Jebakan: jangan pernah mengeluarkan `\033[K` (hapus sampai akhir baris) di kode spinner.
Di bawah `patch_stdout` milik prompt_toolkit ia bocor sebagai teks `?[K`. Pakai padding
spasi.

CLI pembungkus memperluas lewat hook terlindung di `cli_tui_mixin.py`, bukan dengan
menimpa `run()`.

## Registry slash command

`hermes_cli/commands.py` memegang `COMMAND_REGISTRY`, daftar `CommandDef`. Ini
**satu-satunya sumber**; semua konsumen menurunkannya dari sini.

```python
@dataclass(frozen=True)
class CommandDef:
    name: str                          # nama kanonik tanpa garis miring
    description: str
    category: str                      # "Session", "Configuration", "Tools & Skills", "Info", "Exit"
    aliases: tuple[str, ...] = ()
    args_hint: str = ""                # "<prompt>", "[name]"
    subcommands: tuple[str, ...] = ()  # untuk pelengkapan tab
    cli_only: bool = False
    gateway_only: bool = False
    gateway_config_gate: str | None = None   # dotpath konfigurasi yang membuka perintah di gateway
    busy_policy: str = "reject"        # "dispatch" | "reject" | "interrupt_then_dispatch"
    busy_handler: str | None = None
    execute: str | None = None         # kunci eksekutor bersama
    argument_mode: str | None = None   # composer desktop: options | text | mixed
    desktop: str | None = None         # ketersediaan di desktop
    desktop_subcommands: tuple[str, ...] | None = None
```

Yang diturunkan dari registry:

| Konsumen | Turunan |
|---|---|
| CLI | `resolve_command()` untuk alias, `COMMANDS` untuk pelengkapan, `COMMANDS_BY_CATEGORY` untuk `/help` |
| Gateway | `GATEWAY_KNOWN_COMMANDS`, dispatch, `gateway_help_lines()` |
| Telegram | `telegram_bot_commands()` untuk menu BotCommand |
| Slack | `slack_subcommand_map()` |
| TUI dan Desktop | RPC `commands.catalog` dan `complete.slash` |

Menambah alias cukup dengan menambah ke `aliases`; semua permukaan ikut.

### Dispatch di CLI

```python
_SLASH_DISPATCH: dict[str, tuple[str, bool]] = {
    "exit": ("_cmd_exit", True), "help": ("_cmd_help", True),
    "model": ("_handle_model_switch", True), "compress": ("_manual_compress", True),
    ...
}
```

`process_command()` menyelesaikan nama kanonik lewat `resolve_command()`, mencari
`(nama method, oper argumen?)` di `_SLASH_DISPATCH`, dan bila tidak ada, jatuh ke method
`_handle_<nama>_command` berdasarkan konvensi nama. **Tidak ada tangga `elif`.**

### `busy_policy`

Menentukan perilaku perintah ketika agent sedang bekerja di gateway:

- `reject`: ditolak dengan pesan "agent sedang berjalan".
- `dispatch`: tetap dijalankan (`/status`, `/queue`, `/steer`, `/approve`).
- `interrupt_then_dispatch`: interupsi dulu (`/stop`, `/new`).

### Kategori perintah

Dari 102 perintah, yang membentuk pengalaman inti:

| Kategori | Contoh |
|---|---|
| Sesi | `/new`, `/retry`, `/undo`, `/title`, `/branch`, `/compress`, `/resume`, `/sessions`, `/save`, `/stop`, `/queue`, `/steer`, `/bg`, `/btw`, `/goal`, `/status`, `/context` |
| Konfigurasi | `/model`, `/reasoning`, `/personality`, `/yolo`, `/approvals`, `/verbose`, `/skin`, `/config` |
| Tool dan skill | `/tools`, `/toolsets`, `/skills`, `/memory`, `/learn`, `/cron`, `/plugins`, `/reload-mcp`, `/reload-skills` |
| Info | `/help`, `/usage`, `/insights`, `/platforms`, `/profile` |

Perintah yang mengubah keadaan system prompt menunda efeknya ke sesi berikutnya, dengan
`--now` sebagai pilihan sadar.

Selain itu ada **slash command dari skill** (lihat [06-skills.md](06-skills.md)),
**dari plugin** (`ctx.register_command`), dan **`quick_commands`** dari konfigurasi.

## Sistem konfigurasi

Dua file dengan pembagian tegas:

- **`config.yaml`**: semua pengaturan.
- **`.env`**: **rahasia saja** (kunci, token, kata sandi).

Hermes menolak variabel lingkungan `HERMES_*` baru untuk konfigurasi bukan rahasia.
Pengaturan perilaku masuk `config.yaml`. Bila mekanisme internal butuh cermin env,
dijembatani di kode.

### `DEFAULT_CONFIG`

`hermes_cli/config_defaults.py` berisi `DEFAULT_CONFIG`: 99 kunci tingkat atas dengan
komentar yang menjelaskan *alasan* tiap nilai bawaan. Bagian utamanya:

`model`, `providers`, `fallback_providers`, `toolsets`, `agent`, `terminal`, `web`,
`browser`, `checkpoints`, `compression`, `prompt_caching`, `auxiliary`, `display`,
`memory`, `delegation`, `skills`, `curator`, `approvals`, `command_allowlist`,
`quick_commands`, `platform_hints`, `plugins`, `hooks`, `security`, `cron`, `gateway`,
`streaming`, `sessions`, `logging`, serta satu bagian per platform pesan. Di luar
`DEFAULT_CONFIG` ada kunci akar tambahan yang dikenali, misalnya `mcp_servers`.

- Kunci baru **tergabung dalam otomatis** saat dimuat. Tidak perlu migrasi.
- `_config_version` (49 pada commit rujukan) dinaikkan **hanya** untuk mengubah konfigurasi yang ada: ganti nama kunci, restrukturisasi. Migrasi ada di `hermes_cli/config_migrations.py`.
- Rahasia opsional didaftarkan di `OPTIONAL_ENV_VARS` dengan `description`, `prompt`, `url`, `password`, `category`.

### Tiga pemuat

| Pemuat | Dipakai | Sifat |
|---|---|---|
| `load_cli_config()` di `cli.py` | CLI | Bawaan CLI digabung YAML pengguna |
| `load_config()` di `hermes_cli/config.py` | `hermes tools`, `hermes setup`, kebanyakan subcommand | Menggabung `DEFAULT_CONFIG` |
| `load_user_config_effective()` | Gateway, TUI gateway, cron | File pengguna ditambah lapisan terkelola dan ekspansi `${VAR}`, **tanpa** bawaan |

Bila CLI melihat sebuah kunci tetapi gateway tidak, Anda berada di pemuat yang salah.

### Satu jahitan penulis

Setiap penulisan `config.yaml` lewat `atomic_config_write` (menolak penghapusan karena
kelalaian) atau `atomic_config_replace`. Di bawahnya dipakai ruamel YAML bolak-balik,
sehingga komentar, urutan kunci, kutipan, dan baris kosong selamat. Memanggil
`yaml.dump` langsung pada path konfigurasi ditolak lint CI.

Aturan konsistensi: setiap kunci `DEFAULT_CONFIG` punya pembaca runtime, dan setiap
pembaca punya entri registry. Kedua arah penyimpangan sama-sama diam: tombol yang tidak
berbuat apa-apa, dan pembaca kunci yang tidak pernah ditampilkan atau dimigrasi.

### Perintah konfigurasi

```text
hermes config show | edit | get <kunci> | set <kunci> <nilai> | unset <kunci>
hermes config path | env-path | check | migrate
```

`hermes config set NAMA` untuk nama yang terdaftar sebagai rahasia otomatis diarahkan ke
`.env`, bukan ke `config.yaml`.

## Skin

`hermes_cli/skin_engine.py`. Skin adalah **data murni** (`SkinConfig`); menambah skin
tidak butuh perubahan kode. Urutan muat: `~/.hermes/skins/*.yaml` milik pengguna, lalu
bawaan (`default`, `ares`, `mono`, `slate`). Nilai yang hilang mewarisi dari `default`.

Kunci: `colors.*`, `spinner.*` (wajah, kata kerja), `tool_prefix`, `tool_emojis`,
`branding.*` (`agent_name`, `welcome`, `response_label`, `prompt_symbol`).

## Profil

Profil adalah instance Hermes yang sepenuhnya terpisah: home, konfigurasi, rahasia,
memori, sesi, skill, plugin, cron, dan PID gateway sendiri.

```text
~/.hermes/                  profil default
~/.hermes/profiles/kerja/   profil "kerja"
```

- `hermes -p kerja <perintah>` menjalankan perintah pada profil itu.
- `hermes profile list | show | create | use | rename | delete | alias | export | import`.
- **Profil adalah pulau mandiri secara sengaja.** Tidak ada pewarisan konfigurasi langsung dari profil default. `--clone` menyalin saat pembuatan.

Aturan kode yang lahir dari profil:

- **Jangan pernah menulis `~/.hermes` secara harfiah.** Pakai `get_hermes_home()` untuk path kode dan `display_hermes_home()` untuk teks yang dilihat pengguna.
- Konstanta modul yang diturunkan dari home, konfigurasi, atau `.env` adalah **kelas bug**: ia membeku pada profil saat peluncuran. Selesaikan saat dipanggil.
- Satu proses bisa melayani banyak profil (gateway multipleks, backend desktop). Home aktif diikat per aktivitas lewat ContextVar, sementara `os.environ` tetap memegang profil peluncuran.
- Thread baru dari kode berlingkup harus menyalin ContextVar.

## Setup, doctor, logs, update

- **`hermes setup`**: wizard interaktif yang memilih penyedia, mengumpulkan kunci, memilih model, dan menawarkan penyiapan tool serta gateway. Integrasi baru harus menyatu dengan alur ini, bukan menyuruh pengguna menyetel env var mentah.
- **`hermes doctor`**: diagnosis konfigurasi, kredensial, konektivitas penyedia, ketersediaan tool, dan kesehatan basis data.
- **`hermes logs [--follow] [--level] [--session]`**: menelusuri `agent.log`, `errors.log`, `gateway.log`.
- **`hermes update`**: jalur transaksional `rencana → potret → terapkan → restart per jenis → verifikasi → laporan`. Setiap tahap menjaga dari kegagalan nyata di lapangan. Pelajaran utamanya: jangan pernah menjalankan kode yang baru ditarik di interpreter lama.

## Yang perlu ditiru persis

1. Profil diterapkan sebelum modul lain diimpor.
2. Satu registry slash command yang menghidupi semua permukaan.
3. Dispatch lewat tabel dan konvensi nama, tanpa tangga `elif`.
4. `config.yaml` untuk pengaturan, `.env` untuk rahasia saja.
5. Penggabungan dalam dengan bawaan, dan versi konfigurasi hanya untuk migrasi.
6. Satu jahitan penulis konfigurasi yang menjaga komentar.
7. Tidak ada path home yang ditulis harfiah.
8. Skin sebagai data.

## Rujukan di Hermes

`hermes_cli/main.py`, `hermes_cli/_parser.py`, `hermes_cli/subcommands/`, `cli.py`,
`hermes_cli/cli_*_mixin.py`, `hermes_cli/commands.py`, `hermes_cli/config.py`,
`hermes_cli/config_defaults.py`, `hermes_cli/config_migrations.py`,
`hermes_cli/config_effective.py`, `hermes_cli/skin_engine.py`, `hermes_cli/profiles.py`,
`hermes_constants.py`, `hermes_cli/setup.py`, `hermes_cli/doctor.py`,
`hermes_cli/AGENTS.md`, `website/docs/developer-guide/cli-internals.md`,
`website/docs/developer-guide/extending-the-cli.md`.
