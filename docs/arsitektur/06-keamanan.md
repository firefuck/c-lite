# Keamanan

Agent ini menjalankan perintah shell, menulis file, dan membaca halaman web atas nama
pengguna. Dokumen ini menjelaskan siapa yang dipercaya, pagar apa yang ada, dan di mana pagar
itu berakhir.

## Yang perlu dipahami lebih dulu

**C-lite tidak punya sandbox.** Perintah berjalan sebagai pengguna yang menjalankan agent,
dengan hak penuh pengguna itu. Pagar di bawah ini mencegah dua hal: kekeliruan model yang
merusak, dan jalur eskalasi paling langsung dari teks tak tepercaya. Pagar itu **tidak**
menahan model yang sudah berhasil dibujuk untuk bekerja melawan pengguna dan bersedia
melakukannya dalam beberapa langkah. Untuk pekerjaan yang membutuhkan jaminan semacam itu,
jalankan agent di dalam container atau mesin virtual. Backend terminal Docker dan SSH ada di
roadmap (F2-T7).

## Siapa yang dipercaya

| Pihak | Dipercaya untuk | Alasan |
|---|---|---|
| Pengguna di mesin itu | Segalanya | Ia pemilik home, config, dan `.env` |
| `config.yaml` dan `.env` | Menentukan kebijakan dan kredensial | Hanya pengguna yang boleh menulisnya |
| Plugin yang **diaktifkan** | Berjalan dalam proses dengan hak penuh | Pengguna membaca lalu mengaktifkannya sendiri |
| Shell hook yang **disetujui** | Berjalan pada setiap event | Pengguna menyetujui perintah itu secara persis |
| Model | Tidak dipercaya untuk keputusan keamanan | Keluarannya bisa dibentuk oleh teks yang ia baca |
| Halaman web, isi file, keluaran tool | Tidak dipercaya | Bisa memuat instruksi yang ditujukan ke model |
| File proyek (`AGENTS.md`, skill proyek) | Dipindai sebelum masuk prompt | Repositori hasil clone bukan milik pengguna |
| Skill dan plugin dari luar | Tidak dipercaya sampai dipasang dan diaktifkan | |
| Pengguna chat di gateway | Tidak dipercaya sampai diizinkan | Lihat [Gateway](#gateway) |
| Halaman lain di browser pengguna | Tidak dipercaya | Lihat [Server dan dashboard](#server-dan-dashboard) |

## Pagar

### Perintah shell

Gerbang persetujuan (`src/clite/tools/approval.py`) memeriksa teks setiap perintah `terminal`
sebelum dijalankan. Urutannya ada di [spesifikasi tools](../spesifikasi/tools.md#kontrak).

| Lapis | Berlaku di mode | Bisa dibuka dengan |
|---|---|---|
| Terlarang mutlak: `rm` rekursif atas root, direktori home, atau direktori sistem; memformat disk; fork bomb | Semua, termasuk `off` | Tidak ada |
| `approvals.deny` (glob milik pengguna) | Semua, termasuk `off` | Menyunting config |
| Pola berbahaya (hapus rekursif, `sudo`, `git push --force`, unduh lalu jalankan, dan lainnya) | `manual`, `smart` | Jawaban pengguna; bisa diingat per sesi atau selamanya |
| Menjangkau pengaturan atau kredensial agent sendiri | `manual`, `smart` | Jawaban pengguna, **setiap kali** |

Lapis terakhir menutup jalur eskalasi yang paling langsung. `config.yaml` adalah kebijakan itu
sendiri (mode persetujuan, daftar izin, plugin aktif), jadi perintah seperti
`clite config set approvals.mode off` atau `echo ... >> ~/.clite/config.yaml` tidak pernah
diingat, tidak pernah masuk daftar izin, dan tidak pernah diloloskan peninjau `smart`. Yang
dihitung menjangkau:

- path ke dalam salah satu home agent (yang aktif, yang default, dan home tiap profil) yang
  menunjuk file terlindung, yang **bisa** mengembang menjadi file itu (glob, kurung kurawal,
  variabel), atau yang menunjuk direktori pemuatnya, termasuk home itu sendiri. File
  terlindung didaftar sekali di `PROTECTED_PATHS`: `.env`, `config.yaml`, `auth.json`,
  `shell-hooks-allowlist.json`, dan `gateway/pairing.json`;
- perintah apa pun yang dijalankan dari dalam home atau dari direktori yang memuat file
  terlindung, dan dari subdirektori lain bila perintahnya memanjat keluar dengan `..`;
- CLI pengelolaan agent sendiri, dipanggil dengan nama, dengan path, lewat `python -m`, lewat
  pembungkus seperti `sudo`, atau lewat substitusi seperti `$(command -v clite)`.

**Perintah dibaca dua kali**: seperti tertulis, dan seperti shell membacanya, yaitu setelah
tanda kutip, garis miring terbalik, `${NAMA}`, `$IFS`, dan garis miring berulang dibuang.
`rm -rf "$HOME"`, `rm --recursive --force /`, dan `cat ~//.clite/.e*` dinilai sama dengan
ejaan polosnya. Target `rm` dibaca seperti shell menyelesaikannya (`~`, `..`, `/*` di ujung),
dari direktori kerja bila diketahui, dengan mengikuti `cd` di baris yang sama. Gerbang ini
tetap tidak menjalankan shell: nama yang dirakit dari variabel, oleh substitusi perintah, atau
oleh interpreter (`python -c`) tidak terlihat. Lihat [celah yang diketahui](#celah-yang-diketahui).

Tanpa pengguna untuk ditanya (cron, `-q`, chat yang diam), jawabannya tolak.

**Tes**: `test_hardline_commands_are_refused_in_every_mode`,
`test_shell_spellings_do_not_hide_a_hardline_delete`,
`test_a_relative_delete_is_judged_by_where_it_runs`,
`test_a_remembered_delete_does_not_cover_wiping_the_home_directory`,
`test_deny_globs_beat_mode_off`, `test_deny_globs_see_through_shell_spellings`,
`test_no_one_to_ask_means_deny_by_default`,
`test_commands_that_reach_for_the_agents_own_settings_are_flagged`,
`test_shell_spellings_do_not_hide_a_reach_for_the_agents_settings`,
`test_every_home_and_the_pairing_store_are_guarded`,
`test_where_a_command_runs_decides_what_a_relative_name_can_reach`,
`test_reaching_for_the_agents_settings_is_asked_about_every_time`,
`test_smart_mode_never_reviews_a_command_that_reaches_for_the_agents_settings`,
`test_the_command_cannot_talk_the_reviewer_prompt_out_of_its_frame`.

### File

Tool file dijaga `src/clite/tools/file_safety.py`.

| Operasi | Ditolak untuk |
|---|---|
| Tulis (`write_file`, `patch`) | `.env`, `config.yaml`, `auth.json`, `shell-hooks-allowlist.json`, dan `gateway/pairing.json` di setiap home agent (aktif, default, dan tiap profil); `~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.kube`, `~/.netrc`, dan sejenisnya; direktori sistem |
| Baca (`read_file`, isi `search_files`) | `.env` dan `auth.json` di setiap home agent; direktori dan file kredensial yang sama |

Path diselesaikan dulu (symlink, `..`, `~`), dan nama dibandingkan tanpa membedakan huruf
besar-kecil. `gateway/pairing.json` ikut dilindungi karena isinya menentukan pengguna chat
mana yang boleh memerintah agent.

Selain itu, kredensial yang muncul di file lain diredaksi dari apa yang dibaca model, karena
semua yang dibaca model dikirim ke provider dan disimpan di database sesi.

**Tes**: `test_agent_cannot_write_its_own_credentials_or_settings`,
`test_every_profile_and_the_pairing_store_are_guarded_like_the_active_home`,
`test_credential_files_cannot_be_read`,
`test_credentials_are_redacted_from_what_the_model_reads`,
`test_the_allowlist_cannot_be_written_with_the_file_tools`.

### Kredensial

- Kredensial hanya di `<home>/.env` (izin 0600), dibaca lewat `get_secret`.
- Perintah yang dijalankan agent, proses latar, dan server MCP tidak mewarisi kredensial yang
  dikenal: setiap nama dari `.env`, dan setiap kunci provider atau platform walaupun
  di-`export` di shell. Pengecualian harus disebut di `terminal.env_passthrough`.
- Keluaran terminal dan proses diredaksi: nilai persis setiap kredensial yang dikenal, lalu
  pola kunci yang umum.
- Kunci provider hanya dikirim ke host asal kunci itu.
- Profil terpisah penuh. Menyalin profil tidak pernah menyalin `.env`.

**Tes**: `test_secrets_from_dotenv_do_not_reach_the_command`,
`test_provider_keys_exported_in_the_shell_do_not_reach_the_command_either`,
`test_key_shaped_output_is_redacted`, `test_server_environment_excludes_secrets_unless_listed`,
`test_a_provider_key_is_not_sent_to_another_host`,
`test_bound_scope_does_not_fall_through_to_the_process_environment`,
`test_create_clone_copies_settings_but_not_secrets`.

### Teks yang masuk ke prompt

System prompt punya otoritas tertinggi di mata model, jadi teks dari luar dipindai
(`core.threats.scan_text`) sebelum diizinkan masuk: file konteks proyek, skill dari proyek
dan dari direktori eksternal setiap kali ditemukan, skill lokal saat ditulis dan dipasang,
entri memori, dan prompt job cron. Pemindai mencari instruksi untuk mengabaikan
aturan, perintah eksfiltrasi, dan karakter tak terlihat. Yang kena **diblokir dengan alasan**.

Pemindai sengaja sempit: positif palsu akan membuang file milik pengguna tanpa suara. Ia
menangkap serangan yang kasar, bukan yang cermat. Hasil tool dan halaman web **tidak**
dipindai; keduanya masuk sebagai pesan tool, bukan sebagai system prompt.

**Tes**: `test_injected_context_file_is_blocked_not_loaded`,
`test_a_flagged_skill_from_a_repository_is_not_offered`,
`test_duplicates_and_unsafe_content_are_refused`,
`test_install_refuses_a_flagged_skill_unless_forced`, `test_invalid_jobs_are_refused`.

### Kode dari luar

| Sumber | Syarat sebelum berjalan |
|---|---|
| Plugin di `<home>/plugins/` atau dari pip | Namanya ada di `plugins.enabled`. Memasang hanya menyalin |
| Plugin di proyek (`./.clite/plugins/`) | Variabel lingkungan `CLITE_ENABLE_PROJECT_PLUGINS=1`, lalu tetap harus diaktifkan |
| Shell hook di `config.yaml` | `clite hooks approve` untuk pasangan event dan perintah yang persis sama |
| Server MCP | Ditulis pengguna di `mcp_servers` |
| Skill | Tidak pernah dieksekusi. Isinya dibaca model sebagai teks |

Plugin tidak bisa mengganti tool bawaan tanpa izin per plugin di config.

**Tes**: `test_a_discovered_plugin_does_nothing_until_enabled`,
`test_install_copies_but_does_not_enable`,
`test_a_configured_hook_does_not_run_until_it_is_approved`,
`test_approval_is_for_the_exact_event_and_command`,
`test_a_plugin_cannot_replace_a_builtin_tool_without_consent`.

### Web

`web_fetch` hanya menerima `http` dan `https`, dan menolak alamat yang bukan publik
(loopback, jaringan privat, link-local, metadata cloud) kecuali `web.allow_private_urls`.
Setiap lompatan redirect diperiksa dengan aturan yang sama.

**Tes**: `test_private_addresses_are_refused_by_default`,
`test_a_redirect_is_held_to_the_same_rules_as_the_first_url`,
`test_a_redirect_to_another_scheme_is_refused`.

### Server dan dashboard

`clite serve` membuka seluruh agent, termasuk terminal, kepada siapa pun yang punya token.

- Default hanya mendengarkan di `127.0.0.1`. Host lain memicu peringatan.
- Satu token acak per proses, dibandingkan dalam waktu konstan. Token berada di fragmen URL
  dashboard, yang tidak pernah dikirim ke server atau tertulis di log.
- Token masuk hanya lewat variabel lingkungan `CLITE_SESSION_TOKEN`. Tidak ada opsi baris
  perintah untuknya, karena argumen sebuah proses terlihat oleh semua pengguna mesin itu.
- WebSocket dari browser harus berasal dari origin dashboard sendiri.
- Server yang terikat ke loopback hanya melayani permintaan yang ditujukan ke nama loopback,
  sehingga DNS rebinding tidak berguna.
- Dashboard memasukkan semua teks dari model dan tool sebagai teks, tidak pernah sebagai HTML.

**Tes**: `test_health_is_public_and_everything_else_needs_the_token`,
`test_websocket_rejects_a_bad_token_and_a_foreign_origin`,
`test_a_loopback_server_ignores_requests_addressed_to_another_name`,
`test_dashboard_url_keeps_the_token_in_the_fragment`,
`test_the_session_token_cannot_be_given_on_the_command_line`,
`test_slash_commands_and_script_injection_safety`.

### Gateway

Setiap pengguna chat yang **diizinkan** bisa menyuruh agent menjalankan perintah di mesin
gateway, dan dialah yang menjawab permintaan persetujuan. Mengizinkan seseorang berarti
memberinya akses setara shell.

- Pengguna diizinkan lewat `allowed_users` milik platform atau lewat pairing yang disetujui
  pemilik **di mesin gateway** (`clite gateway pair approve`). Perintah pairing itu sendiri
  termasuk yang selalu ditanyakan bila agent mencoba menjalankannya.
- `gateway.allow_all_users: true` memberi akses itu kepada siapa pun yang menemukan bot.
  Jangan dipakai di platform publik.
- Orang asing di grup diabaikan. Kode pairing dibatasi lajunya dan terkunci setelah lima
  percobaan salah.
- Platform pesan memakai toolset `clite-gateway`, terpisah dari toolset terminal pengguna, dan
  bisa dipersempit per platform lewat `platform_toolsets`.

**Tes**: `test_stranger_gets_a_pairing_code_and_is_let_in_once_approved`,
`test_strangers_in_groups_are_ignored`, `test_pairing_store_limits`,
`test_deny_and_silence_both_refuse`.

### Cron dan subagent

Job cron berjalan tanpa pengawasan: tidak bisa bertanya, tidak bisa menjadwalkan job lain, dan
perintah berbahaya ditolak secara default (`approvals.cron_mode`). Subagent tidak bisa
mendelegasikan lagi, bertanya, menulis memori, atau menjadwalkan; perintah berbahaya darinya
tetap meminta persetujuan pengguna lewat induknya.

**Tes**: `test_cron_toolset_cannot_ask_or_schedule`,
`test_subagent_toolset_cannot_delegate_ask_or_write_memory`,
`test_children_cannot_delegate_further`.

## Arah kegagalan

Komponen yang memutuskan boleh atau tidak selalu gagal ke "tidak". Komponen yang hanya
mengamati tidak pernah menghentikan giliran. Tabel lengkapnya ada di
[03-invarian.md](03-invarian.md#d1-keputusan-keamanan-gagal-tertutup-pengamat-gagal-terbuka).

## Celah yang diketahui

Ditulis apa adanya supaya tidak ada yang mengandalkan pagar yang tidak ada.

| Celah | Akibat | Rencana |
|---|---|---|
| Tidak ada sandbox | Perintah yang lolos gerbang berjalan dengan hak penuh pengguna | Backend Docker dan SSH: F2-T7 |
| Gerbang persetujuan membaca teks **satu** perintah | Skrip yang ditulis ke file lalu dijalankan di langkah berikutnya tidak terlihat | Pemindaian yang lebih dalam tidak menggantikan sandbox |
| Gerbang persetujuan tidak menjalankan shell | Nama yang baru terbentuk saat perintah berjalan tidak terbaca: `rm -rf $(echo /)`, `c=clite; $c config set ...`, `python -c "..."`. Yang pertama masih ditanyakan sebagai hapus rekursif; dua yang lain lolos tanpa pertanyaan | Deteksi muatan interpreter dan posisi perintah: F2-T15. Jaminan sungguhan hanya dari sandbox |
| Persetujuan yang diingat berlaku per **pola**, bukan per perintah | Menjawab "session" atau "always" untuk satu `rm -rf build/` meloloskan setiap hapus rekursif berikutnya, kecuali yang terlarang mutlak | Jawab "once" untuk perintah yang tidak ingin digeneralkan |
| Tool file tidak dibatasi ke direktori kerja | Model bisa menulis ke mana pun di luar daftar terlarang | Checkpoint sebelum menulis: F2-T8 |
| Skrip shell hook bisa ditulis ulang | Persetujuan mengikat teks perintah, bukan isi file yang ditunjuknya | Simpan skrip hook di luar jangkauan agent, atau buat hanya-baca |
| Plugin berjalan dalam proses dengan hak penuh | Plugin jahat yang diaktifkan bisa melakukan apa saja | Baca plugin sebelum mengaktifkan |
| Pemindai teks berbasis pola | Injeksi yang ditulis cermat lolos | - |
| Redaksi berbasis pola untuk kredensial yang tidak dikenal | Kunci berformat tak umum di file atau keluaran bisa terkirim ke provider | Daftarkan namanya di `.env` supaya nilainya diredaksi persis |
| `web_fetch` me-resolve nama dua kali | DNS rebinding terhadap `web_fetch` bisa lolos | - |
| Token server berumur sepanjang proses, tanpa pembatasan laju | Token yang bocor berlaku sampai server dimatikan | Akses jarak jauh yang aman: F5-T6 |
| Tidak ada batas ukuran pesan RPC, tidak ada pembatasan laju per pengguna gateway | Klien yang sudah diizinkan bisa membebani proses | - |
| Windows belum pernah dijalankan | Izin file `.env` dan pemutusan grup proses belum terverifikasi di sana | F1-T5 |

## Aturan untuk kode baru

1. **Keputusan boleh atau tidak gagal ke "tidak".** Exception, batas waktu, jawaban tak
   dikenal, dan ketiadaan penjawab semuanya berarti tolak.
2. **Jangan menambah cara menjalankan perintah yang melewati `check_command`.** Tool baru yang
   menjalankan perintah (backend terminal, eksekusi kode) memanggil gerbang yang sama.
3. **Jangan menambah cara menulis file yang melewati `write_denied_reason`**, atau cara membaca
   yang melewati `read_denied_reason` dan `redact`.
4. **Kredensial baru didaftarkan** (`register_secret`, atau `env_vars` pada profil provider),
   supaya ia tidak sampai ke perintah yang dijalankan agent dan diredaksi dari transkrip.
5. **Teks dari luar yang akan masuk system prompt dipindai dulu**, dan yang kena diblokir.
6. **Kode dari luar tidak berjalan tanpa tindakan eksplisit pengguna.** Kunci config tidak
   cukup sebagai persetujuan untuk sesuatu yang berjalan otomatis, karena config bisa diubah
   lewat terminal.
7. **Surface baru tidak mewarisi toolset terminal secara diam-diam.** Tentukan toolset
   default-nya di `runtime.factory.default_toolsets`.
8. **Setiap pagar punya tes yang gagal ketika pagarnya dilepas.** Jalankan tesnya sekali tanpa
   perbaikannya untuk memastikan.
