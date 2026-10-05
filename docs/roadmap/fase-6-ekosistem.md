# Fase 6: ekosistem

Fase ini membuka agent ke luar: skill dan plugin dari orang lain, editor, suara, dan
dokumentasi untuk pengguna. Hampir semua task di sini membawa kode atau teks pihak ketiga ke
dalam jangkauan agent, jadi dua aturan dari
[arsitektur/06-keamanan.md](../arsitektur/06-keamanan.md) berlaku lebih keras di sini:

- **Kode dari luar tidak berjalan tanpa tindakan eksplisit pengguna.** Memasang tidak pernah
  mengaktifkan, dan tidak ada yang memasang dependensi secara diam-diam.
- **Teks dari luar yang masuk system prompt dipindai dulu.** Itu termasuk deskripsi skill dari
  hub dan teks apa pun yang disumbang plugin.

Aturan yang berlaku untuk semua task ada di [README](README.md#selesai-itu-apa).

---

### F6-T1 Hub skill

**Tujuan.** Pengguna mencari skill dari sebuah indeks, memasangnya dengan satu perintah, dan
memperbaruinya, dengan pemindaian yang lebih dalam daripada sekarang.

**Lingkup.**
- **Indeks.** Satu file JSON yang dihasilkan dari repositori skill (nama, deskripsi, kategori,
  sumber, hash). Skrip pembuat indeks ada di repositori ini; lokasi indeks default bisa
  diganti di config.
- **Perintah.** `clite skills search <kata>`, `clite skills install <nama>`,
  `clite skills update [nama]`, `clite skills info <nama>`. `SkillSource.search` yang sekarang
  mengembalikan daftar kosong diimplementasikan.
- **Sumber tambahan** ("tap"): `clite skills tap add owner/repo`.
- **Pemindai yang lebih dalam** untuk skill dari luar: semua file teks, bukan hanya
  `SKILL.md`; skrip di `scripts/` dilaporkan per file beserta perintah yang dikandungnya; URL
  dan nama host yang dituju didaftar; file biner ditolak. Hasil pemindaian ditampilkan sebelum
  pemasangan dan pengguna mengonfirmasi.
- **Asal-usul.** File kunci mencatat sumber, hash, dan waktu pasang; `update` menunjukkan
  diff sebelum menimpa, dan tidak menimpa skill yang disunting pengguna tanpa konfirmasi.

**File.** `src/clite/skills/hub.py`, `src/clite/skills/scanner.py (baru)`,
`src/clite/cli/subcommands/skills.py`, `scripts/build_skills_index.py (baru)`,
`src/clite/core/config_defaults.py`, `tests/skills/test_hub.py (baru)`.

**Rujukan Hermes.** `tools/skills_hub.py`, `tools/skills_hub_search.py`,
`tools/skills_hub_sources.py`, `tools/skills_hub_install.py`, `tools/skills_guard.py`,
`tools/skills_ast_audit.py`, `scripts/build_skills_index.py`.

**Selesai bila.**
- [ ] Tes terhadap indeks dan repositori tiruan lokal: cari, pasang, perbarui.
- [ ] Tes: skill dengan skrip yang memuat perintah eksfiltrasi ditolak dengan laporan per file.
- [ ] Tes: `update` atas skill yang disunting lokal tidak menimpa tanpa konfirmasi.
- [ ] Baris hub dan pemindai di spesifikasi skills menjadi ✅.

**Ukuran.** L

**Bergantung pada.** F1-T4

---

### F6-T2 Porting skill bawaan dari Hermes

**Tujuan.** Instalasi baru membawa kumpulan skill yang berguna, bukan hanya empat.

**Lingkup.**
- Hermes mengirim skill bawaan dan skill opsional berlisensi MIT. Bawa per kategori, satu
  commit per kategori, dimulai dari `software-development`, `productivity`, dan `research`.
- Untuk setiap skill: periksa bahwa tool yang disebutnya ada di C-lite; ganti nama tool yang
  berbeda; buang bagian yang bergantung pada tool yang belum ada, atau tandai skill itu dengan
  `requires_tools` sehingga baru tampil ketika tool-nya tersedia; ganti penyebutan nama produk
  dan path home.
- Skill yang seluruhnya bergantung pada fitur yang belum ada (browser, suara) ditunda dan
  didaftar di task ini.
- Atribusi: setiap skill yang dibawa mencantumkan asalnya di frontmatter, dan `NOTICE.md`
  menyebut kumpulan itu.
- Pisahkan seperti Hermes: yang selalu ikut di `src/clite/bundled/skills/`, dan yang opsional
  di direktori yang bisa dipasang lewat hub (F6-T1).

**File.** `src/clite/bundled/skills/`, `NOTICE.md`, `tests/skills/test_skills.py`,
`docs/spesifikasi/skills.md`.

**Rujukan Hermes.** `skills/` (terutama `skills/software-development/`,
`skills/productivity/`, `skills/research/`), `optional-skills/`,
`website/docs/developer-guide/creating-skills.md`.

**Selesai bila.**
- [ ] Tes: setiap skill bawaan lolos validasi format dan pemindaian ancaman.
- [ ] Tes: tidak ada skill bawaan yang menyebut tool yang tidak terdaftar, kecuali lewat
      `requires_tools` atau `fallback_for_tools`.
- [ ] Tes: tidak ada skill bawaan yang memuat nama produk atau path home Hermes.
- [ ] Indeks skill tetap di bawah batas ukurannya dengan semua skill bawaan aktif.

**Ukuran.** L

**Bergantung pada.** -

---

### F6-T3 Plugin provider memori contoh

**Tujuan.** Ada satu provider memori eksternal yang benar-benar berguna, yang sekaligus
menjadi contoh lengkap untuk penulis plugin.

**Lingkup.**
- Plugin bawaan berjenis `backend` yang mengimplementasikan `MemoryProvider` dengan
  penyimpanan lokal: fakta disimpan di SQLite milik plugin, dicari dengan FTS5, dan diingat
  kembali lewat `prefetch` berdasarkan pesan pengguna.
- Tool milik provider (cari dan simpan) lewat `provider_tool_schemas`.
- Ingatan yang dikembalikan masuk ke `turn_context`, tidak pernah ke system prompt, dan
  dibungkus sebagai informasi latar.
- Dokumen singkat di direktori plugin yang menjelaskan tiap method antarmuka dan kapan
  dipanggil.
- Opsional, sebagai plugin kedua: satu provider yang dihosting.

**File.** `src/clite/bundled/plugins/ (direktori plugin baru)`,
`src/clite/agent/memory/provider.py`, `tests/agent/test_memory_and_delegation.py`,
`docs/spesifikasi/agent.md`.

**Rujukan Hermes.** `agent/memory_provider.py`, `plugins/memory/` (bandingkan dua
implementasi), `website/docs/developer-guide/memory-provider-plugin.md`.

**Selesai bila.**
- [ ] Tes: fakta yang disimpan di satu sesi teringat di sesi lain lewat `turn_context`.
- [ ] Tes: awalan kawat tetap stabil dengan provider aktif (ingatan giliran lama dikirim ulang
      persis sama).
- [ ] Tes: plugin hanya mengimpor API plugin.
- [ ] Baris "Provider contoh" di spesifikasi agent menjadi ✅.

**Ukuran.** M

**Bergantung pada.** -

---

### F6-T4 Server ACP

**Tujuan.** Editor yang berbicara Agent Client Protocol (Zed dan lainnya) bisa memakai C-lite
sebagai agent-nya.

**Lingkup.**
- `clite acp` menjalankan server ACP di atas stdio, di paket `src/clite/acp/` yang sekarang
  baru berupa penanda tempat.
- Method inti: inisialisasi dan negosiasi kemampuan, sesi baru, memuat sesi, prompt,
  pembatalan. Pembaruan sesi (potongan pesan, tool call dan statusnya, rencana dari `todo`)
  dikirim sebagai notifikasi.
- Permintaan izin ACP dipetakan ke callback `approve`; diam berarti tolak.
- Server dibangun di atas `ChatSession`, sama seperti RPC: tidak ada logika percakapan di
  dalamnya.
- Stdout adalah kawat; aturan yang sama dengan `src/clite/rpc/entry.py`.
- Periksa versi protokol ACP yang berlaku saat task ini dikerjakan; spesifikasinya masih
  bergerak.

**Di luar lingkup.** Kemampuan sisi klien (editor membaca file atau menjalankan terminal atas
nama agent). Catat sebagai task lanjutan.

**File.** `src/clite/acp/server.py (baru)`, `src/clite/acp/session.py (baru)`,
`src/clite/acp/__init__.py`, `src/clite/cli/subcommands/misc.py`,
`tests/acp/test_acp.py (baru)`, `docs/spesifikasi/acp.md (baru)`.

**Rujukan Hermes.** `acp_adapter/server.py`, `acp_adapter/session.py`,
`acp_adapter/events.py`, `acp_adapter/permissions.py`, `acp_adapter/tools.py`,
`website/docs/developer-guide/acp-internals.md`.

**Selesai bila.**
- [ ] Tes dengan klien berskrip lewat pipa: satu giliran dengan tool call dan satu permintaan
      izin, dari inisialisasi sampai selesai.
- [ ] Tes: `print` nyasar dari sebuah tool tidak merusak aliran protokol.
- [ ] Dicoba dengan tangan di satu editor dan dicatat di `docs/STATUS.md`.
- [ ] `clite acp` tidak lagi mencetak penunjuk ke roadmap, dan baris ACP di spesifikasi cli
      menjadi ✅.

**Ukuran.** L

**Bergantung pada.** -

---

### F6-T5 Ekosistem plugin

**Tujuan.** Plugin bisa ditemukan, diperbarui, dan diberi kemampuan lebih, tanpa melonggarkan
aturan opt-in.

**Lingkup.** Satu sub-langkah per butir.
1. **Asal-usul dan pembaruan.** Catat sumber dan commit saat memasang; `clite plugins update`
   menunjukkan apa yang berubah sebelum mengganti, dan plugin yang diperbarui kembali
   **nonaktif** sampai pengguna mengaktifkannya lagi.
2. **Katalog.** Indeks plugin dari sebuah repositori; `clite plugins search`.
3. **Dependensi.** `pip_dependencies` di manifest ditampilkan sebagai perintah yang harus
   dijalankan pengguna. Tidak ada pemasangan otomatis.
4. **Jenis `exclusive`.** Tegakkan "hanya satu aktif per kategori", yang sekarang baru
   dikenali.
5. **`ctx.llm`.** Akses plugin ke model bantu dengan anggaran per plugin dan tanpa akses ke
   riwayat percakapan.
6. **Hook tambahan** yang dibutuhkan plugin nyata, masing-masing dengan alasan tertulis dan
   keputusan gagal-terbuka atau gagal-tertutup.
7. **Halaman dashboard dari plugin**, dimuat dalam bingkai terisolasi dengan origin sendiri.

**File.** `src/clite/plugins/manager.py`, `src/clite/plugins/context.py`,
`src/clite/plugins/manifest.py`, `src/clite/plugins/hooks.py`,
`src/clite/cli/subcommands/plugins.py`, `src/clite/server/app.py`,
`tests/plugins/test_manager.py`.

**Rujukan Hermes.** `hermes_cli/plugins_cmd_update.py`, `hermes_cli/plugins_cmd_catalog.py`,
`hermes_cli/plugins_provenance.py`, `plugin-catalog/`, `agent/plugin_llm.py`,
`website/docs/developer-guide/plugin-llm-access.md`,
`website/docs/developer-guide/middleware.md`,
`website/docs/developer-guide/observer-hooks.md`.

**Selesai bila.**
- [ ] Tes: plugin yang diperbarui tidak berjalan sampai diaktifkan lagi.
- [ ] Tes: dua plugin `exclusive` dalam kategori yang sama tidak bisa aktif bersamaan.
- [ ] Tes: `ctx.llm` berhenti pada anggarannya dan tidak pernah menerima pesan sesi.
- [ ] Baris terkait di spesifikasi plugins menjadi ✅, satu per sub-langkah.

**Ukuran.** L

**Bergantung pada.** -

---

### F6-T6 Context engine alternatif

**Tujuan.** Ada lebih dari satu strategi untuk menjaga percakapan muat di jendela, dan penulis
plugin punya cara memastikan engine buatannya benar.

**Lingkup.**
- Engine kedua sebagai plugin bawaan: jendela geser tanpa peringkasan (murah, tanpa panggilan
  model bantu), untuk dibandingkan dengan kompresor bawaan.
- Engine ketiga bila provider mendukungnya: kompaksi di sisi provider. Perhatikan aturan A2:
  apa pun yang dilakukan provider terhadap riwayat harus tetap membuat permintaan berikutnya
  sah.
- **Tes kontrak** yang bisa dipakai ulang: satu fungsi yang menerima sebuah `ContextEngine`
  dan memeriksa semua janji antarmukanya (tidak mengubah masukan, tidak memisahkan tool call
  dari hasilnya, peran tetap berselang, hasil lebih kecil dari masukan). Kompresor bawaan dan
  engine baru sama-sama dijalankan terhadapnya.

**File.** `src/clite/bundled/plugins/ (direktori plugin baru)`,
`src/clite/agent/context/engine.py`, `src/clite/agent/context/contract.py (baru)`,
`tests/agent/test_compression.py`, `docs/spesifikasi/agent.md`.

**Rujukan Hermes.** `agent/context_engine.py`, `plugins/context_engine/`,
`agent/native_compaction.py`,
`website/docs/developer-guide/context-engine-plugin.md`.

**Selesai bila.**
- [ ] Tes kontrak lulus untuk setiap engine yang terdaftar.
- [ ] Tes: engine dipilih lewat `context.engine`, dan nama yang tidak dikenal jatuh ke
      kompresor bawaan dengan peringatan.
- [ ] Resep "Menambah context engine" di `src/clite/agent/AGENTS.md` merujuk tes kontrak.

**Ukuran.** M

**Bergantung pada.** F2-T11

---

### F6-T7 Suara

**Tujuan.** Pengguna bisa mengirim pesan suara di chat dan mendengar jawaban agent.

**Lingkup.**
- Registry `TranscriptionProvider` dan `SpeechProvider`, masing-masing dengan satu plugin
  provider.
- Masuk: pesan suara di gateway ditranskripsi sebelum menjadi giliran; transkripnya tampil
  sebagai teks pengguna.
- Keluar: tool `text_to_speech` yang menghasilkan file audio dan mengirimnya lewat
  `send_file`; opsi per platform untuk selalu membalas pesan suara dengan suara.
- Batas durasi dan ukuran; kunci provider terdaftar sebagai kredensial.

**Di luar lingkup.** Percakapan suara waktu nyata dan kata pemicu.

**File.** `src/clite/tools/builtin/speech.py (baru)`, `src/clite/gateway/media.py (dibuat F4-T4)`,
`src/clite/gateway/runner.py`, `src/clite/plugins/context.py`,
`src/clite/bundled/plugins/ (plugin provider baru)`, `tests/gateway/test_gateway.py`.

**Rujukan Hermes.** `tools/transcription_tools.py`, `tools/tts_tool.py`,
`agent/transcription_provider.py`, `agent/tts_provider.py`, `tools/voice_mode.py`.

**Selesai bila.**
- [ ] Tes: pesan suara dari adapter `local` menjadi giliran dengan transkrip dari provider
      tiruan.
- [ ] Tes: `text_to_speech` tidak ditawarkan tanpa provider yang terkonfigurasi.
- [ ] Dicoba dengan tangan di Telegram dan dicatat di `docs/STATUS.md`.

**Ukuran.** L

**Bergantung pada.** F4-T4

---

### F6-T8 Batch runner dan ekspor lintasan

**Tujuan.** Banyak prompt bisa dijalankan tanpa pengawasan dengan hasil yang terekam, dan
percakapan bisa diekspor dalam format yang dipakai untuk evaluasi dan pelatihan.

**Lingkup.**
- `clite batch run <file.jsonl> --workers N --out <dir>`: tiap baris adalah satu prompt
  dengan pengaturannya, dijalankan di sesi baru pada platform `batch` (tanpa pengguna untuk
  ditanya; perintah berbahaya mengikuti kebijakan non-interaktif).
- Bisa dilanjutkan: baris yang sudah selesai dilewati saat perintah dijalankan ulang.
- Hasil per baris: jawaban akhir, alasan berakhir, pemakaian token, biaya, durasi.
- `clite sessions export --format trajectory`: pesan, tool call, dan hasilnya dalam satu
  format yang didokumentasikan, **diredaksi**, dan tanpa `provider_data`.

**File.** `src/clite/runtime/batch.py (baru)`, `src/clite/cli/subcommands/batch.py (baru)`,
`src/clite/cli/subcommands/sessions.py`, `src/clite/runtime/factory.py`,
`tests/runtime/test_batch.py (baru)`.

**Rujukan Hermes.** `batch_runner.py`, `agent/trajectory.py`, `trajectory_compressor.py`,
`website/docs/developer-guide/trajectory-format.md`.

**Selesai bila.**
- [ ] Tes: batch tiga prompt dengan dua pekerja menghasilkan tiga hasil, dan menjalankan ulang
      tidak mengulang yang sudah selesai.
- [ ] Tes: satu prompt yang gagal tidak menghentikan batch.
- [ ] Tes: ekspor lintasan tidak memuat nilai kredensial yang dikenal.

**Ukuran.** M

**Bergantung pada.** -

---

### F6-T9 Situs dokumentasi pengguna

**Tujuan.** Pengguna yang tidak akan pernah membuka kode punya dokumentasi: pasang, mulai
cepat, konfigurasi, tool, skill, plugin, gateway, keamanan.

**Lingkup.**
- Dokumen di `docs/` sekarang ditulis untuk orang yang **mengubah** kode. Dokumentasi pengguna
  adalah kumpulan terpisah, ditulis dari sudut pandang orang yang **memakai**.
- Putuskan bahasa (Indonesia, Inggris, atau keduanya) sebelum menulis.
- Pembangkit situs statis, diterbitkan lewat GitHub Pages pada setiap rilis.
- Halaman rujukan (perintah, slash command, kunci config, tool) dihasilkan dari kode oleh
  `scripts/gen_docs.py`, sehingga tidak pernah tertinggal.
- Setiap contoh perintah di dokumentasi dijalankan oleh tes terhadap provider `mock`.

**File.** `website/ (baru)`, `scripts/gen_docs.py`, `.github/workflows/docs.yml (baru)`,
`README.md`.

**Rujukan Hermes.** `website/docs/`, `website/docusaurus.config.ts`, `website/sidebars.ts`.

**Selesai bila.**
- [ ] Situs terbit, dan tautannya ada di `README.md`.
- [ ] Tes: halaman rujukan pengguna sama dengan keluaran pembangkitnya.
- [ ] Tes: contoh perintah di halaman mulai cepat berjalan apa adanya.

**Ukuran.** M

**Bergantung pada.** F1-T7

**Butuh dari Anda.** Keputusan bahasa dan nama domain bila tidak memakai alamat GitHub Pages
bawaan.
