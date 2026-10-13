# Beda dengan Hermes

C-lite meniru **fondasi** Hermes Agent: kontrak antar-modul dan invarian desainnya. C-lite
tidak menyalin kodenya dan tidak mengejar jumlah fiturnya. Dokumen ini mencatat apa yang sama,
apa yang sengaja dibuat berbeda, dan apa yang belum dibawa, supaya orang yang memindahkan
fitur dari Hermes tahu apa yang harus disesuaikan.

Rujukan file Hermes di halaman ini mengacu ke commit yang dicatat di
[bedah Hermes](../hermes/README.md). Padanan file demi file ada di
[peta file](../hermes/99-peta-file.md).

## Ukuran

Dihitung 5 Oktober 2026. Angka Hermes dari clone pada commit rujukan.

| | Hermes | C-lite |
|---|---:|---:|
| Python, tanpa tes | sekitar 790 ribu baris | sekitar 18 ribu baris |
| Tes Python | sekitar 1,28 juta baris | sekitar 8 ribu baris |
| TypeScript | sekitar 960 ribu baris | sekitar 3 ribu baris |
| Tool di toolset inti | 55 | 16 |
| Slash command | 102 | 27 |
| Method JSON-RPC | 251 | 32 |
| Provider model bawaan | 38 | 8 |
| Platform pesan | lebih dari 20 | 2 |
| Skill bawaan | 58, ditambah 152 opsional | 4 |

C-lite kira-kira dua persen dari ukuran Hermes. Yang sudah ada adalah kerangka tempat fitur
berikutnya dipasang; [roadmap](../roadmap/README.md) mengurutkan pemasangannya.

## Yang sama

Hal-hal ini diambil dari Hermes dan dijaga dengan tes.

| Prinsip | Di Hermes | Di C-lite |
|---|---|---|
| System prompt dibangun sekali per sesi dan dipakai ulang byte demi byte | `agent/prompt_builder.py`, `run_agent.py` | `src/clite/agent/prompt/builder.py` |
| Inti sempit, kemampuan di tepi (tool, skill, plugin, MCP) | `AGENTS.md` di root Hermes | [03-invarian.md](03-invarian.md) |
| Tool mendaftarkan dirinya saat diimpor | `tools/registry.py` | `src/clite/tools/registry.py` |
| Toolset sebagai kelompok tool yang bisa saling menyertakan | `toolsets.py` | `src/clite/tools/toolsets.py` |
| Provider sebagai profil deklaratif, transport per protokol kawat | `providers/`, `plugins/model-providers/`, `agent/transports/` | `src/clite/providers/base.py`, `src/clite/providers/transports/` |
| Galat API diklasifikasi di satu tempat | `agent/error_classifier.py` | `src/clite/providers/errors.py` |
| Skill dengan pengungkapan bertahap, format agentskills.io | `tools/skills_tool.py`, `tools/skill_manager_tool.py` | `src/clite/skills/` |
| Satu tabel slash command untuk semua surface | `hermes_cli/commands.py` | `src/clite/runtime/commands.py` |
| Plugin opt-in dengan hook siklus hidup dan ledger pembatalan per plugin | `hermes_cli/plugins.py` | `src/clite/plugins/` |
| Home dinamis dan profil terpisah penuh | `hermes_constants.py`, `hermes_cli/profiles.py` | `src/clite/core/constants.py`, `src/clite/core/profiles.py` |
| Rahasia di `.env`, pengaturan di `config.yaml` | `hermes_cli/config.py` | `src/clite/core/env.py`, `src/clite/core/config.py` |
| Sesi di SQLite dengan FTS5 | `hermes_state.py` | `src/clite/state/db.py` |
| TUI sebagai proses terpisah yang berbicara JSON-RPC lewat stdio | `tui_gateway/`, `ui-tui/` | `src/clite/rpc/`, `apps/tui/` |
| Kontrak RPC menghasilkan tipe TypeScript | `tui_gateway/contracts/`, `apps/shared/` | `src/clite/rpc/contracts/`, `packages/shared/` |
| Job cron adalah prompt yang berjalan di sesi baru | `cron/jobs.py`, `cron/scheduler.py` | `src/clite/cron/` |
| Memori bawaan berupa dua file kecil yang dikurasi agent | `agent/memory_manager.py` | `src/clite/agent/memory/` |

## Yang sengaja berbeda

### Struktur

| Hal | Hermes | C-lite | Alasan |
|---|---|---|---|
| Tata letak | Paket di root repositori (`agent/`, `tools/`, `hermes_cli/`) dan modul lepas (`run_agent.py`, `cli.py`, `model_tools.py`) | Satu paket `clite` di `src/` | Satu ruang nama, bisa dipasang bersih |
| Arah import | Konvensi | Peringkat lapisan yang dijaga tes | Aturan yang tidak dijalankan mesin akan dilanggar |
| Logika bersama antar-surface | Tersebar di `cli.py`, `hermes_cli/`, `tui_gateway/server.py`, `gateway/run.py` | Lapisan `runtime` (`build_agent`, `ChatSession`) | Empat surface, satu jalur |
| Loop giliran | `agent/conversation_loop.py` dan puluhan modul `agent/turn_*.py` yang berbagi state lewat objek agent | Fase sebagai fungsi atas `TurnState` | Urutan terbaca di satu file |
| Tool tingkat agent | Ditangani khusus oleh loop | Tool biasa yang menerima `ctx.agent` | Loop tanpa cabang per nama tool |
| Kebijakan paralel tool | Daftar nama di executor | Dideklarasikan per tool saat mendaftar | Tool baru membawa kebijakannya sendiri |

### Perilaku

| Hal | Hermes | C-lite | Alasan |
|---|---|---|---|
| Konteks giliran (ingatan, keluaran hook) | Ditempel ke pesan pengguna hanya pada panggilan itu | Disimpan sebagai `turn_context` dan dikirim ulang | Awalan percakapan tidak pernah berubah; diwajibkan model Claude generasi 5 |
| Kompresi | Membuat sesi anak baru | Di tempat; baris lama diarsipkan di sesi yang sama | Id sesi tetap, riwayat tetap bisa dicari |
| Hasil giliran | `dict` | `TurnResult`; `run_turn` tidak pernah melempar | Surface tidak perlu `try` di sekitar giliran |
| HTTP ke provider | SDK `openai` dan `anthropic`, `httpx` | `http.client` dari pustaka standar | Pembatalan lewat soket, sedikit dependensi |
| Vendor yang berbeda protokolnya | Adapter per vendor | Transport per `api_mode`; vendor adalah profil | Satu jalur kode per protokol |
| Klien MCP | SDK `mcp` | Klien sendiri untuk stdio dan Streamable HTTP | Tanpa dependensi; cakupan lebih sempit (tanpa sampling atau OAuth) |
| Skill bawaan | Disalin ke home dan disinkronkan | Dibaca di tempat, sunting dengan copy-on-write | Pembaruan paket tidak menimpa suntingan |
| Persetujuan shell hook | Saat pertama dipakai, atau lewat config | Perintah eksplisit `clite hooks approve` | Config bisa diubah agent lewat terminal |
| Gateway | Seluruhnya asinkron | Thread; runner sinkron di atas `ChatSession` | Lebih sederhana; lihat catatan di bawah |
| REPL klasik | `prompt_toolkit` dan `rich` | Pustaka standar | Pengalaman kaya ada di TUI |
| TUI | Aplikasi Ink (React) | Antarmuka baris di atas `node:readline` | Kecil dan teruji; lapisan bawahnya dipakai ulang oleh penggantinya |
| Desktop | Renderer React sendiri | Cangkang yang memuat dashboard backend | Satu UI untuk browser dan desktop |
| Dashboard | Aplikasi React dengan server FastAPI sendiri | JavaScript polos, dilayani server yang sama dengan RPC | Tanpa langkah build |
| Provider `mock` | Tidak ada | Bawaan | Setiap surface bisa dicoba dan diuji tanpa kunci |

Catatan gateway: adapter yang pustakanya asinkron (Discord, misalnya) perlu menjalankan event
loop sendiri di thread adapter. Itu harga dari runner yang sinkron.

## Yang belum dibawa

Daftar ini disusun ulang pada 13 Oktober 2026 dengan memeriksa setiap butir daftar lama
terhadap kode di repositori ini; butir yang sudah ada dihapus (antara lain transport Responses
API, Bedrock, Vertex, Azure, OAuth provider, harga, Docker, SSH, review latar belakang,
delegasi asinkron, platform Discord, Slack, WhatsApp, Signal, Matrix, dan email, skrip pra-jalan
dan riwayat cron, endpoint kompatibel OpenAI, webhook, hub skill, katalog plugin, server ACP,
batch runner, dan lintasan pelatihan). Clone Hermes tidak tersedia saat itu, sehingga fitur
Hermes yang tidak pernah masuk daftar lama tidak tercakup. Sebelum dipakai sebagai daftar celah
yang lengkap, daftar ini perlu diaudit terhadap clone Hermes.

| Kelompok | Yang ada di Hermes dan belum ada di sini |
|---|---|
| Provider | Gemini lewat API native-nya; profil `gemini` di sini memakai endpoint kompatibel OpenAI |
| Tool | Browser |
| Lingkungan eksekusi | Backend jarak jauh selain Docker dan SSH |
| MCP | Sampling, dan OAuth untuk server HTTP |
| Agent | Mode campuran model |
| Cron | Satu tugas yang dikirim ke banyak tujuan sekaligus |
| Desktop | Pembaruan otomatis. Renderer khusus sengaja tidak dibawa: satu dashboard melayani browser dan desktop |
| Keamanan | Pemindai eksternal untuk perintah. Cakupan deteksi perintah dan redaksi belum dibandingkan ulang dengan `tools/approval_detection.py` dan `agent/redact.py` |

## Memindahkan fitur dari Hermes

Urutan kerja saat sebuah task roadmap merujuk file Hermes:

1. **Baca file Hermes yang dirujuk**, di clone pada commit rujukan. Jangan mengandalkan
   ingatan tentang Hermes; kodenya berubah cepat.
2. **Ambil perilakunya, bukan bentuknya.** Catat apa yang dijanjikan fitur itu kepada
   pengguna dan kasus tepi yang ditangani kodenya. Tes Hermes untuk fitur itu adalah daftar
   kasus tepi terbaik yang tersedia.
3. **Tulis ulang mengikuti bentuk C-lite.** Tabel di bawah menunjukkan penyesuaian yang
   paling sering diperlukan.
4. **Jangan memindahkan penanganan khusus per vendor ke inti.** Bila fitur Hermes bercabang
   menurut nama provider, cabang itu menjadi method pada `ProviderProfile`.
5. **Bila menyalin potongan kode secara langsung**, pertahankan atribusi lisensi MIT sesuai
   [NOTICE.md](../../NOTICE.md).

| Di Hermes | Menjadi di C-lite |
|---|---|
| `from hermes_constants import get_hermes_home` | `from clite.core.constants import get_home` |
| `os.getenv("X_API_KEY")` | `get_secret("X_API_KEY")`, dan daftarkan namanya |
| `if provider == "..."` di kode inti | Method pada `ProviderProfile`, di-override profil vendor |
| Kwargs lepas ke handler tool (`task_id=`, `session_id=`) | `ctx: ToolContext` |
| Atribut baru pada objek agent untuk state giliran | Bidang pada `TurnState` |
| Cabang baru di loop percakapan | Fase baru di `src/clite/agent/turn/` |
| Konteks yang ditempel sesaat ke pesan pengguna | `turn_context`, tersimpan |
| Handler slash command yang mencetak | Handler yang mengembalikan `SlashResult` |
| Kode `async` di gateway | Kode sinkron di thread adapter |
| Method baru di `tui_gateway/server.py` | Kontrak di `src/clite/rpc/contracts/schema.py`, lalu handler di `src/clite/rpc/methods/<domain>.py` |
| Rute REST baru di server dashboard | Method RPC (rute REST hanya untuk baca sederhana) |
| Pengaturan baru | Kunci di `DEFAULT_CONFIG` **beserta pembacanya** |
