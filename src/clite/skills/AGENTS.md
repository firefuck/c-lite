# skills: aturan kerja

Penemuan, validasi, indeks, penulisan, dan pemasangan skill. Spesifikasi:
`docs/spesifikasi/skills.md`.

Tes: `pytest tests/skills -q`

## Aturan yang tidak boleh dilanggar

1. **Skill tidak pernah mengubah system prompt di tengah sesi.** Skill yang dipanggil masuk
   sebagai pesan pengguna (`commands.build_skill_message`) atau sebagai hasil tool
   (`skill_view`).
2. **Indeks tetap ringkas.** Hanya nama dan deskripsi. Apa pun yang ditambahkan ke indeks
   dibayar di setiap permintaan semua sesi.
3. **Konten dari luar dipindai sebelum dimuat atau ditulis.** Skill berakhir di depan model
   dengan wibawa system prompt. Skill dari tingkat proyek dan eksternal dipindai setiap kali
   ditemukan (`catalog.SCANNED_TIERS`); tingkat baru yang isinya datang dari luar masuk ke
   daftar itu.
4. **Hanya tingkat lokal yang ditulis.** Jangan menulis ke direktori bawaan paket.
5. **Tidak ada yang dieksekusi saat memasang.**
6. **Hanya mengimpor `core` dan `plugins.hooks`.** Tool skill untuk model ada di
   `tools/builtin/skills.py`.

## Resep

### Menambah skill bawaan

1. Buat `src/clite/bundled/skills/<kategori>/<nama>/SKILL.md`. Baca dulu
   `bundled/skills/meta/skill-authoring/SKILL.md`: itu panduan menulis skill yang juga dibaca
   agent.
2. Nama di frontmatter harus sama dengan nama direktori.
3. Skill bawaan ditulis dalam bahasa Inggris (ia dibaca model, dan pengguna bisa berasal dari
   mana saja).
4. `python scripts/gen_docs.py`, lalu `pytest tests/skills -q`.

### Menambah sumber pemasangan

Turunkan `SkillSource` (`hub.py`), implementasikan `fetch(identifier) -> SkillBundle`, dan
daftarkan dengan `register_skill_source`. Validasi, pemindaian, dan penulisan sudah ditangani
`install_skill`.

## Jebakan

- `discover_skills` membaca disk setiap kali dipanggil. Jangan memanggilnya di jalur yang
  berjalan tiap iterasi.
- Frontmatter YAML bisa memuat tipe apa saja. Pakai pembantu `_strings` untuk daftar.
- `metadata.hermes` juga dibaca. Jangan menghapus itu: skill yang ditulis untuk Hermes harus
  tetap bisa dimuat.
