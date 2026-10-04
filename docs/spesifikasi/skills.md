# Spesifikasi: skills

| | |
|---|---|
| Kode | `src/clite/skills/`, skill bawaan di `src/clite/bundled/skills/` |
| Tes | `tests/skills/` |
| Lapisan | 2. Boleh mengimpor `core` dan `plugins.hooks` |
| Bedah Hermes | [06-skills](../hermes/06-skills.md) |

## Tanggung jawab

Skill adalah dokumen prosedur (`SKILL.md`) yang dimuat model hanya ketika dibutuhkan. Paket
ini menemukan skill di beberapa tingkat, memvalidasinya, membuat indeks ringkas untuk system
prompt, menulis dan memperbaikinya (memori prosedural agent), memasangnya dari luar, dan
mengarsipkan yang tidak terpakai.

Tool yang menghadap model (`skills_list`, `skill_view`, `skill_manage`) ada di
`tools/builtin/skills.py`, bukan di sini.

## Bagian-bagian

| File | Isi |
|---|---|
| `frontmatter.py` | Parse dan validasi `SKILL.md`, `SkillMeta` |
| `catalog.py` | Penemuan lintas tingkat, `Skill`, file pendukung |
| `index.py` | Indeks untuk system prompt, aktivasi bersyarat |
| `manager.py` | Tulis: buat, patch, tulis ulang, hapus, file pendukung |
| `commands.py` | Skill sebagai slash command |
| `hub.py` | Pemasangan dari sumber luar (`LocalDirSource`, `GitHubSource`) |
| `usage.py` | Catatan siapa pembuat skill dan seberapa sering dipakai |
| `curator.py` | Pengarsipan skill buatan agent yang basi |

## Format

Mengikuti konvensi agentskills.io, sehingga skill yang ditulis untuk agent lain bisa dimuat
tanpa diubah. Bidang khusus agent dibaca dari `metadata.clite` dan `metadata.hermes`.

```markdown
---
name: nama-skill              # huruf kecil, harus sama dengan nama direktori
description: Apa gunanya dan kapan dipakai.
version: 1.0.0
platforms: [linux, macos]     # opsional
metadata:
  clite:
    category: software-development
    requires_toolsets: [terminal]       # tampil hanya bila toolset ini ada
    fallback_for_tools: [web_search]    # tampil hanya bila tool ini TIDAK ada
---

# Isi instruksi
```

File pendukung berada di `references/`, `templates/`, `scripts/`, `assets/` di dalam direktori
skill.

## Kontrak

**Penemuan**
- Tingkat, yang pertama menang bila nama bentrok: proyek (`<root proyek>/.clite/skills`),
  lokal (`<home>/skills`), eksternal (`skills.external_dirs` dan direktori yang didaftarkan
  plugin), bawaan (di dalam paket).
- Tata letak `<root>/<nama>/SKILL.md` dan `<root>/<kategori>/<nama>/SKILL.md` sama-sama
  dikenali.
- Skill yang tidak valid dilewati dengan alasan di log. Nama direktori harus sama dengan nama
  skill.
- Penemuan tidak di-cache: selalu membaca disk.
- `skills.disabled` dan `platforms` menyaring hasil.

**Indeks**
- Hanya nama dan deskripsi yang masuk system prompt (pengungkapan bertahap), dikelompokkan per
  kategori, dengan batas ukuran total.
- Indeks hanya dibuat bila sesi punya tool `skill_view`.
- Aktivasi bersyarat: `requires_*` dan `fallback_for_*` terhadap tool dan toolset sesi.

**Tulis**
- Hanya tingkat lokal yang bisa ditulis. Menyunting skill dari tingkat lain menyalinnya ke
  tingkat lokal lebih dulu (copy-on-write), jadi pembaruan paket tidak menimpa suntingan.
- Setiap tulisan divalidasi (frontmatter, nama, ukuran), dipindai (`core.threats`), dan
  ditulis secara atomik. Tulisan yang akan merusak skill ditolak dan file lama tetap utuh.
- File pendukung hanya boleh berada di empat direktori yang diizinkan. Path yang keluar dari
  direktori skill ditolak.
- Setiap perubahan memicu hook `on_skill_lifecycle`.

**Slash command**
- `/<nama-skill> [instruksi]` mengirim isi skill sebagai **pesan pengguna**. System prompt
  tidak disentuh.

**Pemasangan**
- Semua sumber melewati jalur yang sama: validasi `SKILL.md`, pindai setiap file teks, tulis ke
  tingkat lokal. Tidak ada yang dieksekusi.
- Skill yang kena pemindaian ditolak kecuali dipaksa.

**Kurator**
- Hanya menyentuh skill yang dibuat agent. Skill bawaan dan skill yang ditulis atau dipasang
  pengguna tidak pernah menjadi kandidat.
- Mengarsipkan ke `<home>/skills/.archive/`, tidak pernah menghapus.

## Status fitur

| Fitur | Status | Catatan |
|---|---|---|
| Format, penemuan bertingkat, indeks | ✅ | |
| `skill_manage` (memori prosedural) | ✅ | |
| Skill sebagai slash command | ✅ | |
| Pasang dari direktori lokal | ✅ | |
| Pasang dari GitHub (`GitHubSource`) | ⬜ belum diverifikasi | Kode ada, belum pernah diuji ke jaringan: F1-T4 |
| Kurator | ✅ | Dijalankan manual (`clite skills curate`). Penjadwalan otomatis: F2-T12 |
| Skill bawaan | 🟡 | 4 skill. Hermes mengirim 58: F6-T2 |
| Hub: indeks registry, pencarian, pembaruan | ⬜ | F6-T1 |
| Pemindai keamanan skill yang lebih dalam | ⬜ | Hermes: `tools/skills_guard.py`. F6-T1 |
| Variabel lingkungan per skill (`env_passthrough`) | 🟡 | Dibaca dari frontmatter, belum diteruskan ke terminal |

## Yang sengaja berbeda dari Hermes

- **Skill bawaan dibaca di tempat.** Hermes menyalin skill bawaan ke home saat pemasangan dan
  menyinkronkannya dengan manifest. Di sini tingkat bawaan hanya-baca dan suntingan memakai
  copy-on-write.
- **Tanpa cache indeks di disk.** Hermes menyimpan cache indeks. Di sini penemuan selalu
  membaca disk; sesi hanya membangun indeks sekali karena prompt dibangun sekali.

## Celah yang diketahui

- `env_passthrough` di frontmatter belum punya efek.
- Tidak ada pencarian skill di registry daring; `SkillSource.search` mengembalikan daftar
  kosong.
