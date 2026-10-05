# C-lite: aturan kerja

C-lite adalah agent AI pribadi: satu inti percakapan (`src/clite/agent/`) yang dilayani CLI,
TUI, dashboard, aplikasi desktop, dan gateway pesan. Arsitekturnya diturunkan dari Hermes
Agent, dan fiturnya ditumbuhkan bertahap mengikuti `docs/roadmap/`.

File ini berlaku untuk seluruh repositori. Tiap area (`src/clite/<area>/`, `tests/`, `ui-tui/`,
`apps/`) punya `AGENTS.md` sendiri berisi aturan dan resep khusus area itu. Baca file area
sebelum mengubah apa pun di dalamnya.

## Perintah

    pip install -e ".[dev]"                             # sekali
    npm install                                         # sekali; untuk type check dan build TypeScript
    scripts/run_tests.sh                                # semuanya: ruff, mypy, pytest, tes TypeScript
    scripts/run_tests.sh python tests/agent -k compress # sebagian
    python -m clite chat -q "halo" --provider mock      # satu giliran tanpa kunci API

Sesudah mengubah sesuatu yang punya turunan, buat ulang turunannya. Suite gagal bila terlupa.

| Yang diubah | Jalankan |
|---|---|
| Tool, slash command, sub-perintah, method RPC, kunci config, simbol publik | `python scripts/gen_docs.py` |
| `src/clite/rpc/contracts/schema.py` | `python scripts/gen_rpc_contracts.py` |
| `ui-tui/src/` atau `apps/shared/src/` | `node build.mjs` di `ui-tui/`, lalu commit `src/clite/tui_dist/` |
| Dokumen yang merujuk file Hermes | `python scripts/check_hermes_refs.py --hermes ../hermes-ref` |

## Di mana mencari

| Yang dicari | Tempatnya |
|---|---|
| Peta semua dokumen | `docs/README.md` |
| Apa yang sudah terbukti jalan dan apa yang belum | `docs/STATUS.md` |
| Paket apa boleh mengimpor paket apa; di mana kode baru diletakkan | `docs/arsitektur/01-lapisan.md` |
| Aturan yang tidak boleh dilanggar, lengkap dengan tes penjaganya | `docs/arsitektur/03-invarian.md` |
| Kontrak dan status tiap modul | `docs/spesifikasi/<modul>.md` |
| Daftar tool, perintah, method RPC, kunci config (dihasilkan dari kode) | `docs/referensi/katalog.md` |
| Modul mana berisi apa (dihasilkan dari kode) | `docs/referensi/peta-modul.md` |
| Pekerjaan berikutnya | `docs/roadmap/README.md` |
| Padanan file Hermes | `docs/hermes/99-peta-file.md` |
| Bekerja dengan model atau harness selain Claude Code | `docs/PANDUAN-MODEL-LAIN.md` |

## Aturan yang tidak boleh dilanggar

Ringkasan dari `docs/arsitektur/03-invarian.md`. Hampir semuanya dijaga tes; yang gagal akan
menyebut aturannya.

1. **Yang sudah dikirim ke model tidak pernah berubah.** System prompt dibangun sekali per
   sesi. Setiap permintaan mengulang permintaan sebelumnya dan menambah di ujungnya. Informasi
   per giliran masuk ke `turn_context` pesan pengguna atau ke hasil tool, tidak ke prompt.
2. **Riwayat tersimpan hanya bertambah.** Yang menulis ulang hanya kompresi.
3. **Import mengarah ke bawah lapisan.** `core` adalah daun. Yang dipakai dua surface tinggal
   di `runtime`. Tabel peringkatnya ada di `tests/test_architecture.py`.
4. **Inti sempit.** Kemampuan baru adalah tool, skill, plugin, profil provider, atau fase di
   `agent/turn/`. `agent/agent.py` dan `agent/loop.py` tidak menampung perilaku baru.
5. **Tidak ada nama vendor di luar profil provider-nya.** Yang berbeda antar-vendor adalah
   method pada `ProviderProfile`.
6. **Dideklarasikan sekali.** Tool, slash command, kontrak RPC, kunci config, dan hook
   masing-masing punya satu tempat deklarasi. Kunci config tanpa pembaca menggagalkan suite.
7. **Home dinamis.** Path didapat dari `core.constants` saat dipanggil, tidak dieja dan tidak
   disimpan di konstanta modul. Thread untuk pekerjaan sesi dimulai dengan
   `core.threads.start_thread`.
8. **Rahasia hanya di `.env`**, dibaca dengan `get_secret`, didaftarkan supaya tidak sampai ke
   perintah yang dijalankan agent dan diredaksi dari apa pun yang dibaca model.
9. **Keputusan boleh atau tidak gagal ke "tidak"; pengamat tidak pernah menghentikan
   giliran.** Tidak ada yang dilempar ke model atau ke surface: galat adalah hasil.
10. **Kode dari luar tidak berjalan tanpa tindakan eksplisit pengguna**, dan teks dari luar
    dipindai sebelum masuk system prompt. Aturan keamanan untuk kode baru ada di
    `docs/arsitektur/06-keamanan.md`.
11. **Kode pustaka tidak mencetak.** Pakai logging, kembalikan teks ke surface, atau panggil
    callback. Pada transport stdio, stdout adalah kawat protokol.

Bila sebuah tugas tampak menuntut pelanggaran salah satunya, berhenti dan jelaskan
pertentangannya. Itu tanda rancangan tugasnya yang perlu diubah.

## Cara bekerja di sini

**Bahasa.** Dokumen (`docs/`, setiap `AGENTS.md`, prompt) berbahasa Indonesia. Kode, nama,
docstring, komentar, pesan log, keluaran CLI, dan pesan commit berbahasa Inggris.

**Tes.**
- Setiap perilaku baru punya tes yang gagal bila perilaku itu dilepas. Pastikan sekali dengan
  menjalankan tes tanpa perubahannya, di salinan terpisah dan dengan batas waktu.
- Nama tes adalah kalimat tentang perilaku. Daftar nama tes sebuah modul terbaca sebagai
  spesifikasinya.
- Tes tidak memakai jaringan dan tidak menyentuh home asli. Model ditiru dengan
  `ScriptedClient`; ujung jauh ditiru dengan server lokal sungguhan. Lihat `tests/AGENTS.md`.
- Tes yang gagal tidak diperbaiki dengan melemahkannya.

**Status ditulis jujur.** Tanda ✅ di spesifikasi berarti ada tes yang menjaganya. Kode yang
ditulis tetapi belum pernah dijalankan terhadap hal yang sebenarnya (API asli, platform asli,
sistem operasi lain) dicatat sebagai belum diverifikasi di `docs/STATUS.md`.

**Dokumen berubah bersama kode**, dalam commit yang sama: kontrak dan baris status di
spesifikasi modul, indeks roadmap, dan `docs/STATUS.md`. Dokumen tidak boleh menyebut file,
tes, atau task yang tidak ada; `tests/test_docs.py` memeriksanya.

**Gaya kode** yang tidak bisa ditebak dari alat:
- Docstring modul menjelaskan apa tanggung jawab modul itu; baris pertamanya masuk ke peta
  modul. Komentar menjelaskan *mengapa*, bukan *apa*.
- Tidak ada kode mati, tidak ada pengaturan yang tidak dibaca, tidak ada parameter "untuk
  nanti".
- Pesan galat untuk pengguna dan untuk model menyebut apa yang salah dan apa yang bisa
  dilakukan berikutnya.

**Dependensi.** Paket wajib hanya untuk yang dibutuhkan setiap sesi, selalu dengan batas atas.
Yang khusus satu provider, platform, atau fitur masuk ke extra atau ke plugin. Menambah
dependensi disebut di laporan.

**Commit.** Kalimat perintah berbahasa Inggris yang menyebut apa dan mengapa. Satu perubahan
logis per commit. Jangan push kecuali diminta.

**Lingkup.** Kerjakan yang diminta. Hal lain yang ditemukan dilaporkan, tidak diperbaiki
sambil lalu, kecuali bug yang menghalangi pekerjaan atau celah keamanan.

## Membawa sesuatu dari Hermes

Baca file Hermes yang dirujuk langsung di clone `../hermes-ref` (commit-nya dicatat di
`docs/hermes/README.md`), bukan dari ingatan. Ambil perilaku dan kasus tepinya, lalu tulis
mengikuti bentuk proyek ini. Tabel penyesuaiannya ada di
`docs/arsitektur/07-beda-dengan-hermes.md`.

## Jebakan

- `AIAgent.config` adalah potret saat agent dibuat. Di dalam agent pakai `agent.config`, di
  tool pakai `ctx.setting(...)`; jangan memanggil `load_config()` di tengah giliran.
- Registry dan cache baru yang hidup sepanjang proses butuh fungsi reset yang didaftarkan di
  `tests/conftest.py`, kalau tidak satu tes membocorkan state ke tes berikutnya.
- Tool bisa dipanggil dari thread pekerja saat satu ronde berjalan paralel.
- Path di dalam dokumen diperiksa mesin: path dalam backtick merujuk repositori ini, kecuali
  di `docs/hermes/` dan di paragraf yang menyebut Hermes. File yang belum ada ditulis
  `path (baru)`.

## Berhenti dan laporkan bila

- Tugas menuntut pelanggaran aturan di atas, atau mengubah kontrak di spesifikasi tanpa
  diminta.
- Ada yang dibutuhkan dari pemilik proyek: kunci API, akun, keputusan produk.
- Tes yang ada gagal dan tidak jelas mana yang salah, kode atau harapan tesnya.
- Perbaikan yang benar ternyata jauh lebih besar dari tugasnya.
