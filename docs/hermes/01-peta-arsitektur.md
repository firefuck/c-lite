# 01. Peta Arsitektur Hermes

## Hermes dalam satu paragraf

Hermes adalah agent AI pribadi yang menjalankan **satu inti agent yang sama** di banyak
permukaan: CLI, TUI, aplikasi desktop, dashboard web, gateway pesan (Telegram, Discord,
Slack, dan sekitar 20 platform lain), editor lewat ACP, serta tugas terjadwal. Agent
belajar lintas sesi lewat memori dan skill, bisa mendelegasikan pekerjaan ke subagent,
dan mengendalikan terminal serta browser sungguhan. Perluasan kemampuan terutama lewat
**plugin dan skill**, bukan dengan menambah isi inti.

## Dua invarian yang membentuk hampir semua keputusan

Kedua hal ini adalah kacamata untuk menilai setiap perubahan. Sumbernya `AGENTS.md` di root Hermes.

**1. Cache prompt per percakapan itu sakral.** Percakapan panjang memakai ulang prefiks
yang sudah di-cache penyedia model di setiap giliran. Apa pun yang mengubah konteks
lampau, mengganti toolset, memuat ulang memori, atau membangun ulang system prompt di
tengah percakapan akan membatalkan cache itu dan melipatgandakan biaya pengguna. Hermes
tidak melakukannya. Satu-satunya pengecualian adalah kompresi konteks. Slash command
yang mengubah keadaan system prompt (skill, tool, memori) harus sadar cache: efeknya
ditunda ke sesi berikutnya, dengan flag `--now` sebagai pilihan sadar.

**2. Inti itu pinggang yang sempit; kemampuan hidup di tepi.** Setiap tool model dikirim
pada setiap panggilan API, sehingga syarat untuk menambah tool *inti* sangat tinggi.
Kemampuan baru sebaiknya datang sebagai perintah CLI plus skill, tool yang hanya muncul
bila prasyaratnya terpenuhi, atau plugin.

### Tangga jejak (Footprint Ladder)

Untuk kemampuan baru, Hermes memilih anak tangga tertinggi yang masih menyelesaikan masalah:

1. **Perluas kode yang ada.** Tidak ada permukaan baru.
2. **Perintah CLI plus skill.** Agent menjalankan `hermes <subcommand>` dengan panduan skill. Ini pilihan baku untuk langganan, tugas terjadwal, dan penyiapan layanan.
3. **Tool bergerbang layanan** (`check_fn`). Butuh parameter terstruktur dan hanya muncul bila prasyarat dikonfigurasi.
4. **Plugin.** Untuk hal pihak ketiga, ceruk, atau khusus pengguna.
5. **Server MCP di katalog.** Tool sungguhan tetapi bukan hal mendasar; tanpa jejak permanen di skema inti.
6. **Tool inti baru.** Hanya bila mendasar, berguna bagi hampir semua pengguna, dan tidak terjangkau lewat terminal plus file.

## Peta sistem

```text
┌──────────────────────────────────────────────────────────────────────┐
│                           Entry point                                │
│  CLI (cli.py)   Gateway (gateway/run.py)   ACP (acp_adapter/)        │
│  TUI/Desktop/Dashboard (tui_gateway/)   Batch runner   Cron          │
└──────────┬───────────────┬──────────────────────┬────────────────────┘
           ▼               ▼                      ▼
┌──────────────────────────────────────────────────────────────────────┐
│                      AIAgent (run_agent.py)                          │
│  Perakit prompt        Resolusi provider       Dispatch tool         │
│  agent/system_prompt   hermes_cli/             model_tools.py        │
│  agent/prompt_builder  runtime_provider.py     tools/registry.py     │
│  Kompresi dan cache    3 mode API              Toolset               │
│  agent/context_*       agent/transports/       toolsets.py           │
└──────────┬───────────────────────────────────────┬───────────────────┘
           ▼                                       ▼
┌────────────────────────┐            ┌──────────────────────────────┐
│ Penyimpanan sesi       │            │ Backend tool                 │
│ SQLite + FTS5          │            │ Terminal: local, docker, ssh,│
│ hermes_state*.py       │            │ modal, daytona, singularity  │
│ gateway/session*.py    │            │ Browser, web, MCP, file      │
└────────────────────────┘            └──────────────────────────────┘
```

## Struktur direktori

Jumlah file terus berubah; sistem file adalah sumber kebenaran. Yang menopang beban:

```text
hermes-agent/
├── run_agent.py          Fasad AIAgent. Loop ada di agent/conversation_loop.py dan agent/turn_*.py
├── model_tools.py        Orkestrasi tool: discover_builtin_tools(), handle_function_call()
├── toolsets.py           Kamus TOOLSETS dan _HERMES_CORE_TOOLS
├── cli.py                HermesCLI (REPL, dispatch slash) ditambah hermes_cli/cli_*_mixin.py
├── hermes_state.py       Fasad SessionDB ditambah saudara hermes_state_*.py
├── hermes_constants.py   get_hermes_home(), display_hermes_home(): path yang sadar profil
├── hermes_logging.py     agent.log, errors.log, gateway.log
├── batch_runner.py       Pemrosesan batch paralel untuk data latih
├── agent/                Fase loop, transport, memori, kompresi, perakit prompt
├── providers/            ABC ProviderProfile dan registry-nya
├── hermes_cli/           Subcommand, setup, konfigurasi, pemuat plugin, skin, updater
│   └── web_routers/      Router FastAPI dashboard, satu file per permukaan
├── tools/                Implementasi tool, ditemukan otomatis lewat tools/registry.py
│   └── environments/     Backend terminal
├── gateway/              Fasad run.py, fase run_*.py, sesi, adapter platform
├── plugins/              memory/, context_engine/, model-providers/, platforms/, image_gen/, ...
├── skills/               Skill bawaan per kategori. optional-skills/: dikirim tetapi tidak aktif
├── ui-tui/               TUI Ink (React) untuk `hermes --tui`
├── tui_gateway/          Backend JSON-RPC Python untuk TUI dan Desktop
├── apps/desktop/         Aplikasi Electron. apps/shared/: klien JSON-RPC bersama
├── web/                  SPA dashboard
├── acp_adapter/          Server ACP untuk VS Code, Zed, JetBrains
├── cron/                 jobs.py, scheduler.py
├── evals/                Tolok ukur offline
├── scripts/              run_tests.sh, release, CI
├── website/              Dokumentasi Docusaurus
└── tests/                Suite pytest
```

Keadaan pengguna tersimpan di `~/.hermes/`:

```text
~/.hermes/
├── config.yaml     Pengaturan
├── .env            Rahasia saja (kunci API, token)
├── auth.json       Kredensial OAuth
├── SOUL.md         Persona global agent (opsional)
├── state.db        Sesi dan pesan (SQLite)
├── memories/       MEMORY.md dan USER.md
├── skills/         Skill, termasuk yang dibuat agent
├── plugins/        Plugin pengguna
├── cron/           jobs.json dan catatan eksekusi
├── logs/           agent.log, errors.log, gateway.log
└── profiles/<nama>/  Profil lain, masing-masing dengan isi yang sama
```

## Rantai ketergantungan yang wajib dijaga

```text
tools/registry.py        tanpa ketergantungan; diimpor semua file tool
       ↑
tools/*.py               tiap file memanggil registry.register() saat diimpor
       ↑
model_tools.py           mengimpor registry dan memicu discovery
       ↑
run_agent.py, cli.py, batch_runner.py, environments/
```

Registrasi tool terjadi saat impor, sebelum instance agent mana pun dibuat. File
`tools/*.py` yang memanggil `registry.register()` di tingkat modul ditemukan otomatis,
tanpa daftar impor manual.

## Alur data

### Sesi CLI

```text
Input pengguna → HermesCLI.process_input()
  → AIAgent.run_conversation()
    → build_system_prompt()                    sekali per percakapan
    → resolve_runtime_provider()
    → panggilan API (chat_completions / codex_responses / anthropic_messages)
    → ada tool_calls? → handle_function_call() → ulangi
    → jawaban akhir → tampilkan → simpan ke SessionDB
```

### Pesan gateway

```text
Event platform → Adapter.on_message() → MessageEvent
  → GatewayRunner._handle_message()
    → otorisasi pengguna
    → tentukan kunci sesi
    → buat atau ambil AIAgent dari cache, dengan riwayat sesi
    → AIAgent.run_conversation()
    → kirim jawaban lewat adapter
```

### Tugas cron

```text
Detak penjadwal → muat job yang jatuh tempo dari jobs.json
  → buat AIAgent baru tanpa riwayat
  → sisipkan skill terlampir sebagai konteks
  → jalankan prompt job
  → kirim hasil ke platform tujuan
  → perbarui keadaan job dan next_run
```

### TUI dan Desktop

```text
hermes --tui
  └─ Node (Ink)  ──stdio JSON-RPC──  Python (tui_gateway)
       │                                  └─ AIAgent + tool + sesi
       └─ menggambar transkrip, composer, prompt, aktivitas

Desktop (Electron) ──WebSocket JSON-RPC──  hermes serve  (server yang sama)
```

TypeScript memegang layar. Python memegang sesi, tool, panggilan model, dan logika
slash command. Perilaku agent tidak pernah dipindahkan ke renderer.

## Prinsip desain

| Prinsip | Wujudnya |
|---|---|
| Prompt stabil | System prompt tidak berubah di tengah percakapan. Tidak ada mutasi yang merusak cache kecuali aksi eksplisit pengguna. |
| Eksekusi teramati | Setiap panggilan tool terlihat pengguna lewat callback: spinner di CLI, pesan progres di gateway. |
| Dapat diinterupsi | Panggilan API dan eksekusi tool bisa dibatalkan di tengah jalan. |
| Inti agnostik platform | Satu kelas `AIAgent` melayani semua permukaan. Perbedaan platform ada di entry point. |
| Kopling longgar | Subsistem opsional memakai pola registry dan gerbang `check_fn`, bukan ketergantungan keras. |
| Isolasi profil | Tiap profil punya `HERMES_HOME`, konfigurasi, memori, sesi, dan PID gateway sendiri. |

## Kemampuan sebagai sifat sesi, bukan sifat proses

Tool yang hanya masuk akal karena *siapa yang ada di ujung sana* (panel desktop, browser
dalam aplikasi, reaksi pesan) harus menentukan ketersediaannya dari **sumber sesi itu
sendiri**, bukan dari variabel lingkungan di proses backend. Klien dan backend bisa
berada di mesin berbeda: aplikasi desktop mungkin menggerakkan backend lokal, backend
lewat SSH, atau backend di cloud. Gerbang berbasis env var diam-diam tidak berfungsi
pada topologi selain yang pertama.

Polanya: tool semacam itu ditaruh di toolset bernama (`desktop_ui`, `project`) yang
dilipat masuk oleh penentu toolset ketika platform sesinya adalah GUI. `check_fn`
menjawab "apakah layanan terjangkau", tidak pernah "siapa yang memanggil saya".

## Urutan baca yang disarankan

1. Dokumen ini.
2. [02-agent-loop.md](02-agent-loop.md).
3. [03-prompt-dan-cache.md](03-prompt-dan-cache.md).
4. [04-provider-dan-model.md](04-provider-dan-model.md).
5. [05-tools-dan-toolsets.md](05-tools-dan-toolsets.md).
6. [11-state-sesi-memori.md](11-state-sesi-memori.md).
7. Sisanya sesuai modul yang sedang dikerjakan.

## Rujukan di Hermes

`AGENTS.md`, `website/docs/developer-guide/architecture.md`, `README.md`.
