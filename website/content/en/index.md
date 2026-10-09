# C-lite

C-lite is a personal AI agent: one conversation core used from the terminal, the web dashboard,
the desktop app, and chat. Its architecture is derived from Nous Research's
[Hermes Agent](https://github.com/NousResearch/hermes-agent), then grown stage by stage in this
project.

This installation is still **scaffolding**: what exists already runs and is guarded by tests,
but some of it has never been run against the real thing (a real provider API, real Telegram,
the desktop app on Windows and macOS). What has and has not been verified is recorded in
[STATUS.md](https://github.com/dragovics/clite/blob/main/docs/STATUS.md).

## What it can do

- **Chat and get tasks done.** The agent runs shell commands, reads and writes files, searches
  the web, remembers things about you, and uses stored procedures.
- **Many interfaces, one conversation core.** The classic REPL, the TUI, the web dashboard, the
  desktop app, and the chat gateway use the same sessions and memory.
- **Chat.** Telegram, Discord, Slack, email, Matrix, Signal, and WhatsApp; voice messages are
  transcribed and the replies can be spoken back.
- **Scheduled.** Cron jobs run tasks without you, and the results are sent to chat.
- **Extensible.** Tools, skills (`SKILL.md`), Python plugins, MCP servers, and shell hooks.

## Where to start

| If you want to | Read |
|---|---|
| Install it | [Installing](start/install.md) |
| Try it now, without an API key | [Quickstart](start/quickstart.md) |
| Change the settings | [Configuration](guide/configuration.md) |
| Know what the agent can do | [Tools](guide/tools.md) |
| Save your own ways of working | [Skills](guide/skills.md) |
| Add abilities with code | [Plugins](guide/plugins.md) |
| Use it from Telegram or Slack | [Gateway](guide/gateway.md) |
| Know what is guarded and where the limits are | [Security](guide/security.md) |
| The list of commands, config keys, and tools | [Reference](reference/commands.md) |

## Languages

This site exists in two languages. Every page has its counterpart in the other language; the
button at the top right switches to the same page in that language.

## Licence

MIT. The attribution for Hermes Agent is in
[NOTICE.md](https://github.com/dragovics/clite/blob/main/NOTICE.md).
