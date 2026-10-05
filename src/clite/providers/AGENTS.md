# providers: aturan kerja

Dari "model X" ke satu panggilan HTTP, dan dari jawaban provider ke `NormalizedResponse`.
Spesifikasi: `docs/spesifikasi/providers.md`.

Tes: `pytest tests/providers -q`

## Aturan yang tidak boleh dilanggar

1. **Tidak ada nama provider di kode inti.** Tidak ada `if provider == "..."` di luar profil.
   Perilaku khusus masuk ke method profil yang di-override.
2. **Hanya mengimpor `core`.** Paket ini berada di lapisan 1.
3. **Transport tidak menyentuh jaringan.** Ia membangun `HttpRequest`, mem-parse respons, dan
   merakit stream. Jaringan hanya di `http.py`.
4. **Loop tidak membaca kode status.** Pengetahuan baru tentang sebuah galat masuk ke
   `errors.classify_api_error` sebagai petunjuk di `ClassifiedError`.
5. **Kunci tidak pernah keluar dari host asalnya, tidak pernah masuk log, tidak pernah masuk
   `describe()`.**
6. **Fakta tentang model harus punya sumber.** Sebelum mengubah apa yang dikirim ke sebuah
   model (parameter penalaran, batas token, header beta), baca dokumentasi provider yang
   berlaku sekarang dan catat tanggalnya di docstring profil. Jangan menulis dari ingatan:
   aturan ini berubah di setiap generasi model.

## Resep

### Menambah provider yang kompatibel dengan OpenAI

1. Buat `src/clite/bundled/plugins/model-providers/<nama>/__init__.py`.
2. Isi dengan `register_provider(ProviderProfile(name=..., env_vars=(...), base_url=..., ...))`.
   Contoh paling sederhana: `deepseek/`. Contoh dengan keanehan: `openrouter/`. Nama di
   `env_vars` otomatis terdaftar sebagai kredensial: dibuang dari lingkungan perintah yang
   dijalankan agent dan diredaksi dari apa yang dibaca model.
3. Tambahkan nama provider ke tes `test_bundled_providers_are_discovered`.
4. Jalankan `python scripts/gen_docs.py` (katalog provider ikut berubah).

Pengguna bisa melakukan hal yang sama tanpa menyentuh repositori: direktori yang sama di
`<home>/plugins/model-providers/`, atau bagian `providers:` di `config.yaml`.

### Menambah protokol kawat baru

1. Turunkan `ProviderTransport` dan `StreamAccumulator` (`transports/base.py`).
2. Daftarkan dengan `register_transport(...)` di akhir modul, lalu impor modul itu di
   `transports/base.py` bersama transport lain.
3. Tes: bentuk permintaan, parse respons, perakitan stream dari potongan SSE yang terpecah.
   Pola lengkapnya ada di `tests/providers/test_transports.py`.

### Mengajari pemulihan untuk galat baru

1. Tambahkan nilai `FailoverReason` bila perlu, dan aturannya di `_classify_http`.
2. Bila butuh tindakan baru, tambahkan petunjuk boolean di `ClassifiedError` dan tangani di
   `agent/turn/request.py::_recover`.
3. Tambahkan baris ke tabel parametris `test_classification`.

## Jebakan

- Pemeriksaan frasa di `_classify_http` berjalan sebelum pemeriksaan status, dan urutannya
  penting. Frasa baru yang terlalu umum akan menelan galat lain. Tambahkan juga kasus negatif
  di tes.
- `ProviderProfile` adalah dataclass yang bisa diubah dan dipakai bersama oleh semua sesi.
  Jangan menyimpan state per panggilan di dalamnya.
- `RuntimeRoute.with_model` dan `with_credential` mengembalikan rute baru. Rute lama tidak
  berubah.
- Pengujian HTTP memakai server lokal sungguhan (`fake_api` di `tests/providers/conftest.py`),
  bukan mock. Tes baru sebaiknya mengikuti pola itu.
