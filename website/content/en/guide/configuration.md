# Configuration

All settings live in one YAML file inside your home, `~/.clite/config.yaml`. No part has to be
written by hand: `clite setup` fills in the essentials, and `clite config set` changes a single
value without disturbing the comments or the order of the file.

## Changing settings

```console
$ clite config show            # only the values you changed, not the whole file
$ clite config get model.default
$ clite config set agent.max_turns 25
agent.max_turns = 25
$ clite config unset agent.max_turns   # back to the default value
$ clite config path            # where the file is
$ clite config env             # stored secrets, values masked
$ clite config edit            # open in $EDITOR
```

A few keys change what the agent may do without asking — `approvals`, `plugins.enabled`,
`hooks`, `command_allowlist`, `mcp_servers`, and `gateway.allow_all_users`. Writing them through
`config.set` from the dashboard requires explicit confirmation, because it is the same as
changing security policy.

A value you delete from the file still has a default: what is read is your file stacked on top of
the defaults, so deleting a key means "use the default", not "off". The list of every key and its
default is in [Configuration reference](../reference/config.md).

Values may refer to environment variables with `${NAME}`; the contents are substituted when the
config is read. Secrets should not be written here — see the `.env` section below.

If the file is broken, `clite` reports it as a warning and still starts, so that `clite config
edit` and `clite doctor` can be used to fix it. A broken file is never overwritten by itself.

## Secrets

API keys and other secrets are stored only in `~/.clite/.env` (permissions 0600), and are read
only through paths that mark them as credentials. You get the consequences without configuring
anything:

- commands the agent runs inherit no keys at all — including keys you `export` yourself in the
  shell;
- terminal output is redacted before it enters the conversation;
- a provider's key is sent only to the host that key came from.

The profile's `.env` beats old variables still present in your shell. `clite config env` shows
the stored names without their values.

## Profiles

A profile is a full separate home: config, `.env`, sessions, memory, skills, and plugins of its
own. Useful for separating work and personal, or for trying another model without disturbing the
one in use.

```console
$ clite profile create kerja     # new home, a one-time copy of the current one
$ clite profile use kerja
$ clite -p kerja                 # a single run, without changing the active profile
$ clite profile list
```

A profile that does not exist is an error, not silently created. A profile never inherits secrets
from another profile: copying a profile copies settings, not keys.

The home directory can also be moved at once:

```console
$ CLITE_HOME=/media/disk/clite clite
```

## The main sections

| Section | Contents |
|---|---|
| `model` | Default model, provider, custom `base_url`, context length, token limit |
| `providers` | Providers of your own: `{base_url, api_key_env, api_mode, models}` |
| `fallback_providers` | Routes tried in order when the main route fails |
| `toolsets`, `disabled_toolsets` | Active toolsets; `platform_toolsets` narrows them per platform |
| `agent` | Turn limit, API call retry and timeout, `reasoning_effort`, time budget |
| `terminal` | Execution backend (`local`, `docker`, `ssh`), timeouts, credentials passed through |
| `approvals` | Command approval mode, timeout, and patterns that are always denied |
| `command_allowlist` | Command patterns you approve forever |
| `memory` | Long-term memory and the user profile, their size limits |
| `compression`, `context` | Compaction of long conversations |
| `skills`, `plugins` | Active skills and plugins, their index sources |
| `mcp_servers` | MCP servers: `command` for stdio, `url` for Streamable HTTP |
| `hooks` | Shell hooks on lifecycle events; they run only after you approve them |
| `gateway` | Chat platforms, `allowed_users`, session reset policy, send targets |
| `cron` | Scheduler: missed jobs, delivery attempt limit |
| `speech` | Voice message transcription and spoken replies |
| `sessions`, `checkpoints` | Automatic session cleanup, checkpoint storage limit |
| `display` | Streaming, tool progress, skin, built-in interface |
| `timezone`, `logging` | Time zone and log size |

## Common things to change

### Model and provider

```console
$ clite model show
$ clite model list
$ clite model providers           # providers installed and the keys they need
$ clite model set openrouter:anthropic/claude-sonnet-5
Model: anthropic/claude-sonnet-5 via openrouter (saved as default)
```

The `provider:model` form switches provider and model at once; `--provider` does the same when
the model is ambiguous. The available model names come from each provider, and `clite model list`
shows the ones it knows about (the list is cached inside the home).

### Fallback routes

```yaml
model:
  provider: openrouter
  default: anthropic/claude-sonnet-5
fallback_providers:
  - provider: deepseek
    model: deepseek-chat
```

When the main route fails — rate limit, server error, dropped connection — the same request is
tried on the next route, and the conversation keeps going.

### A provider that is not in the list

```yaml
providers:
  office:
    base_url: https://llm.internal/v1
    api_key_env: OFFICE_API_KEY
    api_mode: chat_completions
model:
  provider: office
  default: in-house-model
```

The key is still stored in `.env` as `KANTOR_API_KEY`, not in the config.

### Toolsets

```console
$ clite tools list
$ clite tools disable web
$ clite tools enable web
```

A toolset determines which tools are offered to the model. `clite tools list` shows how many
tools are active in each toolset; the tool list is in [Tools](tools.md).

### Terminal backend

```yaml
terminal:
  backend: docker
  docker:
    image: python:3.12-slim
    network: none
```

Commands and code execution then run inside the container, not on your machine. This is a real
sandbox: files outside the working directory are not visible. Details are in
[Security](security.md).

### Server MCP

```console
$ clite mcp add notes --command npx --args "-y @modelcontextprotocol/server-filesystem /data"
Added MCP server 'notes' (command npx).
$ clite mcp list
$ clite mcp test notes
```

Each server becomes a toolset `mcp-<name>` holding its tools, and can be tested once with
`clite mcp test` before use. `clite mcp add` writes to `config.yaml` without deleting your
comments. Remote HTTP servers are added with `--url` and the header `--header NAME=VALUE`, whose
values may refer to `${NAME}` from `.env`.

### Shell hooks

```yaml
hooks:
  pre_tool_call:
    - command: /usr/local/bin/audit-tool.sh
      matcher: terminal
```

A hook runs only after you approve that event-and-command pair with `clite hooks approve`. See
[Plugins](plugins.md) and [Security](security.md).

## Environment variables

| Variable | Purpose |
|---|---|
| `CLITE_HOME` | Home location, replacing `~/.clite` |
| `CLITE_ENABLE_PROJECT_PLUGINS` | Allow plugins from `./.clite/plugins/` inside the project |
| `CLITE_ACCEPT_HOOKS` | Approve shell hooks without a prompt (careful) |
| `CLITE_SESSION_TOKEN` | Dashboard token; it may pass only through the environment, not through arguments |
| `NO_COLOR` | Turn off colour in the terminal |

## Checking and upgrading

```console
$ clite doctor          # includes "config.yaml is valid"
$ clite config migrate  # bring an old file up to the current config version
```

`clite config migrate` runs transformations that change the shape of the file (renaming keys,
rearranging sections). A fresh installation never needs it.
