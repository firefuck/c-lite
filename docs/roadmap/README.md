# Roadmap

Daftar pekerjaan dari keadaan sekarang sampai agent yang setara fiturnya dengan Hermes, dipecah
menjadi task yang bisa dikerjakan satu per satu oleh AI. Keadaan sekarang dicatat di
[STATUS.md](../STATUS.md).

## Cara memakai

1. Pilih task dengan status ⬜ yang semua ketergantungannya sudah ✅. Bila tidak ada alasan
   lain, ikuti urutan nomor.
2. Berikan task itu ke AI dengan prompt di
   [prompts/02-kerjakan-task.md](../prompts/02-kerjakan-task.md). Di Claude Code:
   `/kerjakan-task F1-T1`.
3. Setelah selesai, AI memperbarui status di tabel indeks di bawah dan di spesifikasi modul.
   Periksa hasilnya dengan [prompts/03-tinjau.md](../prompts/03-tinjau.md) (`/tinjau F1-T1`),
   di konteks yang bersih.

Satu task per sesi adalah default yang aman: riwayat sesi tetap relevan dan hasilnya mudah
ditinjau. Model yang sanggup memegang sesi panjang boleh mengerjakan task L dalam satu sesi,
dan beberapa task S yang berkaitan boleh digabung. Cara menyiapkan alatnya ada di
[prompts/README.md](../prompts/README.md).

## Fase

| Fase | Isi | Hasil di akhir fase |
|---|---|---|
| [1. Fondasi terverifikasi](fase-1-fondasi.md) | Menjalankan yang sudah ada terhadap dunia nyata | Bisa dipasang, CI hijau, provider dan Telegram sungguhan teruji, rilis pertama |
| [2. Inti agent](fase-2-inti-agent.md) | Provider, tool, dan kemampuan loop yang belum ada | Agent yang layak dipakai untuk pekerjaan harian |
| [3. CLI dan TUI](fase-3-cli-tui.md) | Pengalaman di terminal | TUI layar penuh, perintah pengelolaan lengkap |
| [4. Gateway](fase-4-gateway.md) | Platform pesan dan otomasi | Agent yang hidup di chat dan berjalan sebagai layanan |
| [5. Desktop dan dashboard](fase-5-desktop-dashboard.md) | Antarmuka grafis | Aplikasi desktop terpaket, dashboard lengkap |
| [6. Ekosistem](fase-6-ekosistem.md) | Skill, plugin, integrasi editor | Hub skill, katalog plugin, ACP, dokumentasi pengguna |

Fase 1 dikerjakan lebih dulu dan sampai habis: ia mengubah "ditulis" menjadi "terbukti jalan".
Sesudah itu fase 2 sampai 6 boleh berjalan berselang sesuai kebutuhan Anda, selama
ketergantungan tiap task dipenuhi.

## Bentuk sebuah task

| Bagian | Isi |
|---|---|
| **Tujuan** | Apa yang bisa dilakukan pengguna setelah task selesai, dalam satu atau dua kalimat |
| **Lingkup** | Yang dikerjakan. Bila ada, **Di luar lingkup** menyebut yang sengaja tidak dikerjakan |
| **File** | File yang disentuh. Path dengan tanda `(baru)` belum ada dan dibuat oleh task ini |
| **Rujukan Hermes** | File di repositori Hermes yang dibaca dulu sebelum menulis. Sudah diperiksa keberadaannya |
| **Selesai bila** | Kriteria yang bisa diperiksa. Setiap butir menjadi tes, kecuali yang jelas menyebut pemeriksaan manual |
| **Ukuran** | Lihat tabel di bawah |
| **Bergantung pada** | Task yang harus ✅ lebih dulu |
| **Butuh dari Anda** | Hal yang tidak bisa disediakan AI sendiri: kunci API, akun, mesin Windows, layar |

| Ukuran | Kira-kira | Arti untuk AI |
|---|---|---|
| S | Sampai 300 baris berubah | Satu sesi, satu commit |
| M | 300 sampai 1.000 baris | Satu sesi; rencanakan dulu, commit bertahap |
| L | 1.000 sampai 3.000 baris | Satu sesi panjang atau beberapa sesi. Pecah menjadi sub-langkah di awal, commit per sub-langkah, dan catat kemajuannya di task ini |
| XL | Lebih dari itu | Jangan dimulai sebagai satu task. Pecah dulu menjadi task baru di file fase dengan [prompts/10-pecah-task.md](../prompts/10-pecah-task.md) |

## Selesai itu apa

Berlaku untuk **setiap** task, di samping kriteria miliknya sendiri:

1. Setiap perilaku baru punya tes yang gagal bila perilaku itu dilepas. Jalankan tesnya sekali
   tanpa perubahannya untuk memastikan.
2. `scripts/run_tests.sh` lulus seluruhnya: lint, pemeriksa tipe, tes Python, tes TypeScript.
3. Tidak ada invarian di [arsitektur/03-invarian.md](../arsitektur/03-invarian.md) yang
   dilanggar. Bila task tampak menuntutnya, berhenti dan laporkan.
4. Spesifikasi modul diperbarui dalam commit yang sama: kontrak baru, dan baris status dari ⬜
   ke ✅ atau 🟡.
5. File hasil generate diperbarui: `python scripts/gen_docs.py` bila ada tool, perintah, method
   RPC, kunci config, atau simbol publik yang berubah; `python scripts/gen_rpc_contracts.py`
   bila kontrak RPC berubah; `node build.mjs` di `ui-tui/` bila TypeScript berubah.
6. Yang ditulis tetapi tidak bisa dijalankan terhadap hal yang sebenarnya dicatat di
   [STATUS.md](../STATUS.md) sebagai belum diverifikasi, bukan diberi ✅.
7. Baris task di indeks di bawah diperbarui.

## Indeks

Status: ⬜ belum, 🟡 sedang dikerjakan atau selesai sebagian, ✅ selesai.

### Fase 1: fondasi terverifikasi

| Task | Judul | Ukuran | Bergantung pada | Status |
|---|---|---|---|---|
| F1-T1 | Pasang di lingkungan nyata dan hijaukan CI | S | - | ⬜ |
| F1-T2 | Uji provider sungguhan | M | F1-T1 | ⬜ |
| F1-T3 | Uji Telegram sungguhan | S | F1-T1 | ⬜ |
| F1-T4 | Pasang skill dari GitHub | S | F1-T1 | ⬜ |
| F1-T5 | Windows | M | F1-T1 | ⬜ |
| F1-T6 | Penulis config yang mempertahankan komentar | S | F1-T1 | ⬜ |
| F1-T7 | Rilis pertama | S | F1-T1, F1-T2 | ⬜ |

### Fase 2: inti agent

| Task | Judul | Ukuran | Bergantung pada | Status |
|---|---|---|---|---|
| F2-T1 | Transport Responses API | M | F1-T2 | ⬜ |
| F2-T2 | Profil provider tambahan | M | F1-T2 | ⬜ |
| F2-T3 | Harga dan estimasi biaya | S | F1-T2 | ⬜ |
| F2-T4 | Patch toleran dan patch multi-file | M | - | ⬜ |
| F2-T5 | Pencarian web | M | - | ⬜ |
| F2-T6 | Gambar: masukan, analisis, pembuatan | L | F1-T2 | ⬜ |
| F2-T7 | Backend terminal Docker dan SSH | L | - | ⬜ |
| F2-T8 | Checkpoint dan rollback file | M | - | ⬜ |
| F2-T9 | Eksekusi kode | M | F2-T7 | ⬜ |
| F2-T10 | MCP: HTTP, resources, prompts, `clite mcp` | L | - | ⬜ |
| F2-T11 | Kompresi yang lebih baik | M | F1-T2 | ⬜ |
| F2-T12 | Review latar belakang dan kurator terjadwal | M | - | ⬜ |
| F2-T13 | Delegasi yang lebih kaya | M | - | ⬜ |
| F2-T14 | OAuth dan `clite auth` | L | F1-T2 | ⬜ |
| F2-T15 | Deteksi perintah yang lebih tahan penyamaran | L | - | ⬜ |

### Fase 3: CLI dan TUI

| Task | Judul | Ukuran | Bergantung pada | Status |
|---|---|---|---|---|
| F3-T1 | Input REPL klasik: saat sibuk, multi-baris, riwayat | M | - | ⬜ |
| F3-T2 | Render Markdown dan diff | M | - | ⬜ |
| F3-T3 | TUI layar penuh | XL | F1-T1 | ⬜ |
| F3-T4 | Slash command tambahan | M | - | ⬜ |
| F3-T5 | Wizard setup | M | F1-T2 | ⬜ |
| F3-T6 | `clite update`, `backup`, `uninstall` | M | F1-T7 | ⬜ |
| F3-T7 | Pelengkapan shell | S | - | ⬜ |
| F3-T8 | `/insights` | S | F2-T3 | ⬜ |

### Fase 4: gateway

| Task | Judul | Ukuran | Bergantung pada | Status |
|---|---|---|---|---|
| F4-T1 | Discord | M | F1-T3 | ⬜ |
| F4-T2 | Slack | M | F1-T3 | ⬜ |
| F4-T3 | WhatsApp, Signal, Matrix, email | L | F1-T3 | ⬜ |
| F4-T4 | Lampiran masuk dan keluar | M | F2-T6 | ⬜ |
| F4-T5 | Jawaban streaming dan progres tool di chat | M | F1-T3 | ⬜ |
| F4-T6 | Gateway sebagai layanan sistem | M | F1-T3 | ⬜ |
| F4-T7 | Kebijakan reset sesi dan home channel | S | - | ⬜ |
| F4-T8 | Tool `send_message` | S | F4-T7 | ⬜ |
| F4-T9 | Cron lanjutan | M | F4-T7 | ⬜ |
| F4-T10 | Endpoint kompatibel OpenAI dan webhook masuk | M | - | ⬜ |

### Fase 5: desktop dan dashboard

| Task | Judul | Ukuran | Bergantung pada | Status |
|---|---|---|---|---|
| F5-T1 | Jalankan dan verifikasi cangkang Electron | S | F1-T1 | ⬜ |
| F5-T2 | Halaman dashboard: config, cron, log, memori, sesi | L | - | ⬜ |
| F5-T3 | Dashboard React dan Vite | XL | F5-T2 | ⬜ |
| F5-T4 | Pemaketan desktop | M | F5-T1 | ⬜ |
| F5-T5 | Fitur desktop: multi-sesi, lampiran, notifikasi, putar ulang event | L | F5-T1, F5-T2 | ⬜ |
| F5-T6 | Akses jarak jauh yang aman | M | F5-T2 | ⬜ |

### Fase 6: ekosistem

| Task | Judul | Ukuran | Bergantung pada | Status |
|---|---|---|---|---|
| F6-T1 | Hub skill | L | F1-T4 | ⬜ |
| F6-T2 | Porting skill bawaan dari Hermes | L | - | ⬜ |
| F6-T3 | Plugin provider memori contoh | M | - | ⬜ |
| F6-T4 | Server ACP | L | - | ⬜ |
| F6-T5 | Ekosistem plugin | L | - | ⬜ |
| F6-T6 | Context engine alternatif | M | F2-T11 | ⬜ |
| F6-T7 | Suara | L | F4-T4 | ⬜ |
| F6-T8 | Batch runner dan ekspor lintasan | M | - | ⬜ |
| F6-T9 | Situs dokumentasi pengguna | M | F1-T7 | ⬜ |

## Menambah atau memecah task

- Task baru mendapat nomor berikutnya di fasenya. Nomor tidak pernah dipakai ulang.
- Judul task ditulis sebagai `### F<fase>-T<nomor> Judul` di file fase, dengan semua bagian wajib, lalu
  didaftarkan di indeks. `tests/test_docs.py` menggagalkan suite bila salah satunya terlewat.
- Task XL dipecah menjadi task baru sebelum dikerjakan. Task induknya tetap ada sebagai payung
  dan mendaftar anak-anaknya.
- Spesifikasi modul merujuk task dengan nomornya. Rujukan ke nomor yang tidak ada juga
  menggagalkan suite.
