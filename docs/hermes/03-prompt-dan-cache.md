# 03. Prompt, Cache, dan Kompresi

Hermes memisahkan dengan tegas dua hal: **system prompt yang di-cache** dan **tambahan
sementara pada saat panggilan API**. Ini salah satu keputusan desain terpenting karena
memengaruhi biaya token, efektivitas cache, kesinambungan sesi, dan kebenaran memori.

## Tiga tingkat system prompt

`agent/system_prompt.py::build_system_prompt_parts` merakit prompt sebagai tiga tingkat
berurutan. Prompt akhir adalah gabungan `stable` lalu `context` lalu `volatile`.

| Tingkat | Isi | Sifat |
|---|---|---|
| **stable** | Identitas (`SOUL.md` atau identitas bawaan), panduan pemakaian tool, panduan khusus model, skill yang dipasang tetap (`skills.auto_load`), panduan kerja coding | Sama di semua sesi, profil, dan direktori kerja |
| **context** | `system_message` dari pemanggil, file konteks proyek, potret workspace git, petunjuk platform | Bergantung pada proyek dan worktree |
| **volatile** | Indeks skill, potret `MEMORY.md`, potret `USER.md`, blok penyedia memori eksternal, bagian dari plugin, baris profil aktif, baris tanggal dan sesi, petunjuk lingkungan runtime | Paling mungkin berbeda saat dirakit ulang |

Urutan ini disengaja. Cache penyedia bekerja dengan **prefiks terpanjang yang sama**,
jadi bagian yang paling jarang berubah ditaruh paling depan.

Catatan: dokumen Hermes `prompt-assembly.md` di satu bagian menyebut indeks skill berada
di tingkat stable. Kode pada commit rujukan menaruhnya di awal tingkat volatile, dengan
alasan yang tertulis di komentar: skill bisa berubah saat runtime, sehingga indeks yang
tidak berubah tetap berada dalam prefiks yang dipakai ulang, sedangkan indeks yang
berubah hanya memaksa pengisian ulang mulai dari titik itu. Ikuti kodenya.

Beberapa rincian yang menjaga kestabilan byte:

- **Baris tanggal hanya memuat tanggal**, bukan jam, sehingga prompt stabil sepanjang hari. Zona waktu dan selisih UTC disertakan agar tool tidak perlu menebak.
- **Baris profil aktif** memuat path, jadi ditaruh di volatile supaya prefiks stable identik di semua profil.
- **Potret workspace git** dibekukan per sesi dan diputar ulang saat prompt dirakit ulang. Memeriksa git lagi akan menghasilkan byte berbeda untuk repo yang sudah berubah.
- **Bagian dari plugin** dikurung pada satu jangkar di ekor volatile dan dibekukan per sesi.

## Prompt dirakit sekali, lalu disimpan

`build_system_prompt()` menyimpan hasilnya di `agent._cached_system_prompt` dan di baris
sesi pada `state.db`. Giliran berikutnya, juga setelah proses restart, memakai ulang
byte yang tersimpan. Prompt hanya dirakit ulang pada:

- sesi baru,
- setelah kompresi konteks (`invalidate_system_prompt()`), yang sekaligus memuat ulang memori dari disk,
- aksi eksplisit pengguna yang mengubah rute, misalnya `/model`.

Pergantian permukaan (desktop ke TUI dan sebaliknya) tidak merakit ulang prompt. Panduan
untuk permukaan baru dikirim sebagai catatan sekali pakai di kanal pesan pengguna
(`agent/surface_switch.py`), sehingga prefiks cache selamat.

## Identitas: `SOUL.md`

`SOUL.md` berada di `~/.hermes/SOUL.md` dan menjadi bagian paling awal dari prompt.

```python
# Disederhanakan dari agent/prompt_builder.py
def load_soul_md() -> Optional[str]:
    soul_path = get_hermes_home() / "SOUL.md"
    if not soul_path.exists():
        return None
    content = soul_path.read_text(encoding="utf-8").strip()
    content = _scan_context_content(content, "SOUL.md", user_authored=True)  # diperingatkan, tetap dimuat
    content = _truncate_content(content, "SOUL.md")
    return content
```

Bila `SOUL.md` tidak ada, dipakai `DEFAULT_AGENT_IDENTITY`: satu paragraf yang meminta
jawaban sepadan dengan bobot pertanyaan, tanpa basa-basi, tanpa mengulang permintaan,
dan tanpa menceritakan panggilan tool yang sudah terlihat pengguna.

Subagent dijalankan dengan `skip_context_files`, sehingga tidak memuat `SOUL.md` dan
memakai identitas bawaan.

## File konteks proyek

`build_context_files_prompt()` memakai sistem prioritas. **Hanya satu jenis** yang
dimuat; yang pertama ditemukan menang.

| Prioritas | File | Cakupan pencarian |
|---|---|---|
| 1 | `.hermes.md`, `HERMES.md` | Dari direktori kerja naik sampai root git |
| 2 | `AGENTS.md` | Rantai dari root git turun ke direktori kerja |
| 3 | `CLAUDE.md` | Direktori kerja |
| 4 | `.cursorrules`, `.cursor/rules/*.mdc` | Direktori kerja |

Semua file konteks:

- **Dipindai keamanan** terhadap pola injeksi prompt: unicode tak terlihat, kalimat seperti "abaikan instruksi sebelumnya", upaya mengeluarkan kredensial. File proyek yang kena diganti penanda `[BLOCKED: ...]`. `SOUL.md` milik pengguna hanya diperingatkan lalu tetap dimuat, karena kelas kepercayaannya sama dengan `config.yaml`.
- **Dipotong** pada batas karakter dengan pembagian kepala 70% dan ekor 20% serta penanda pemotongan. Batas dasarnya 20.000 karakter dan membesar mengikuti jendela konteks model. Nilai `context_file_max_chars` di konfigurasi selalu menang.
- **Dimuat hanya saat sesi dimulai.** `AGENTS.md` di subdirektori ditemukan bertahap selama sesi oleh `agent/subdirectory_hints.py` dan ditempelkan ke **hasil tool**, bukan ke system prompt.

Hermes tidak pernah memuat `AGENTS.md` dari pohon instalasinya sendiri sebagai konteks
proyek, dan petunjuk subdirektori menolak path di luar direktori kerja.

## Potret memori

Memori lokal dan profil pengguna direkam ke tingkat volatile sebagai **potret beku**.
Penulisan di tengah sesi memperbarui file di disk tetapi tidak mengubah prompt yang
sudah dirakit, sampai jalur perakitan ulang berjalan. Rincian penyimpanannya ada di
[11-state-sesi-memori.md](11-state-sesi-memori.md).

## Indeks skill

Bila tool skill tersedia, prompt memuat indeks ringkas: nama dan deskripsi satu baris
per skill, dikelompokkan per kategori, dibungkus tag `<available_skills>`. Model diminta
memuat skill yang relevan dengan `skill_view(name)` sebelum bekerja. Isi lengkap skill
tidak pernah masuk system prompt. Rinciannya di [06-skills.md](06-skills.md).

## Petunjuk platform

`PLATFORM_HINTS` di `agent/prompt_builder.py` berisi panduan per permukaan, misalnya
"Anda berada di terminal, hindari Markdown". Platform dari plugin menyediakan
petunjuknya lewat registry platform. Administrator bisa menambah atau mengganti petunjuk
satu platform dari `config.yaml`:

```yaml
platform_hints:
  whatsapp:
    append: "Bila tabel berguna, pakai skill table_formatting."
  slack:
    replace: "Anda di Slack. Jawab ringkas dan hindari tabel lebar."
  telegram: "Utamakan pesan pendek."     # string polos berarti append
```

Hasilnya stabil byte untuk konfigurasi yang tetap, jadi tidak merusak cache.

## Lapisan yang hanya ada saat panggilan API

Ini sengaja **tidak** disimpan sebagai bagian system prompt yang di-cache:

- `ephemeral_system_prompt`,
- pesan prefill,
- lapisan konteks sesi dari gateway,
- hasil recall memori eksternal untuk giliran berjalan,
- konteks dari hook plugin `pre_llm_call`.

Konteks dari `pre_llm_call` ditempelkan ke **pesan pengguna giliran berjalan**, bukan
ke system prompt. Bila beberapa plugin mengembalikan konteks, bloknya digabung.

## Cache prompt Anthropic

`agent/prompt_caching.py` berisi fungsi murni tanpa ketergantungan pada `AIAgent`.
Tata letak bawaan memakai 4 titik `cache_control`:

1. prefiks sistem yang statis (tingkat stable),
2. akhir system prompt,
3. dan 4. dua pesan non-sistem terakhir.

Tanpa prefiks statis: satu titik di sistem ditambah tiga pesan terakhir. Semua penanda
memakai satu TTL, `5m` atau `1h`, dari `prompt_caching.cache_ttl` (bawaan `5m`).
Penanda dipasang pada **salinan permintaan**, tidak pernah pada pesan yang tersimpan.

Karena penanda statis membutuhkan pemisahan `[static, volatile]`, agent menyimpan
`_cached_system_prompt_static`. Saat sesi dipulihkan dari disk, hanya prompt utuh yang
tersimpan, sehingga `reconstruct_static_prefix()` merakit ulang tingkat stable dan
memakainya **hanya jika** prompt tersimpan benar-benar diawali byte yang sama.

## Kompresi konteks

Kompresi adalah satu-satunya pemutusan cache yang direstui. Sistemnya berlapis dua.

```text
Pesan masuk ──► Kebersihan sesi gateway     ambang 85% jendela konteks
                (sebelum agent, taksiran)   jaring pengaman sesi besar
                        │
                        ▼
                ContextCompressor agent     ambang bawaan 50%
                (dalam loop, token nyata)   pengelolaan konteks normal
```

### Mesin konteks yang dapat diganti

`agent/context_engine.py` mendefinisikan ABC `ContextEngine`. `ContextCompressor`
adalah implementasi bawaan. Plugin bisa menggantinya lewat `context.engine` di
konfigurasi. Hanya satu mesin yang aktif, dan mesin plugin tidak pernah aktif otomatis.

Method inti yang wajib ada:

```python
class ContextEngine(ABC):
    name: str
    # Keadaan token yang dibaca langsung oleh loop
    last_prompt_tokens: int; threshold_tokens: int; context_length: int; compression_count: int
    threshold_percent: float = 0.75; protect_first_n: int = 3; protect_last_n: int = 6

    def update_from_response(self, usage: dict) -> None: ...   # setelah tiap panggilan LLM
    def should_compress(self, prompt_tokens: int = None) -> bool: ...
    def compress(self, messages, current_tokens=None, focus_topic=None,
                 force=False, memory_context="") -> list[dict]: ...
```

Method opsional: `prune_tool_results_only()` (pangkas tanpa LLM), `select_context()`
(ganti konteks per permintaan), `on_session_start/end/reset()`, `get_tool_schemas()` dan
`handle_tool_call()` (mesin boleh menyediakan tool), `update_model()` (hitung ulang
ambang saat model berganti).

### Algoritma kompresor bawaan

1. **Pangkas hasil tool lama** tanpa memanggil LLM.
2. **Tentukan batas**: pertahankan `protect_first_n` pesan awal dan ekor terbaru. Pasangan panggilan tool dan hasilnya tidak pernah dipisah.
3. **Buat ringkasan terstruktur** dengan model `auxiliary.compression`.
4. Memori ditulis ke disk lebih dulu agar tidak ada yang hilang.
5. System prompt dirakit ulang.

Ringkasan memakai templat bagian tetap: *Historical Task Snapshot, Goal, Constraints &
Preferences, Completed Actions, Active State, Blocked, Key Decisions, Errors & Fixes,
Resolved Questions, Relevant Files, Critical Context*. Templat menuntut hal konkret:
path file, perintah, nomor baris, pesan error, dan melarang kredensial.

Ringkasan diberi **awalan serah-terima** (`SUMMARY_PREFIX`) yang menyatakan bahwa isi
itu hanya rujukan dari jendela konteks sebelumnya, bukan instruksi aktif; bahwa model
hanya menjawab pesan pengguna terbaru sesudah ringkasan; bahwa memori persisten tetap
berwenang; dan bahwa tool tetap aktif. Kalimat terakhir ditambahkan setelah terlihat
model berhenti memakai tool sesudah kompresi. Tanpa awalan semacam ini, model cenderung
melanjutkan tugas lama yang disebut di ringkasan.

### Kompresi di tempat

`compression.in_place` (bawaan `true`) menulis ulang daftar pesan dan system prompt
**tanpa mengganti id sesi**. Giliran sebelum kompresi diarsipkan lunak di bawah id yang
sama (`active=0`, `compacted=1`) dan tetap bisa dicari. Jalur lama membuat sesi anak
dengan `parent_session_id`; jalur itu menimbulkan banyak bug rotasi sesi.

### Penghitungan token

Setiap gerbang kompresi bertanya dulu ke **jangkar pemakaian** (`agent/usage_anchor.py`):
jumlah token prompt dan completion terakhir yang dilaporkan penyedia, ditambah taksiran
kasar **hanya** untuk pesan yang ditambahkan sesudahnya. Tanpa jangkar (permintaan
pertama), taksiran kasar yang melebihi ambang **menunggu satu permintaan** untuk bukti
dari penyedia, karena besar taksiran tidak membuktikan permintaan akan gagal.

### Pendinginan setelah gagal

Ringkasan yang gagal atau macet memasang pendinginan per sesi yang meningkat (60 detik,
300 detik, 900 detik) dan disimpan di `state.db`, supaya backend ringkasan yang rusak
tidak dipicu ulang tiap giliran. `/compress` manual melewati pendinginan. Kegagalan
berulang berakhir dengan ringkasan cadangan deterministik, tidak pernah dengan
pemangkasan di luar jalur resmi.

### Kompresi mikro

`compression.micro_compact` mati secara bawaan. Fitur ini melipat percakapan tertua ke
ringkasan bergulir setelah tiap giliran, tetapi setiap lintasan menulis ulang riwayat
terkirim dan memutus prefiks cache **setiap giliran**.

## Yang perlu ditiru persis

1. Tiga tingkat dengan urutan stable, context, volatile.
2. Prompt dirakit sekali per percakapan, disimpan, dan dipakai ulang byte demi byte.
3. Isi tengah percakapan menumpang pada pesan pengguna atau hasil tool.
4. Penanda cache hanya pada salinan permintaan.
5. Kompresi sebagai satu-satunya mutasi, dengan awalan serah-terima dan templat ringkasan terstruktur.
6. Test yang menegaskan invarian bentuk (prompt stabil byte, selang-seling peran), bukan potret teks prompt.

## Rujukan di Hermes

`agent/system_prompt.py`, `agent/prompt_builder.py`, `agent/prompt_caching.py`,
`agent/context_engine.py`, `agent/context_compressor.py`,
`agent/conversation_compression.py`, `agent/usage_anchor.py`,
`agent/subdirectory_hints.py`, `agent/surface_switch.py`,
`website/docs/developer-guide/prompt-assembly.md`,
`website/docs/developer-guide/context-compression-and-caching.md`.
