# Installing

## What you need

| | |
|---|---|
| Python | 3.11 or newer |
| Node.js | 22, only for the TUI and the desktop app. The classic REPL, the dashboard, the gateway, and cron do not need Node |
| System | Linux, macOS, or Windows |

The distribution is named `c-lite`; the Python package and its command stay `clite`. Releases
are published via [GitHub Releases](https://github.com/dragovics/clite/releases), not PyPI.

## From the release assets

Release `v0.1.0` has been published. Download the wheel (the repository is still private, so
downloading needs an account with access), then install it with pipx or inside a virtualenv:

```console
$ gh release download v0.1.0 --repo dragovics/clite --pattern '*.whl' --dir dist
$ pipx install ./dist/c_lite-0.1.0-py3-none-any.whl
$ clite --version
C-lite 0.1.0
```

Without pipx, replace the second line with `pip install ./dist/c_lite-0.1.0-py3-none-any.whl`
after activating a virtualenv.

## From source

```console
$ git clone https://github.com/dragovics/clite && cd clite
$ pip install -e ".[dev]"
$ python -m clite chat -q "halo" --provider mock
You said: halo
```

`--provider mock` answers without an API key, so the last line is useful for making sure the
installation is alive before you pick a real provider.

## After installing

```console
$ clite setup        # choose a provider, save the API key, choose a model
$ clite doctor       # check the installation
$ clite              # the classic REPL
```

`clite setup` runs in stages: provider, key (tested with one real call and rejected if it is
wrong), a model from that provider, the toolset, then the safety options and Telegram.
Everything can be skipped with flags, so a non-interactive script produces the same config.

`clite doctor` checks the Python version, a writable home, the config, full SQLite search,
configured providers, the terminal backend, active plugins, shell hooks waiting for approval,
and Node.js. As long as no provider has been chosen, that one line is what it reports — the
rest has been green since installation.

## Where the data is

All the state is in one directory, `~/.clite`:

| Path | Contents |
|---|---|
| `config.yaml` | all the settings |
| `.env` | API keys and other secrets, permission 0600 |
| `state.db` | sessions and messages (SQLite, with full-text search) |
| `memories/` | long-term memory and the user profile |
| `skills/`, `plugins/` | your skills and plugins |
| `logs/` | `agent.log` and `errors.log` |

That directory can be moved with the `CLITE_HOME` environment variable. Profiles give you
several fully separate homes — their own config, secrets, memory, sessions, skills, and
plugins — see `clite profile --help` and [Configuration](../guide/configuration.md).

Back up before you change a lot of things:

```console
$ clite backup create              # archive the home, without secrets
$ clite backup create --include-secrets   # include .env, permission 0600
```

## Updating and removing

```console
$ clite update          # recognise the installation method (git, pipx, pip) and install a newer one
$ clite update --check  # only check
$ clite uninstall       # remove the package; --purge deletes the home data too
```

## Running without installing

As long as you are inside the checkout, every command can be run as a module:

```console
$ python -m clite doctor
```

That is useful when you are developing C-lite itself; for everyday use, install the package so
that the `clite` command is always on your PATH.

## If something goes wrong

| Symptom | What to try |
|---|---|
| `clite: command not found` | The command is installed inside a virtualenv or pipx's Scripts directory, which may not be on your PATH |
| `clite doctor` says the config is invalid | `clite config path` shows the file; `clite config edit` opens it in your editor. A broken config is never overwritten on its own |
| No provider | `clite setup`, or put the key in `.env` then choose a model with `clite model` |
| The TUI refuses to start | Node.js 22 is not installed. The classic REPL still works; `clite` with no arguments opens it |
