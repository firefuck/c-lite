# Security

This agent runs shell commands, writes files, and reads web pages on your behalf. This page
explains what is guarded, what is not, and where the fences end — so that you do not rely on a
fence that is not there.

## What to understand first

**By default there is no sandbox.** The `local` terminal backend runs commands as you, with your
full rights. The fences below prevent two things: a model mistake that causes damage, and the most
direct escalation path from untrusted text. Those fences do **not** hold back a model that has
already been persuaded to work against you and is willing to do so over several steps.

What holds back a model like that is an isolated terminal backend:

```yaml
terminal:
  backend: docker
  docker:
    image: python:3.12-slim
    network: none
```

Commands and file tools then run inside the container: the working directory is mounted at the same
path, files outside it are not visible, and the container starts without the host's environment
variables — no provider keys, no contents of `.env`. The `ssh` backend gives the same separation
from another machine.

Docker and SSH are already implemented and tested, but have never been run against a real daemon
and host in this project. Treat both as promising fences, not ones already proven on your machine.

## Who is trusted

| Party | Trusted for | Reason |
|---|---|---|
| You on that machine | Everything | You own the home, config, and `.env` |
| `config.yaml` and `.env` | Setting policy and credentials | Only you may write them |
| An enabled plugin | Running in-process with full rights | You read it and then enable it yourself |
| An approved shell hook | Running on every event | You approve that exact command |
| The model | No, for security decisions | Its output can be shaped by the text it reads |
| Web pages, file contents, tool output | No | Can carry instructions aimed at the model |
| Skills and plugins from outside | No, until installed and enabled | |
| Chat users on the gateway | No, until allowed | See [Gateway](gateway.md) |

## Shell commands

Every `terminal` command — and every program run by `execute_code` — passes through an approval gate
before it runs. Four layers, from the one that cannot be opened:

| Layer | Applies in mode | Can be opened with |
|---|---|---|
| Absolutely forbidden: recursive delete over root, the home directory, or system directories; `mkfs`; `dd` to a disk; writing to block devices; fork bombs; `kill -1`/`kill -HUP`; shutting down or rebooting the machine | All, including `off` | Nothing |
| `approvals.deny` — globs you write yourself | All, including `off` | Editing the config |
| Reaching the agent's own settings or credentials | `manual`, `smart` | Your answer, **every time** |
| Dangerous patterns (recursive delete, `sudo`, `git push --force`, download then run, and the like) | `manual`, `smart` | Your answer; can be remembered per session or forever |

The third layer closes the most direct escalation path. `config.yaml` **is** its own policy —
approval mode, allowlist, active plugins — so a command like `clite config set approvals.mode off`
or anything that writes to `~/.clite/` is never remembered, never enters the allowlist, and is
never let through by the `smart` reviewer. You are asked every time.

A command is read twice: as written, and as the shell reads it — so `rm -rf "$HOME"` and
`rm --recursive --force /` are judged the same as their plain spelling. A name assembled on the
same line is also resolved first: `d=/; rm -rf $d` is rejected as a recursive delete over root.
`execute_code` text enters the same gate, with patterns that read Python syntax, so
`shutil.rmtree(...)` and `subprocess.run(["rm", ...])` are flagged like their command forms.

When there is nobody to ask — cron, `clite chat -q`, a silent chat — the answer is deny.

Two warnings that matter:

- **This gate does not run a shell.** A name that only forms while the command runs, or a script
  written to a file and then run in a later step, is not seen by it. This gate is a safety belt
  against mistakes, not a sandbox.
- **A remembered approval applies per pattern, not per command.** Answering "session" for
  `rm -rf build/` lets through every later recursive delete, except those absolutely forbidden.
  For a command you do not want to generalise, answer `once`.

## Files

File tools cannot write to the things that set policy or store credentials: `.env`, `config.yaml`,
`auth.json`, the shell hook approval list, and gateway pairing data in every home — including the
home of another profile. Credential directories (`~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.kube`,
`~/.netrc`) and system directories are also refused, for writing as well as reading.

Besides that, credentials that appear in other files are redacted from what the model reads,
because everything the model reads is sent to the provider and stored in the session database.

Worth knowing: **file tools are not confined to the working directory.** What is confined is only
the deny-list above. Changes the agent makes can be undone with `/rollback` inside the session, but
that restores, it does not prevent — the real boundary is still the sandbox.

## Credentials

- API keys exist only in `~/.clite/.env` with 0600 permissions, and are read only through paths
  that mark them as credentials.
- Commands run by the agent, background processes, MCP servers, and `execute_code` **do not
  inherit** any credentials — including keys you `export` yourself in the shell. Exceptions must be
  named one by one in `terminal.env_passthrough`.
- Terminal output is redacted before it enters the transcript.
- Provider keys are sent only to the host that the key belongs to, so an OpenRouter key never goes
  along to requests to other hosts.
- Each profile has its own `.env`; copying a profile copies settings, not secrets.

Because of that, the safest way to store a third-party key is to put it in `.env` under a known
name. Keys in unusual formats that appear in files or command output are not always caught by
pattern-based redaction.

## Text from outside

The system prompt has the highest authority in the model's eyes, so text from outside is scanned
before it is allowed in: project context files, skills from repositories, skills at install time,
memory entries, and cron job prompts. The scanner looks for instructions to ignore rules,
exfiltration commands, and invisible characters. What it catches is **blocked along with its
reason**.

This scanner is deliberately narrow — a false positive means silently discarding your file — so it
catches crude attacks, not careful ones. Tool results and web pages are not scanned: both enter as
tool messages, not as the system prompt, and are treated as data.

## Code from outside

| Source | Condition before it runs |
|---|---|
| A plugin in `~/.clite/plugins/` or from pip | Its name is in `plugins.enabled`; installing only copies |
| A plugin in the project (`./.clite/plugins/`) | `CLITE_ENABLE_PROJECT_PLUGINS=1` **and** it still has to be enabled |
| A shell hook in `config.yaml` | `clite hooks approve` for the exact same pair of event and command |
| An MCP server | You write it yourself in `mcp_servers` |
| A skill | Never executed; its contents are read by the model as text |

A plugin cannot replace a bundled tool without per-plugin permission in the config. Shell hook
approval is kept separate from the config because the config can be changed by the agent through
the terminal; a config key is not enough as approval for something that runs automatically.

## Web

`web_fetch` accepts only `http` and `https`, and refuses addresses that are not public — loopback,
private networks, link-local, cloud metadata — unless `web.allow_private_urls` is turned on. Every
redirect hop is checked with the same rules, so a public page cannot bounce the agent to an
internal address.

## Server and dashboard

`clite serve` opens the whole agent — including the terminal — to anyone who holds the token.

- By default it listens only on `127.0.0.1`. Binding it to another host triggers a warning.
- The token is generated randomly per process and compared in constant time. It is in the URL
  fragment of the dashboard, which is never sent to the server nor recorded in the log.
- The token enters only through the `CLITE_SESSION_TOKEN` environment variable; there is no
  command-line option for it, because a process's arguments are visible to all users of that
  machine.
- A WebSocket from the browser must come from the dashboard's own origin, and a server bound to
  loopback only serves requests addressed to a loopback name — so DNS rebinding is useless.
- Text from the model and tools is shown as text, never as HTML.

## Gateway

Every allowed chat user can tell the agent to run commands on the gateway machine, and that user is
the one who answers approval requests. **Allowing someone means giving them shell-equivalent
access.** Strangers in a group are ignored, pairing codes are rate-limited and locked after five
wrong attempts, and pairing can be approved only by you on the gateway machine.

Session keys separate conversation contexts, but users allowed in one profile still share the
session database, memory, and files. Do not promise privacy between family members or team members
within one profile.

## Known gaps

Written plainly, so that nothing relies on a fence that is not there.

| Gap | Consequence |
|---|---|
| The `local` backend has no sandbox | A command that gets past the gate runs with your full rights |
| The gate reads the text of **one** command | A script written to a file and then run in a later step is not seen |
| A remembered approval applies per pattern | One "always" lets through that entire pattern from then on |
| File tools are not confined to the working directory | The model can write outside the deny-list |
| A shell hook script can be rewritten | Approval binds the command text, not the contents of the file it points to |
| A plugin runs with full rights | A malicious plugin you enable can do anything |
| A pattern-based text scanner | A carefully written injection gets through |
| Pattern-based redaction | A key in an unusual format in a file or output can be sent to the provider |
| `web_fetch` resolves the name twice | DNS rebinding can get through |
| The server token lives for the whole process | A leaked token is valid until the server is stopped; `clite serve token` gives a named token that can be revoked |

The complete document on security, the trust model, and the failure directions is in the
repository:
[06-keamanan.md](https://github.com/dragovics/clite/blob/main/docs/arsitektur/06-keamanan.md).
