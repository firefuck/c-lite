# 13. Aturan Rekayasa Hermes yang Layak Diwarisi

Sebagian besar isi `AGENTS.md` Hermes bukan penjelasan arsitektur, melainkan **aturan
yang lahir dari insiden nyata**. Bab ini menyarikannya. Aturan-aturan ini sudah
diadaptasi ke `AGENTS.md` proyek ini, sehingga AI yang mengerjakannya ikut terikat.

## Bentuk kode

### Fasad dan saudara

Hermes pernah punya file raksasa (`run_agent.py`, `cli.py`, `gateway/run.py`) dan
memecahnya. Polanya:

- **Fasad** `<nama>.py` memuat pintu masuk publik dan nama yang diimpor paket lain.
- **Saudara** `<nama>_<topik>.py` di folder yang sama, masing-masing memiliki satu topik.
- Saudara boleh saling mengimpor dan boleh mengimpor fasad secara tertunda di dalam fungsi. Fasad tidak pernah mengimpor saudara di tingkat modul sekaligus diimpor saudara itu di tingkat modul.
- **Cari kode berdasarkan topik, bukan lewat fasad**: `grep -rn "def nama" <dir>/<stem>_*.py`.

Batas yang memicu pemecahan: file melewati sekitar 2.000 baris, atau fungsi melewati
sekitar 300 baris atau kompleksitas siklomatik 30. Pecah **dulu**, dalam commit sendiri.
Perilaku baru masuk ke saudara baru atau saudara topikal, tidak pernah ditempel ke fasad.

### Tabel, bukan tangga

Tidak ada tangga `if/elif` dengan empat cabang atau lebih yang dikunci nama atau jenis.
Pakai kamus atau tabel yang memetakan ke handler. Contoh di Hermes: `_SLASH_DISPATCH`,
`_command_handler_table`, `INLINE_TOOL_EXECUTORS`, `_DYNAMIC_SCHEMA_REWRITERS`, tabel
method RPC.

### Tanpa hiasan pertahanan

- Tidak ada pembungkus "pertahanan berlapis", `try/except: pass` di sekitar kode yang tidak bisa gagal, atau flag yang tidak pernah disetel siapa pun.
- Docstring dan komentar menyimpan **alasan**, membuang **apa**.
- Tidak ada shim ekspor ulang untuk perpindahan internal. Path internal bukan API.
- Memindahkan simbol berarti memperbaiki dokumennya di PR yang sama.

### Jangan menebak identitas proses dari potongan argv

`"serve" in cmdline` adalah kelas bug yang menyebabkan sekitar sepuluh insiden pembaruan.
Pakai pencocok kanonik; himpunan flag **diturunkan dari parser**, tidak ditulis tangan.
Kehidupan proses adalah pasangan `(pid, waktu mulai)`, tidak pernah keberadaan PID saja.

### Fakta mesin lewat satu pintu

Keluarga OS, arsitektur, WSL, kontainer: satu modul yang menjawab, di-cache per proses,
tanpa masukan variabel lingkungan. `shutil.which` polos atau tabel path buatan tangan di
luar modul itu gagal di test.

## Konfigurasi

- `.env` untuk **rahasia saja**. Pengaturan perilaku masuk `config.yaml`.
- Kunci baru masuk `DEFAULT_CONFIG` dan tergabung otomatis. Versi konfigurasi dinaikkan hanya untuk migrasi.
- Setiap kunci punya pembaca, setiap pembaca punya entri. Kunci baru disertai satu test invarian yang menyetelnya di `config.yaml` sementara dan menegaskan perilakunya lewat pemuat yang dipakai permukaan konsumennya.
- Satu jahitan penulis konfigurasi.
- Integrasi baru menyatu dengan alur setup yang ada (`hermes tools`, `hermes setup`), tidak menyuruh pengguna menyetel env var.

## Aman terhadap profil

- Tidak ada `~/.hermes` yang ditulis harfiah.
- Tidak ada konstanta modul yang diturunkan dari home, konfigurasi, atau `.env`.
- Kode yang berjalan di luar giliran (probe awal, akhir sesi, detak, callback tertunda, method RPC) mengikat lingkup profil pemiliknya secara eksplisit.
- Thread baru dari kode berlingkup menyalin ContextVar. Proses anak menerima lingkungan yang dibangun eksplisit, tidak pernah `os.environ.copy()`.
- Buktikan dengan **dua home** (A, B, lalu A lagi), bukan satu `HERMES_HOME` sementara.

## Pengujian

### Jalankan lewat pembungkus, bukan `pytest` polos

`scripts/run_tests.sh` menegakkan kesetaraan dengan CI: variabel kredensial dikosongkan,
`TZ=UTC`, `LANG=C.UTF-8`, `HERMES_HOME` diarahkan ke direktori sementara, dan isolasi
subproses per file. `pytest` langsung di mesin yang punya kunci API berulang kali
menyebabkan "jalan di lokal, gagal di CI".

### Test tidak boleh menulis ke home pengguna

Fixture otomatis `_isolate_hermes_home` di `tests/conftest.py` mengalihkan home. Test
profil juga meniru `Path.home()`.

### Kontrak perilaku, bukan potret

**Test pendeteksi perubahan dilarang.** Test semacam itu gagal setiap kali data yang
memang *diharapkan berubah* diperbarui: katalog model, versi konfigurasi, jumlah
enumerasi.

| Jangan | Lakukan |
|---|---|
| `assert "gemini-2.5-pro" in _PROVIDER_MODELS["gemini"]` | `assert "gemini" in _PROVIDER_MODELS and len(_PROVIDER_MODELS["gemini"]) >= 1` |
| `assert DEFAULT_CONFIG["_config_version"] == 21` | `assert raw["_config_version"] == DEFAULT_CONFIG["_config_version"]` |
| `assert len(models) == 8` | Setiap model di katalog punya entri panjang konteks |

Bila sebuah test terbaca seperti potret, hapus. Bila terbaca seperti kontrak antara dua
data, pertahankan.

### Jangan membaca source code di dalam test

Test yang membaca teks file `.py` atau `.ts` menguji **bentuk source**, bukan perilaku.
Ia lolos ketika implementasi rusak halus dan gagal pada refactor yang benar. Ekstrak
logikanya menjadi fungsi murni yang bisa disuntik ketergantungannya, lalu panggil. Bila
ekstraksi terasa mengganggu karena logikanya terkubur di file raksasa, itulah tanda
untuk mengekstrak.

### E2E, bukan hanya mock hijau

Apa pun yang menyentuh rantai resolusi, propagasi konfigurasi, batas keamanan, backend
jarak jauh, atau I/O file dan jaringan harus menguji jalur nyata dengan impor nyata
terhadap home sementara. Mock menyembunyikan bug integrasi.

Uji handler tool **lewat registry**, tidak hanya fungsi telanjangnya. Tegaskan kontrak
("setiap tool terdaftar punya toolset"), bukan jumlah tool.

### Tambal di tempat produksi membaca

Saudara sering melakukan `from <fasad> import nama` di dalam fungsi, sehingga
`monkeypatch.setattr(fasad, "nama", ...)` adalah jahitannya. Tambalan pada modul yang
mendefinisikan lolos diam-diam. Hermes pernah merusak lebih dari 130 test karena
mengarahkan ulang target tambalan secara buta.

### Jangan memalsukan sistem operasi

Perilaku yang sungguh berbeda per host diuji **di host itu** dengan penanda platform,
tidak dengan menambal `sys.platform`. Bila test butuh interpreter percaya ia berada di
OS lain agar lolos, test itu milik OS tersebut.

### Kebijakan flake dan waktu

File yang gagal dicoba ulang sekali di subproses baru; lolos-saat-diulang tetap dicetak
sebagai flaky dan dianggap bug. Test waktu memakai batas longgar (minimal 2 detik) dan
sinkronisasi berbasis event.

### Penempatan

Test mencerminkan pohon source: `tests/<direktori source>/`. Tanpa nomor isu di nama
file. Test Python yang menegaskan isi `package.json` atau source `.ts` tidak akan jalan
pada PR khusus JS, jadi tempatnya di suite vitest.

## Ketergantungan

Semua ketergantungan punya batas atas, setelah insiden rantai pasok.

- Ketergantungan langsung inti dipin **tepat** (`==X.Y.Z`).
- Hanya paket yang dipakai **setiap** sesi yang masuk ketergantungan inti. Yang khusus penyedia masuk extra dan dipasang saat pengguna memilih backend itu.
- URL git dipin ke SHA 40 karakter. GitHub Actions dipin ke SHA.
- `exclude-newer = "14 days"`: karantina dua minggu untuk paket baru.

Untuk proyek baru, cukup mulai dengan rentang berbatas atas (`>=X,<Y`) dan berkas kunci,
lalu perketat seiring matang.

## Commit dan PR

- Squash merge dari cabang basi diam-diam membatalkan perbaikan terbaru. Bawa cabang ke `main` dulu.
- 1 sampai 2 test **invarian** per perbaikan, terbukti merah di basis.
- PR fitur: setiap baris terlacak ke permintaan. PR refactor yang dinyatakan: permintaannya *adalah* ekstraksi itu.

## Periksa premis sebelum menyebutnya bug

Alasan paling umum PR yang ditulis rapi ditutup adalah **premis yang salah**, atau
menganggap **desain yang disengaja** sebagai celah.

- **"Desain yang disengaja, bukan celah."** Tanyakan apakah isolasi itu memang desainnya. Baca `git log -p -S "<simbol>"` sebelum menganggap sesuatu belum selesai.
- **"Premisnya tidak bertahan terhadap cara kerja sebenarnya."** Telusuri runtime nyata. Bila Anda tidak bisa menunjuk baris tempat bug muncul **dan** menunjukkan perbaikan mengubah perilaku baris itu, premisnya belum terverifikasi.
- **"Ketiadaan itu disengaja."** Ada berkas yang sengaja tidak dibuat karena keberadaannya merusak sesuatu.
- **"Melampaui cakupan."** Perluasan di luar yang disepakati ditolak walau berjalan.

Benang merahnya: verifikasi klaim **dan** niat terhadap kode sebelum menulis perbaikan.

## Yang diinginkan dan yang ditolak

**Diinginkan:** memperbaiki bug nyata beserta seluruh kelasnya; memperluas jangkauan di
tepi (adapter, penyedia, model, fitur UI); memecah file raksasa; menjaga inti tetap
sempit; memperluas yang ada alih-alih menduplikasi; kontrak perilaku; validasi E2E; aman
terhadap cache, selang-seling, dan invarian.

**Ditolak walau dibangun dengan baik:**

- Infrastruktur spekulatif: hook atau titik perluasan tanpa konsumen nyata.
- Variabel lingkungan baru untuk konfigurasi bukan rahasia.
- Tool inti baru ketika terminal ditambah file, atau skill, sudah cukup.
- Jalan pintas baca-malas pada tool instruksi (`offset` dan `limit` pada pemuat skill).
- "Perbaikan" yang menghancurkan fitur yang diamankannya.
- Telemetri keluar tanpa gerbang persetujuan pengguna.
- Test pendeteksi perubahan, pemutusan cache di tengah percakapan, kode mati yang disambung tanpa bukti E2E, plugin yang menyentuh berkas inti.
- Produk pihak ketiga yang diintegrasikan ke pohon inti.

## Keamanan

- Kerentanan yang belum diungkap dilaporkan secara privat, tidak lewat isu publik.
- Batas kepercayaan didefinisikan di `SECURITY.md`. Lolosnya gerbang persetujuan, redaksi, atau injeksi prompt tanpa akibat berantai digolongkan sebagai pengerasan biasa, bukan kerentanan.
- Agent tidak bisa membaca `~/.hermes/.env` atau mengubah source-nya sendiri dari dalam backend terisolasi.

## Rujukan di Hermes

`AGENTS.md`, `CONTRIBUTING.md`, `SECURITY.md`, `tests/conftest.py`, `scripts/run_tests.sh`,
`scripts/check_config_yaml_writers.py`, `scripts/check_profile_scope_patterns.py`,
`evals/codebase_navigability/`.
