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
| `hub.py` | Pemasangan dari sumber luar (`LocalDirSource`, `GitHubSource`), indeks, tap, pembaruan |
| `scanner.py` | Pemindaian dalam untuk bundel dari luar |
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
- Skill dari tingkat proyek dan eksternal dipindai (`core.threats`) setiap kali ditemukan, dan
  yang kena dilewati. Skill semacam itu datang bersama file orang lain (repositori hasil
  clone), deskripsinya masuk system prompt, dan isinya diikuti sebagai prosedur. Skill yang
  kena juga tidak menutupi skill bernama sama di tingkat bawahnya.
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
  direktori skill atau melewati symlink ditolak. Tool `skill_manage` juga memeriksa kebijakan
  tulis file sebelum mengubah skill lokal.
- Setiap perubahan memicu hook `on_skill_lifecycle`.
- Pemasangan memvalidasi kategori sebagai satu nama direktori dan memeriksa semua tujuan
  file sebelum menulis. Kategori absolut, traversal, dan tujuan bersymlink ditolak, juga
  saat mengganti skill dengan `--force`.

**Slash command**
- `/<nama-skill> [instruksi]` mengirim isi skill sebagai **pesan pengguna**. System prompt
  tidak disentuh.

**Pemasangan**
- Semua sumber melewati jalur yang sama: validasi `SKILL.md`, pindai setiap file, tulis ke
  tingkat lokal. Tidak ada yang dieksekusi.
- Skill yang kena pemindaian ditolak kecuali dipaksa.

**Indeks hub**
- Satu berkas JSON: `{"version": 1, "skills": [{"name", "description", "category", "source",
  "identifier", "version", "hash"}]}`. `scripts/build_skills_index.py` membuatnya dari pohon
  direktori skill; versi bawaan ada di dalam paket (`bundled/skills-index.json`), dibangun dari
  skill bawaan dengan awalan `dragovics/clite/src/clite/bundled/skills`, dan dijaga tes agar
  tetap sama dengan sumbernya.
- Lokasi: `skills.hub.index` (kosong berarti indeks bawaan), lalu tiap tap dari
  `clite skills tap add owner/repo|path|url` (`<home>/skills/.hub/taps.json`). Sebuah tap yang
  tidak terbaca dilaporkan sebagai peringatan, bukan menghentikan pencarian.
- `clite skills install <nama>` mengambil entri indeks, dan menolak hasil unduhan yang hashnya
  tidak sama dengan yang dijanjikan indeks. Sebuah nama yang tidak ada di indeks disebutkan
  beserta nama yang ada.

**Pemindaian bundel** (`scanner.py`)
- Setiap file diperiksa, bukan hanya `SKILL.md`. Teks dipindai dengan pola yang sama seperti
  konten lain yang masuk system prompt.
- Berkas biner (ada byte NUL di kepala berkas) ditolak.
- Skrip (`scripts/**` dan berkas berakhiran `.py`, `.sh`, `.js`, …) dilaporkan per file beserta
  perintah yang dikandungnya (`subprocess`, `os.system`, `shell=True`, `download`, …); URL dan
  nama host yang disebut dilaporkan juga.
- Laporan ditampilkan sebelum penulisan, dan pengguna mengonfirmasi. Yang ditolak hanya bisa
  lewat `--force`.

**Pembaruan**
- Kunci mencatat sumber, identifier, waktu pasang, versi, dan hash isi. `plan_update`
  membandingkan versi terbaru dari sumber dengan isi direktori sekarang: `added`, `removed`,
  `changed` per file.
- Skill yang disunting pengguna (hash direktori berbeda dari yang dicatat) **tidak** ditimpa
  tanpa konfirmasi; `--force` yang menimpanya. Suntingan tidak pernah digabung.
- Versi baru yang ditandai pemindai tidak pernah ditulis oleh `clite skills update`.

**Kurator**
- Hanya menyentuh skill yang dibuat agent. Skill bawaan dan skill yang ditulis atau dipasang
  pengguna tidak pernah menjadi kandidat.
- Mengarsipkan ke `<home>/skills/.archive/`, tidak pernah menghapus.
- Dijalankan manual dengan `clite skills curate [--apply]` (bawaan laporan saja), dan otomatis
  paling banyak sekali per `curator.interval_hours` dari `run_startup_maintenance`
  (`curator.enabled`, `curator.stale_days`; pola yang sama dengan auto-prune sesi). Kegagalan
  kurator tidak pernah menghalangi sesi.

## Status fitur

| Fitur | Status | Catatan |
|---|---|---|
| Format, penemuan bertingkat, indeks | ✅ | |
| `skill_manage` (memori prosedural) | ✅ | |
| Skill sebagai slash command | ✅ | |
| Pasang dari direktori lokal | ✅ | |
| Pasang dari GitHub (`GitHubSource`) | ✅ | `owner/repo/path[@ref]`; `GITHUB_TOKEN` opsional dan hanya dikirim ke host API dan host unduhan GitHub; ukuran dicek dari daftar sebelum mengunduh; galat batas laju menyebut waktu reset. Diuji terhadap tiruan lokal dan ke repositori publik sungguhan (`test_install_a_skill_from_a_real_public_github_repository`, `-m network`) |
| Kurator | ✅ | Manual (`clite skills curate`) dan otomatis paling banyak sekali per `curator.interval_hours` dari `run_startup_maintenance` (`curator.enabled`, `curator.stale_days`). Dijaga `tests/skills/test_skills.py` dan `tests/agent/test_review.py`. F2-T12 |
| Skill bawaan | 🟡 | 4 skill. Hermes mengirim 58: F6-T2 |
| Hub: indeks registry, pencarian, pembaruan | ✅ | F6-T1: indeks JSON (+ tap lewat `clite skills tap`), `clite skills search`/`info`/`install <nama>`/`update`, hash isi dicatat di kunci dan diverifikasi saat memasang; `update` menampilkan diff per file dan tidak menimpa skill yang disunting pengguna tanpa konfirmasi. Dijaga `tests/skills/test_hub.py` |
| Pemindai keamanan skill yang lebih dalam | ✅ | F6-T1: `scanner.py` membaca setiap file (bukan hanya `SKILL.md`), menolak berkas biner, dan melaporkan skrip beserta perintahnya serta host yang dituju. Dijaga `tests/skills/test_hub.py` |
| Variabel lingkungan per skill (`env_passthrough`) | 🟡 | Dibaca dari frontmatter, belum diteruskan ke terminal |

## Yang sengaja berbeda dari Hermes

- **Skill bawaan dibaca di tempat.** Hermes menyalin skill bawaan ke home saat pemasangan dan
  menyinkronkannya dengan manifest. Di sini tingkat bawaan hanya-baca dan suntingan memakai
  copy-on-write.
- **Tanpa cache indeks di disk.** Hermes menyimpan cache indeks. Di sini penemuan selalu
  membaca disk; sesi hanya membangun indeks sekali karena prompt dibangun sekali.

## Celah yang diketahui

- `env_passthrough` di frontmatter belum punya efek.
- `SkillSource.search` masih mengembalikan daftar kosong untuk sumber bawaan: pencarian
  dijawab indeks (`IndexSource` lewat `search_skills`), bukan oleh pencarian di sisi GitHub.
  Registry pihak ketiga (skills.sh, ClawHub) yang punya API sendiri tinggal menurunkan
  `SkillSource` dan menimpa `search`.
- Indeks bawaan hanya memuat skill bawaan; `clite skills search` baru berguna kalau
  `skills.hub.index` diarahkan ke indeks yang lebih besar atau sebuah tap ditambahkan.
- Indeks tidak di-cache di disk: setiap pencarian membaca ulang berkasnya.
