# Tambah provider model

**Kapan dipakai.** Untuk menambah satu provider inferensi yang belum ada di
`src/clite/bundled/plugins/model-providers/`.

**Di Claude Code:** `/tambah-provider <nama>`

**Isian.** `<PROVIDER>`: nama provider, alamat dokumentasi API-nya, dan apakah Anda punya
kunci untuk mengujinya.

## Prompt

Tambahkan provider model `<PROVIDER>` ke repositori ini.

**Hasil yang diminta.** Pengguna bisa menjalankan `clite setup`, memilih provider ini,
memasukkan kuncinya, dan bercakap-cakap dengan tool call yang berfungsi.

**Yang dibaca dulu.** `src/clite/providers/AGENTS.md` (resep "Menambah provider yang
kompatibel dengan OpenAI"), `docs/spesifikasi/providers.md`, satu profil yang ada sebagai
contoh (`src/clite/bundled/plugins/model-providers/openrouter/`), dan dokumentasi API provider
itu.
Bila Hermes punya profilnya di `plugins/model-providers/` pada clone rujukan, baca juga:
keanehan provider biasanya sudah tercatat di sana.

**Batasan.**
- Provider adalah satu direktori profil. Tidak ada nama provider di kode inti; yang berbeda
  dari perilaku umum menjadi method yang di-override pada `ProviderProfile`. Bila method yang
  dibutuhkan belum ada, tambahkan ke kelas dasarnya dengan default yang tidak mengubah
  provider lain.
- Protokol kawat yang sudah ada dipakai ulang. Transport baru hanya bila protokolnya memang
  berbeda.
- `env_vars` diisi, supaya kuncinya dikenal sebagai kredensial.
- Override hanya untuk keanehan yang terbukti dari dokumentasi atau dari panggilan sungguhan.
  Jangan menyalin daftar override dari provider lain "untuk berjaga-jaga".

**Bukti.**
- Tes resolusi rute dan bentuk permintaan terhadap `fake_api`, termasuk satu ronde tool.
- Bila ada kunci: satu tes bertanda `network` yang benar-benar memanggil provider itu.
- Baris provider di tabel status `docs/spesifikasi/providers.md`, dengan keterangan jujur:
  sudah dipanggil sungguhan pada tanggal berapa, atau belum.
- `python scripts/gen_docs.py` dijalankan, dan `scripts/run_tests.sh` lulus.
