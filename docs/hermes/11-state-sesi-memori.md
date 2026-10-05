# 11. Penyimpanan Sesi dan Memori

## Basis data sesi

Hermes menyimpan semua sesi dan pesan di **satu berkas SQLite** per profil,
`~/.hermes/state.db`, dengan pencarian teks penuh lewat **FTS5**.

`hermes_state.py` adalah fasad `SessionDB`. Isinya dipecah ke 21 saudara
`hermes_state_*.py`: `schema`, `sessions`, `messages`, `search`, `fts`, `compression`,
`repair`, `wal`, `maintenance`, `usage`, `titles`, dan seterusnya.

### Tabel inti

Disarikan dari `SCHEMA_SQL` di `hermes_state_common.py`:

```sql
CREATE TABLE sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,              -- "cli", "tui", "desktop", "telegram", "cron", "oneshot", ...
    user_id TEXT, session_key TEXT,    -- identitas perutean gateway
    chat_id TEXT, chat_type TEXT, thread_id TEXT, display_name TEXT, origin_json TEXT,
    model TEXT, model_config TEXT,
    system_prompt TEXT,                -- prompt yang dirakit, disimpan untuk dipakai ulang
    system_prompt_hash TEXT,
    parent_session_id TEXT REFERENCES sessions(id),   -- silsilah
    started_at REAL NOT NULL, ended_at REAL, end_reason TEXT,
    message_count INTEGER DEFAULT 0, tool_call_count INTEGER DEFAULT 0,
    input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0,
    cache_read_tokens INTEGER DEFAULT 0, cache_write_tokens INTEGER DEFAULT 0,
    reasoning_tokens INTEGER DEFAULT 0,
    estimated_cost_usd REAL, actual_cost_usd REAL,
    cwd TEXT, git_branch TEXT, git_repo_root TEXT,
    title TEXT, title_source TEXT,
    last_activity_at REAL,
    profile_name TEXT,
    archived INTEGER NOT NULL DEFAULT 0, pinned INTEGER NOT NULL DEFAULT 0,
    hidden INTEGER NOT NULL DEFAULT 0,
    tool_names TEXT
    -- ditambah kolom keadaan kompresi, serah-terima, dan penagihan
);

CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,                -- system | user | assistant | tool
    content TEXT,
    tool_call_id TEXT, tool_calls TEXT, tool_name TEXT,   -- tool_calls berupa JSON
    timestamp REAL NOT NULL,
    token_count INTEGER, finish_reason TEXT,
    reasoning TEXT, reasoning_content TEXT, reasoning_details TEXT,
    codex_reasoning_items TEXT, codex_message_items TEXT,
    active INTEGER NOT NULL DEFAULT 1,       -- 0 setelah dikompres
    compacted INTEGER NOT NULL DEFAULT 0,    -- 1 untuk giliran yang diarsipkan lunak
    api_content TEXT,                        -- isi yang benar-benar dikirim bila berbeda dari yang ditampilkan
    display_kind TEXT, display_metadata TEXT,
    message_uid TEXT
);

CREATE TABLE schema_version (version INTEGER NOT NULL);
CREATE TABLE state_meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE system_prompts (hash TEXT PRIMARY KEY, prompt TEXT NOT NULL);
```

Tabel pendukung: `session_model_usage` (pemakaian per model per sesi),
`gateway_routing`, `conversation_generations`, `gateway_heartbeats`,
`compression_locks`, `session_turn_leases`, `async_delegations`.

Indeks utama: `sessions(source)`, `sessions(parent_session_id)`,
`sessions(started_at DESC)`, `messages(session_id, timestamp)`,
`messages(session_id, id)`, indeks parsial untuk pesan asisten ber-tool, dan indeks unik
pada `sessions(title)` untuk judul yang tidak kosong.

### Pencarian teks penuh

`hermes_state_fts.py` membuat tabel virtual FTS5 **external-content** di atas `messages`,
mengindeks tiga kolom: `content`, `tool_name`, `tool_calls`. Trigger `AFTER INSERT`,
`AFTER DELETE`, dan `AFTER UPDATE` menjaganya tetap sinkron. Ada varian trigram dan
varian CJK untuk bahasa tanpa spasi. Pencarian juga punya jalur cadangan berbasis `LIKE`
(`hermes_state_search.py`), dan skema memeriksa lebih dulu apakah build SQLite mendukung FTS5.

Tool `session_search` memakainya untuk mengingat percakapan lama: cari dengan `query`,
atau gulir di dalam satu sesi dengan `session_id` dan `around_message_id`.

### Kontrak yang dijaga

- **Hanya menambah.** Pesan ditambahkan seiring diproduksi; riwayat tidak ditulis ulang, kecuali oleh kompresi.
- **Simpan sebelum berefek.** Pesan asisten ber-`tool_calls` ditulis sebelum tool dijalankan (lihat [02-agent-loop.md](02-agent-loop.md)).
- **Pesan pengguna tahan lama saat dikirim.** Di TUI dan Desktop, `prompt.submit` menulis baris sesi dan baris pengguna sebelum agent dibangun. Macet atau paksa-keluar saat pembangunan pertama tetap meninggalkan transkrip yang bisa dilanjutkan.
- **Baris sesi dibuat malas** pada giliran pertama. Kegagalan sementara (kunci SQLite) dicoba lagi di giliran berikutnya.
- **Nama profil disimpan eksplisit**, termasuk `"default"`. NULL berarti tanpa pemilik.
- **System prompt disimpan di baris sesi**, sehingga proses baru memakai ulang byte yang sama dan cache penyedia tetap kena.
- **Mode WAL** dengan penanganan kontensi tulis, karena banyak proses (CLI, gateway, backend desktop) berbagi satu berkas.
- **Sewa giliran** (`session_turn_leases`): hanya satu giliran yang berjalan per percakapan pada satu waktu.

### Silsilah sesi

Sesi bisa punya induk (`parent_session_id`):

- `/branch` membuat cabang dari sesi berjalan.
- Subagent membuat sesi anak.
- Kompresi jalur lama membuat sesi anak; kompresi di tempat (bawaan) tidak, melainkan mengarsipkan lunak giliran lama dengan `active=0, compacted=1` di bawah id yang sama.

`/resume <judul atau id>` dan `hermes chat --resume` melanjutkan sesi. `-c` melanjutkan
yang terakhir.

### Sumber sesi

Kolom `source` membedakan asal: `cli`, `oneshot` (jalan `-q` tanpa interaksi, supaya
tidak muncul di pemilih sesi), `tui`, `desktop`, nama platform gateway, `cron`. Pemilih
sesi menyaring berdasarkan ini.

### Pemeliharaan

`hermes sessions list | export | prune | archive | repair | optimize | rename | pin |
browse | import`. Pembersihan otomatis diatur lewat `sessions.auto_prune` dan
`sessions.retention_days`. Ada juga pemulihan basis data rusak
(`hermes_state_repair.py`).

## Memori bawaan

Memori Hermes adalah **dua berkas teks yang dikurasi agent**, bukan basis data vektor.

```text
~/.hermes/memories/
├── MEMORY.md     catatan pribadi agent: fakta lingkungan, konvensi, pelajaran
└── USER.md       profil pengguna: nama, preferensi, gaya kerja
```

`tools/memory_tool_store.py` berisi kelas `MemoryStore`.

### Bentuk dan batas

- Tiap berkas adalah daftar **entri** yang dipisah `\n§\n`.
- Batas karakter keras: `memory.memory_char_limit` (bawaan 2.200, sekitar 800 token) dan `memory.user_char_limit` (bawaan 1.375, sekitar 500 token).
- Batas itulah yang memaksa kurasi. Bila penuh, agent harus merapatkan atau mengganti entri, bukan menumpuk.

### Tool `memory`

```json
{"target": "memory", "operations": [
  {"action": "add", "content": "Pengguna memakai pnpm, bukan npm"},
  {"action": "replace", "old_text": "Python 3.11", "new_text": "Python 3.13"},
  {"action": "remove", "old_text": "catatan usang"}
]}
```

- `target`: `memory` atau `user`.
- Satu panggilan memuat **larik operasi** yang diterapkan sebagai satu batch.
- `old_text` mencari entri lewat potongan teks yang unik. Bila cocok dengan lebih dari satu entri, operasi ditolak.
- Respons sukses bersifat **terminal dan tidak memuat daftar entri**. Mengembalikan daftar mengundang model "mencari lagi yang bisa diperbaiki" dan mengulang operasi yang sama.
- Isi dipindai terhadap pola injeksi dan eksfiltrasi sebelum ditulis, karena memori masuk system prompt dan entri beracun akan bertahan lintas sesi.
- Berkas dikunci saat ditulis, dan penyimpangan dari luar (pengguna menyunting berkas selagi sesi berjalan) dideteksi.

### Potret beku

`MemoryStore.load_from_disk()` merekam potret saat sesi dimulai.
`format_for_system_prompt(target)` mengembalikan **potret itu**, bukan keadaan hidup.
Penulisan di tengah sesi mengubah disk tetapi tidak mengubah prompt, sehingga prefiks
cache selamat. Potret diperbarui pada sesi baru atau setelah kompresi.

Blok di system prompt:

```text
══════════════════════════════════════════════
MEMORY (your personal notes) [63% — 1,386/2,200 chars]
══════════════════════════════════════════════
entri pertama
§
entri kedua
```

Indikator pemakaian di judul memberi tahu model seberapa penuh memorinya.

### Dorongan berkala

`memory.nudge_interval` (bawaan 10 giliran): agent diingatkan secara berkala untuk
menyimpan pengetahuan yang layak. Ditambah peninjauan latar setelah giliran, inilah
"lingkaran belajar" Hermes.

### Pembagian peran memori dan skill

Panduan di system prompt memisahkan keduanya dengan tegas:

- **Skill**: prosedur yang dipelajari dari tugas, jebakan, dan preferensi khusus tugas.
- **Memori**: pengecualian sempit untuk fakta yang berlaku di **setiap** sesi apa pun tugasnya.

Bila `skill_manage` tidak tersedia, cakupan memori **tidak** melebar.

`memory.write_approval` menahan penulisan memori sampai disetujui pengguna, ditinjau
lewat `/memory pending | approve | reject`.

## Penyedia memori eksternal

Selain berkas bawaan, **satu** penyedia eksternal bisa aktif lewat `memory.provider`.
`agent/memory_provider.py` mendefinisikan ABC `MemoryProvider`, dan
`agent/memory_manager.py` mengorkestrasinya.

```python
class MemoryProvider(ABC):
    name: str                                         # properti abstrak
    def is_available(self) -> bool                    # cek konfigurasi saja, tanpa jaringan
    def initialize(self, session_id, **kwargs)        # kwargs memuat hermes_home, platform
    def get_tool_schemas(self) -> list[dict]

    # Opsional
    def system_prompt_block(self) -> str              # teks STATIS untuk system prompt
    def prefetch(self, query, *, session_id="") -> str        # konteks recall untuk giliran ini
    def queue_prefetch(self, query, *, session_id="")         # recall latar untuk giliran berikutnya
    def sync_turn(self, user_content, assistant_content, *, session_id="", messages=None)
    def handle_tool_call(self, tool_name, args, **kwargs) -> str
    def on_turn_start(...), on_session_end(messages), on_session_switch(...)
    def on_pre_compress(messages) -> str              # wawasan dari pesan yang akan dikompres
    def on_delegation(task, result, ...), on_memory_write(action, target, content, ...)
    def get_config_schema(), save_config(values, hermes_home), shutdown()
```

Aturan penting:

- `prefetch()` harus **cepat**: recall dilakukan di latar dan hasil yang di-cache dikembalikan.
- Hasil recall ditempelkan ke **pesan pengguna giliran berjalan**, tidak ke system prompt.
- Prompt remeh ("ya", "lanjut", "terima kasih") melewati recall (`is_trivial_prompt`).
- Thread latar penyedia dimulai lewat `spawn_context_thread`, yang menyalin ContextVar. Thread polos akan mendarat di profil default.
- Penyedia tidak pernah menyimpan `hermes_home` dari `initialize()` sebagai "satu-satunya" home, karena satu proses bisa melayani beberapa profil.
- Sesi cron melewati memori (`skip_memory=True`).
- Penyiapan lewat `hermes memory setup`, yang memanggil `provider.post_setup(hermes_home, config)`.

Hermes sudah menutup folder `plugins/memory/` untuk penyedia baru. Backend baru dikirim
sebagai repo mandiri yang mengimplementasikan ABC yang sama.

## Yang perlu ditiru persis

1. Satu berkas SQLite per profil dengan FTS5 external-content dan trigger.
2. Riwayat hanya-tambah; pesan asisten disimpan sebelum tool berjalan.
3. System prompt disimpan di baris sesi.
4. Memori sebagai berkas teks berbatas karakter, dengan potret beku di prompt.
5. Tool memori dengan larik operasi dan respons sukses tanpa daftar entri.
6. Pemindaian isi memori sebelum ditulis.
7. ABC penyedia memori dengan recall yang menumpang pesan pengguna.

## Rujukan di Hermes

`hermes_state.py`, `hermes_state_common.py`, `hermes_state_schema.py`,
`hermes_state_sessions.py`, `hermes_state_messages.py`, `hermes_state_search.py`,
`hermes_state_fts.py`, `agent/session_persistence.py`, `tools/session_search_tool.py`,
`tools/memory_tool.py`, `tools/memory_tool_store.py`, `agent/memory_provider.py`,
`agent/memory_manager.py`, `plugins/memory/`,
`website/docs/developer-guide/session-storage.md`,
`website/docs/developer-guide/memory-provider-plugin.md`.
