# Fase 1: fondasi terverifikasi

Semua kode di repositori ini lulus tesnya sendiri, tetapi sebagian belum pernah bertemu hal
yang sebenarnya: registry paket, GitHub Actions, API provider, Telegram, Windows. Fase ini
mengubah "ditulis" menjadi "terbukti jalan". Daftar yang belum terverifikasi ada di
[STATUS.md](../STATUS.md); setiap task di sini mencoret sebagian darinya.

Kerjakan F1-T1 lebih dulu. Semua task lain bergantung padanya.

Aturan yang berlaku untuk semua task ada di [README](README.md#selesai-itu-apa).

---

### F1-T1 Pasang di lingkungan nyata dan hijaukan CI

**Tujuan.** Siapa pun bisa meng-clone repositori, menjalankan dua perintah pasang, dan
melihat seluruh pemeriksaan lulus, di mesinnya dan di GitHub Actions.

**Lingkup.**
- Jalankan `pip install -e ".[dev]"` di lingkungan virtual bersih (Python 3.11, 3.12, 3.13).
  Perbaiki batas versi dependensi di `pyproject.toml` bila ada yang tidak teresolusi.
- Jalankan `npm install` di root, lalu `npm run typecheck`, `npm test`, dan `npm run build`.
  Rentang versi di `package.json` belum pernah dipasang lewat registry; sempitkan bila perlu
  dan commit `package-lock.json`.
- Jalankan `scripts/run_tests.sh` tanpa variabel lingkungan tambahan.
- Dorong ke GitHub dan buat `.github/workflows/ci.yml` hijau. Hal yang patut dicurigai lebih
  dulu: versi Node bawaan runner (tes bundle TUI butuh Node 22), tes yang butuh `playwright`
  (harus terlewati, bukan gagal), dan `mypy` terhadap versi dependensi yang berbeda. Runner
  juga memberi tahu bahwa label `ubuntu-latest` berpindah ke Ubuntu 26 mulai 19 Oktober 2026.
- Tambahkan job yang membangun wheel, memasangnya ke lingkungan bersih, lalu menjalankan
  `clite --version`, `clite doctor`, dan satu giliran dengan provider `mock`.

**Di luar lingkup.** Windows (F1-T5) dan rilis ke PyPI (F1-T7).

**File.** `pyproject.toml`, `package.json`, `ui-tui/package.json`, `apps/shared/package.json`,
`apps/desktop/package.json`, `.github/workflows/ci.yml`, `scripts/run_tests.sh`,
`docs/STATUS.md`.

**Rujukan Hermes.** `scripts/run_tests.sh` dan `scripts/install.sh` untuk melihat apa saja
yang diperiksa Hermes saat memasang.

**Selesai bila.**
- [ ] CI hijau di ketiga versi Python dan di job Node, pada commit di `main`.
- [ ] `package-lock.json` ada dan `npm ci` berhasil di CI.
- [ ] Job wheel membuktikan paket terpasang membawa plugin bawaan, skill bawaan, dashboard,
      dan bundle TUI (`clite tui --help` jalan dari wheel).
- [ ] Komentar "NOT VERIFIED" di `ci.yml` dihapus.
- [ ] Butir pemasangan dan CI di `docs/STATUS.md` dipindah dari "belum diverifikasi".

**Ukuran.** S

**Bergantung pada.** -

**Butuh dari Anda.** Akses dorong ke repositori GitHub dengan Actions aktif. Saat scaffolding
ini dibuat, workflow sudah terpicu di setiap push tetapi GitHub menolak semua job sebelum
berjalan, dengan pesan "account is locked due to a billing issue". Kunci itu dibuka di
pengaturan penagihan akun GitHub pemilik repositori; sebelum itu task ini tidak bisa selesai.

---

### F1-T2 Uji provider sungguhan

**Tujuan.** Transport `anthropic_messages` dan `chat_completions` terbukti benar terhadap API
yang asli, dan setiap selisih dari server tiruan ditangkap oleh tes yang berjalan tanpa
jaringan.

**Lingkup.**
- Tulis tes bertanda `@pytest.mark.network` yang hanya jalan bila kuncinya ada. Untuk
  Anthropic (`claude-fable-5-1` dan satu model generasi 4.5) dan satu provider kompatibel
  OpenAI: teks streaming, satu ronde tool, ronde tool paralel, pemakaian token termasuk cache
  baca di panggilan kedua, pembatalan di tengah stream.
- Untuk model Claude generasi 5: beberapa ronde tool berturut-turut dalam satu giliran, lalu
  giliran kedua, untuk membuktikan blok penalaran bertanda tangan diputar ulang dengan benar;
  lalu `/compress` dan `/model` di tengah percakapan untuk membuktikan `provider_data` dibuang
  pada saat yang tepat.
- Periksa `thinking.display`. Model generasi 5 secara default tidak mengirim teks penalaran,
  sehingga `display.show_reasoning` tidak menampilkan apa pun. Putuskan nilai yang dikirim,
  terapkan di profil `anthropic`, dan uji.
- Picu galat sungguhan dan bandingkan dengan `classify_api_error`: kunci salah, model tidak
  ada, batas laju, konteks meluap, penolakan.
- Simpan potongan respons asli (tanpa kunci) sebagai fixture dan putar ulang lewat `fake_api`,
  supaya perilaku yang baru diketahui dijaga tes biasa.

**File.** `src/clite/providers/transports/anthropic_messages.py`,
`src/clite/providers/transports/chat_completions.py`, `src/clite/providers/errors.py`,
`src/clite/bundled/plugins/model-providers/anthropic/__init__.py`,
`tests/providers/test_live.py (baru)`, `tests/providers/fixtures/ (baru)`,
`docs/spesifikasi/providers.md`.

**Rujukan Hermes.** `agent/transports/anthropic.py`, `agent/anthropic_adapter.py`,
`agent/anthropic_thinking_replay.py`, `agent/transports/chat_completions.py`,
`agent/error_classifier.py`, `agent/reasoning_summaries.py`.

**Selesai bila.**
- [ ] Tes jaringan lulus terhadap Anthropic dan satu provider kompatibel OpenAI.
- [ ] Setiap perbaikan yang lahir dari tes jaringan punya tes tanpa jaringan dengan fixture.
- [ ] Teks penalaran model generasi 5 tampil bila `display.show_reasoning: true`.
- [ ] Tabel "Aturan model Claude yang sudah diverifikasi" di spesifikasi providers diperbarui
      dengan tanggal dan apa yang benar-benar diamati.
- [ ] Baris "Panggilan ke provider sungguhan" berubah dari "belum diverifikasi".

**Ukuran.** M

**Bergantung pada.** F1-T1

**Butuh dari Anda.** `ANTHROPIC_API_KEY`, satu kunci provider kompatibel OpenAI (OpenRouter
atau OpenAI), dan anggaran beberapa dolar untuk panggilan uji.

---

### F1-T3 Uji Telegram sungguhan

**Tujuan.** Adapter Telegram terbukti jalan terhadap Bot API yang asli.

**Lingkup.**
- Jalankan `clite gateway run` dengan bot sungguhan dan lalui daftar periksa: pesan langsung,
  pairing orang asing, grup (mention, balasan, perintah untuk bot lain), jawaban lebih dari
  4096 karakter, persetujuan lewat `/approve`, klarifikasi, interupsi oleh pesan baru, restart
  gateway yang melanjutkan percakapan, dan job cron dengan `deliver: origin`.
- Uji juga `deliver: telegram:<chat id>`, yang belum punya tes sama sekali, dan tambahkan
  tesnya dengan adapter `local`.
- Setiap selisih antara Bot API tiruan di `tests/gateway/` dan yang asli diperbaiki **di
  tiruannya juga**, supaya suite menangkapnya.
- Pastikan token bot tidak pernah muncul di log, termasuk saat permintaan gagal.

**File.** `src/clite/gateway/platforms/telegram.py`, `src/clite/gateway/runner.py`,
`tests/gateway/test_gateway.py`, `docs/spesifikasi/gateway.md`, `docs/spesifikasi/cron.md`.

**Rujukan Hermes.** `plugins/platforms/telegram/adapter.py`,
`plugins/platforms/telegram/telegram_network.py`, `gateway/delivery.py`.

**Selesai bila.**
- [ ] Daftar periksa di atas dijalankan dan hasilnya dicatat di `docs/STATUS.md`.
- [ ] `deliver: <platform>:<chat id>` punya tes, dan nilainya divalidasi saat job dibuat.
- [ ] Ada tes bahwa galat jaringan adapter tidak menulis token ke log.
- [ ] Baris adapter Telegram di spesifikasi gateway menjadi ✅.

**Ukuran.** S

**Bergantung pada.** F1-T1

**Butuh dari Anda.** Token bot dari @BotFather dan satu grup uji.

---

### F1-T4 Pasang skill dari GitHub

**Tujuan.** `clite skills install owner/repo/path` bekerja terhadap GitHub yang asli.

**Lingkup.**
- Uji `GitHubSource` terhadap repositori publik sungguhan dengan tes bertanda `network`.
- Tangani yang pasti muncul di dunia nyata: batas laju tanpa token, `GITHUB_TOKEN` untuk
  repositori privat (daftarkan sebagai kredensial), cabang atau tag tertentu
  (`owner/repo/path@ref`), dan direktori yang isinya melebihi batas ukuran.
- Ganti tes yang ada dengan server HTTP lokal yang meniru API contents GitHub, mengikuti pola
  `fake_api`, supaya jalur unduh diuji tanpa jaringan.

**File.** `src/clite/skills/hub.py`, `src/clite/cli/subcommands/skills.py`,
`tests/skills/test_skills.py`, `docs/spesifikasi/skills.md`.

**Rujukan Hermes.** `tools/skills_hub_github.py`, `tools/skills_hub_install.py`.

**Selesai bila.**
- [ ] Memasang satu skill dari repositori publik sungguhan berhasil (tes `network`).
- [ ] Jalur unduh, batas ukuran, dan galat batas laju diuji tanpa jaringan.
- [ ] Token GitHub tidak pernah dikirim ke host selain `api.github.com` dan host unduhannya.
- [ ] Baris "Pasang dari GitHub" di spesifikasi skills menjadi ✅.

**Ukuran.** S

**Bergantung pada.** F1-T1

---

### F1-T5 Windows

**Tujuan.** Suite lulus di Windows dan CLI klasik bisa dipakai di sana.

**Lingkup.**
- Tambahkan `windows-latest` ke matriks CI dan perbaiki yang gagal.
- Kunci file: memori (`src/clite/agent/memory/store.py`) dan penyimpanan job
  (`src/clite/cron/jobs.py`) memakai `fcntl`, dan di Windows saat ini berjalan **tanpa kunci**.
  Ganti dengan mekanisme yang mengunci di kedua sistem.
- Terminal: `cmd.exe` dan Git Bash, pemutusan pohon proses dengan `taskkill`, penanda akhir
  perintah, dan pelacakan `cd`.
- Home default di `%LOCALAPPDATA%`, izin file `.env`, dan pemisah path di
  `src/clite/tools/file_safety.py` serta di pola `detect_self_access`.
- Tandai dengan `@pytest.mark.platforms("posix")` hanya tes yang memang tidak bermakna di
  Windows, masing-masing dengan alasan.

**Di luar lingkup.** Layanan Windows untuk gateway (F4-T6) dan pemaketan desktop (F5-T4).

**File.** `.github/workflows/ci.yml`, `src/clite/core/constants.py`, `src/clite/core/env.py`,
`src/clite/core/io.py`, `src/clite/agent/memory/store.py`, `src/clite/cron/jobs.py`,
`src/clite/tools/environments/local.py`, `src/clite/tools/file_safety.py`,
`src/clite/tools/approval.py`.

**Rujukan Hermes.** `scripts/check-windows-footguns.py`, `tools/environments/local.py`,
`hermes_cli/gateway_windows.py`.

**Selesai bila.**
- [ ] Job CI Windows hijau.
- [ ] Tes dua proses membuktikan kunci file benar-benar mengunci, di Linux dan di Windows.
- [ ] Baris Windows di spesifikasi core, tools, agent, dan cron diperbarui.

**Ukuran.** M

**Bergantung pada.** F1-T1

**Butuh dari Anda.** Tidak wajib. Mesin Windows membantu untuk mencoba REPL dengan tangan.

---

### F1-T6 Penulis config yang mempertahankan komentar

**Tujuan.** `clite config set` dan setiap penulisan config lain tidak lagi menghapus komentar
dan urutan kunci di `config.yaml` milik pengguna.

**Lingkup.**
- Ganti jalur tulis di `src/clite/core/config.py` dengan penulis yang mempertahankan komentar,
  urutan, dan gaya kutip (`ruamel.yaml`). Jalur baca boleh tetap PyYAML.
- Semua penulisan sudah lewat `atomic_config_update`, jadi perubahan ada di satu tempat.
- Tambahkan dependensi dengan batas atas di `pyproject.toml`.

**File.** `src/clite/core/config.py`, `pyproject.toml`, `tests/core/test_config.py`,
`docs/spesifikasi/core.md`.

**Rujukan Hermes.** `hermes_yaml.py`, `scripts/check_config_yaml_writers.py`.

**Selesai bila.**
- [ ] Tes: file dengan komentar, baris kosong, dan urutan kunci tertentu tetap sama setelah
      `config_set`, `config_unset`, dan persetujuan `always`, kecuali baris yang diubah.
- [ ] File yang rusak tetap tidak pernah ditimpa.
- [ ] Baris "Penulis config yang mempertahankan komentar" di spesifikasi core menjadi ✅.

**Ukuran.** S

**Bergantung pada.** F1-T1

---

### F1-T7 Rilis pertama

**Tujuan.** Versi 0.1.0 bisa dipasang orang lain dengan satu perintah.

**Lingkup.**
- Skrip rilis: menaikkan versi di satu tempat, membangun wheel dan sdist, memeriksa isi wheel,
  membuat tag.
- `CHANGELOG.md` dengan isi rilis pertama.
- Workflow rilis yang berjalan pada tag: membangun, menguji wheel di lingkungan bersih, lalu
  menerbitkan.
- Periksa apakah nama paket `clite` masih tersedia di PyPI. Bila tidak, pilih nama distribusi
  lain; nama perintah tetap `clite`.
- README: bagian pemasangan diperbarui dengan perintah yang sudah terbukti.

**File.** `scripts/release.py (baru)`, `CHANGELOG.md (baru)`,
`.github/workflows/release.yml (baru)`, `pyproject.toml`, `README.md`.

**Rujukan Hermes.** `scripts/release.py`.

**Selesai bila.**
- [ ] `pipx install` dari artefak rilis menghasilkan `clite` yang lulus `clite doctor`.
- [ ] Tes: versi di `pyproject.toml`, `clite --version`, dan tag sama.
- [ ] Rilis GitHub pertama terbit dengan wheel dan sdist terlampir.

**Ukuran.** S

**Bergantung pada.** F1-T1, F1-T2

**Butuh dari Anda.** Keputusan nama paket dan lisensi, dan akun PyPI bila ingin menerbitkan di
sana.
