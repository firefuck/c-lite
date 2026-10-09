# Gateway

The gateway connects the agent to chat platforms: Telegram, Discord, Slack, email, Matrix, Signal,
WhatsApp. One long-lived process receives messages, decides who may speak, routes them to their
session, runs the turn, then sends the reply.

The important thing to understand: messages from chat enter the **same** session you use in the
terminal — the same memory, files, skills, and procedural memory. So an agent you train in the REPL
is immediately useful on Telegram.

## Setting up Telegram

Telegram is the simplest platform to try: it needs only a bot token, without a webhook.

1. Create a bot via [@BotFather](https://t.me/BotFather) and copy its token.
2. Store the token in `~/.clite/.env` as `TELEGRAM_BOT_TOKEN=...`.
3. Enable the platform in `config.yaml`:

```yaml
gateway:
  platforms:
    telegram:
      allowed_users: [123456789]   # your Telegram id
```

4. Run the gateway:

```console
$ clite gateway run
```

Send a message to your bot, and the agent answers there. To see your user id, first send a message
without `allowed_users`; a stranger who writes directly is offered a pairing code, and the code
appears in the gateway log.

Other platforms are added with the same pattern. Discord and Slack have built-in adapters; `email`,
`matrix`, `signal`, and `whatsapp` are platform plugins already in the package.

## Who may speak

Nobody is allowed by default. Three ways to give access:

| Way | For |
|---|---|
| `allowed_users` per platform | A fixed list you write in the config |
| Pairing | An unknown person is offered an eight-character code; you approve it on the gateway machine |
| `gateway.allow_all_users: true` | Anyone who finds the bot. **Do not use on a public platform** |

```console
$ clite gateway pair approve telegram ABC-DEF-GH
```

Every user you allow can tell the agent to run commands on the gateway machine, and they are the
one who answers approval requests. Allowing someone is the same as giving them shell-equivalent
access on that machine.

Session keys separate conversation contexts, not data: people allowed in one profile share the
session database, memory, and files. C-lite is currently aimed at a single owner or a group of
people who trust each other.

## Running it continuously

```console
$ clite gateway install      # install as a service (systemd user / LaunchAgent)
$ clite gateway start
$ clite gateway status
$ clite gateway logs
```

`install` creates one service unit per profile, so several profiles can run side by side. A lock
refuses a second instance in the same home. When stopped (SIGTERM), the gateway stops accepting new
messages and then waits for the turn in progress to finish.

The manual way still exists: `clite gateway run`, or `clite dashboard`, which runs the backend and
opens the web dashboard.

## How the agent replies

- **One turn per thread.** One long task does not block other chats.
- **Long replies are split** at paragraph boundaries, then lines, then words, then sent in stages.
  Adapters that can edit messages (Telegram, Discord, Slack) update one message as the text flows.
- **When you write again while the agent is still working**: `display.busy_input_mode` decides what
  happens. `interrupt` (default) stops the running turn and starts a new one — a burst of quick
  messages is merged into one. `queue` runs them in order. `steer` inserts your message into the
  running turn without stopping it.
- **Approval over chat.** If the agent needs to run a dangerous command, it sends the command and
  waits for `/approve`, `/approve session`, `/approve always`, or `/deny`. Silence until
  `approvals.timeout` means deny.
- **Attachments.** Images go into the model request; documents are mentioned as files that can be
  read. A reply can send files back via `send_file`.
- **Voice messages** are transcribed first, and for platforms you register in
  `speech.reply_with_voice` the reply is spoken back. Both need a speech provider; without one the
  agent still replies, only in text.

## Cron

A cron job is a **prompt**, not a shell command: it runs in a new session without the conversation
memory that created it, then its result is delivered to where you specify. This is how to let the
agent work while you are away.

```console
$ clite cron add --name "morning digest" --schedule "0 9 * * 1-5" \
    --prompt "Summarise last night's mail and important news, then send today's to-do list." \
    --deliver telegram
$ clite cron list
$ clite cron history "morning digest"
```

Three forms of schedule:

| Kind | Example | Meaning |
|---|---|---|
| Once | `30m`, `2h`, `1d`, `2026-01-31T09:00` | That long from now, or at a specific timestamp |
| Repeating | `every 30m`, `every 1d` | At least 60 seconds |
| Cron | `0 9 * * 1-5` | Five fields, like classic cron |

The timezone comes from `timezone` in the config; the default is the system zone.

Where the result is delivered:

| `deliver` | Meaning |
|---|---|
| `local` | Only stored in `~/.clite/cron/output/` |
| `origin` | Sent back to the chat where the job was created |
| `telegram:123456789` | Sent to a specific chat on a platform |

A reply that begins with `[SILENT]` or is empty is not sent, so a monitoring job can stay quiet
when there is nothing to report.

A job runs unattended: it cannot ask you questions, it cannot schedule other jobs, and dangerous
commands are denied by default (`approvals.cron_mode`). Its prompt is scanned when it is created
and when it is changed, because it will later run with the agent's tools without you beside it.

Who runs the scheduler: the gateway (a background ticker, for as long as the gateway is alive),
`clite cron daemon`, or an external timer that calls `clite cron tick`. A job runs at most once —
a process that dies mid-way can lose one run, but never duplicates it.

## What is not there yet

- There is no durable delivery queue: a message that fails to send is only recorded in the log.
- There is no per-user rate limiting.
- Adapters other than `local` are tested against mock servers; Telegram, Discord, Slack, email,
  Matrix, Signal, and WhatsApp have not been tried against the real services. The details are in
  [STATUS.md](https://github.com/dragovics/clite/blob/main/docs/STATUS.md).
