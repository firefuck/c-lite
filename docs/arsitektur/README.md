# Arsitektur

Folder ini menjelaskan bentuk C-lite secara keseluruhan: lapisan apa saja yang ada, bagaimana
satu pesan pengguna berjalan dari surface sampai jawaban, aturan apa yang tidak boleh
dilanggar, dan seperti apa data yang berpindah antar-bagian.

Spesifikasi per modul ada di [`../spesifikasi/`](../spesifikasi/README.md). Dokumen di sini
menjawab pertanyaan yang melintasi modul.

## Ringkasan satu halaman

C-lite adalah **satu inti agent yang dilayani banyak surface**. Intinya sempit: sebuah loop
yang memanggil model, menjalankan tool yang diminta model, dan mengulang sampai model menjawab
dengan teks. Semua kemampuan lain menempel di tepi sebagai tool, skill, plugin, provider, atau
server MCP.

```
   CLI klasik     TUI (Node)     Desktop (Electron)   Dashboard (browser)   Telegram, ...   Jadwal
       │              │                  │                    │                  │            │
       │          JSON-RPC           JSON-RPC             JSON-RPC               │            │
       │           (stdio)          (WebSocket)          (WebSocket)             │            │
       ▼              ▼                  ▼                    ▼                  ▼            ▼
   ┌───────┐      ┌───────┐         ┌──────────────────────────┐          ┌──────────┐   ┌───────┐
   │  cli  │      │  rpc  │◄────────│          server          │          │ gateway  │   │ cron  │
   └───┬───┘      └───┬───┘         └──────────────────────────┘          └────┬─────┘   └───┬───┘
       └──────────────┴────────────────────────┬───────────────────────────────┴─────────────┘
                                               ▼
                              ┌─────────────────────────────────┐
                              │  runtime: build_agent,          │   yang dipakai bersama
                              │  ChatSession, slash command     │   oleh semua surface
                              └────────────────┬────────────────┘
                                               ▼
                              ┌─────────────────────────────────┐
                              │  agent: AIAgent, loop giliran,  │   satu percakapan
                              │  prompt, kompresi, memori       │
                              └───┬──────────┬──────────────┬───┘
                                  ▼          ▼              ▼
                             ┌────────┐ ┌─────────┐  ┌────────────┐
                             │ tools  │ │ skills  │  │ providers  │──► API model
                             └───┬────┘ └────┬────┘  └─────┬──────┘
                                 ▼           ▼             ▼
                              ┌─────────────────────────────────┐
                              │  state (SQLite)   core (home,   │
                              │  plugins.hooks    config, env)  │
                              └─────────────────────────────────┘
```

Dua aturan menentukan hampir semua keputusan desain lain:

1. **Yang sudah dikirim ke model tidak pernah berubah.** System prompt dibangun sekali per
   sesi dan setiap permintaan mengulang permintaan sebelumnya lalu menambah di ujungnya.
   Cache prompt bergantung pada ini, dan model Claude generasi 5 menolak permintaan yang
   riwayatnya diubah.
2. **Inti sempit, kemampuan di tepi.** Fitur baru masuk sebagai tool, skill, plugin, atau
   profil provider. Loop dan `AIAgent` jarang perlu disentuh.

## Daftar dokumen

| Dokumen | Menjawab |
|---|---|
| [01-lapisan.md](01-lapisan.md) | Paket apa boleh mengimpor paket apa, dan di mana kode baru harus diletakkan |
| [02-alur-giliran.md](02-alur-giliran.md) | Apa yang terjadi sejak pengguna menekan Enter sampai jawaban tampil |
| [03-invarian.md](03-invarian.md) | Aturan yang tidak boleh dilanggar, alasannya, dan tes yang menjaganya |
| [04-format-data.md](04-format-data.md) | Bentuk pesan, tool, respons model, dan setiap file di home |
| [05-protokol-rpc.md](05-protokol-rpc.md) | Protokol antara backend Python dan front-end (TUI, desktop, dashboard) |
| [06-keamanan.md](06-keamanan.md) | Siapa yang dipercaya, pagar apa yang ada, dan celah yang masih terbuka |
| [07-beda-dengan-hermes.md](07-beda-dengan-hermes.md) | Di mana C-lite sengaja menyimpang dari Hermes, dan apa yang belum dibawa |

## Urutan baca

Untuk mulai bekerja di proyek ini: dokumen ini, lalu `01`, `03`, dan `02`. Sisanya dibaca saat
tugasnya menyentuh topik itu.

## Aturan memelihara folder ini

- Dokumen di sini menjelaskan **mengapa** dan **bagaimana bagian-bagian terhubung**. Daftar
  yang bisa dihasilkan dari kode (tool, method RPC, kunci config) tidak ditulis ulang di sini:
  rujuk [`../referensi/katalog.md`](../referensi/katalog.md).
- Setiap invarian di `03` menyebut tes yang menjaganya. Invarian tanpa tes diberi tanda
  demikian, bukan dibiarkan terlihat seolah terjaga.
- Mengubah arah import, urutan fase, bentuk pesan, atau amplop protokol berarti mengubah
  dokumen yang bersangkutan dalam commit yang sama.
