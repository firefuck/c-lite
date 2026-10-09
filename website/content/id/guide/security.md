# Keamanan

Agent ini menjalankan perintah shell, menulis berkas, dan membaca halaman web atas nama Anda.
Halaman ini menjelaskan apa yang dijaga, apa yang tidak, dan di mana pagarnya berakhir — supaya
Anda tidak mengandalkan pagar yang tidak ada.

## Yang perlu dipahami lebih dulu

**Secara bawaan tidak ada sandbox.** Backend terminal `local` menjalankan perintah sebagai Anda,
dengan hak penuh Anda. Pagar di bawah mencegah dua hal: kekeliruan model yang merusak, dan jalur
eskalasi paling langsung dari teks tak tepercaya. Pagar itu **tidak** menahan model yang sudah
berhasil dibujuk untuk bekerja melawan Anda dan bersedia melakukannya dalam beberapa langkah.

Yang menahan model seperti itu adalah backend terminal terisolasi:

```yaml
terminal:
  backend: docker
  docker:
    image: python:3.12-slim
    network: none
```

Perintah dan tool file lalu berjalan di dalam container: direktori kerja di-mount pada path yang
sama, berkas di luarnya tidak terlihat, dan container mulai tanpa variabel lingkungan host — tidak
ada kunci provider, tidak ada isi `.env`. Backend `ssh` memberi pemisahan yang sama terhadap mesin
lain.

Docker dan SSH sudah diimplementasikan dan diuji, tetapi belum pernah dijalankan terhadap daemon
dan host sungguhan dalam proyek ini. Perlakukan keduanya sebagai pagar yang menjanjikan, bukan
yang sudah terbukti di mesin Anda.

## Siapa yang dipercaya

| Pihak | Dipercaya untuk | Alasan |
|---|---|---|
| Anda di mesin itu | Segalanya | Anda pemilik home, config, dan `.env` |
| `config.yaml` dan `.env` | Menentukan kebijakan dan kredensial | Hanya Anda yang boleh menulisnya |
| Plugin yang diaktifkan | Berjalan dalam proses dengan hak penuh | Anda membacanya lalu mengaktifkannya sendiri |
| Shell hook yang disetujui | Berjalan pada setiap event | Anda menyetujui perintah itu persis |
| Model | Tidak, untuk keputusan keamanan | Keluarannya bisa dibentuk oleh teks yang ia baca |
| Halaman web, isi berkas, keluaran tool | Tidak | Bisa memuat instruksi yang ditujukan ke model |
| Skill dan plugin dari luar | Tidak, sampai dipasang dan diaktifkan | |
| Pengguna chat di gateway | Tidak, sampai diizinkan | Lihat [Gateway](gateway.md) |

## Perintah shell

Setiap perintah `terminal` — dan setiap program yang dijalankan `execute_code` — lewat gerbang
persetujuan sebelum berjalan. Empat lapis, dari yang paling tidak bisa dibuka:

| Lapis | Berlaku di mode | Bisa dibuka dengan |
|---|---|---|
| Terlarang mutlak: hapus rekursif atas root, direktori home, atau direktori sistem; `mkfs`; `dd` ke disk; menulis ke perangkat blok; fork bomb; `kill -1`/`kill -HUP`; mematikan atau reboot mesin | Semua, termasuk `off` | Tidak ada |
| `approvals.deny` — glob yang Anda tulis sendiri | Semua, termasuk `off` | Menyunting config |
| Menjangkau pengaturan atau kredensial agent sendiri | `manual`, `smart` | Jawaban Anda, **setiap kali** |
| Pola berbahaya (hapus rekursif, `sudo`, `git push --force`, unduh lalu jalankan, dan sejenisnya) | `manual`, `smart` | Jawaban Anda; bisa diingat per sesi atau selamanya |

Lapis ketiga menutup jalur eskalasi yang paling langsung. `config.yaml` **adalah** kebijakannya
sendiri — mode persetujuan, daftar izin, plugin aktif — jadi perintah seperti `clite config set
approvals.mode off` atau apa pun yang menulis ke `~/.clite/` tidak pernah diingat, tidak pernah
masuk daftar izin, dan tidak pernah diloloskan peninjau `smart`. Anda ditanya setiap kali.

Perintah dibaca dua kali: seperti tertulis, dan seperti shell membacanya — jadi `rm -rf "$HOME"`
dan `rm --recursive --force /` dinilai sama dengan ejaan polosnya. Nama yang dirakit di baris yang
sama juga diselesaikan lebih dulu: `d=/; rm -rf $d` ditolak sebagai hapus rekursif atas root.
Teks kode `execute_code` masuk gerbang yang sama, dengan pola yang membaca sintaks Python, jadi
`shutil.rmtree(...)` dan `subprocess.run(["rm", ...])` ditandai seperti bentuk perintahnya.

Kalau tidak ada yang bisa ditanya — cron, `clite chat -q`, chat yang diam — jawabannya tolak.

Dua peringatan yang penting:

- **Gerbang ini tidak menjalankan shell.** Nama yang baru terbentuk saat perintah berjalan, atau
  skrip yang ditulis ke berkas lalu dijalankan di langkah berikutnya, tidak terlihat olehnya.
  Gerbang ini sabuk pengaman terhadap kekeliruan, bukan sandbox.
- **Ingatan berlaku per pola, bukan per perintah.** Menjawab "session" untuk `rm -rf build/`
  meloloskan setiap hapus rekursif berikutnya, kecuali yang terlarang mutlak. Untuk perintah yang
  tidak ingin Anda umumkan, jawab `once`.

## Berkas

Tool berkas tidak bisa menulis ke hal-hal yang menentukan kebijakan atau menyimpan kredensial:
`.env`, `config.yaml`, `auth.json`, daftar persetujuan shell hook, dan data pairing gateway di
setiap home — termasuk home profil lain. Direktori kredensial (`~/.ssh`, `~/.gnupg`, `~/.aws`,
`~/.kube`, `~/.netrc`) dan direktori sistem juga ditolak, untuk tulis maupun baca.

Selain itu, kredensial yang muncul di berkas lain diredaksi dari apa yang dibaca model, karena
semua yang dibaca model dikirim ke provider dan tersimpan di database sesi.

Perlu diketahui: **tool berkas tidak dibatasi ke direktori kerja.** Yang dibatasi hanya daftar
terlarang di atas. Perubahan yang dibuat agent bisa dibatalkan dengan `/rollback` di dalam sesi,
tetapi itu mengembalikan, bukan mencegah — batas yang sebenarnya tetap sandbox.

## Kredensial

- Kunci API hanya ada di `~/.clite/.env` dengan izin 0600, dan hanya dibaca lewat jalur yang
  menandainya sebagai kredensial.
- Perintah yang dijalankan agent, proses latar, server MCP, dan `execute_code` **tidak mewarisi**
  kredensial apa pun — termasuk kunci yang Anda `export` sendiri di shell. Pengecualian harus
  Anda sebut satu per satu di `terminal.env_passthrough`.
- Keluaran terminal diredaksi sebelum masuk transkrip.
- Kunci provider hanya dikirim ke host asal kunci itu, jadi kunci OpenRouter tidak pernah ikut ke
  permintaan ke host lain.
- Setiap profil punya `.env` sendiri; menyalin profil menyalin pengaturan, bukan rahasia.

Karena itu, cara paling aman menyimpan kunci pihak ketiga adalah menaruhnya di `.env` dengan
nama yang dikenal. Kunci berformat tidak umum yang muncul di berkas atau keluaran perintah tidak
selalu tertangkap oleh redaksi berbasis pola.

## Teks dari luar

System prompt punya otoritas tertinggi di mata model, jadi teks dari luar dipindai sebelum
diizinkan masuk: berkas konteks proyek, skill dari repositori, skill saat dipasang, entri memori,
dan prompt job cron. Pemindainya mencari instruksi untuk mengabaikan aturan, perintah
eksfiltrasi, dan karakter tak terlihat. Yang kena **diblokir beserta alasannya**.

Pemindai ini sengaja sempit — positif palsu berarti membuang berkas Anda tanpa suara — jadi ia
menangkap serangan yang kasar, bukan yang cermat. Hasil tool dan halaman web tidak dipindai:
keduanya masuk sebagai pesan tool, bukan sebagai system prompt, dan diperlakukan sebagai data.

## Kode dari luar

| Sumber | Syarat sebelum berjalan |
|---|---|
| Plugin di `~/.clite/plugins/` atau dari pip | Namanya ada di `plugins.enabled`; memasang hanya menyalin |
| Plugin di proyek (`./.clite/plugins/`) | `CLITE_ENABLE_PROJECT_PLUGINS=1` **dan** tetap harus diaktifkan |
| Shell hook di `config.yaml` | `clite hooks approve` untuk pasangan event dan perintah yang persis sama |
| Server MCP | Anda tulis sendiri di `mcp_servers` |
| Skill | Tidak pernah dieksekusi; isinya dibaca model sebagai teks |

Plugin tidak bisa mengganti tool bawaan tanpa izin per plugin di config. Persetujuan shell hook
dipisahkan dari config karena config bisa diubah agent lewat terminal; kunci config tidak cukup
sebagai persetujuan untuk sesuatu yang berjalan otomatis.

## Web

`web_fetch` hanya menerima `http` dan `https`, dan menolak alamat yang bukan publik — loopback,
jaringan privat, link-local, metadata cloud — kecuali `web.allow_private_urls` dinyalakan. Setiap
lompatan redirect diperiksa dengan aturan yang sama, jadi halaman publik tidak bisa memantulkan
agent ke alamat internal.

## Server dan dashboard

`clite serve` membuka seluruh agent — termasuk terminal — kepada siapa pun yang memegang token.

- Bawaannya hanya mendengarkan di `127.0.0.1`. Mengikatnya ke host lain memicu peringatan.
- Token dibuat acak per proses dan dibandingkan dalam waktu konstan. Ia berada di fragmen URL
  dashboard, yang tidak pernah dikirim ke server maupun dicatat di log.
- Token masuk hanya lewat variabel lingkungan `CLITE_SESSION_TOKEN`; tidak ada opsi baris perintah
  untuknya, karena argumen sebuah proses terlihat oleh semua pengguna mesin itu.
- WebSocket dari browser harus berasal dari origin dashboard sendiri, dan server yang terikat ke
  loopback hanya melayani permintaan yang ditujukan ke nama loopback — jadi DNS rebinding tidak
  berguna.
- Teks dari model dan tool ditampilkan sebagai teks, tidak pernah sebagai HTML.

## Gateway

Setiap pengguna chat yang diizinkan bisa menyuruh agent menjalankan perintah di mesin gateway, dan
dialah yang menjawab permintaan persetujuan. **Mengizinkan seseorang berarti memberinya akses
setara shell.** Orang asing di grup diabaikan, kode pairing dibatasi lajunya dan terkunci setelah
lima percobaan salah, dan pairing hanya bisa disetujui oleh Anda di mesin gateway.

Kunci sesi memisahkan konteks percakapan, tetapi pengguna yang diizinkan dalam satu profil tetap
berbagi database sesi, memori, dan berkas. Jangan menjanjikan privasi antar-anggota keluarga atau
tim dalam satu profil.

## Celah yang diketahui

Ditulis apa adanya, supaya tidak ada yang mengandalkan pagar yang tidak ada.

| Celah | Akibat |
|---|---|
| Backend `local` tidak punya sandbox | Perintah yang lolos gerbang berjalan dengan hak penuh Anda |
| Gerbang membaca teks **satu** perintah | Skrip yang ditulis ke berkas lalu dijalankan di langkah berikutnya tidak terlihat |
| Persetujuan yang diingat berlaku per pola | Satu "always" meloloskan seluruh pola itu seterusnya |
| Tool berkas tidak dibatasi ke direktori kerja | Model bisa menulis di luar daftar terlarang |
| Skrip shell hook bisa ditulis ulang | Persetujuan mengikat teks perintah, bukan isi berkas yang ditunjuknya |
| Plugin berjalan dengan hak penuh | Plugin jahat yang Anda aktifkan bisa melakukan apa saja |
| Pemindai teks berbasis pola | Injeksi yang ditulis cermat lolos |
| Redaksi berbasis pola | Kunci berformat tidak umum di berkas atau keluaran bisa terkirim ke provider |
| `web_fetch` me-resolve nama dua kali | DNS rebinding bisa lolos |
| Token server berumur sepanjang proses | Token yang bocor berlaku sampai server dimatikan; `clite serve token` memberi token bernama yang bisa dicabut |

Dokumen lengkap soal keamanan, model kepercayaan, dan arah kegagalan ada di repositori:
[06-keamanan.md](https://github.com/dragovics/clite/blob/main/docs/arsitektur/06-keamanan.md).
