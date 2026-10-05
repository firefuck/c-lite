# tests: aturan kerja

    pytest tests -q                      # semua tes Python
    pytest tests/agent -q -k compress    # sebagian
    scripts/run_tests.sh                 # lint, mypy, Python, TypeScript

Tata letak mengikuti paket: `tests/<area>/` menguji `src/clite/<area>/`.
`tests/test_architecture.py` menguji bentuk kode itu sendiri (arah import, pembaca config,
file hasil generate).

## Aturan yang tidak boleh dilanggar

1. **Tidak ada tes yang menyentuh `~/.clite` asli atau kredensial pengembang.** Fixture
   `clite_home` (otomatis untuk semua tes) memberi home sementara, mengalihkan `Path.home()`,
   menghapus variabel `*_API_KEY` dan `CLITE_*`, dan mengembalikan `os.environ` sesudahnya.
2. **Tidak ada tes yang memakai jaringan.** Yang ditiru adalah ujung jauhnya, bukan kode kita:
   provider diuji terhadap server HTTP lokal sungguhan (`fake_api`), Telegram terhadap Bot API
   tiruan lokal, MCP terhadap proses server sungguhan. Tes yang benar-benar butuh jaringan
   diberi `@pytest.mark.network` dan tidak jalan di CI.
3. **Model ditiru dengan `ScriptedClient`, bukan dengan menambal fungsi.** Tes menyatakan apa
   yang "dikatakan" model dan memeriksa apa yang dilakukan loop.
4. **Nama tes adalah kalimat tentang perilaku.**
   `test_a_broken_hook_fails_open_by_default_and_closed_on_request`, bukan nama bernomor
   seperti *test_hook_3*.
   Daftar nama tes sebuah modul harus terbaca sebagai spesifikasinya.
5. **Tes menguji perilaku lewat pintu publik.** Panggil `handle_function_call`, `main([...])`,
   `agent.run_conversation`, bukan fungsi privat, kecuali fungsi privat itu memang unitnya.
6. **Tidak ada `time.sleep` untuk menunggu sesuatu terjadi.** Suntikkan waktu (`now=`), atau
   tunggu kondisi dengan batas waktu.
7. **State global dibersihkan.** Registry atau cache baru yang hidup sepanjang proses harus
   punya fungsi reset yang didaftarkan di `_reset_process_state` (`tests/conftest.py`).
8. **Tes yang gagal tidak "diperbaiki" dengan melemahkannya.** Bila sebuah tes gagal setelah
   perubahan, tentukan dulu mana yang salah: kode atau harapan tes. Bila harapannya yang
   berubah, itu perubahan kontrak dan spesifikasinya ikut diubah.

## Fixture yang tersedia

| Fixture | Di | Guna |
|---|---|---|
| `clite_home` | `tests/conftest.py` (otomatis) | Home sementara; mengembalikan path-nya |
| `make_agent(responses, **kwargs)` | `tests/agent/conftest.py` | `(agent, client)` dengan `ScriptedClient`; toolset default `file` |
| `probe_tools` | `tests/agent/conftest.py` | Tiga tool uji dengan kebijakan paralel berbeda |
| `fake_api` | `tests/providers/conftest.py` | Server HTTP lokal yang berperan sebagai provider |
| `make_session(responses, **kwargs)` | `tests/runtime/test_session_and_slash.py` | `(ChatSession, client)` |
| `cli(*argv, expect=0)` | `tests/cli/test_cli.py` | Menjalankan `main([...])`, mengembalikan stdout |

Pembantu di `clite.providers.testing`: `ScriptedClient`, `text_response`,
`tool_call_response`, `mock_route`.

## Penanda

| Penanda | Arti |
|---|---|
| `@pytest.mark.platforms("linux", "macos")` | Hanya jalan di host itu (`posix` = linux dan macos) |
| `@pytest.mark.network` | Butuh jaringan sungguhan; tidak jalan di CI |
| `@pytest.mark.browser` | Mengendalikan dashboard di Chromium (butuh `playwright`) |

Tes yang dependensi opsionalnya tidak ada dilewati dengan `pytest.importorskip`, tidak gagal.

## Jebakan

- Config di-cache terhadap mtime dan ukuran file. Tes yang menulis ulang `config.yaml` dengan
  isi berukuran sama sebaiknya memanggil `reset_config_cache()`.
- Tool yang didaftarkan tes memakai `origin="test"` supaya dibersihkan otomatis.
- `ScriptedClient` yang kehabisan respons melempar `AssertionError`: loop memanggil model
  lebih sering daripada yang diharapkan tes.
- Tes TypeScript (`ui-tui`, `apps/desktop`) menjalankan backend Python sungguhan dan butuh
  dependensi Python terpasang.
