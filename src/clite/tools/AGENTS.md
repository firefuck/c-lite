# tools: aturan kerja

Registry, toolset, dispatch, persetujuan perintah, lingkungan eksekusi, tool bawaan, MCP.
Spesifikasi: `docs/spesifikasi/tools.md`.

Tes: `pytest tests/tools -q`

## Aturan yang tidak boleh dilanggar

1. **Handler mengembalikan string JSON dan tidak pernah melempar ke model.** Pakai
   `tool_result(...)` dan `tool_error(...)`.
2. **Pesan galat ditulis untuk model.** Katakan apa yang salah dan apa yang harus dilakukan
   berikutnya ("old_string cocok di 3 tempat; sertakan lebih banyak baris di sekitarnya"),
   bukan sekadar "invalid input".
3. **Deskripsi tool adalah bagian dari prompt.** Ia dibayar di setiap permintaan dan ikut
   awalan yang di-cache. Tulis sekali dengan teliti, jangan menyisipkan nilai yang berubah.
4. **Daftar tool tetap selama sesi.** Jangan membuat tool yang muncul atau hilang di tengah
   percakapan. `check_fn` hanya untuk ketersediaan yang stabil (kunci API ada, biner ada).
5. **Setiap jalan menuju shell lewat `check_command`.** Tool baru yang menjalankan perintah
   harus memanggil gerbang persetujuan lebih dulu.
6. **Setiap jalan menuju penulisan file lewat `write_denied_reason`, dan setiap jalan menuju
   pembacaan file lewat `read_denied_reason`.** Yang dibaca model dikirim ke provider dan
   disimpan di database sesi.
7. **Rahasia tidak masuk ke proses anak dan tidak masuk ke hasil.** Pakai `build_child_env`
   untuk subprocess, dan `redact` untuk apa pun yang berasal dari luar: keluaran perintah, isi
   file, hasil pencarian.
8. **Tidak ada import dari `agent` di tingkat modul.** Tool yang butuh agent memakai
   `ctx.agent`. Dua pengecualian yang diizinkan tercatat di `tests/test_architecture.py`.

## Resep

### Menambah tool bawaan

Contoh terkecil: `builtin/todo.py`.

1. Buat `builtin/<nama>.py` dengan skema, handler `def <nama>_tool(args, ctx=None) -> str`,
   dan satu panggilan `registry.register("<nama>", "<toolset>", SKEMA, handler, ...)` di akhir.
2. Pilih kebijakan paralel: `parallel="safe"` untuk tool yang hanya membaca, `"path"` dengan
   `path_args=("path",)` untuk tool yang bekerja pada satu file, default `"never"`.
3. Masukkan nama tool ke sebuah toolset di `toolsets.py` (atau buat toolset baru dan sertakan
   di toolset komposit yang tepat).
4. Bila tool memerlukan panduan pemakaian, tambahkan blok di `agent/prompt/identity.py` yang
   dipasang hanya ketika tool itu tersedia.
5. Tes di `tests/tools/`. Panggil handler lewat `handle_function_call(nama, args, ToolContext(...))`
   supaya hook dan batas ukuran ikut teruji.
6. `python scripts/gen_docs.py`.

### Menambah pola berbahaya

Tambahkan `(regex, kunci, deskripsi)` ke `DANGEROUS_PATTERNS` di `approval.py`, lalu satu
baris ke tes parametris `test_dangerous_commands_are_detected` dan satu perintah mirip yang
tidak boleh kena ke `test_ordinary_commands_are_not_flagged`. `kunci` adalah yang diingat
ketika pengguna menjawab "always", jadi pola yang sejenis memakai kunci yang sama.

Pola di `DANGEROUS_PATTERNS` bisa disetujui untuk satu sesi atau selamanya. Perintah yang
menjangkau pengaturan atau kredensial agent sendiri ditangani `detect_self_access` dan tidak
pernah diingat. Sub-perintah `clite` baru yang mengubah pengaturan ditambahkan ke daftar di
`OWN_CLI_SUBCOMMANDS`, dengan satu baris di
`test_commands_that_reach_for_the_agents_own_settings_are_flagged`.

### Menambah backend terminal

Turunkan `BaseEnvironment` (`environments/base.py`), implementasikan `execute` dan
`resolve_path`, daftarkan dengan `register_environment_backend("nama", factory)`. Tool
terminal, tool file, dan gerbang persetujuan tidak perlu diubah.

## Jebakan

- `get_tool_definitions` di-cache menurut `registry.generation`. Mengubah skema tanpa
  mendaftar ulang tidak akan terlihat.
- `ToolContext.setting(...)` membaca potret config milik agent bila ada. Jangan memanggil
  `load_config()` di handler: sesi itu mungkin dimulai dengan config lain.
- Tes yang mendaftarkan tool harus memakai `origin="test"`; fixture membersihkan origin itu
  setelah tiap tes.
- Hasil tool dibatasi `tool_result_max_chars`. Tool yang bisa menghasilkan keluaran besar
  sebaiknya berhalaman sendiri (`offset`, `limit`) dan memberi tahu model cara melanjutkan.
