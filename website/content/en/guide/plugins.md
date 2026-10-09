# Plugins

If a skill teaches the agent *what to do*, a plugin adds *what it can do*: new tools, model
providers, context engines, chat platforms, dashboard pages. A plugin is Python code that runs
inside the C-lite process.

That is why the rules of the game differ from skills. **Installing a plugin does not mean enabling
it.** `clite plugins install` only copies files to your home — nothing is run — and a new plugin
runs only after you write its name in `plugins.enabled`.

## Seeing and enabling

```console
$ clite plugins list
not_enabled  audit-log            1.0.0  standalone  bundled  Record every tool call to logs/tool-audit.jsonl and show recent ones with /audit
loaded       context-sliding-window 1.0.0  backend   bundled  Sliding-window context engine: drop the middle, keep a protected head and tail
loaded       email                1.0.0  platform    bundled  Receive allowed email senders over IMAP and reply over SMTP
loaded       image-gen-openai     1.0.0  backend     bundled  Image generation via the OpenAI Images API (requires OPENAI_API_KEY)
...
```

The first column is the status: `loaded` (active), `not_enabled` (present but not yet enabled),
`error` (failed to load, the reason is visible in the longer listing), or `disabled`.

```console
$ clite plugins enable audit-log
$ clite plugins disable audit-log
```

Inside the REPL, `/plugins` shows the same listing.

## What the package ships

Eleven bundled plugins are already present in every installation. Some are of kind `backend` or
`platform`: neither does anything until you configure it, so they may be "active" from the start at
no cost.

| Plugin | What it does |
|---|---|
| `web-search-ddg` | Web search via DuckDuckGo, without an API key |
| `web-search-tavily` | Web search via Tavily, needs `TAVILY_API_KEY` |
| `image-gen-openai` | Generates images via the OpenAI Images API, needs `OPENAI_API_KEY` |
| `speech-openai` | Transcribes voice messages and speaks replies, needs `OPENAI_API_KEY` |
| `context-sliding-window` | Alternative context engine: drops the middle of the conversation, without summariser calls |
| `memory-sqlite` | Long-term memory in SQLite, with full-text search |
| `email`, `matrix`, `signal`, `whatsapp` | Extra chat platforms for the gateway |
| `audit-log` | Records every tool call to `logs/tool-audit.jsonl`; there is `/audit` to see the latest ones |

One plugin of kind `exclusive` may be active per category: the second one registered has status
`error` along with the name of the winning plugin. This is what keeps two context engines from
fighting over the same spot.

## Installing from outside

```console
$ clite plugins search greeting
$ clite plugins info greeting
$ clite plugins install greeting
$ clite plugins update greeting
```

The source is a directory, a git URL, or a name from the catalogue. What is downloaded is checked
against the hash promised by the catalogue, then copied to `~/.clite/plugins/` — still disabled.

After you read it and enable it, `clite plugins update` fetches the latest version from the same
source, shows a summary and one line per file that changed, then waits for confirmation. A plugin
you have edited yourself is not overwritten without `--force`, and after updating the plugin is
**disabled** again — you have not read the new code, so it does not run until you enable it again.

If a plugin needs another Python package, `install` and `info` show it as a `pip install ...`
command. That installation is not done automatically.

## Writing a plugin

A plugin is a single directory holding `plugin.yaml` and a Python module with a `register(ctx)`
function. `ctx` provides what a plugin may register: tools, toolsets, hooks, slash commands, model
providers, context engines, memory providers, chat platforms, and more.

```yaml
name: greeting
version: 1.0.0
kind: standalone
description: Add a single greeting tool.
```

Everything a plugin registers is recorded, so that when the plugin is stopped or reloaded, its
whole registration is undone and a bundled tool it had overridden returns to how it was.

A plugin runs inside the C-lite process with full rights, just like your own code. There is no
sandbox between the two: opt-in and "installing does not mean enabling" are the only barriers. Read
the contents before enabling.

## Shell hooks

The lightest way to add behaviour without writing a Python plugin is a shell hook: a command that
runs on one of the lifecycle events, written in `config.yaml`.

```yaml
hooks:
  pre_tool_call:
    - command: /usr/local/bin/audit-tool.sh
      matcher: terminal
```

A hook receives one JSON object on stdin (event name, tool name, its arguments, session id, working
directory) and may answer over stdout: block that call along with its reason, change its arguments,
or add context.

A hook runs only after you approve the exact same pair of event and command:

```console
$ clite hooks list
$ clite hooks approve pre_tool_call /usr/local/bin/audit-tool.sh
```

`clite hooks list` shows which are already approved and which are still waiting.
`clite hooks revoke` withdraws it, and `clite hooks test` runs a hook with made-up input so you can
see its output before trusting it.

Approval binds *the command text*, not the contents of the file it points to. Keep the hook script
out of the agent's reach, or make it read-only, so its contents cannot be changed behind your
approval.

## What is not there yet

- Dashboard pages from plugins can already be made, but have no data bridge yet: a page cannot
  call C-lite or read files outside its directory, so what it can show is still limited.
- `plugins update` compares files, it does not keep history; there is no way back to a previous
  version other than installing again.
- The plugin catalogue has no concept of a tap like the skill catalogue: a single location only.
