# Peta dokumen

Semua dokumen di folder ini ditulis untuk orang atau AI yang **mengubah** kode. Dokumentasi
untuk pengguna akhir belum ada (roadmap F6-T9).

## Mulai dari mana

| Tujuan Anda | Baca berurutan |
|---|---|
| Mengerjakan proyek ini dengan AI | [prompts/README.md](prompts/README.md), lalu [roadmap/README.md](roadmap/README.md) |
| Mengerjakannya dengan model atau harness selain Claude Code | [PANDUAN-MODEL-LAIN.md](PANDUAN-MODEL-LAIN.md) |
| Memahami bentuk proyek | [arsitektur/README.md](arsitektur/README.md), [arsitektur/01-lapisan.md](arsitektur/01-lapisan.md), [arsitektur/03-invarian.md](arsitektur/03-invarian.md) |
| Mengubah satu modul | Spesifikasinya di [spesifikasi/](spesifikasi/README.md), lalu `AGENTS.md` di direktori modul itu |
| Tahu apa yang sudah terbukti jalan | [STATUS.md](STATUS.md) |
| Memahami mengapa Hermes dibangun seperti itu | [hermes/README.md](hermes/README.md) |

## Isi folder

| Folder | Isi | Sifat |
|---|---|---|
| [arsitektur/](arsitektur/README.md) | Lapisan, alur giliran, invarian, format data, protokol RPC, keamanan, beda dengan Hermes | Ditulis tangan; berubah bila arsitektur berubah |
| [spesifikasi/](spesifikasi/README.md) | Satu dokumen per modul: tanggung jawab, kontrak, status fitur, celah | Ditulis tangan; berubah bersama kode modulnya |
| [referensi/](referensi/katalog.md) | Katalog (tool, perintah, method RPC, kunci config) dan peta modul | **Dihasilkan** oleh `scripts/gen_docs.py`; jangan disunting |
| [roadmap/](roadmap/README.md) | 55 task dalam enam fase, dengan kriteria selesai | Ditulis tangan; status diperbarui tiap task selesai |
| [prompts/](prompts/README.md) | Prompt siap pakai untuk mengerjakan proyek dengan AI | Ditulis tangan |
| [hermes/](hermes/README.md) | Bedah Hermes Agent dan peta padanan file | Ditulis tangan; mengacu ke satu commit Hermes |
| [STATUS.md](STATUS.md) | Apa yang dijaga tes, apa yang belum diverifikasi | Diperbarui tiap ada yang terverifikasi |
| [PANDUAN-MODEL-LAIN.md](PANDUAN-MODEL-LAIN.md) | Apa yang pindah dan apa yang diganti bila model atau harness bukan Claude Code | Ditulis tangan; dilengkapi dari sesi nyata |

Di luar folder ini: `AGENTS.md` di root repositori (aturan kerja untuk seluruh proyek) dan
`AGENTS.md` di tiap direktori area (aturan dan resep area itu).

## Konvensi

**Bahasa.** Dokumen berbahasa Indonesia. Nama di dalam kode, perintah, dan kutipan keluaran
tetap seperti aslinya.

**Path.** Path di dalam backtick merujuk ke repositori ini, kecuali di dua tempat, di mana ia
merujuk ke repositori Hermes:

- di mana pun di dalam `docs/hermes/`;
- di paragraf, butir daftar, atau baris tabel yang menyebut Hermes, dan di kolom tabel yang
  judulnya menyebut Hermes.

Path yang diawali `src/clite/` atau `docs/` selalu merujuk ke repositori ini. Path ke file
yang belum ada ditulis dengan tanda di dalam backtick, misalnya
`src/clite/tools/builtin/contoh.py (baru)`.

**Status fitur.** ✅ berarti ada tes yang gagal bila fitur itu rusak. 🟡 berarti ada sebagian,
atau ada tetapi belum pernah dijalankan terhadap hal yang sebenarnya. ⬜ berarti belum ada.

**Nomor task.** `F2-T4` adalah task keempat di fase dua. Setiap nomor yang disebut di dokumen
mana pun harus terdefinisi di `docs/roadmap/`.

## Yang diperiksa mesin

Dokumen yang menyebut hal yang tidak ada akan menyesatkan pembacanya, jadi rujukan diperiksa
oleh suite:

| Yang diperiksa | Oleh |
|---|---|
| Tautan relatif dan jangkar judul | `test_relative_links_in_the_docs_resolve` |
| Path ke file di repositori ini | `test_paths_named_in_the_docs_exist` |
| Nama modul dan atribut `clite.*` | `test_modules_named_in_the_docs_exist` |
| Nama tes yang dikutip sebagai penjaga | `test_tests_named_in_the_docs_exist` |
| Nomor task roadmap, dan kelengkapan bagian tiap task | `test_roadmap_tasks_cited_in_the_docs_are_defined`, `test_every_roadmap_task_is_in_the_index_and_has_the_standard_fields` |
| Halaman hasil generate masih sama dengan kodenya | `test_generated_reference_pages_are_current` |
| Setiap `AGENTS.md` punya `CLAUDE.md` yang mengimpornya, dan tetap pendek | `test_every_agents_file_has_a_claude_file_that_imports_it`, `test_instruction_files_stay_short` |
| Nama proyek bisa diganti: tidak ada file, termasuk dokumen, yang mengejanya dengan cara yang tidak terlihat skrip pengganti nama | `test_renaming_leaves_no_trace_of_the_old_name_and_the_program_still_runs` |

Path ke repositori Hermes tidak bisa diperiksa suite, karena suite tidak boleh bergantung pada
repositori kedua. Untuk itu ada skrip tersendiri:

```bash
python scripts/check_hermes_refs.py --hermes ../hermes-ref
```
