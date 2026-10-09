# Plugin

Kalau skill mengajari agent *apa yang harus dilakukan*, plugin menambah *apa yang bisa
dilakukannya*: tool baru, penyedia model, mesin konteks, platform chat, halaman dashboard. Plugin
adalah kode Python yang berjalan di dalam proses C-lite.

Karena itu aturan mainnya berbeda dari skill. **Memasang plugin tidak berarti mengaktifkannya.**
`clite plugins install` hanya menyalin berkas ke home Anda — tidak ada yang dijalankan — dan
plugin baru berjalan setelah namanya Anda tulis di `plugins.enabled`.

## Melihat dan mengaktifkan

```console
$ clite plugins list
not_enabled  audit-log            1.0.0  standalone  bundled  Record every tool call to logs/tool-audit.jsonl and show recent ones with /audit
loaded       context-sliding-window 1.0.0  backend   bundled  Sliding-window context engine: drop the middle, keep a protected head and tail
loaded       email                1.0.0  platform    bundled  Receive allowed email senders over IMAP and reply over SMTP
loaded       image-gen-openai     1.0.0  backend     bundled  Image generation via the OpenAI Images API (requires OPENAI_API_KEY)
...
```

Kolom pertama adalah statusnya: `loaded` (aktif), `not_enabled` (ada tapi belum diaktifkan),
`error` (gagal dimuat, alasannya bisa dilihat di daftar yang lebih panjang), atau `disabled`.

```console
$ clite plugins enable audit-log
$ clite plugins disable audit-log
```

Di dalam REPL, `/plugins` menampilkan daftar yang sama.

## Yang dibawa paket

Sebelas plugin bawaan sudah ada di setiap instalasi. Beberapa di antaranya berjenis `backend` atau
`platform`: keduanya tidak melakukan apa pun sampai Anda mengonfigurasinya, jadi mereka boleh
"aktif" sejak awal tanpa biaya.

| Plugin | Kegunaan |
|---|---|
| `web-search-ddg` | Pencarian web lewat DuckDuckGo, tanpa kunci API |
| `web-search-tavily` | Pencarian web lewat Tavily, butuh `TAVILY_API_KEY` |
| `image-gen-openai` | Membuat gambar lewat OpenAI Images API, butuh `OPENAI_API_KEY` |
| `speech-openai` | Transkripsi pesan suara dan jawaban bersuara, butuh `OPENAI_API_KEY` |
| `context-sliding-window` | Mesin konteks alternatif: membuang bagian tengah percakapan, tanpa panggilan peringkas |
| `memory-sqlite` | Memori jangka panjang di SQLite, dengan pencarian teks penuh |
| `email`, `matrix`, `signal`, `whatsapp` | Platform chat tambahan untuk gateway |
| `audit-log` | Mencatat setiap panggilan tool ke `logs/tool-audit.jsonl`; ada `/audit` untuk melihat yang terakhir |

Satu plugin berjenis `exclusive` boleh aktif per kategori: yang kedua kali didaftarkan berstatus
`error` beserta nama plugin yang menang. Ini yang membuat dua mesin konteks tidak berebut.

## Memasang dari luar

```console
$ clite plugins search kata
$ clite plugins info nama-plugin
$ clite plugins install nama-plugin
$ clite plugins update nama-plugin
```

Sumbernya sebuah direktori, URL git, atau nama dari katalog. Yang diunduh diperiksa hashnya
terhadap yang dijanjikan katalog, lalu disalin ke `~/.clite/plugins/` — masih nonaktif.

Setelah Anda membacanya dan mengaktifkannya, `clite plugins update` mengambil versi terbaru dari
sumber yang sama, menampilkan ringkasan dan satu baris per berkas yang berubah, lalu menunggu
konfirmasi. Plugin yang sudah Anda sunting sendiri tidak ditimpa tanpa `--force`, dan setelah
diperbarui plugin kembali **nonaktif** — kode baru belum Anda baca, jadi ia tidak berjalan sampai
Anda mengaktifkannya lagi.

Kalau sebuah plugin membutuhkan paket Python lain, `install` dan `info` menampilkannya sebagai
perintah `pip install ...`. Pemasangan itu tidak dilakukan otomatis.

## Menulis plugin

Plugin adalah satu direktori berisi `plugin.yaml` dan modul Python dengan fungsi `register(ctx)`.
`ctx` menyediakan apa yang boleh didaftarkan plugin: tool, toolset, hook, perintah slash, penyedia
model, mesin konteks, penyedia memori, platform chat, dan lainnya.

```yaml
name: sapaan
version: 1.0.0
kind: standalone
description: Menambahkan satu tool sapaan.
```

Semua yang didaftarkan plugin dicatat, sehingga saat plugin dimatikan atau dimuat ulang, seluruh
pendaftarannya dibatalkan dan tool bawaan yang sempat ditimpa kembali seperti semula.

Plugin berjalan di dalam proses C-lite dengan hak penuh, sama seperti kode Anda sendiri. Tidak ada
sandbox di antara keduanya: opt-in dan "memasang tidak berarti mengaktifkan" adalah satu-satunya
penghalang. Baca isinya sebelum mengaktifkan.

## Shell hook

Cara paling ringan menambahkan perilaku tanpa menulis plugin Python adalah shell hook: sebuah
perintah yang dijalankan pada salah satu event siklus hidup, ditulis di `config.yaml`.

```yaml
hooks:
  pre_tool_call:
    - command: /usr/local/bin/audit-tool.sh
      matcher: terminal
```

Hook menerima satu objek JSON di stdin (nama event, nama tool, argumennya, id sesi, direktori
kerja) dan boleh menjawab lewat stdout: memblokir panggilan itu beserta alasannya, mengubah
argumennya, atau menambah konteks.

Hook baru berjalan setelah pasangan event dan perintah yang persis sama Anda setujui:

```console
$ clite hooks list
$ clite hooks approve pre_tool_call /usr/local/bin/audit-tool.sh
```

`clite hooks list` memperlihatkan mana yang sudah disetujui dan mana yang masih menunggu. `clite
hooks revoke` mencabutnya, dan `clite hooks test` menjalankan sebuah hook dengan masukan buatan
supaya Anda bisa melihat keluarannya sebelum mempercayainya.

Persetujuan mengikat *teks perintahnya*, bukan isi berkas yang ditunjuknya. Letakkan skrip hook di
luar jangkauan agent, atau buat hanya-baca, supaya isinya tidak bisa diubah di belakang
persetujuan Anda.

## Yang belum ada

- Halaman dashboard dari plugin sudah bisa dibuat, tetapi belum punya jembatan data: halaman tidak
  bisa memanggil C-lite atau membaca berkas di luar direktorinya, jadi yang bisa ditampilkan masih
  terbatas.
- `plugins update` membandingkan berkas, bukan menyimpan riwayat; tidak ada cara kembali ke versi
  sebelumnya selain memasang ulang.
- Katalog plugin tidak punya konsep tap seperti katalog skill: satu lokasi saja.
