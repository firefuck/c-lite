# plugins: aturan kerja

Bus hook, pemuatan plugin, shell hook. Spesifikasi: `docs/spesifikasi/plugins.md`.

Tes: `pytest tests/plugins -q`

## Aturan yang tidak boleh dilanggar

1. **`hooks.py` adalah daun.** Ia hanya mengimpor `core`, supaya setiap lapisan bisa
   menembakkan hook tanpa siklus import. Jangan menambah import lain di sana.
2. **Kontrak hook hanya boleh bertambah.** Menambah kwarg ke sebuah `invoke_hook` aman.
   Mengganti nama atau menghapus kwarg mematahkan plugin pihak ketiga: jangan.
3. **Plugin yang rusak tidak boleh menjatuhkan agent.** Setiap pemanggilan kode plugin
   dibungkus; kegagalan dicatat dan dilaporkan di `clite plugins list`.
4. **Setiap `register_*` di `PluginContext` mencatat pembatalannya** lewat `self._record`.
   Method baru tanpa pembatalan akan bocor saat plugin dibongkar.
5. **Opt-in tetap opt-in.** Jangan menambah jalur yang menjalankan kode plugin tanpa namanya
   ada di `plugins.enabled`.
6. **Hook kebijakan gagal tertutup.** Bila menambah hook yang bisa memveto sesuatu, masukkan
   ke `FAIL_CLOSED_HOOKS`.

## Resep

### Menambah hook baru

1. Tambahkan nama ke `VALID_HOOKS` di `hooks.py` dengan komentar tentang arahan yang dipahami.
2. Tembakkan dari tempat kejadiannya: `if has_hook("nama"): invoke_hook("nama", kwarg=...)`.
   `has_hook` dulu supaya jalur tanpa plugin tetap murah.
3. Putuskan apakah shell hook boleh menanganinya. Bila tidak (butuh nilai kembalian non-JSON
   atau objek hidup), tambahkan ke pengecualian `SHELL_HOOK_EVENTS` di `shell_hooks.py`.
4. Tes di `tests/plugins/test_hooks.py` dan di tes modul yang menembakkannya.
5. `python scripts/gen_docs.py`.

### Menambah kemampuan ke `PluginContext`

1. Tambahkan method `register_<sesuatu>` yang mengimpor registry tujuannya **di dalam
   fungsi** (plugin berada di atas lapisan itu; import tingkat modul akan dilarang tes
   arsitektur bila tujuannya lebih tinggi).
2. Panggil `self._record(jenis, nama, undo)`.
3. Tes: daftar, bongkar, pastikan tidak ada yang tertinggal
   (`test_everything_a_plugin_registered_is_removed_on_unload`).

### Menulis plugin

Contoh lengkap dan pendek: `src/clite/bundled/plugins/audit-log/`. Sebuah plugin adalah
direktori berisi `plugin.yaml` dan `__init__.py` yang mendefinisikan `register(ctx)`.

## Jebakan

- Bus hook dan manajer plugin ada satu per home. Kode yang menyimpan referensi ke bus di
  tingkat modul akan memakai bus profil yang salah.
- `ctx.settings` membaca config setiap kali diakses, bukan sekali saat dimuat.
- Callback hook dipanggil dari thread giliran, dan bisa dari thread pekerja saat tool
  berjalan paralel.
- Direktori plugin bernama `model-providers` dan `shell-hooks` dicadangkan.
