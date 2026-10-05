# Tambah tool

**Kapan dipakai.** Untuk memberi model satu kemampuan baru.

**Di Claude Code:** `/tambah-tool <nama dan gunanya>`

**Isian.** `<TOOL>`: nama tool, apa yang dilakukannya, dan kapan model seharusnya memakainya.

## Prompt

Tambahkan tool `<TOOL>` ke repositori ini.

**Sebelum menulis kode, jawab dulu:** apakah ini memang tool? Pengetahuan atau prosedur
adalah skill, bukan tool. Reaksi atas sebuah event adalah hook. Sesuatu yang bisa dilakukan
dengan `terminal` dan tidak butuh jaminan khusus mungkin tidak perlu ada. Bila jawabannya
bukan tool, katakan dan usulkan bentuk yang tepat.

**Hasil yang diminta.** Model bisa memanggil tool itu di sesi yang toolset-nya aktif, hasilnya
berguna bagi model, dan galatnya menjelaskan cara memperbaiki panggilan.

**Yang dibaca dulu.** `src/clite/tools/AGENTS.md` (resep "Menambah tool bawaan"),
`docs/spesifikasi/tools.md`, dan satu tool yang mirip di `src/clite/tools/builtin/`.

**Batasan.**
- Deskripsi tool dan parameternya dibaca model pada setiap permintaan: tulis untuk model,
  sebut kapan memakainya dan kapan tidak, dan tetap ringkas.
- Handler mengembalikan string JSON dan tidak pernah melempar. Galat adalah hasil.
- Nyatakan kebijakan paralelnya (`never`, `safe`, atau `path`) dengan benar. Tool yang
  mengubah sesuatu bukan `safe`.
- Aturan keamanan di `docs/arsitektur/06-keamanan.md` berlaku: yang menjalankan perintah
  melewati `check_command`; yang menulis file melewati `write_denied_reason`; yang membaca
  file melewati `read_denied_reason` dan `redact`; yang mengambil dari jaringan menolak alamat
  bukan publik; kredensial yang dipakainya didaftarkan.
- Tool yang butuh backend atau kunci memakai `check_fn`, sehingga tidak ditawarkan bila tidak
  bisa bekerja.
- Putuskan toolset-nya, dan apakah ia pantas ada di `clite-gateway`, `clite-cron`, dan
  `clite-subagent`. Kemampuan yang tidak aman tanpa pengguna di depan layar tidak masuk ke
  sana.

**Bukti.**
- Tes lewat `handle_function_call`: jalur sukses, argumen salah, dan setiap penolakan
  keamanan yang berlaku.
- Baris tool di tabel status `docs/spesifikasi/tools.md`.
- `python scripts/gen_docs.py` dijalankan, dan `scripts/run_tests.sh` lulus.
