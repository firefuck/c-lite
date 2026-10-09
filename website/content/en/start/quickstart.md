# Quickstart

Ten minutes, starting from what needs no API key. Every command on this page can be copied as
is; the ones in the `bash` blocks are run by this project's test suite, so their output will
never differ from what is written here.

## 1. Make sure the installation is alive

The `mock` provider answers without an API key and without a network. Use it to make sure the
command exists and the home is writable:

```bash
clite --version
clite chat -q "list three things you can do" --provider mock
clite model list
clite tools list
clite skills list
clite doctor
```

What you see, in order: the version number; the `mock` answer to that question; the list of
models each provider knows; the list of toolsets with the number of active tools; the list of
bundled skills; and the result of the installation check.

`clite doctor` will report exactly one problem — no provider configured — until the next step
is done. The rest has been green since installation. If there is another red line, the fix is
in [Installing](install.md#if-something-goes-wrong).

## 2. Choose a provider and model

```console
$ clite setup
Setting up /home/you/.clite
...
$ clite config get model.provider
openrouter
```

`clite setup` asks for the provider, the API key, the model (the list is fetched from that
provider), the toolset, the approval mode, and the Telegram token. The key is tested with one
real call; if it is wrong, that step is repeated instead of being saved. What is saved: the key
to `.env` (permission 0600), the rest to `config.yaml`.

The questions can be skipped entirely with flags, which is useful for scripts:

```console
$ clite setup --provider openrouter --api-key "$OPENROUTER_KEY" --model anthropic/claude-sonnet-5
Saved: provider openrouter, model anthropic/claude-sonnet-5
```

Without a terminal (stdin is not a TTY), `clite setup` refuses to run and names that flag form.
The available providers, each one's key variable, and their default models are in
[Configuration](../guide/configuration.md).

If you want to use a local model, Ollama and LM Studio are in the provider list and need no
key. For an endpoint that is not in the list, register your own provider in the `providers`
section of the config.

## 3. Chat

```console
$ clite
> summarise the file notes.md, then save the summary as summary.md
…
> /help
```

`clite` with no arguments opens the classic REPL. Write commands the way you would explain them
to another person; the agent picks the tools it uses itself, and every dangerous shell command
will ask for your approval first.

A few slash commands you will use often:

| Command | Purpose |
|---|---|
| `/help` | The full list of slash commands |
| `/new`, `/sessions`, `/resume` | Start a new session, pick an old session, continue |
| `/model`, `/provider` | Change the model or provider for this session |
| `/tools` | View, enable, disable toolsets |
| `/skills`, `/memory` | Skills and long-term memory |
| `/status`, `/compress` | The state of the session, and compact a long conversation |
| `/rollback`, `/checkpoints` | Undo file edits the agent made |
| `/image` | Attach an image to the next message |
| `/stop` | Stop the turn that is running |
| `/quit` | Quit |

## 4. One question without the REPL

For scripts and pipes, `-q` runs one turn then exits. Only the answer goes to stdout; tool
progress goes to stderr, and `--json` prints the turn's result in full.

```bash
clite config get model.provider
clite chat -q "summarise the file notes.md"
clite sessions list
```

In a script, do not forget that nothing can answer approval questions: dangerous commands are
refused (`approvals.single_query_mode`). See [Security](../guide/security.md).

## 5. Continue from here

| If you want to | Read |
|---|---|
| Change the model, toolset, or other behaviour | [Configuration](../guide/configuration.md) |
| Know which tools exist | [Tools](../guide/tools.md) |
| Teach the agent how you work | [Skills](../guide/skills.md) |
| Add abilities with code | [Plugins](../guide/plugins.md) |
| Use the agent from Telegram, Discord, Slack | [Gateway](../guide/gateway.md) |
| Let the agent work while you are away | [Gateway](../guide/gateway.md#cron) |
| See the dashboard in the browser | `clite dashboard` |
| Check what has and has not been verified | [STATUS.md](https://github.com/dragovics/clite/blob/main/docs/STATUS.md) |
