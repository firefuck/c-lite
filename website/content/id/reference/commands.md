# Rujukan perintah

Halaman ini dibuat dari kode oleh `scripts/gen_docs.py`, jadi isinya tidak pernah tertinggal dari programnya. Jangan disunting dengan tangan: ubah kodenya, lalu jalankan skrip itu.

Setiap perintah slash dan sub-perintah `clite`, dibaca dari registry di kode.

## Perintah slash

| Perintah | Alias | Kategori | Argumen | Saat sibuk | Hanya CLI | Deskripsi |
| --- | --- | --- | --- | --- | --- | --- |
| `/new` | `/reset` | Session |  | queue |  | Start a fresh session |
| `/image` | `/attach` | Session | `<path>` | queue |  | Attach an image file to your next message |
| `/retry` |  | Session |  | queue |  | Remove the last exchange and send your last message again |
| `/undo` |  | Session |  | queue |  | Remove the last exchange |
| `/history` |  | Session | `[count]` | queue |  | Show the conversation so far |
| `/title` |  | Session | `[title]` | queue |  | Show or set the session title |
| `/sessions` |  | Session | `[count]` | queue |  | List recent sessions |
| `/resume` |  | Session | `<id \| title>` | queue |  | Switch to an earlier session |
| `/branch` |  | Session | `[title]` | queue |  | Copy this conversation into a new session |
| `/queue` |  | Session | `<text>` | allow |  | Queue a message to run after the running turn |
| `/background` | `/bg` | Session | `<text>` | allow |  | Run one turn in a separate session and report the result |
| `/export` |  | Session | `[path]` | queue |  | Save the transcript as Markdown or JSON |
| `/pin` |  | Session |  | queue |  | Mark this session so it is never pruned |
| `/archive` |  | Session |  | queue |  | Hide this session from the session list |
| `/compress` |  | Session | `[focus]` | queue |  | Summarise older turns to free context |
| `/rollback` |  | Session | `[turns]` | queue |  | Undo the files the agent changed in the last turn(s) |
| `/checkpoints` |  | Session |  | queue |  | List the file checkpoints kept for this session |
| `/stop` |  | Session |  | allow |  | Interrupt the running turn |
| `/steer` |  | Session | `<text>` | allow |  | Guide the running turn without interrupting it |
| `/quit` | `/exit`, `/q` | Session |  | allow | ya | Exit |
| `/model` |  | Configuration | `[provider:model] [--global]` | queue |  | Show or switch the model |
| `/provider` |  | Configuration |  | queue |  | List model providers and whether they are configured |
| `/tools` |  | Configuration | `[enable\|disable <toolset>]` | queue |  | List toolsets, or enable/disable one |
| `/reasoning` |  | Configuration | `[none\|minimal\|low\|medium\|high\|xhigh\|max]` | queue |  | Show or set the reasoning effort |
| `/yolo` |  | Configuration |  | queue |  | Toggle command approval for this session |
| `/config` |  | Configuration | `[key]` | queue |  | Show a setting or the config file path |
| `/reload` |  | Configuration |  | queue |  | Reload config and plugins |
| `/profile` |  | Configuration |  | queue |  | Show the active profile and list the others |
| `/verbose` |  | Configuration | `[off\|new\|all\|verbose]` | queue |  | Set how much tool progress is shown |
| `/skin` |  | Configuration | `[name]` | queue | ya | Show or change the display skin/theme |
| `/skills` |  | Tools & Skills | `[filter]` | queue |  | List skills |
| `/plugins` |  | Tools & Skills |  | queue |  | List plugins and their status |
| `/hooks` |  | Tools & Skills |  | queue |  | List shell hooks and which await approval |
| `/mcp` |  | Tools & Skills | `[name]` | queue |  | Show the status of the MCP servers |
| `/memory` |  | Tools & Skills |  | queue |  | Show what is in persistent memory |
| `/cron` |  | Tools & Skills |  | queue |  | List scheduled jobs |
| `/help` | `/?` | Info |  | allow |  | List commands |
| `/status` |  | Info |  | allow |  | Show model, session and context usage |
| `/context` |  | Info |  | queue |  | Break down the context window: prompt tiers, tools, history |
| `/usage` |  | Info |  | allow |  | Show token usage for this session |
| `/tasks` |  | Info |  | queue |  | Show this session's todo list |
| `/logs` |  | Info | `[count]` | queue | ya | Show the last lines of the agent log |
| `/copy` |  | Info |  | queue | ya | Copy the last answer to the clipboard |
| `/insights` |  | Info | `[days]` | queue |  | Show usage insights, tokens and costs |
| `/sethome` |  | Gateway |  | queue |  | Set this chat as the platform's home channel |
| `/debug` |  | Info |  | queue |  | Show prompt and context internals |

## Perintah CLI

| Perintah | Fungsi | Sub-perintah |
| --- | --- | --- |
| `clite auth` | manage OAuth authentication for model providers | `login`, `status`, `logout` |
| `clite chat` | talk to the agent (default command) |  |
| `clite setup` | choose a provider, store its API key and pick a model |  |
| `clite model` | show, list or set the model | `show`, `list`, `set`, `providers` |
| `clite config` | show or change settings | `show`, `get`, `set`, `unset`, `path`, `env`, `edit`, `migrate` |
| `clite tools` | list, enable or disable toolsets | `list`, `enable`, `disable` |
| `clite skills` | list, search, install and curate skills | `list`, `search`, `info`, `view`, `install`, `update`, `tap`, `remove`, `curate` |
| `clite plugins` | list, enable, disable, install or remove plugins | `list`, `enable`, `disable`, `install`, `remove`, `search`, `info`, `update` |
| `clite hooks` | review, approve or test shell hooks from config.yaml | `list`, `approve`, `revoke`, `test` |
| `clite mcp` | add, list, remove and test MCP servers | `list`, `add`, `remove`, `test` |
| `clite sessions` | list, show, search, export or delete sessions | `list`, `show`, `rename`, `delete`, `export`, `search`, `prune` |
| `clite batch` | run many prompts unattended | `run` |
| `clite profile` | manage profiles (separate homes) | `list`, `show`, `create`, `use`, `delete` |
| `clite cron` | schedule agent tasks | `list`, `add`, `history`, `pause`, `resume`, `run`, `remove`, `tick`, `daemon` |
| `clite gateway` | run the messaging gateway | `run`, `install`, `uninstall`, `start`, `stop`, `restart`, `logs`, `status`, `pair` |
| `clite webhook` | manage inbound HMAC webhooks | `add`, `list`, `remove` |
| `clite serve` | run the headless backend (for the desktop app or a remote client) | `token` |
| `clite dashboard` | run the backend and open the web dashboard |  |
| `clite tui` | start the terminal UI (needs Node.js) |  |
| `clite completion` | print a shell completion script for bash, zsh or fish |  |
| `clite update` | check for updates and upgrade c-lite |  |
| `clite backup` | archive or restore the agent's home directory | `create`, `restore` |
| `clite uninstall` | uninstall c-lite and optionally purge data |  |
| `clite version` | print version information |  |
| `clite status` | show what is configured |  |
| `clite doctor` | check the installation |  |
| `clite logs` | show the agent log |  |
| `clite memory` | show persistent memory |  |
| `clite acp` | Agent Client Protocol server for editors (Zed and others), on stdio |  |
| `clite insights` | show usage analytics, tokens and costs |  |
