# 09. TUI dan Protokol RPC

TUI Hermes dan aplikasi desktopnya memakai **backend yang sama**: `tui_gateway`, sebuah
server JSON-RPC berbahasa Python. Dashboard web juga berbicara ke server itu. Jadi
perubahan di `tui_gateway/` punya tiga konsumen.

## Model proses

```text
hermes --tui
  └─ Node (Ink)  ──stdio JSON-RPC──  Python (tui_gateway)
       │                                  └─ AIAgent + tool + sesi
       └─ menggambar transkrip, composer, prompt, aktivitas
```

- `hermes --tui` meluncurkan proses Node. Node lalu menjalankan `python -m tui_gateway.entry` sebagai anak, dengan pipa stdio. Interpreter Python ditentukan lewat variabel `HERMES_PYTHON` yang disetel peluncur.
- TUI juga bisa **menempel** ke gateway yang sudah berjalan lewat WebSocket (`HERMES_TUI_GATEWAY_URL`).
- Pembagian tanggung jawab tegas: **TypeScript memegang layar; Python memegang sesi, tool, panggilan model, dan logika slash command.** Perilaku agent tidak pernah dipindahkan ke renderer.

Karena stdout adalah kanal RPC pada mode stdio, **tidak ada kode Python yang boleh
mencetak ke stdout**. `tui_gateway` memegang stdout asli dan mengalihkan cetakan lain.
Stdin gateway juga ditandai close-on-exec agar proses anak tidak menelan permintaan RPC.

## Protokol kawat

JSON-RPC 2.0, satu objek JSON per baris (dibatasi baris baru), **dua arah**.

**Permintaan klien ke server:**

```json
{"jsonrpc":"2.0","id":"r1","method":"prompt.submit","params":{"session_id":"abc","text":"halo"}}
```

**Respons:**

```json
{"jsonrpc":"2.0","id":"r1","result":{"status":"streaming"}}
{"jsonrpc":"2.0","id":"r1","error":{"code":4001,"message":"unknown session","data":{}}}
```

**Event (notifikasi server ke klien):**

```json
{"jsonrpc":"2.0","method":"event","params":{"type":"message.delta","session_id":"abc","payload":{"text":"Ha"}}}
```

Semua event memakai method `event`; jenisnya ada di `params.type`. Tiap frame event
mendapat nomor urut `seq` yang naik per sesi dan disimpan di cincin putar ulang, sehingga
klien yang menyambung kembali bisa meminta `session.events.since`.

**Permintaan server ke klien** (agent bertanya kepada pengguna):

```json
{"jsonrpc":"2.0","id":"srq-7","method":"approval","params":{"session_id":"abc","request_id":"...","command":"rm -rf build","choices":["once","session","always","deny"]}}
```

Klien menjawab dengan frame respons ber-id sama:

```json
{"jsonrpc":"2.0","id":"srq-7","result":{"choice":"once"}}
```

`server_requests.send()` **memblokir thread agent** sampai frame respons tiba, batas
waktu lewat, atau permintaan ditarik (event `request.cancel`).

### Kode error

| Kode | Arti |
|---|---|
| `-32600` | Permintaan tidak valid |
| `-32601` | Method tidak dikenal (klien dan backend berbeda versi) |
| `-32602` | Params bukan objek |
| `-32603` | Gagal menyerialkan respons |
| `-32000` | Handler melempar exception |
| `4000` | Kunci params tidak dikenal, dengan path kuncinya |
| `4001` | Sesi atau transport tidak valid |
| `4006` | `session_id` hilang |
| `5035` | Backend sedang pensiun; sambungkan ulang |

## Kontrak dideklarasikan di Python, dihasilkan untuk TypeScript

Ini keputusan desain paling berharga di bagian ini. Folder `tui_gateway/contracts/`
memuat satu model **Pydantic** untuk setiap bentuk di kawat:

```python
class Params(BaseModel):   # params method dan params server request
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

class Result(BaseModel):   # hasil method dan hasil server request
    model_config = ConfigDict(extra="forbid")

class Payload(BaseModel):  # payload event
    model_config = ConfigDict(extra="forbid")

class WireEnum(StrEnum):   # himpunan tertutup, menjadi union literal di TS
    ...
```

Tiga tabel di `contracts/registry.py` diisi saat modul topik diimpor:

```python
method("prompt.submit", params=PromptSubmitParams, result=PromptSubmitResult, doc="...")
server_request("approval", params=ApprovalRequestParams, result=ApprovalResult, doc="...")
event("message.complete", MessageCompletePayload, doc="...")
```

Akibatnya:

- `register_method` **menolak nama yang tidak dideklarasikan** saat impor. Tidak ada permukaan kawat yang tak terdokumentasi.
- Dispatcher menolak kunci params tak dikenal dengan kode `4000` dan path kuncinya. Kunci yang salah eja adalah bug klien, bukan sesuatu yang diabaikan diam-diam.
- Hasil handler dan payload event diperiksa terhadap modelnya. Di bawah test, pelanggaran melempar `ContractViolation`; di produksi hanya dicatat.
- `scripts/gen_gateway_contracts.py` menghasilkan `apps/shared/src/gateway-contract.generated.ts` (tipe `RpcMethods`, `ServerRequestMap`, `BackendGatewayEventMap`) dan `gateway-contract.openrpc.json`.
- Sebuah test gagal bila file hasil generate basi.

Alurnya: **ubah model, generate ulang, lalu `tsc` menunjukkan setiap konsumen yang
terkena.** Field yang dihapus di Python menjadi error kompilasi di TypeScript.

Aturan pemodelan: nama field `snake_case` persis seperti di kawat; `dict[str, Any]`
dilarang di kontrak (deklarasikan bentuknya); `X | None = None` menjadi `x?: X | null`.

## Katalog

Pada commit rujukan ada 251 method di 66 namespace, 13 server request, dan 69 event.
Yang membentuk inti:

### Method

| Namespace | Method |
|---|---|
| `session` | `create`, `resume`, `activate`, `list`, `close`, `delete`, `title`, `history`, `status`, `usage`, `compress`, `interrupt`, `steer`, `branch`, `undo`, `save`, `events.since` |
| `prompt` | `submit`, `background`, `btw` |
| `slash`, `command`, `commands` | `slash.exec`, `command.dispatch`, `command.resolve`, `commands.catalog` |
| `complete` | `slash`, `path` |
| `config` | `get`, `set`, `show` |
| `model` | `options`, `save_key`, `disconnect` |
| `tools`, `toolsets` | `tools.list`, `tools.show`, `tools.configure`, `toolsets.list` |
| `skills`, `plugins`, `mcp` | `skills.manage`, `skills.reload`, `plugins.list`, `plugins.manage`, `mcp.servers.*` |
| `profiles` | `list`, `create`, `describe`, `configure` |
| `subagent` | `list`, `steer`, `interrupt`, `tail` |
| `approval`, `clarify`, `request` | `approval.respond`, `clarify.lock`, `request.answer` |
| `client`, `gateway`, `ping` | `client.capabilities`, `gateway.capabilities`, `ping` |

### Server request

`approval`, `clarify`, `sudo`, `secret`, ditambah jembatan desktop (`terminal.read`,
`preview.read`, `preview.act`, `window.read`, `tour`) dan prompt vault.

### Event

| Kelompok | Event |
|---|---|
| Sambungan | `gateway.ready`, `error`, `notice` |
| Pesan | `message.start`, `message.delta`, `message.interim`, `message.complete` |
| Penalaran | `thinking.delta`, `reasoning.delta`, `reasoning.available` |
| Tool | `tool.start`, `tool.generating`, `tool.complete`, `tool.output_risk` |
| Sesi | `session.info`, `session.title`, `session.usage`, `sessions.changed` |
| Status | `status.update`, `todo.updated`, `background.complete`, `btw.complete` |
| Permintaan | `request.cancel`, `approval.cancelled` |
| Tampilan | `skin.changed`, `notification.show`, `notification.clear` |

### Bentuk yang paling penting

```python
# session.create
class SessionCreateParams:   cols, source, cwd, title, model, provider, parent_session_id,
                             hidden, idempotency_key, ...
class SessionCreateResult:   session_id, stored_session_id, message_count, messages, info

# prompt.submit
class PromptSubmitParams:    session_id, text, queued, surface, ...
class PromptSubmitResult:    status ("streaming" | "queued" | "steered" | "redirected"), user_row_id

# event message.complete
class MessageCompletePayload: text, usage, status, reasoning, error, failure_reason, partial, persisted_turn

# event tool.start / tool.complete
class ToolStartPayload:      tool_id, name, args, preview
class ToolCompletePayload:   tool_id, name, args, duration_s, result, summary, inline_diff, todos

# server request approval
class ApprovalRequestParams: session_id, request_id, command, description, choices, tool_name
class ApprovalResult:        choice ("once" | "session" | "always" | "deny")

# server request clarify
class ClarifyRequestParams:  session_id, questions[{qid, question, choices, multi_select}]
class ClarifyResult:         answers {qid: str | null}
```

Dua identitas sesi berjalan berdampingan: `session_id` adalah id **runtime** yang
dipakai streaming, dan `stored_session_id` adalah id **tersimpan** yang dipakai navigasi
dan apa pun yang disematkan pengguna. `session.resume` menerima id tersimpan dan
menjawab dengan id runtime. Mencampur keduanya adalah sumber berulang bug "sesi tidak
ditemukan".

## Dispatch di server

`tui_gateway/server.py` adalah fasad: tabel `_methods`, dekorator `@method(name)`,
pembantu `_ok(rid, result)` dan `_err(rid, code, msg)`, serta `_emit(event, sid, payload)`.
Method hidup di saudara `methods_<topik>.py`. RPC baru berarti modul topik baru atau
entri di modul topik yang ada, **tanpa rantai `if method == ...`**.

`rpc_dispatch.dispatch(req, transport)`:

1. Ikat transport ke ContextVar untuk permintaan ini.
2. Bila frame adalah **respons** atas server request kita, selesaikan permintaan yang menunggu dan jangan balas.
3. Validasi bentuk permintaan.
4. Handler singkat dijalankan langsung dan responsnya dikembalikan.
5. Handler panjang (`_LONG_HANDLERS`, misalnya `prompt.submit`) dikirim ke kumpulan thread dengan salinan konteks. Pekerja menulis responsnya sendiri lewat transport yang terikat.

`write_json(obj)` memilih transport paling spesifik: transport milik sesi untuk frame
ber-`session_id`, lalu transport yang terikat konteks, lalu stdio.

### Transport

`tui_gateway/transport.py` mendefinisikan protokol:

```python
class Transport(Protocol):
    def write(self, obj: dict) -> bool: ...   # False bila lawan sudah pergi
    def close(self) -> None: ...
```

`StdioTransport` menulis satu baris JSON di bawah kunci, dengan serialisasi di luar
kunci. Transport WebSocket ada di `tui_gateway/ws.py`. Payload yang gagal diserialkan
menjadi frame error JSON-RPC dengan id asli, supaya klien tidak menunggu selamanya.

### Sambungan dan kemampuan

1. Server mengirim `gateway.ready` sebagai frame pertama: skin, kemampuan event perubahan, epoch putar ulang, dan dukungan heartbeat.
2. Klien menjawab `client.capabilities {server_requests: true}`. Klien yang tidak pernah menyatakan ini dianggap versi lama, dan `send()` gagal cepat alih-alih membuat agent menunggu.
3. Heartbeat `gateway.ping` tiap 15 detik dengan tenggat 45 detik mendeteksi sambungan yang mati diam-diam. Frame ini dijawab langsung oleh pembaca WebSocket (`tui_gateway/ws.py`), tidak lewat dispatcher, sehingga tetap terjawab walau semua agent sedang sibuk.

## Sisi TypeScript

### `apps/shared`

Paket `@hermes/shared`, dipakai TUI, Desktop, dan dashboard:

- `json-rpc-channel.ts`: kelas `JsonRpcRequestChannel`. Bagian yang **agnostik transport**: id permintaan, peta permintaan tertunda dengan batas waktu dan `AbortSignal`, pemetaan error, dekode event, handler server request, dan heartbeat. Pemilik menyediakan `JsonRpcTransport { send(text) }` dan memanggil `handleFrame(text)` untuk setiap frame masuk.
- `json-rpc-gateway.ts`: `JsonRpcGatewayClient` di atas WebSocket, dengan sambung ulang dan putar ulang.
- `gateway-contract.generated.ts`: tipe hasil generate.
- `gateway-events.ts`: amplop `GatewayEvent` dan event sintetis lokal klien.

Handler server request dicoba berurutan sampai ada yang menerima. Permintaan tanpa
handler dijawab `-32601`, dan handler yang melempar dijawab `-32603`, supaya backend
tidak pernah menunggu sampai tenggat pada klien yang tidak bisa menjawab.

### `ui-tui`

Aplikasi **Ink** (React untuk terminal) dengan **nanostores** untuk keadaan.

| Permukaan | Komponen | Method atau event |
|---|---|---|
| Streaming obrolan | `app.tsx`, `messageLine.tsx` | `prompt.submit`, `message.delta`, `message.complete` |
| Aktivitas tool | `thinking.tsx` | `tool.start`, `tool.generating`, `tool.complete` |
| Persetujuan | `prompts.tsx` | Server request `approval` |
| Klarifikasi, sudo, rahasia | `prompts.tsx`, `maskedPrompt.tsx` | Server request `clarify`, `sudo`, `secret` |
| Pemilih sesi | `sessionPicker.tsx` | `session.list`, `session.resume` |
| Slash command | Handler lokal lalu diteruskan | `slash.exec`, `command.dispatch` |
| Pelengkapan | Hook `useCompletion` | `complete.slash`, `complete.path` |
| Tema | `theme.ts`, `branding.tsx` | `gateway.ready` membawa data skin |

Susunan sumber: `src/app/` (store, handler event, pengendali giliran), `src/components/`,
`src/domain/` (logika murni), `src/hooks/`, `src/lib/`, `src/i18n/`, dan
`gatewayClient.ts` (meluncurkan dan mengawasi proses Python).

### Alur slash command di TUI

1. Perintah klien bawaan (`/help`, `/quit`, `/clear`, `/resume`, `/copy`) ditangani lokal.
2. Selebihnya dikirim ke `slash.exec`, yang berjalan di subproses `_SlashWorker` yang persisten. Bila gagal, jatuh ke `command.dispatch`, yang menyelesaikannya menjadi skill, alias, atau perintah eksekusi. Perintah skill menghasilkan `{type: "skill", message}` dan dikirim sebagai prompt biasa.

`commands.catalog` dan `complete.slash` sudah memuat perintah bawaan, `quick_commands`
pengguna, dan perintah turunan skill. Klien tidak butuh RPC baru untuk melihat skill.

## Gaya TypeScript Hermes

- Nanostores kecil untuk keadaan bersama; tiap fitur memiliki atom-nya.
- Komponen yang menggambar memakai `useStore`; aksi non-render membaca `$atom.get()`.
- Jangan mengoper keadaan melewati tiga komponen bila daunnya bisa berlangganan.
- Tidak ada hook monolitik; satu hook, satu tugas.
- `interface` untuk props publik.
- Tabel mengalahkan tangga kondisi.

## Yang perlu ditiru persis

1. Python memegang perilaku; TypeScript memegang layar.
2. JSON-RPC dibatasi baris baru, dua arah, dengan server request untuk pertanyaan agent.
3. Kontrak Pydantic sebagai satu sumber kebenaran, dengan TypeScript hasil generate dan test kebasian.
4. Kunci params tak dikenal ditolak.
5. Satu kanal RPC agnostik transport yang dipakai TUI, Desktop, dan web.
6. Stdout dilindungi pada mode stdio.
7. Nomor urut event dan putar ulang untuk sambung kembali.

## Rujukan di Hermes

`tui_gateway/server.py`, `tui_gateway/rpc_dispatch.py`, `tui_gateway/transport.py`,
`tui_gateway/entry.py`, `tui_gateway/ws.py`, `tui_gateway/server_requests.py`,
`tui_gateway/contracts/`, `tui_gateway/methods_*.py`, `tui_gateway/prompt_turn.py`,
`tui_gateway/agent_callbacks.py`, `scripts/gen_gateway_contracts.py`, `apps/shared/src/`,
`ui-tui/src/`, `tui_gateway/AGENTS.md`.
