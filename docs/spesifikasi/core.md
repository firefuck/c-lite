# Spesifikasi: core

| | |
|---|---|
| Kode | `src/clite/core/` |
| Tes | `tests/core/` |
| Lapisan | 0. Tidak mengimpor apa pun dari paket lain di `clite` |
| Bedah Hermes | [08-cli](../hermes/08-cli.md) (konfigurasi, profil), [13-aturan-rekayasa](../hermes/13-aturan-rekayasa.md) |

## Tanggung jawab

Hal-hal yang dibutuhkan semua lapisan: nama produk, lokasi home, konfigurasi, rahasia, profil,
logging, penulisan file atomik, redaksi, dan pemindaian teks yang akan masuk ke prompt.

## Bagian-bagian

| File | Isi |
|---|---|
| `brand.py` | Semua string nama produk. `scripts/rename_project.py` membaca nama dari sini |
| `constants.py` | Resolusi home yang sadar profil, lokasi file baku |
| `config.py`, `config_defaults.py` | `config.yaml`: baca, tulis, migrasi; `DEFAULT_CONFIG` |
| `env.py` | `.env`: rahasia, cakupan rahasia per profil |
| `profiles.py` | Profil: home terpisah penuh |
| `logging.py` | Log ke file di `<home>/logs` |
| `io.py` | `atomic_write_text`, `atomic_write_json`, `read_json` |
| `threads.py` | `start_thread`: thread yang membawa konteks pemanggil (home, cakupan rahasia) |
| `redact.py` | Menghapus kredensial dari teks |
| `threats.py` | Memindai teks yang akan disuntikkan ke system prompt |
| `errors.py` | `CliteError` dan turunannya |

## Isi home

`~/.clite` (atau `CLITE_HOME`, atau `~/.clite/profiles/<nama>` untuk profil):

| Path | Isi | Ditulis oleh |
|---|---|---|
| `config.yaml` | Pengaturan | `core.config` |
| `.env` | Rahasia (izin 0600) | `core.env` |
| `SOUL.md` | Identitas agent, mengganti identitas bawaan | Pengguna |
| `state.db` | Sesi dan pesan (SQLite + FTS5) | `state` |
| `memories/MEMORY.md`, `memories/USER.md` | Memori bawaan | `agent.memory` |
| `skills/` | Skill lokal, `.usage.json`, `.archive/`, `.hub/lock.json` | `skills` |
| `plugins/`, `plugins/model-providers/` | Plugin dan profil provider milik pengguna | Pengguna, `plugins` |
| `shell-hooks-allowlist.json` | Shell hook yang disetujui | `plugins.shell_hooks` |
| `cron/jobs.json`, `cron/output/<job>/` | Job terjadwal dan keluarannya | `cron` |
| `gateway/pairing.json`, `gateway/sessions.json` | Pairing dan peta sesi gateway | `gateway` |
| `cache/models/<provider>.json` | Katalog model | `providers.models` |
| `logs/agent.log`, `logs/errors.log` | Log | `core.logging` |
| `skins/<nama>.yaml` | Tema CLI | Pengguna |
| `.cli_history` | Riwayat input CLI | `cli.repl` |
| `profiles/<nama>/` | Home profil lain (hanya di root default) | `core.profiles` |
| `active_profile` | Profil lengket (hanya di root default) | `core.profiles` |

## Kontrak

**Home**
- Urutan resolusi: override lokal-konteks (`home_scope`), lalu `CLITE_HOME`, lalu default.
- Tidak ada kode yang menulis `~/.clite` secara harfiah. Path didapat dari `get_home()` dan
  kawan-kawannya pada saat dipanggil, tidak pernah disimpan di konstanta tingkat modul: satu
  proses bisa melayani beberapa profil.
- `home_key()` memberi kunci stabil untuk cache dan registry per profil.
- Thread baru tidak mewarisi home yang diikat dengan `home_scope`. Thread yang bekerja untuk
  sebuah sesi dimulai dengan `core.threads.start_thread`, yang menyalin konteks pemanggil.

**Konfigurasi**
- `load_config()` mengembalikan file pengguna yang digabung dalam di atas `DEFAULT_CONFIG`,
  setelah migrasi dan ekspansi `${VAR}`. Hasilnya di-cache per home terhadap mtime dan ukuran
  file, dan setiap pemanggil mendapat salinannya sendiri.
- File yang rusak melempar `ConfigError` dan **tidak pernah ditimpa**.
- Semua penulisan lewat `config_set`, `config_unset`, atau `atomic_config_update`.
- Kunci baru cukup ditambahkan ke `DEFAULT_CONFIG`. `_config_version` hanya dinaikkan untuk
  mengubah file yang sudah ada (ganti nama kunci, ubah struktur), dengan fungsi di
  `MIGRATIONS`.
- **Setiap kunci punya pembaca.** Dijaga `tests/test_architecture.py`.
- Bentuk pendek `model: nama-model` diangkat menjadi `model: {default: nama-model}`.

**Rahasia**
- Rahasia hanya di `<home>/.env`. Pengaturan perilaku tidak pernah di sana.
- Kode membaca rahasia lewat `get_secret`, bukan `os.getenv`. `secret_scope` mengikat rahasia
  satu profil ke aktivitas yang sedang berjalan.
- `.env` profil mengalahkan `export` basi di shell.
- `save_secret` mengganti di tempat dan membatasi izin file.

**Profil**
- Profil adalah home terpisah penuh: config, rahasia, memori, sesi, skill, plugin sendiri.
  Tidak ada pewarisan hidup dari profil default. `clone` menyalin sekali saat dibuat, dan
  tidak pernah menyalin rahasia.
- `-p/--profile` diproses sebelum apa pun membaca home. Profil yang tidak ada adalah galat,
  bukan dibuat diam-diam.

**Logging**
- Log ke file, tidak pernah ke stdout. Pada transport stdio, stdout adalah kawat protokol.

**Redaksi dan pemindaian**
- `secret_names()` adalah daftar variabel yang dikenal sebagai kredensial: setiap nama dari
  `.env`, setiap nama yang didaftarkan provider atau platform (`register_secret`), dan varian
  bernomornya (`NAMA_2` sampai `NAMA_9`).
- `redact` mengganti nilai persis setiap kredensial yang dikenal, lalu pola kunci yang dikenal.
- `scan_text` sengaja spesifik: positif palsu akan membuang file milik pengguna tanpa suara.
  Yang kena diblokir dengan alasan, tidak dibersihkan lalu dilanjutkan.

## Status fitur

| Fitur | Status | Catatan |
|---|---|---|
| Home, profil, profil lengket | ✅ | |
| Config: baca, tulis, migrasi, ekspansi env | ✅ | |
| Penulis config yang mempertahankan komentar | ⬜ | PyYAML menulis ulang file tanpa komentar: F1-T6 |
| Rahasia, cakupan rahasia | ✅ | |
| Logging berputar | ✅ | |
| Redaksi, pemindaian ancaman | ✅ | Daftar pola pendek; Hermes jauh lebih luas (`agent/redact.py`) |
| Path Windows (`%LOCALAPPDATA%`) | 🟡 | Kodenya ada, belum pernah dijalankan di Windows: F1-T5 |
| Validasi skema config | ⬜ | Nilai bertipe salah baru ketahuan di pembacanya |

## Celah yang diketahui

- Tidak ada validasi tipe untuk `config.yaml`. `clite doctor` hanya memeriksa bahwa file bisa
  diparse.
- Cache config memakai mtime dan ukuran. Dua penulisan berukuran sama dalam satu tik jam bisa
  terlewat (hanya terlihat di tes; `reset_config_cache()` tersedia).
