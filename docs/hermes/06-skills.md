# 06. Skills

Skill adalah cara Hermes menyimpan **pengetahuan prosedural**: alur kerja, perintah
khusus, jebakan yang pernah ditemui. Skill dimuat sesuai kebutuhan, bukan ditaruh
permanen di prompt. Inilah yang membuat inti tetap sempit: kemampuan baru cukup berupa
satu file Markdown, tanpa tool baru.

## Bentuk sebuah skill

Satu skill adalah satu folder dengan `SKILL.md` dan file pendukung opsional:

```text
skills/software-development/github/
├── SKILL.md
├── references/     dokumen rujukan yang dibaca bila perlu
├── scripts/        skrip siap pakai, supaya model tidak menulis ulang logika tiap kali
└── templates/      templat keluaran
```

`SKILL.md` terdiri dari frontmatter YAML dan badan Markdown:

```markdown
---
name: systematic-debugging
description: "4-phase root cause debugging: understand bugs before fixing."
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [debugging, troubleshooting]
    related_skills: [test-driven-development]
---

# Systematic Debugging
...
```

Field frontmatter:

| Field | Arti |
|---|---|
| `name` | Nama unik: huruf kecil dengan tanda hubung atau garis bawah, maksimum 64 karakter |
| `description` | Satu kalimat. Inilah yang tampil di indeks prompt |
| `version`, `author`, `license` | Metadata |
| `platforms` | Gerbang sistem operasi: `[macos]`, `[linux, macos]` |
| `metadata.hermes.tags` | Tag pencarian |
| `metadata.hermes.category` | Kategori bila berbeda dari folder induk |
| `metadata.hermes.related_skills` | Skill terkait |
| `metadata.hermes.config` | Pengaturan yang dibutuhkan skill, disimpan di `skills.config.<kunci>` dan disisipkan saat skill dimuat |

Format ini sejalan dengan standar terbuka Agent Skills, sehingga skill dari ekosistem
lain bisa dipakai.

## Dua permukaan di repo

- **`skills/`**: skill bawaan yang aktif sejak awal, per kategori (`software-development`, `research`, `devops`, `productivity`, dan seterusnya). 58 skill pada commit rujukan.
- **`optional-skills/`**: skill yang lebih berat atau ceruk, dikirim tetapi tidak aktif. Dipasang dengan `hermes skills install official/<kategori>/<skill>`. 152 skill pada commit rujukan.

Skill bawaan disalin ke `~/.hermes/skills/` oleh `tools/skills_sync.py`, dengan catatan
asal supaya perubahan pengguna tidak tertimpa saat pembaruan.

## Urutan pencarian skill

`agent/skill_utils.py::get_skill_search_roots()` adalah **satu-satunya urutan** yang
dipakai daftar skill, indeks prompt, slash command, `skill_view`, dan cron:

| Tingkat | Lokasi | Catatan |
|---|---|---|
| `TIER_PROJECT` | Folder skill di proyek | Hanya direktori yang dipercaya (`skills.trusted_project_dirs`) |
| `TIER_LOCAL` | `~/.hermes/skills/` | Skill bawaan hasil salin, hasil pasang, dan buatan agent |
| `TIER_CREATE_DIR` | `skills.create_dir` | Tempat alternatif untuk skill baru |
| `TIER_EXTERNAL` | `skills.external_dirs` | Misalnya `~/.agents/skills` atau folder tim |

Tingkat lebih atas menang untuk nama yang sama. Bila dua skill **berbeda** memakai nama
yang sama dalam satu tingkat, keduanya dianggap ambigu dan `skill_view` menolak memilih,
kecuali isinya terbukti identik. Ini mencegah skill jahat membayangi skill asli.

`skills.disabled` mematikan skill berdasarkan nama, bisa per platform.

## Pengungkapan bertahap

Hermes tidak pernah memasukkan isi skill ke system prompt. Yang masuk hanya **indeks**:

```text
## Skills
Before replying, scan the skills below. If a skill matches or is even partially relevant
to your task, you MUST load it with skill_view(name) and follow its instructions. ...

<available_skills>
  software-development: <deskripsi kategori>
    - code-review: Structured code review workflow
    - test-driven-development: TDD methodology
  research:
    - arxiv: Search and summarize arXiv papers
</available_skills>

Only proceed without loading a skill if genuinely none are relevant to the task.
```

Tiga tahap:

1. **Indeks** di system prompt: nama dan deskripsi, dikelompokkan per kategori. Deskripsi kategori datang dari `DESCRIPTION.md` di folder kategori.
2. **`skill_view(name)`** memuat `SKILL.md` lengkap, ditambah kamus `linked_files` berisi file pendukung.
3. **`skill_view(name, file_path=...)`** memuat satu file pendukung.

Indeks dirakit oleh `agent/prompt_builder.py::build_skills_system_prompt()` dan di-cache
dengan kunci yang memuat platform, karena daftar skill yang dimatikan bisa berbeda per
platform. Dalam konteks coding, kategori di luar coding diturunkan menjadi satu baris
nama saja. **Tidak ada skill yang pernah disembunyikan**: skill buatan agent adalah
memori proyek model, dan model tidak akan menemukannya lagi bila hilang dari indeks.

Karena deskripsi tampil di setiap sesi, Hermes membatasinya 60 karakter, satu kalimat,
tanpa kata pemasaran.

## Tool skill

| Tool | Guna |
|---|---|
| `skills_list(category?)` | Daftar nama dan deskripsi |
| `skill_view(name, file_path?)` | Memuat skill atau file pendukungnya. Melihat ulang skill yang sama dan belum berubah dalam satu sesi mengembalikan penanda singkat |
| `skill_manage(operations=[...])` | Membuat dan memelihara skill |

Operasi `skill_manage`, tiap butir menyebut `name` skill sasarannya:

| `action` | Field | Arti |
|---|---|---|
| `create` | `content`, `category?` | `SKILL.md` lengkap |
| `patch` | `old_string`, `new_string`, `replace_all?`, `file_path?` | Suntingan bertarget |
| `patch` | `content` | Tulis ulang seluruh `SKILL.md` (pilihan terakhir) |
| `write_file` | `file_path`, `file_content` | File pendukung |
| `remove_file` | `file_path` | Hapus file pendukung |
| `delete` | | Hapus skill |

Satu panggilan memuat **larik operasi**. Skemanya memakai cabang `anyOf` per aksi, bukan
satu objek gabungan, karena model kecil sering mengisi field aksi lain dan seluruh batch
gagal.

Tiap skill membawa asal-usul (`created_by: "agent"`, bawaan, atau hasil pasang).
`skills.write_approval` menahan penulisan skill oleh agent sampai disetujui pengguna.
`skills.guard_agent_created` memindai skill buatan agent.

## Lingkaran belajar

Inilah klaim utama Hermes, "agent yang tumbuh bersama Anda":

1. Panduan di system prompt meminta model menyimpan prosedur yang dipelajari dari tugas sebagai skill, dan menyimpan fakta yang berlaku di semua sesi sebagai memori.
2. Setelah tugas sulit, model menawarkan menyimpannya sebagai skill.
3. Bila skill yang dimuat ternyata kurang langkah atau salah perintah, model memperbaikinya dengan `skill_manage(patch)` sebelum selesai.
4. **Peninjauan latar** (`agent/background_review.py`) berjalan setelah giliran: agent cabang meninjau percakapan dan menulis pelajaran ke memori atau skill. Slash command `/refine` memicunya secara manual.
5. `/learn <sumber>` membuat skill dari direktori, URL, atau percakapan berjalan.

## Skill sebagai slash command

`agent/skill_commands.py::scan_skill_commands()` memindai folder skill dan membuat satu
slash command per skill. `/nama-skill instruksi` membangun **pesan pengguna** berisi:

```text
<catatan aktivasi>

<isi SKILL.md setelah praproses>

[Skill directory: /path/absolut/skill]
[This skill has supporting files ...]
- references/x.md

<instruksi pengguna>
```

Pesan ini dikirim sebagai giliran biasa. Ia **tidak pernah** masuk system prompt, demi
cache. Bagian sebelum instruksi pengguna didaftarkan sebagai prefiks stabil agar
perencana cache bisa memasang titik putus di sana.

Beberapa skill bisa ditumpuk dalam satu perintah. `skills.auto_load` memuat skill
tertentu ke tingkat stable setiap sesi. Flag CLI `-s/--skills` memuat skill di awal.

## Hub skill

`hermes skills` dan `/skills` mengelola skill dari sumber luar:

```text
hermes skills search <kueri>
hermes skills browse
hermes skills inspect <id>
hermes skills install <id>
hermes skills uninstall <nama>
hermes skills list | list-modified | diff
hermes skills check | update | audit
hermes skills trust | untrust | tap | publish
```

Sumber didefinisikan sebagai subkelas ABC `SkillSource` (`tools/skills_hub_models.py`):
`OptionalSkillSource` untuk optional-skills di repo, `GitHubSource` untuk repo apa pun,
`UrlSource` untuk URL langsung, dan beberapa indeks komunitas (`ClawHubSource`,
`SkillsShSource`, `LobeHubSource`, dan lainnya). Menambah sumber berarti menambah
subkelas, bukan `elif`.

Skill dari luar dipindai `tools/skills_guard.py` sebelum dipasang. Pemasangan mengubah
indeks di system prompt, sehingga secara bawaan **berlaku di sesi berikutnya**;
`/skills install --now` adalah pilihan sadar yang memutus cache.

## Kurator

Pemeliharaan latar yang melacak pemakaian skill buatan agent dan mengarsipkan yang basi.

- Inti: `agent/curator.py` (lintasan tinjau, transisi otomatis, prompt tinjauan LLM) dan `agent/curator_backup.py` (potret tar.gz sebelum jalan).
- Telemetri: `tools/skill_usage.py` menyimpan `~/.hermes/skills/.usage.json` berisi `use_count`, `view_count`, `patch_count`, `last_activity_at`, `state` (`active`, `stale`, `archived`), `pinned`.
- CLI: `hermes curator status|run|pause|resume|pin|unpin|archive|restore|prune|backup|rollback`.
- Konfigurasi `curator:`: `enabled`, `interval_hours` (bawaan seminggu), `min_idle_hours`, `stale_after_days` (14), `archive_after_days` (30).

Invarian kurator:

- Hanya menyentuh skill `created_by: "agent"`. Skill bawaan dan hasil pasang di luar jangkauan.
- **Tidak pernah menghapus.** Arsip adalah tindakan maksimum, dan arsip di `~/.hermes/skills/.archive/` bisa dipulihkan.
- Skill yang disematkan (`pinned`) kebal dari semua transisi otomatis.

## Standar penulisan skill

Hermes menegakkan ini lewat test (`tests/skills/test_authoring_standards.py`):

1. `description` paling banyak 60 karakter, satu kalimat, diakhiri titik, menyebut kemampuan dan bukan implementasi.
2. Prosa merujuk **tool Hermes** dalam backtick (`terminal`, `read_file`, `patch`, `search_files`), bukan utilitas shell yang sudah dibungkus: `grep` menjadi `search_files`, `cat` menjadi `read_file`, `sed` menjadi `patch`.
3. Gerbang `platforms:` diaudit terhadap impor skrip. Primitif khusus POSIX mewajibkan deklarasi platform.
4. Urutan bagian: judul, pengantar 2 sampai 3 kalimat, `## When to Use`, `## Prerequisites`, `## How to Run`, `## Quick Reference`, `## Procedure`, `## Pitfalls`, `## Verification`. Sekitar 200 baris untuk skill rumit, 100 untuk yang sederhana.
5. Logika tak-sepele dikirim sebagai skrip di `scripts/`, bukan ditulis ulang model tiap kali.
6. Test per skill tanpa jaringan.

## Yang perlu ditiru persis

1. `SKILL.md` dengan frontmatter, kompatibel dengan standar Agent Skills.
2. Pengungkapan bertahap: indeks di prompt, isi lewat `skill_view`.
3. Satu urutan pencarian yang dipakai semua konsumen.
4. Skill sebagai slash command yang disisipkan sebagai pesan pengguna.
5. `skill_manage` dengan larik operasi dan skema per aksi.
6. Perubahan indeks berlaku di sesi berikutnya secara bawaan.
7. Kurator yang hanya mengarsipkan, tidak pernah menghapus.

## Rujukan di Hermes

`skills/`, `optional-skills/`, `agent/skill_utils.py`, `agent/skill_commands.py`,
`agent/prompt_builder.py` (fungsi `build_skills_system_prompt`), `tools/skills_tool.py`,
`tools/skill_manager_tool.py`, `tools/skills_hub*.py`, `tools/skills_guard.py`,
`tools/skills_sync.py`, `tools/skill_usage.py`, `agent/curator.py`,
`agent/background_review.py`, `skills/AGENTS.md`,
`website/docs/developer-guide/creating-skills.md`.
