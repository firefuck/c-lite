# 10. GUI: Server Backend, Desktop, dan Dashboard

Hermes punya dua antarmuka grafis, **aplikasi desktop** (Electron) dan **dashboard web**.
Keduanya berbicara ke server backend Python yang sama, yang juga melayani TUI.

```text
                         ┌─────────────────────────────────────┐
 Desktop (Electron) ──WS─┤                                     │
 Dashboard (browser) ─WS─┤  Server backend (FastAPI + uvicorn) ├── AIAgent, sesi, tool
 TUI (Ink) ─── stdio ────┤  + dispatcher tui_gateway           │
                         └─────────────────────────────────────┘
```

## Server backend: `serve` dan `dashboard`

Dua subcommand berbagi satu server (`hermes_cli/web_server.py`, fungsi `start_server`)
tetapi merupakan permukaan yang **mandiri**; yang satu tidak meluncurkan yang lain.

| | `hermes serve` | `hermes dashboard` |
|---|---|---|
| Guna | Backend tanpa kepala untuk desktop dan klien jarak jauh | Dashboard web untuk manusia |
| SPA | Dimatikan, walau ada berkas hasil build | Dibangun dan disajikan |
| Browser | Tidak pernah dibuka | Dibuka otomatis kecuali `--no-open` |
| Yang terjangkau | JSON-RPC, WebSocket, REST | Semua itu ditambah antarmuka web |

### Isi server

- **FastAPI** dengan satu router per permukaan di `hermes_cli/web_routers/`: `sessions`, `models`, `tools`, `skills`, `config_env`, `cron`, `mcp`, `profiles`, `status`, `files`, `git`, `messaging`, `analytics`, `oauth`, dan lainnya. Permukaan baru berarti file router baru, bukan `web_server.py` yang membesar.
- **WebSocket JSON-RPC** (`tui_gateway/ws.py`): dispatcher yang sama dengan TUI, hanya transportnya berbeda.
- **Jembatan PTY** (`hermes_cli/pty_bridge.py`, endpoint `/api/pty`): dipakai dashboard, dijelaskan di bawah.

### Autentikasi

Satu skema untuk semua rute:

- Token sesi diambil dari `HERMES_DASHBOARD_SESSION_TOKEN` bila disetel, kalau tidak dibuat acak tiap server mulai (`secrets.token_urlsafe(32)`).
- REST: header sesi atau `Authorization: Bearer <token>`, dibandingkan dengan `hmac.compare_digest`.
- WebSocket: `?token=...` pada URL, karena browser tidak bisa menyetel header `Authorization` saat upgrade WebSocket.
- Aturan: setiap rute REST dan endpoint WS baru memakai token yang sama. Tidak pernah ada skema kedua.

### Jabat tangan siap

Desktop menjalankan `hermes serve --port 0` (port dipilih sistem operasi) dan mengawasi
stdout anak. Setelah server mengikat port, ia mencetak satu baris penanda:

```text
HERMES_BACKEND_READY port=65238
```

Electron membaca baris itu (`apps/desktop/electron/backend-ready.ts`), lalu menyambung
ke `ws://127.0.0.1:<port>` dengan token yang ia sendiri berikan lewat variabel
lingkungan anak. Batas waktu pengumuman dihitung sejak proses diluncurkan.

## Aplikasi desktop

Lokasi: `apps/desktop/`. Desktop adalah **permukaan obrolan sendiri**. Ia bukan dashboard
di dalam bingkai, dan ia tidak menanam TUI. Ia punya composer, transkrip, dan jalur
slash-nya sendiri.

### Tumpukan teknologi

Electron 40, Vite 8, React 19, TypeScript 6, Tailwind 4, nanostores, TanStack Query,
react-router, Radix UI, xterm.js dengan node-pty (terminal dalam aplikasi), shiki
(penyorotan kode), streamdown (Markdown streaming), dan `@hermes/shared` untuk klien
JSON-RPC.

### Tiga pihak, masing-masing berwenang atas satu hal

| Pihak | Berwenang atas |
|---|---|
| **Electron** (proses utama) | Mesin: daur hidup proses, sistem file, git, jendela, pemasangan dan pembaruan, serta jembatan kemampuan yang sempit dan bertipe |
| **Renderer** (React) | Pengalaman: navigasi, presentasi, keadaan interaksi sementara |
| **Backend agent** | Pekerjaan: sesi, tool, panggilan model, streaming |

Aturan jahitan:

- Renderer tidak pernah menjangkau Node atau Electron secara langsung. Kemampuan asli datang lewat `contextBridge.exposeInMainWorld(...)` di `electron/preload.ts`, bukan pintu darurat umum.
- Perilaku agent hidup di balik gateway, tidak pernah ditulis ulang di React.
- Bila sebuah perubahan mengaburkan jahitan, perbaiki jahitannya, jangan dilebarkan.

### Keadaan ditentukan oleh wewenang

Pertanyaan pertama untuk setiap keadaan: *siapa yang berhak benar tentangnya*.

- **Backend** berwenang atas apa pun yang juga bisa diubah permukaan Hermes lain. Salinan di renderer hanyalah cache.
- **Electron** berwenang atas fakta mesin dan runtime.
- **Renderer** hanya memiliki hal yang murni soal presentasi jendela ini.

Turunannya: keadaan bersama renderer di store kecil milik fiturnya; data server
berbentuk permintaan di lapisan query; rincian interaksi singkat di komponen; koordinasi
panas yang tidak boleh menggambar ulang di ref.

Keadaan yang disimpan harus menyatakan **lingkupnya di kuncinya sendiri**: global, per
sambungan, per profil, per sesi, per proyek, atau per jendela. Salah lingkup adalah cara
pengaturan satu profil bocor ke profil lain.

### Kebenaran server di-cache, bukan dimiliki

- **Gabungkan, jangan timpa.** Penyegaran adalah informasi baru di atas yang sudah diketahui.
- **Optimistis, lalu jujur.** Manipulasi langsung menggambar seketika; tulis yang gagal digulung balik secara terlihat.
- **Jaga dari masa lalu.** Hasil async bisa tiba tidak berurutan. Respons basi tidak boleh menimpa niat yang lebih baru; pakai penghitung generasi.
- **Isolasi latar depan.** Hanya permukaan yang sedang dilihat pengguna yang boleh menerbitkan ke tampilan bersama.
- **Gabungkan derau, alirkan sinyal.** Pembaruan kosmetik frekuensi tinggi digabung; transisi penting (giliran selesai, butuh input, gagal) sampai seketika.

### Sambungan dan backend

- Backend yang diluncurkan aplikasi adalah `hermes serve --port 0` **per pasangan (sambungan, profil)**, dengan `HERMES_DESKTOP=1`.
- Sambungan jarak jauh (SSH, URL dan token, cloud) menjangkau backend tanpa variabel desktop, yang mungkin melayani beberapa profil dari satu proses.
- Karena itu kemampuan yang bergantung pada klien ditentukan dari `source: 'desktop'` yang dikirim pada `session.create`, tidak pernah dari variabel lingkungan backend.
- `serve` **mati bersama aplikasi** secara sengaja. Gateway pesan **bertahan** setelah aplikasi ditutup karena diluncurkan terlepas.
- Uji sambungan harus menguji kaki yang benar-benar dipakai. Probe status HTTP yang lolos sementara kaki WebSocket gagal adalah positif palsu.

Folder `apps/desktop/electron/` didominasi modul `backend-*`: penemuan runtime, perintah
luncur, lingkungan anak, jabat tangan siap, kesehatan, daur ulang, dan pemulihan saat
backend keluar. Setiap resolusi mengikuti pola **tangga kandidat**: urutan prioritas
tertulis di satu tempat, kandidat dipercaya hanya setelah divalidasi, pembacaan yang
gagal turun ke anak tangga berikutnya, dan percobaan ulang selalu berbatas.

### Slash command di desktop

Backend menyediakan segalanya lewat `commands.catalog` dan `complete.slash`. Desktop
**mengkurasi** di sisi klien: perintah khusus terminal atau khusus pesan disembunyikan,
tetapi ekstensi yang diaktifkan pengguna (skill, perintah cepat, perintah plugin) **tidak
pernah** disembunyikan. Disposisi tiap perintah ditulis sekali, sebagai field `desktop=`
pada `CommandDef`.

### Konten tamu tidak pernah membuka apa pun sendiri

HTML tak tepercaya (pratinjau artefak, panel pratinjau) berjalan di iframe ber-sandbox
atau `<webview>`. Keduanya tidak boleh membuka browser sistem tanpa tangan pengguna:
`setWindowOpenHandler` menolak semuanya, dan hanya klik tepercaya pada tautan
`target="_blank"` yang diteruskan, itu pun hanya untuk skema `http` dan `https`.

### Menghormati pengguna

- Jangan pernah berpindah halaman, memindah fokus, atau membuka permukaan karena sesuatu terjadi di latar. Tawarkan, jangan membajak.
- Kosong, memuat, menyambung ulang, basi, dan pemulihan habis adalah pengalaman berbeda yang masing-masing berhak atas teks jujur dan jalan keluar.
- Permukaan mahal yang berkeadaan (terminal, tool hidup) tetap hidup saat disembunyikan. Terlihat bukan berarti daur hidup.

### Susunan sumber

```text
apps/desktop/
├── electron/      proses utama: backend-*, preload.ts, pembaruan, kebijakan jendela
├── src/
│   ├── app/       rute dan halaman: chat, settings, session, cron, profiles, shell
│   ├── store/     atom bersama: gateway, composer, sesi, sambungan, layout
│   ├── lib/       pembantu murni
│   ├── components/, hooks/, i18n/, themes/
│   ├── sdk/, plugins/, contrib/   permukaan plugin desktop
│   └── main.tsx
├── e2e/           Playwright
└── vite.config.ts, electron-builder.config.cjs
```

`src/app` memiliki rute dan halaman, `src/store` atom bersama, `src/lib` pembantu murni.
Akar rute tetap tipis: merangkai rute dan cangkang, bukan menjadi pengendali.

## Dashboard web

Lokasi: `web/` untuk frontend, `hermes_cli/web_routers/` untuk backend.

Tumpukan: React 19, Vite, Tailwind 4, react-router, xterm.js, dan `@hermes/shared`.

Halaman: Chat, Sessions, Models, Config, Env, Skills, Plugins, MCP, Cron, Profiles,
Channels, Pairing, Webhooks, Files, Logs, Analytics, System.

### Dashboard menanam TUI yang sesungguhnya

Ini keputusan yang menghemat sangat banyak pekerjaan. Halaman Chat **tidak** menulis
ulang obrolan dalam React:

- `web/src/pages/ChatPage.tsx` memasang `Terminal` xterm.js dengan renderer WebGL, addon fit, dan addon unicode11.
- `/api/pty?token=...` di-upgrade menjadi WebSocket.
- Server meluncurkan persis apa yang diluncurkan `hermes --tui`, lewat `ptyprocess` (PTY POSIX; WSL bisa, Windows asli tidak).
- Frame adalah byte PTY mentah di kedua arah. Perubahan ukuran dikirim sebagai `\x1b[RESIZE:<kolom>;<baris>]`, dicegat server dan diterapkan dengan `TIOCSWINSZ`.

Aturannya: **jangan mengimplementasikan ulang pengalaman obrolan utama di React.**
Transkrip, alur composer, dan terminal ber-PTY adalah milik TUI yang ditanam. Apa pun
yang ditambahkan ke Ink otomatis muncul di sini. UI React terstruktur *di sekitar* TUI
(bilah samping, inspektur, panel status) boleh, selama bukan permukaan obrolan kedua dan
kegagalannya tidak merusak panel terminal.

## Mengapa desainnya begini

| Keputusan | Akibat |
|---|---|
| Satu dispatcher RPC untuk tiga klien | Fitur backend ditulis sekali |
| Kontrak hasil generate | Perubahan field tertangkap `tsc` di ketiga klien |
| Desktop sebagai permukaan sendiri | Pengalaman asli desktop tanpa batasan terminal |
| Dashboard menanam TUI | Tidak ada implementasi obrolan ketiga yang harus dijaga |
| `serve` tanpa kepala | Desktop tidak bergantung pada build frontend dashboard |
| Port 0 dan baris penanda | Tidak ada tabrakan port, tidak ada tebakan |

## Yang perlu ditiru persis

1. Satu server backend dengan satu dispatcher untuk TUI, desktop, dan web.
2. Satu skema token untuk REST dan WebSocket.
3. Port 0 dan baris siap di stdout.
4. Tiga pihak di desktop dengan jembatan preload yang sempit.
5. Keadaan ditentukan oleh wewenang; renderer hanya menyimpan cache.
6. Kemampuan klien dibaca dari sumber sesi, bukan dari lingkungan proses.
7. Dashboard menanam TUI lewat PTY alih-alih menulis ulang obrolan.

## Rujukan di Hermes

`hermes_cli/web_server.py`, `hermes_cli/web_routers/`, `hermes_cli/pty_bridge.py`,
`hermes_cli/subcommands/dashboard.py`, `tui_gateway/ws.py`, `apps/desktop/AGENTS.md`,
`apps/desktop/src/AGENTS.md`, `apps/desktop/DESIGN.md`, `apps/desktop/electron/`,
`apps/desktop/src/`, `web/AGENTS.md`, `web/src/`.
