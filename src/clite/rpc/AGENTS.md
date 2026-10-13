# rpc: aturan kerja

Protokol JSON-RPC untuk TUI, desktop, dan dashboard. Spesifikasi: `docs/spesifikasi/rpc.md`.

Tes: `pytest tests/rpc -q`, dan `node --test test/*.test.ts` di `packages/shared`.

## Aturan yang tidak boleh dilanggar

1. **Kontrak dulu.** Method, event, atau bidang baru dideklarasikan di
   `contracts/schema.py`, lalu `python scripts/gen_rpc_contracts.py`, baru handler dan klien.
   Jangan menyunting `packages/shared/src/contracts.generated.ts`.
2. **Jangan mematahkan klien lama.** Bidang baru harus opsional. Jangan menghapus atau
   mengganti nama bidang atau method: tambahkan yang baru dan pertahankan yang lama.
3. **Server tidak punya logika percakapan.** Handler memanggil `ChatSession`, `runtime`,
   atau lapisan di bawahnya. Bila sebuah handler mulai berisi aturan bisnis, pindahkan ke
   `runtime`.
4. **Tidak ada yang menulis ke stdout selain transport.** Pakai logging.
5. **Klien selalu mendapat `turn.complete`.** Jalur galat apa pun di sebuah giliran harus
   berakhir di sana.
6. **Diam berarti tolak.** Permintaan persetujuan tanpa jawaban tidak pernah berarti setuju.

## Resep

### Menambah method

1. Di `contracts/schema.py`: model `Params` dan `Result` (turunkan dari `Params` / `Result`
   di `base.py`), lalu `method("area.nama", XParams, XResult, "deskripsi satu kalimat")`.
2. Di modul domainnya, `methods/<domain>.py` (awalan nama method menentukan modulnya; petanya
   ada di docstring `methods/__init__.py`): `@rpc_method("area.nama")` pada fungsi
   `def area_nama(server: RpcServer, params: schema.XParams) -> schema.XResult`. Domain baru
   mendapat modul sendiri yang diimpor `methods/__init__.py`. Handler di modul yang tidak diimpor tidak
   pernah terdaftar; `test_every_declared_method_has_a_handler_and_the_reverse` menangkapnya.
3. `python scripts/gen_rpc_contracts.py` dan `python scripts/gen_docs.py`.
4. Tes di `tests/rpc/test_rpc.py` (fixture klien di file itu mengirim permintaan lewat
   `MemoryTransport`).
5. Bila dashboard memakainya: `apps/web/src/`. Bila TUI memakainya: `apps/tui/src/`. Lalu bangun
   ulang bundle yang bersangkutan (`npm run build` di direktori itu).

### Menambah event

1. Model `Payload` dan `event("area.nama", XPayload)` di `contracts/schema.py`.
2. Kirim dari `RpcSession` lewat `self._emit("area.nama", {...})`.
3. Tangani di `packages/shared/src/transcript.ts` bila memengaruhi transkrip, dan di klien.

## Jebakan

- `Params` memakai `extra="forbid"`. Klien yang mengirim bidang tak dikenal mendapat -32602.
  Itu disengaja.
- Handler berjalan di kumpulan thread. Yang ia sentuh di `RpcServer` harus lewat kunci.
- `RpcSession.id` (runtime) bukan `chat.session_id` (tersimpan). Event memakai yang pertama.
