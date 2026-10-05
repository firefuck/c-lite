# 04. Provider dan Model

Hermes bisa memakai model apa pun dari puluhan penyedia tanpa mengubah kode inti. Itu
dicapai dengan empat lapisan yang terpisah rapi: **profil provider** (deklaratif),
**transport** (konversi format per mode API), **resolusi runtime** (kredensial dan
endpoint), dan **katalog model** (daftar model dan metadatanya).

## Lapisan 1: `ProviderProfile`

`providers/base.py` mendefinisikan dataclass `ProviderProfile`. Profil **mendeskripsikan**
perilaku penyedia. Profil tidak membangun klien, tidak merotasi kredensial, dan tidak
menangani streaming; itu tetap tugas `AIAgent`. Transport membaca profil alih-alih
menerima puluhan flag boolean.

Field terpenting:

| Kelompok | Field |
|---|---|
| Identitas | `name`, `api_mode` (bawaan `chat_completions`), `aliases` |
| Tampilan | `display_name`, `description`, `signup_url` |
| Auth dan endpoint | `env_vars` (urutan prioritas), `base_url`, `models_url`, `auth_type` (`api_key`, `oauth_device_code`, `oauth_external`, `copilot`, `aws_sdk`) |
| Katalog | `fallback_models` (daftar kurasi bila pengambilan langsung gagal), `model_aliases`, `default_aux_model` |
| Kekhasan klien | `default_headers` |
| Kekhasan permintaan | `fixed_temperature`, `default_max_tokens`, `unsupported_response_formats` |
| Kemampuan | `supports_vision`, `supports_vision_tool_messages`, `supports_prompt_cache_key` |

Hook yang bisa ditimpa di subkelas untuk penyedia yang rumit:

```python
def prepare_messages(self, messages) -> list[dict]             # praproses pesan
def build_extra_body(self, *, session_id=None, **ctx) -> dict   # field extra_body
def build_api_kwargs_extras(self, *, reasoning_config=None, **ctx) -> tuple[dict, dict]
    # mengembalikan (tambahan extra_body, kwargs tingkat atas)
def default_reasoning_config(self, model=None) -> dict | None
def supported_reasoning_efforts(self, model) -> tuple[str, ...] | None
def get_max_tokens(self, model) -> int | None
def get_model_context_length(self, model) -> int | None
def fetch_models(self, *, api_key=None, base_url=None, timeout=8.0) -> list[str] | None
def create_client(self, **client_kwargs) -> Any | None          # klien khusus, atau None
def classify_api_error(...)                                    # klasifikasi error khusus penyedia
```

`build_api_kwargs_extras` mengembalikan dua kamus karena penyedia menaruh konfigurasi
penalaran di tempat berbeda: OpenRouter di `extra_body.reasoning`, yang lain sebagai
`reasoning_effort` tingkat atas.

### Profil adalah plugin

Setiap profil hidup di `plugins/model-providers/<nama>/`:

```text
plugins/model-providers/deepseek/
├── __init__.py     memanggil register_provider(profile) saat diimpor
└── plugin.yaml     name, kind: model-provider, version, description
```

Contoh minimal:

```python
from providers import register_provider
from providers.base import ProviderProfile

register_provider(ProviderProfile(
    name="penyedia-anda",
    aliases=("alias1",),
    display_name="Penyedia Anda",
    signup_url="https://contoh.example/keys",
    env_vars=("PENYEDIA_API_KEY",),
    base_url="https://api.contoh.example/v1",
    default_aux_model="model-murah",
))
```

Tidak ada file lain yang perlu diubah. Auth, konfigurasi, katalog model, `doctor`,
metadata model, resolusi runtime, dan transport tersambung otomatis dari registry.

### Registry dan discovery

`providers/__init__.py` menyediakan `register_provider()`, `get_provider_profile()`
(mencari nama dan alias), dan `list_providers()`. Discovery **malas**: baru berjalan
pada panggilan pertama.

Urutan, dengan aturan **penulis terakhir menang**:

1. Entry point pip pada grup `hermes_agent.plugins`. Paling rendah prioritasnya, dan hanya yang terdaftar di `plugins.enabled`.
2. Plugin bawaan di `plugins/model-providers/`.
3. Plugin pengguna di `$HERMES_HOME/plugins/model-providers/`, dimuat per home profil pada saat pencarian.

Karena pengguna dimuat terakhir, pengguna bisa mengganti profil bawaan tanpa menyentuh
repo. Karena entry point pip dimuat pertama, paket pihak ketiga tidak bisa membajak nama
penyedia resmi.

Nama `custom:<rute>` yang tidak terdaftar jatuh ke profil generik `custom`.

## Lapisan 2: transport dan tiga mode API

| `api_mode` | Dipakai untuk | Klien |
|---|---|---|
| `chat_completions` | Endpoint kompatibel OpenAI: OpenRouter, lokal, sebagian besar penyedia | `openai.OpenAI` |
| `codex_responses` | OpenAI Codex dan Responses API | `openai.OpenAI` dengan format Responses |
| `anthropic_messages` | Messages API asli Anthropic | `anthropic.Anthropic` lewat adapter |

Ketiga mode bertemu pada **format pesan internal yang sama** sebelum dan sesudah
panggilan API.

Urutan penentuan mode:

1. Argumen `api_mode` eksplisit.
2. Deteksi dari penyedia, misalnya `anthropic` berarti `anthropic_messages`.
3. Heuristik URL, misalnya `api.anthropic.com`.
4. Bawaan `chat_completions`.

### ABC transport

`agent/transports/base.py`:

```python
class ProviderTransport(ABC):
    api_mode: str                                    # properti abstrak
    def convert_messages(self, messages, **kw) -> Any
    def convert_tools(self, tools) -> Any
    def build_kwargs(self, model, messages, tools=None, **params) -> dict   # pintu utama
    def normalize_response(self, response, **kw) -> NormalizedResponse
    def validate_response(self, response) -> bool            # opsional
    def extract_cache_stats(self, response) -> dict | None   # opsional
    def map_finish_reason(self, raw_reason) -> str
```

Transport memiliki **jalur data** satu mode API. Transport **tidak** memiliki
konstruksi klien, streaming, kredensial, cache, interupsi, atau retry.

Transport mendaftar diri lewat `register_transport(api_mode, cls)`, dan
`get_transport(api_mode)` mengembalikan instance. Plugin penyedia yang berbicara dialek
sendiri bisa mendaftarkan transport baru.

### Tipe respons ternormalisasi

`agent/transports/types.py`:

```python
@dataclass
class ToolCall:
    id: str | None
    name: str
    arguments: str                    # string JSON
    provider_data: dict | None = None # mis. call_id Codex, thought_signature Gemini

@dataclass
class Usage:
    prompt_tokens: int = 0; completion_tokens: int = 0
    total_tokens: int = 0; cached_tokens: int = 0

@dataclass
class NormalizedResponse:
    content: str | None
    tool_calls: list[ToolCall] | None
    finish_reason: str                # "stop", "tool_calls", "length", "content_filter"
    reasoning: str | None = None
    usage: Usage | None = None
    provider_data: dict | None = None # mis. reasoning_details Anthropic
```

Hanya field yang dibaca semua konsumen yang ada di tingkat atas. Keadaan khusus
protokol tinggal di `provider_data`, sehingga tipe bersama tidak melebar.

### Hal yang perlu diperhatikan per mode

**Anthropic**: pesan sistem dipisah dari daftar pesan; `tool_calls` menjadi blok
`tool_use`; pesan `tool` menjadi blok `tool_result` di dalam pesan pengguna; blok
thinking bertanda tangan harus diputar ulang **dalam urutan aslinya** ketika berselingan
dengan `tool_use`, kalau tidak API menolak dengan HTTP 400. `stop_reason` dipetakan:
`end_turn` ke `stop`, `tool_use` ke `tool_calls`, `max_tokens` ke `length`, `refusal` ke
`content_filter`.

**Chat completions**: penalaran bisa datang sebagai `reasoning` atau
`reasoning_content`, berupa string, kamus, atau daftar; semuanya diratakan sebelum
diolah. `reasoning_details` adalah catatan buram yang ditambahkan apa adanya dan diputar
ulang.

**Codex Responses**: item reasoning terenkripsi diputar ulang antar-giliran. Bila
penyedia menolaknya (`invalid_encrypted_content`), item dibuang dan permintaan diulang
sekali.

## Lapisan 3: resolusi runtime

`hermes_cli/runtime_provider.py::resolve_runtime_provider()` adalah penentu bersama yang
dipakai CLI, gateway, cron, ACP, dan panggilan model pembantu. Fungsi ini memetakan
permintaan menjadi kamus berisi `provider`, `api_mode`, `base_url`, `api_key`, `source`,
dan metadata kedaluwarsa.

```python
def resolve_runtime_provider(*, requested=None, explicit_api_key=None,
                             explicit_base_url=None, target_model=None) -> dict
```

### Prioritas

1. Permintaan eksplisit dari CLI atau runtime.
2. Konfigurasi model dan provider di `config.yaml`.
3. Variabel lingkungan.
4. Bawaan penyedia atau deteksi otomatis.

Urutan ini penting: pilihan yang tersimpan adalah sumber kebenaran untuk pemakaian
normal, supaya `export` usang di shell tidak diam-diam menimpa endpoint yang terakhir
dipilih pengguna lewat `hermes model`.

### Tangga resolusi

Implementasinya berupa tangga. Tiap anak tangga mengembalikan hasil atau melempar error,
kalau tidak, turun ke anak tangga berikutnya:

1. Penjaga provider yang dimatikan (`providers.<nama>.enabled: false`).
2. Jalan pintas nama khusus.
3. Provider kustom bernama, alias lokal seperti `ollama` dan `llamacpp`.
4. Jalur endpoint lokal: tanpa kredensial eksplisit dan `base_url` menunjuk host non-cloud.
5. `--api-key` atau `--base-url` eksplisit.
6. Kumpulan kredensial.
7. Spesifikasi OAuth, proses eksternal, kunci env Anthropic, Bedrock, lalu provider berkunci API dari registry.
8. Cadangan OpenRouter atau custom polos.

### Kunci tidak boleh bocor ke endpoint yang salah

Setiap kunci API dibatasi pada URL dasarnya sendiri:

- `OPENROUTER_API_KEY` hanya dikirim ke endpoint `openrouter.ai`.
- `AI_GATEWAY_API_KEY` hanya ke `ai-gateway.vercel.sh`.
- `OPENAI_API_KEY` dipakai untuk endpoint kustom dan sebagai cadangan.

Hermes juga membedakan endpoint kustom sungguhan yang dipilih pengguna dari jalur
cadangan OpenRouter. Pembedaan ini penting untuk server model lokal dan untuk berpindah
penyedia tanpa mengulang setup.

### Kredensial

- **Kunci API** di `~/.hermes/.env`.
- **OAuth** di `~/.hermes/auth.json`, dengan penyegaran otomatis. `hermes_cli/auth.py` memegang `PROVIDER_REGISTRY` dan `resolve_provider()`.
- **Kumpulan kredensial** (`agent/credential_pool.py`): beberapa kredensial per penyedia dengan strategi `fill_first`, `round_robin`, `random`, atau `least_used`. Kredensial yang kena batas laju didinginkan lalu dirotasi.
- Kredensial Anthropic: file kredensial Claude Code yang bisa disegarkan didahulukan daripada token env.

## Lapisan 4: katalog dan metadata model

- `hermes_cli/models.py` memegang katalog model per penyedia dan validasi model yang diminta.
- `ProviderProfile.fetch_models()` mengambil daftar langsung dari `{base_url}/models`. Pemanggil selalu jatuh ke `fallback_models` bila hasilnya `None`.
- `agent/models_dev.py` mengintegrasikan registry `models.dev` untuk harga dan kemampuan.
- `agent/model_metadata.py::get_model_context_length()` menentukan panjang konteks dengan urutan: penimpaan di konfigurasi, cache persisten, endpoint `/models` kustom dan probe lokal, API penyedia, katalog, tabel bawaan, lalu cadangan 256 ribu token.

Penimpaan pengguna (`model.context_length`, `model_overrides`) selalu menang.

## Mengganti model

### `hermes model`

Pemilih interaktif berbasis curses: pilih penyedia, masukkan kredensial bila belum ada,
lalu pilih model dari daftar langsung. Pilihan disimpan ke `config.yaml`.

### `/model` di dalam sesi

`hermes_cli/model_switch.py` adalah **satu jalur bersama** untuk CLI, gateway, TUI, dan
Desktop. Tidak ada permukaan yang punya pengurai sendiri.

```text
/model [model] [--provider nama] [--reasoning level] [--global|--session] [--refresh]
```

- Bawaan berlingkup sesi; `--global` menyimpannya ke konfigurasi.
- `parse_model_switch_args()` menghasilkan `ModelSwitchRequest`.
- Alias pendek diselesaikan terhadap katalog penyedia berjalan.
- Hasilnya `ModelSwitchResult`: `success`, `new_model`, `target_provider`, `api_key`, `base_url`, `api_mode`, `error_message`, `warning_message`, dan kemampuan model.
- `AIAgent.switch_model()` menukar rute, mengevaluasi ulang cache prompt, dan menghitung ulang ambang kompresi lewat `ContextEngine.update_model()`.

Mengganti model adalah salah satu dari sedikit aksi yang boleh memutus cache, karena
diminta pengguna secara eksplisit.

## Model pembantu

Tugas sampingan memakai rute tersendiri agar tidak membebani model utama:
kompresi, pembuatan judul sesi, vision, ekstraksi web, peninjauan latar, kurator skill.

`agent/auxiliary_client.py` menentukan rutenya. Tiap tugas bisa dipasangi
`provider`, `model`, `base_url`, dan `reasoning_effort` sendiri di bawah `auxiliary:`
pada konfigurasi:

```yaml
auxiliary:
  compression:
    provider: main        # "main" berarti rute yang sama dengan percakapan
    model: ""
  title_generation:
    provider: openrouter
    model: "model-murah"
```

Panggilan pembantu memicu hook `pre_auxiliary_call` dan `post_auxiliary_call`, **bukan**
`pre_api_request` dan `post_api_request` yang khusus giliran utama.

## Model cadangan

```yaml
fallback_providers:
  - provider: openrouter
    model: "vendor/model-cadangan"
```

Dicoba berurutan saat rute utama gagal (lihat [02-agent-loop.md](02-agent-loop.md)).
Subagent dan tugas pembantu tidak mewarisi rantai ini; tugas pembantu punya rantainya
sendiri. Cron tanpa model tetap mendukung cadangan.

## Yang perlu ditiru persis

1. Profil penyedia deklaratif sebagai plugin, dengan registry penulis-terakhir-menang.
2. ABC transport per mode API dan tipe `NormalizedResponse`.
3. Satu fungsi resolusi runtime yang dipakai semua permukaan.
4. Kunci API dibatasi pada URL dasarnya.
5. Satu jalur `/model` untuk semua permukaan.
6. Rute model pembantu yang terpisah dan bisa diatur per tugas.

## Rujukan di Hermes

`providers/base.py`, `providers/__init__.py`, `plugins/model-providers/`,
`agent/transports/`, `agent/anthropic_adapter.py`, `agent/anthropic_message_convert.py`,
`agent/codex_responses_adapter.py`, `hermes_cli/runtime_provider.py`,
`hermes_cli/auth.py`, `agent/credential_pool.py`, `hermes_cli/models.py`,
`agent/model_metadata.py`, `agent/models_dev.py`, `hermes_cli/model_switch.py`,
`agent/auxiliary_client.py`, `website/docs/developer-guide/provider-runtime.md`,
`website/docs/developer-guide/adding-providers.md`,
`website/docs/developer-guide/model-provider-plugin.md`.
