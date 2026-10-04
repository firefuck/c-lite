---
name: skill-authoring
description: Write or improve a skill (SKILL.md). Use when saving a reusable procedure with skill_manage, or when a skill turned out wrong or incomplete.
version: 1.0.0
author: C-lite
license: MIT
metadata:
  clite:
    tags: [skills, meta]
    category: meta
---

# Writing a skill

A skill is a short procedure a future session can follow without the context you have now.
Write for a capable reader who has never seen this task.

## When to save one

- You solved something that took several tries, and the working path is not obvious.
- The user corrected your approach and the correction will apply again.
- A task has a fixed sequence that you would otherwise have to rediscover.

Do not save a skill for a one-off, or for something a single tool call already does.

## The file

```markdown
---
name: lowercase-with-hyphens        # must equal the directory name
description: What it does and when to use it. One or two sentences; this line is all the
  model sees until it loads the skill, so name the trigger.
version: 1.0.0
---

# Title

## When to use
## Steps            numbered, concrete, with the exact commands
## Pitfalls         what went wrong before, and how to recognise it
## Verification     how to know it worked
```

## Rules

1. The description decides whether the skill is ever loaded. Say what it does and when.
2. Put exact commands and paths in the steps. "Run the tests" is weaker than
   `scripts/run_tests.sh tests/agent -q`.
3. Record the pitfall that cost you time. That is the part worth saving.
4. Keep SKILL.md under about 200 lines. Move long reference material to `references/` and
   say in the skill when to read it.
5. Never put secrets, tokens or personal data in a skill.

## Maintaining

Prefer `skill_manage(action="patch")` over rewriting: it changes one passage and cannot drop
the rest. Patch a skill as soon as you find it wrong, in the same session.
