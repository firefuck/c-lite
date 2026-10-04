# Bedah Hermes Agent

Folder ini berisi hasil pembedahan **Hermes Agent** (Nous Research, lisensi MIT), yang
menjadi acuan arsitektur proyek ini. Tujuannya dua: supaya Anda paham *mengapa* Hermes
dibangun seperti itu, dan supaya AI yang mengerjakan proyek ini punya rujukan persis ke
file Hermes ketika mengimplementasikan sebuah modul.

## Sumber yang dibedah

| | |
|---|---|
| Repo | `https://github.com/NousResearch/hermes-agent` |
| Commit | `1298c8e74baa73e1a2b90124228d017261ac6bc4` |
| Tanggal commit | 4 Oktober 2026 |
| Lisensi | MIT, hak cipta 2025 Nous Research |
| Cara baca | Source code langsung, ditambah 12 file `AGENTS.md` dan dokumen `website/docs/developer-guide/` |

Semua path di folder ini, misalnya `agent/conversation_loop.py`, adalah path **di dalam
repo Hermes** pada commit di atas. Hermes bergerak cepat, jadi nama file bisa berpindah
di commit yang lebih baru. Simpan clone pada commit tersebut sebagai rujukan tetap:

```bash
git clone https://github.com/NousResearch/hermes-agent ../hermes-ref
git -C ../hermes-ref checkout 1298c8e74baa73e1a2b90124228d017261ac6bc4
```

## Ukuran Hermes

Angka ini penting untuk menakar pekerjaan. Semuanya dihitung dari clone pada commit di atas.

| Bagian | File | Baris | Isi |
|---|---:|---:|---|
| `agent/` | 317 `.py` | 131 ribu | Loop percakapan, prompt, kompresi, transport provider, memori |
| `hermes_cli/` | 644 `.py` | 260 ribu | Subcommand, konfigurasi, auth, plugin manager, web server |
| `tools/` | 338 `.py` | 120 ribu | Registry dan implementasi tool, backend terminal, MCP |
| `gateway/` | 175 `.py` | 95 ribu | Gateway pesan dan adapter platform |
| `plugins/` | 225 `.py` | 81 ribu | Plugin bawaan: provider model, platform, memori |
| `tui_gateway/` | 101 `.py` | 43 ribu | Backend JSON-RPC untuk TUI dan Desktop |
| File `.py` di root | 52 | 33 ribu | `run_agent.py`, `cli.py`, `model_tools.py`, `hermes_state*.py` |
| `cron/` | 35 `.py` | 18 ribu | Penjadwal tugas |
| `acp_adapter/` | 14 `.py` | 4,5 ribu | Integrasi editor (ACP) |
| `apps/desktop/` | 3.392 `.ts/.tsx` | 788 ribu | Aplikasi desktop Electron |
| `ui-tui/` | 522 `.ts/.tsx` | 104 ribu | TUI berbasis Ink (React) |
| `web/` | 195 `.ts/.tsx` | 58 ribu | Dashboard web |
| `apps/shared/` | 40 `.ts` | 12 ribu | Klien JSON-RPC bersama dan kontrak hasil generate |
| `tests/` | 5.653 `.py` | 1,28 juta | Test pytest |

Angka lain yang berguna:

- 102 slash command di `hermes_cli/commands.py`.
- 251 method JSON-RPC, 13 server request, dan 69 jenis event di `tui_gateway/contracts/`.
- 99 kunci tingkat atas di `DEFAULT_CONFIG`, dengan `_config_version` bernilai 49.
- 38 plugin provider model di `plugins/model-providers/`.
- 21 plugin platform pesan di `plugins/platforms/`, ditambah adapter bawaan di `gateway/platforms/`.
- 58 skill bawaan di `skills/` dan 152 skill opsional di `optional-skills/`.

Artinya Hermes bukan proyek yang bisa ditiru utuh dalam beberapa minggu, bahkan dengan AI.
Yang realistis adalah meniru **fondasinya**, yaitu kontrak antar-modul dan invarian
desainnya, lalu menumbuhkan fitur di tepi secara bertahap. Itulah yang disiapkan
scaffolding ini.

## Daftar dokumen

| Dokumen | Isi |
|---|---|
| [01-peta-arsitektur.md](01-peta-arsitektur.md) | Peta besar, entry point, alur data, dua invarian utama |
| [02-agent-loop.md](02-agent-loop.md) | `AIAgent`, fase-fase satu giliran, format pesan, interupsi, anggaran iterasi |
| [03-prompt-dan-cache.md](03-prompt-dan-cache.md) | Tiga tingkat system prompt, file konteks, cache, kompresi |
| [04-provider-dan-model.md](04-provider-dan-model.md) | `ProviderProfile`, transport, resolusi runtime, fallback, katalog model |
| [05-tools-dan-toolsets.md](05-tools-dan-toolsets.md) | Registry, discovery, toolset, dispatch, persetujuan perintah, delegasi |
| [06-skills.md](06-skills.md) | Format `SKILL.md`, indeks, tool skill, hub, kurator |
| [07-plugins.md](07-plugins.md) | Jenis plugin, manifest, `PluginContext`, hook, kontrak kompatibilitas |
| [08-cli.md](08-cli.md) | Subcommand, REPL, registry slash command, konfigurasi, profil |
| [09-tui-dan-rpc.md](09-tui-dan-rpc.md) | Model proses TUI, protokol kawat, kontrak, katalog method |
| [10-gui-desktop-dashboard.md](10-gui-desktop-dashboard.md) | `serve`, aplikasi desktop, dashboard |
| [11-state-sesi-memori.md](11-state-sesi-memori.md) | Skema SQLite, pencarian, silsilah sesi, memori |
| [12-gateway-cron.md](12-gateway-cron.md) | Gateway pesan, adapter, kunci sesi, cron |
| [13-aturan-rekayasa.md](13-aturan-rekayasa.md) | Aturan rekayasa Hermes yang layak diwarisi |
| [99-peta-file.md](99-peta-file.md) | Tabel padanan file Hermes ke modul proyek ini |

## Cara memakai dokumen ini bersama AI

Saat memberi tugas ke AI untuk sebuah modul, sertakan tiga hal: spesifikasi modul di
`docs/spesifikasi/`, bab bedah yang relevan di folder ini, dan path file Hermes yang
disebut di bab itu. AI lalu membaca file Hermes tersebut di clone rujukan, bukan
menebak dari ingatan. Pola ini dijelaskan lebih rinci di `docs/prompts/`.

## Catatan lisensi

Lisensi MIT mengizinkan Anda menyalin, mengubah, dan menjual ulang kode Hermes selama
pemberitahuan hak cipta dan teks lisensinya ikut disertakan. Scaffolding ini ditulis
ulang, tidak menyalin file Hermes, tetapi arsitekturnya jelas diturunkan dari sana.
Karena itu `NOTICE.md` di root mencantumkan atribusi. Jika nanti AI Anda menyalin
potongan kode Hermes secara langsung, pertahankan atribusi itu.
