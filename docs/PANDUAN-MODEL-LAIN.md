# Panduan untuk model AI selain Claude

Dokumen ini untuk **model atau harness selain Claude Code** yang akan mengerjakan C-lite:
GPT, Gemini, model terbuka, Cursor, Codex CLI, Aider, dan sejenisnya. Ia menjawab tiga hal:
apa yang bisa dipakai apa adanya, apa yang hanya berlaku di Claude Code dan harus diganti, dan
bagaimana menjaga model yang berbeda tetap berada di dalam aturan proyek.

## Status jujur

Seluruh pembuktian di [STATUS.md](STATUS.md) dilakukan dengan Claude di Claude Code. **Belum
pernah ada model lain yang mengerjakan repositori ini.** Dokumen ini disusun dari isi
repositori: apa yang bergantung pada Claude Code dan apa yang tidak. Hal-hal tentang harness
lain di bawah adalah hal yang harus Anda periksa sendiri, bukan jaminan. Setelah satu sesi
nyata dengan model lain, perbarui bagian [Catatan dari sesi nyata](#catatan-dari-sesi-nyata).

## Ringkasan: apa yang pindah dan apa yang tidak

| Bagian | Ikut pindah? | Keterangan |
|---|---|---|
| `AGENTS.md` di root dan di tiap area | Ya | Teks biasa. Banyak harness membacanya otomatis; periksa milik Anda. Bila tidak, tempelkan atau suruh model membacanya |
| Dokumen di `docs/` | Ya | Teks biasa dengan tautan relatif |
| Bagian "Prompt" di `docs/prompts/` | Ya | Ditulis tidak bergantung pada alat. Tempel ke harness mana pun |
| Seluruh pemeriksaan (`scripts/run_tests.sh`, tes arsitektur, tes dokumen) | Ya | Perintah biasa; tidak memakai jaringan |
| `CLAUDE.md` di root dan di tiap area | Tidak berguna di luar Claude Code | Hanya mengimpor `AGENTS.md`. **Jangan dihapus**, lihat bagian "Yang tidak boleh dilanggar" |
| Skill di `.claude/skills/` (`/kerjakan-task` dan sembilan lainnya) | Tidak | Hanya penunjuk tipis ke file di `docs/prompts/`. Gantinya ada di tabel perintah di bawah |
| Subagent `peninjau` di `.claude/agents/` | Tidak | Gantinya: sesi baru yang bersih. Lihat bagian "Meninjau tanpa subagent" |
| Saran di `docs/prompts/README.md` tentang `/goal`, `/model fable`, pengalihan ke Opus | Tidak | Khusus Claude Code dan Fable. Abaikan |

## Syarat minimum harness dan model

Harness harus bisa:

1. Membaca dan menyunting file, dan menjalankan perintah shell dengan **batas waktu** per
   perintah. Beberapa tes memang menguji kode yang bisa menggantung.
2. Menjalankan `git` termasuk `git worktree add`, dipakai untuk membuktikan bahwa sebuah tes
   gagal tanpa perubahannya.
3. Menjalankan Python 3.11 atau lebih baru dan Node 22 atau lebih baru. Tes tidak butuh
   jaringan; pemasangan dependensi butuh PyPI dan npm.
4. Menyimpan konteks yang cukup untuk membaca `AGENTS.md` (sekitar 140 baris), satu spesifikasi
   modul, dan satu blok task sekaligus, ditambah kode yang diubah.

Subagent, mode rencana, dan perintah garis miring itu berguna tetapi tidak wajib.

Model sebaiknya sanggup: mengikuti instruksi panjang yang berlapis tanpa melenceng, menulis
Python bertipe yang lolos `mypy`, membaca TypeScript, dan **berhenti serta melapor** alih-alih
menebak. Yang terakhir paling menentukan. Proyek ini penuh aturan yang dijaga tes, dan model
yang suka "membuat tes hijau" dengan jalan pintas akan merusaknya pelan-pelan.

## Menyiapkan sesi

1. Buka sesi di root repositori. Pasang: `pip install -e ".[dev]"` dan `npm install`.
2. Pastikan model membaca `AGENTS.md` di root. Cara memeriksa: tanyakan "sebutkan sebelas aturan
   yang tidak boleh dilanggar". Bila ia tidak bisa, harness Anda tidak memuat file itu; tempel
   isinya ke prompt sistem atau ke pesan pertama.
3. Bila harness Anda mencari nama file aturan yang lain, buat file penunjuk satu baris
   ("Baca `AGENTS.md` di root repositori sebelum mengubah apa pun") dengan nama yang diminta
   harness itu. Jangan menyalin isi `AGENTS.md` ke sana: dua salinan akan berselisih. Simpan
   file penunjuk itu di luar commit kecuali pemilik proyek memutuskan lain.
4. Aturan area (`src/clite/<area>/AGENTS.md`, `tests/AGENTS.md`, `ui-tui/AGENTS.md`,
   `apps/AGENTS.md`) di Claude Code termuat otomatis saat file di area itu dibaca. Di harness
   lain tidak ada jaminan itu. **Perintahkan model membaca `AGENTS.md` area sebelum menyunting
   apa pun di dalamnya.** Ini aturan yang sama dengan yang tertulis di root.
5. Siapkan rujukan Hermes bila task-nya membutuhkannya (kolom "Rujukan Hermes" pada task):
   ikuti langkah clone di [prompts/README.md](prompts/README.md#menyiapkan-claude-code), langkah 3.
6. Jalankan `scripts/run_tests.sh` sekali sebelum mengubah apa pun, dan catat hasilnya. Itulah
   garis dasar; kegagalan yang sudah ada sebelum Anda mulai bukan milik model.

## Pengganti perintah Claude Code

Skill di `.claude/skills/` hanya berbunyi "baca file prompt ini dan jalankan bagian Prompt-nya
dengan `<TASK>` diganti argumen". Di harness lain lakukan itu sendiri:

| Di Claude Code | Di harness lain |
|---|---|
| `/orientasi` | Tempel bagian "Prompt" dari [01-orientasi.md](prompts/01-orientasi.md) |
| `/kerjakan-task F2-T4` | Tempel bagian "Prompt" dari [02-kerjakan-task.md](prompts/02-kerjakan-task.md), ganti `<TASK>` dengan `F2-T4` |
| `/tinjau F2-T4` | Sesi baru; lihat "Meninjau tanpa subagent" |
| `/perbaiki-bug <gejala>` | [04-perbaiki-bug.md](prompts/04-perbaiki-bug.md), ganti isian gejala |
| `/tambah-provider <nama>` | [05-tambah-provider.md](prompts/05-tambah-provider.md) |
| `/tambah-tool <nama dan gunanya>` | [06-tambah-tool.md](prompts/06-tambah-tool.md) |
| `/tambah-platform <nama>` | [07-tambah-platform.md](prompts/07-tambah-platform.md) |
| `/porting-dari-hermes <fitur>` | [08-porting-dari-hermes.md](prompts/08-porting-dari-hermes.md) |
| `/verifikasi-lingkungan` | [09-verifikasi-lingkungan.md](prompts/09-verifikasi-lingkungan.md) |
| `/pecah-task F3-T3` | [10-pecah-task.md](prompts/10-pecah-task.md) |

Tiap file prompt punya bagian "Isian" yang menyebut apa yang harus diganti. Bagian "Prompt" ke
bawah ditulis berupa hasil yang diminta, yang dibaca dulu, batasan, dan bukti. Tempel
seutuhnya; jangan diringkas.

Satu pesan awal yang bisa dipakai di mana pun, sebelum prompt di atas:

```text
Anda mengerjakan repositori C-lite. Baca AGENTS.md di root sampai habis, lalu docs/README.md.
Sebelum menyunting file di sebuah direktori, baca AGENTS.md direktori itu. Dokumen berbahasa
Indonesia; kode, komentar, docstring, pesan commit, dan keluaran CLI berbahasa Inggris. Jangan
push. Bila tugas tampak menuntut pelanggaran aturan, atau tes gagal dan tidak jelas mana yang
salah, berhenti dan jelaskan; jangan mencari jalan memutar dan jangan melemahkan tes.
```

## Meninjau tanpa subagent

Subagent `peninjau` hanya memberi satu hal: konteks yang tidak memuat penalaran pengerjaan.
Hal itu bisa ditiru:

1. **Sesi baru, atau model lain.** Mulai percakapan kosong. Jangan lanjutkan sesi pengerjaan.
   Meninjau dengan model yang berbeda dari yang mengerjakan lebih baik lagi.
2. Tempel bagian "Prompt" dari [03-tinjau.md](prompts/03-tinjau.md), dengan `<TASK>` diganti.
3. Tiga syarat dari definisi peninjau tetap berlaku, tulis ulang di pesan awal bila perlu:
   peninjau **tidak mengubah direktori kerja** (membuktikan "tes ini gagal tanpa perubahannya"
   dilakukan di `git worktree add` ke direktori sementara, dengan batas waktu); **temuan hanya
   hal yang menyangkut kebenaran, keamanan, invarian, atau kriteria task** (gaya dan penamaan
   bukan temuan); dan **tiap temuan membawa bukti** (file dan baris, cara memicu, atau
   keluaran perintah).
4. Bila harness tidak bisa melarang peninjau menulis file, periksa `git status` sesudahnya.
   Peninjau yang mengubah file telah keluar dari tugasnya.

## Yang tidak boleh dilanggar

Aturannya sama untuk semua model dan dibaca di [AGENTS.md](../AGENTS.md) serta
[arsitektur/03-invarian.md](arsitektur/03-invarian.md). Bagian ini hanya menunjuk tempat
model yang berbeda gaya paling sering tergelincir, dan tes yang akan menangkapnya.

| Kebiasaan yang wajar di tempat lain | Mengapa salah di sini | Yang menangkapnya |
|---|---|---|
| Mengimpor paket "yang dekat" dari lapisan atas | Import hanya boleh mengarah ke bawah | `tests/test_architecture.py` |
| Menaruh perilaku baru di `agent/agent.py` atau `agent/loop.py` | Inti sengaja sempit; kemampuan baru adalah tool, skill, plugin, profil provider, atau fase | Tidak ada tes; tanggung jawab peninjau |
| Menyebut nama vendor (nama model atau perusahaan) di luar profil providernya | Yang berbeda antar-vendor adalah method pada `ProviderProfile` | `tests/test_architecture.py` |
| Mengeja nama direktori home (`~/.clite`) di luar `core/brand.py` | Home dinamis, diambil dari `core.constants` saat dipanggil | `tests/test_architecture.py` |
| Membaca lingkungan proses (`os.environ`, `os.getenv`) di luar daftar yang diizinkan | Rahasia hanya di `.env`, dibaca dengan `get_secret` | `tests/test_architecture.py` |
| `print(...)` di kode pustaka | Pada transport stdio, stdout adalah kawat protokol | `tests/test_architecture.py` |
| Memulai `threading.Thread` langsung, atau menyimpan path home di konstanta modul | Thread sesi dimulai dengan `core.threads.start_thread` supaya home ikut terbawa | Tidak ada tes yang menolak pemakaiannya; tanggung jawab peninjau |
| Melempar galat dari handler tool | Handler mengembalikan string JSON; galat adalah hasil | Tes tool di `tests/tools/` |
| Menambah kunci config yang tidak dibaca siapa pun, atau parameter "untuk nanti" | Dideklarasikan sekali dan harus ada pembacanya | Suite gagal |
| Menyunting `docs/referensi/` atau `src/clite/rpc/contracts/` dengan tangan | Dihasilkan; edit berikutnya akan tertimpa dan suite gagal | `test_generated_reference_pages_are_current` |
| Menulis dokumen berbahasa Inggris, atau kode dan komentar berbahasa Indonesia | Pembagian bahasa ada di `AGENTS.md` | Tidak ada tes; ini tanggung jawab peninjau |
| Menyebut file, tes, atau nomor task yang tidak ada di dokumen | Rujukan diperiksa mesin | `tests/test_docs.py` |
| Menghapus `CLAUDE.md`, atau menambah `AGENTS.md` area baru tanpa `CLAUDE.md` pendamping yang berisi `@AGENTS.md` | Suite memeriksa pasangan itu | `tests/test_docs.py` |

Dua hal yang tidak punya penjaga tes dan paling sering terjadi pada model yang sedang mengejar
hasil hijau:

- **Melemahkan tes.** Menghapus asersi, memperlebar toleransi, menambah `skip`, atau mengubah
  harapan supaya cocok dengan kode. Yang benar: putuskan dulu mana yang salah, kode atau
  harapan, dan bila tidak jelas, berhenti dan lapor.
- **Mengklaim ✅ tanpa bukti.** ✅ di spesifikasi berarti ada tes yang gagal bila fitur itu
  rusak. Kode yang belum pernah dijalankan terhadap hal yang sebenarnya (API sungguhan,
  platform sungguhan, sistem operasi lain) ditandai 🟡 dan dicatat di
  [STATUS.md](STATUS.md) sebagai belum diverifikasi.

Model yang dipasang ke proyek ini juga bertemu kode keamanan: gerbang persetujuan perintah dan
pemindai injeksi prompt. Sebagian harness menolak atau melemahkan pekerjaan semacam itu.
Bila model menolak mengerjakan task keamanan, itu perilaku harness dan bukan galat proyek;
ganti model untuk task itu dan tinjau hasilnya dengan model lain. Aturan keamanan untuk kode
baru ada di [arsitektur/06-keamanan.md](arsitektur/06-keamanan.md).

## Alur satu task, tanpa skill

Ini isi `/kerjakan-task` dan `/tinjau` diuraikan, untuk dipegang manusia yang mengoordinasi
model lain.

1. **Pilih task.** Status ⬜ dan semua "Bergantung pada" sudah ✅ ([roadmap/README.md](roadmap/README.md)).
2. **Sesi pengerjaan.** Pesan awal dari bagian sebelumnya, lalu prompt 02 dengan `<TASK>` terisi.
3. **Garis dasar.** `scripts/run_tests.sh` hijau sebelum mulai, atau kegagalannya dicatat.
4. **Pekerjaan.** Tes ditulis lebih dulu dan dilihat gagal; kode menyusul. Perilaku baru tanpa
   tes yang gagal bila perilaku itu dilepas tidak dihitung selesai.
5. **Turunan.** Jalankan perintah di tabel "Sesudah mengubah sesuatu yang punya turunan" pada
   [AGENTS.md](../AGENTS.md) (`python scripts/gen_docs.py` dan kawan-kawannya).
6. **Dokumen.** Spesifikasi modul, indeks roadmap, dan `docs/STATUS.md` diperbarui dalam commit yang sama.
7. **Pemeriksaan penuh.** `scripts/run_tests.sh` lulus seluruhnya.
8. **Tinjauan.** Sesi atau model terpisah, prompt 03. Temuan yang menyangkut kebenaran atau
   kriteria task diperbaiki; sisanya diabaikan.
9. **Commit.** Satu perubahan logis per commit, pesan bahasa Inggris berbentuk kalimat perintah
   yang menyebut apa dan mengapa. **Jangan push** kecuali Anda yang menyuruh.
10. **Laporan akhir** memuat: perubahan per file, perintah pemeriksaan beserta hasilnya, yang
    **tidak** diverifikasi, dan temuan di luar lingkup.

Soal tanda tangan commit: lampiran penulis bersama (`Co-Authored-By`) yang ditambahkan Claude
Code adalah milik Claude. Harness lain mengikuti aturannya sendiri atau Anda mengaturnya;
repositori ini tidak mewajibkan satu bentuk pun.

## Memilih model untuk jenis pekerjaan

Ini saran, bukan hasil pengujian.

| Pekerjaan | Yang dibutuhkan | Catatan |
|---|---|---|
| Task S dan M di satu area | Model yang baik dalam mengikuti aturan dan menulis tes | Cukup satu sesi per task |
| Task L | Konteks panjang atau disiplin mencatat kemajuan | Pecah jadi sub-langkah di awal, commit per sub-langkah, catat kemajuan di blok task |
| Task XL | Jangan dimulai | Pecah dulu dengan prompt 10 |
| Kode keamanan (persetujuan perintah, file guard, rahasia, server, gateway) | Model yang mau mengerjakannya, dan peninjau dari model lain | Tinjauan wajib; lihat [arsitektur/06-keamanan.md](arsitektur/06-keamanan.md) |
| Meninjau | Model yang berbeda dari pengerjanya bila mungkin | Konteks bersih lebih penting daripada model yang lebih besar |
| Porting dari Hermes | Model yang membaca kode sumber dengan teliti | Harus membaca clone Hermes langsung, bukan dari ingatan |

## Tanda sesi sedang melenceng

Hentikan sesi dan mulai ulang dengan prompt yang memuat apa yang sudah dipelajari bila:

- model mengoreksi hal yang sama lebih dari dua kali;
- model mengubah tes dan kode produksi dalam satu langkah tanpa menjelaskan mana yang salah;
- model menyatakan "semua lulus" tanpa keluaran `scripts/run_tests.sh` di percakapan;
- model menyebut file, fungsi, atau tes yang tidak ada (jalankan `tests/test_docs.py` dan baca
  hasilnya untuk dokumen; periksa dengan `ls` atau `grep` untuk kode);
- model mengubah file di luar lingkup task, atau menyentuh `docs/referensi/` dengan tangan;
- model mulai menulis dokumen berbahasa Inggris atau komentar berbahasa Indonesia;
- diff jauh lebih besar dari ukuran task (lihat tabel ukuran di [roadmap/README.md](roadmap/README.md)).

## Daftar periksa sebelum menerima hasil

- [ ] `scripts/run_tests.sh` lulus seluruhnya, dan Anda melihat keluarannya sendiri
- [ ] `git status` bersih setelah commit, dan tidak ada file di luar lingkup task
- [ ] Setiap butir "Selesai bila" punya tes, dan tes itu gagal tanpa perubahannya
- [ ] Spesifikasi, indeks roadmap, dan `docs/STATUS.md` ikut berubah di commit yang sama
- [ ] File hasil generate diperbarui (suite akan gagal bila lupa)
- [ ] Laporan akhir menyebut yang **tidak** diverifikasi
- [ ] Tinjauan sesi bersih sudah dijalankan dan temuannya ditangani
- [ ] Tidak ada push yang tidak Anda minta

## Catatan dari sesi nyata

Belum ada. Catat di sini setiap kali model atau harness baru dipakai: nama dan versinya,
apakah `AGENTS.md` termuat otomatis, task yang dikerjakan, aturan yang dilanggar dan tes yang
menangkapnya, dan penyesuaian yang ternyata dibutuhkan. Satu sesi nyata lebih berharga daripada
dokumen ini.
