# Tools

A tool is one concrete ability the model can call: run a command, read a file, search the web,
send a message. You do not pick them one by one for each task — the agent decides for itself
which tool it needs, and says what it is doing in the terminal.

Tools are grouped into **toolsets**. What is active in a session determines what the model can
call; what is not active is never offered, so the model cannot "misremember" that it has that
ability.

## What is available

```console
$ clite tools list
on   clarify          1/1  Ask the user a question
part clite-cli        19/23  Everything, for the interactive terminal
part clite-cron       17/18  Scheduled runs
part clite-gateway    19/23  Messaging platforms
on   clite-subagent   14/14  Delegated workers
on   cronjob          1/1  Schedule recurring or one-off agent tasks
on   delegation       1/1  Spawn subagents with isolated context
on   file             4/4  Read, write, patch and search files
on   memory           1/1  Persistent notes across sessions
off  messaging        0/3  Send messages and files to connected chat platforms, and speak
on   session_search   1/1  Search past conversations
on   skills           3/3  List, read and maintain skills
on   terminal         3/3  Run shell commands, Python snippets and background processes
on   todo             1/1  Task list for multi-step work
part vision           1/2  Look at images through a helper model
on   web              2/2  Search and fetch web pages as text
```

The `active/total` number shows how many tools in that toolset can actually be called right now;
`part` means some of its tools are waiting on a condition not yet met (an API key, a provider, or
a connected platform). The full list of every tool with its description is in
[Tool reference](../reference/tools.md).

| Toolset | Contents |
|---|---|
| `terminal` | `terminal` (shell commands), `execute_code` (short Python programs), `process` (background processes) |
| `file` | `read_file`, `write_file`, `patch`, `search_files` |
| `web` | `web_fetch`, `web_search` |
| `vision` | `vision_analyze`, `image_generate` |
| `memory`, `todo`, `skills`, `session_search`, `clarify` | One tool each |
| `delegation` | `delegate_task` — run a subagent for a self-contained task |
| `cronjob` | Schedule tasks |
| `messaging` | `send_message`, `send_file`, `text_to_speech` |

The four `clite-*` toolsets are ready-made groups for each surface — `clite-cli` for the terminal,
`clite-gateway` for chat, `clite-cron` for scheduled tasks, `clite-subagent` for delegated
workers. They contain the toolsets above, arranged by what makes sense on that surface:
`clite-cron` has no `clarify` (there is no one to ask) and `clite-subagent` cannot delegate again.

## Changing the active toolsets

```console
$ clite tools disable web
$ clite tools enable web
```

To change the default for all sessions, edit `toolsets` and `disabled_toolsets` in the config.
`disabled_toolsets` always wins, including over a tool pulled in through a combined toolset.

Certain interfaces have their own toolset. Chat uses `clite-gateway`, cron uses `clite-cron`;
`platform_toolsets` narrows them further per platform. So you can, for example, give Telegram
read-only access while the REPL on your machine still has `terminal`.

## Command approval

Every shell command the agent runs passes through an approval gate before it runs. The mode is a
single setting, `approvals.mode`:

| Mode | Meaning |
|---|---|
| `manual` | Default. A command matching a dangerous pattern is asked of you |
| `smart` | A helper model judges first; clearly safe ones run, clearly dangerous ones are denied, the rest are asked |
| `off` | No questions, except two layers that cannot be turned off |

Your answer can apply to that command alone (`once`), to the whole pattern for the session
(`session`), or forever through `command_allowlist` (`always`). Remember that `session` and
`always` apply to the **pattern**, not to that exact command: answering "always" for
`rm -rf build/` also lets through other similar recursive deletes. For something you do not want
to make general, answer `once`.

Two layers can never be turned off: absolutely forbidden commands (recursive delete over root,
the home directory, or system directories; `mkfs`; `dd` to a disk; a fork bomb; shutting the
machine down) are always denied, and globs you write yourself in `approvals.deny` are always
denied, including in `off` mode.

Inside the REPL, `/yolo` turns off the questions for that session; `/config` shows the mode in
effect.

## Where commands run

```yaml
terminal:
  backend: local        # default: directly on your machine
```

`local` means commands run as you, with your full rights. The guardrails above prevent mistakes
and the most direct escalation paths, not a model that has been talked into working against you
over several steps. If you want a real boundary, choose `docker` or `ssh` — commands and file
tools then run inside a container or on another machine. See [Security](security.md) for the
sandbox and its limits.

## Tools waiting for their provider

Some tools appear only when something can answer them. This is deliberate: the model is never
told it can do something that will end up failing.

| Tool | Appears when |
|---|---|
| `web_search` | A search provider exists: `web-search-ddg` (no key) or `web-search-tavily` (`TAVILY_API_KEY`) |
| `image_generate` | An image provider exists, for example `image-gen-openai` (`OPENAI_API_KEY`) |
| `text_to_speech` | A speech provider exists, for example `speech-openai` (`OPENAI_API_KEY`) |
| `vision_analyze` | The `auxiliary.vision` route points at a model that accepts images |
| `send_message`, `send_file` | The gateway is running |

`vision_analyze` sends the image to a helper model and returns only its text answer to the main
model, so your conversation model does not need to be able to see. If the route is blind, the
tool refuses with a message that says how to point it, rather than sending the image to a model
that will refuse it.

## MCP servers

[MCP](https://modelcontextprotocol.io) servers add tools from outside the C-lite process. Each
server becomes a toolset `mcp-<name>` holding its tools, and follows the same rules: it can be
turned off, and the commands it runs still pass through the approval gate. An example of adding
one is in [Configuration](configuration.md#server-mcp).

## What is not there yet

Written plainly so you do not go looking for them:

- **Browser automation** is not there yet. `web_fetch` fetches a page as text; it does not run
  the page.
- **A built-in sandbox** is not there yet; `local` runs unconfined. Docker and SSH already work
  but have never been tested against a real daemon and host.
- **MCP sampling and OAuth** are outside the current scope.
