# Skills

A skill is a stored procedure: a single `SKILL.md` file holding your way of doing something,
which the model reads only when it is relevant. Not code that runs — a skill is never executed —
but instructions that enter the conversation when it is used.

The difference from writing the instructions in a message: a skill persists across sessions, has
a name, and appears in a list the model sees before it starts working. That is how the agent can
remember "this is how we write the weekly report" without you repeating it every time.

## Seeing what is available

```console
$ clite skills list
skill-authoring                bundled   meta                   Write or improve a skill (SKILL.md). Use when saving a reusable proced
meeting-action-items           bundled   productivity           Turn meeting notes or a transcript into cited decisions, owners and fo
plan-before-acting             bundled   productivity           Break a large or ambiguous task into verifiable steps before starting.
weekly-review-planning         bundled   productivity           Run a bounded weekly review over the user's notes and tasks, then prop
arxiv                          bundled   research               Search arXiv and Semantic Scholar for papers by keyword, author, categ
...
```

The second column is the level it comes from: `bundled` (shipped with the package), `local`
(yours inside the home), `project` (from the project you are working in), or `external`.

Seventeen bundled skills are grouped into five categories: `meta`, `productivity`, `research`,
`software-development`, and `web`. They hold things like writing a new skill, breaking a large
task down before starting, citing sources, and software development procedures. The full list is
in [Tool reference](../reference/tools.md).

Inside the REPL, `/skills` shows the same thing.

## Using a skill

The model uses them by itself through the `skills_list` and `skill_view` tools: it reads the list
of names and descriptions (that alone enters the prompt), then opens the full contents of one
skill when the work matches that description. You do not have to point at a skill; if the agent
misses one you meant, naming it is enough.

A skill can also be invoked directly as a slash command:

```console
> /grounded-citations write a two-page summary of these research notes
```

Its contents are sent as your message, not inserted into the system prompt. So what happens is
the same as if you pasted the procedure yourself, and the result follows the ordinary
conversation rules.

## Writing your own skill

Just ask the agent, or write the file directly at `~/.clite/skills/<name>/SKILL.md`. The format
follows the agentskills.io convention, so a skill written for another agent can be used without
changes:

```markdown
---
name: weekly-report
description: Build a weekly report from notes and tasks. Use when asked to recap this week.
version: 1.0.0
metadata:
  clite:
    category: productivity
---

# Weekly report

## Steps
1. Read `notes/` and take what is dated this week.
...
```

The name in `name` must match its directory name. `description` is the only part the model always
sees — write when the skill is used, not just what it contains. Supporting files (images,
templates, scripts) may be placed in `references/`, `templates/`, `scripts/`, or `assets/` inside
the skill directory.

The agent writes skills through the `skill_manage` tool, so you can ask it to save a procedure
that just worked: *"save this as a skill"*.

Wherever a skill is written, the editable copy is the `local` level inside your home. Editing a
skill from another level copies it there first, so a package update does not overwrite your
edits.

## Installing skills from outside

```console
$ clite skills search arxiv
$ clite skills info arxiv
$ clite skills install arxiv
$ clite skills update arxiv
```

The source is a catalogue (a single JSON index file) or a tap you register yourself with
`clite skills tap add owner/repo`, then `install <name>` fetches that catalogue entry.

What is downloaded **is never run** at install time. Every file is inspected first, and the
result is shown for you to approve before anything is written: text is scanned, binary files are
rejected, and scripts are reported per command they contain (`subprocess`, `os.system`, a target
URL). What is rejected can pass only with `--force`. A new version the scanner flags is also
never written by `clite skills update`.

Installing does not overwrite your edits: if the skill directory differs from what was recorded,
`update` shows it first and waits for confirmation.

## Tidying up

The agent piles up skills over time. The curator archives the ones long unused — moved to
`skills/.archive/`, never deleted — and touches only skills the agent itself created; bundled
skills and skills you wrote or installed are never candidates.

```console
$ clite skills curate            # report only, has not changed anything yet
$ clite skills curate --apply    # archive
```

The curator also runs on its own at most once per `curator.interval_hours` (default 168 hours)
during the session's startup maintenance, if `curator.enabled`. Its failure never blocks your
session.

## Discovery levels

The same name can exist in several places. The first wins, in order: project (`.clite/skills`
inside the repository you are working in), local (your home), external (`skills.external_dirs`
and directories from plugins), then bundled.

Skills from the project and external levels come from someone else's files — a cloned
repository — and their contents are followed as a procedure. That is why both are scanned every
time they are found, and anything flagged is skipped without being used. This is the same reason
`CLITE_ENABLE_PROJECT_PLUGINS=1` is needed for project plugins: a project directory is not yours
until you declare it so.
