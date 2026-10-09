---
name: codebase-inspection
description: Measure a codebase with pygount or the shell, to answer how big it is and what it is made of. Use when asked for lines of code, a language breakdown, or code-to-comment ratios.
version: 1.0.0
author: C-lite
license: MIT
metadata:
  clite:
    category: software-development
    tags: [loc, metrics, codebase, pygount]
    requires_toolsets: [terminal]
    attribution: "Adapted from the codebase-inspection skill in Nous Research's hermes-agent (skills/software-development/codebase-inspection, MIT, Copyright (c) 2025 Nous Research)."
---

# Codebase inspection

Answer "how big is this repository, and what is it made of?" with a measurement rather than a
guess. `pygount` is the best tool for it; `cloc` or a plain shell one-liner will do when it is
not installed.

## When to use

- A lines-of-code count, a language breakdown, or a code-versus-comment ratio.
- "How big is this repo" before a refactor or a review.
- Deciding where the weight of a project actually sits.

## Steps

1. **Check what is available.**

   ```bash
   command -v pygount || command -v cloc || command -v tokei
   ```

   Install the first one only if the user wants a real breakdown and is happy to add a tool:
   `python -m pip install pygount`. Otherwise fall back to step 4.

2. **Get the summary.** Always exclude dependency and build directories, or the crawl takes
   minutes and swamps the answer:

   ```bash
   pygount --format=summary \
     --folders-to-skip=".git,node_modules,venv,.venv,__pycache__,.cache,dist,build,.next,.tox,.mypy_cache,coverage" \
     .
   ```

3. **Narrow when the repo is large** — a monorepo is usually several questions:

   ```bash
   pygount --suffix=py --format=summary .          # one language only
   pygount --format=json .                          # machine-readable
   pygount --folders-to-skip=".git,node_modules" . | sort -t$'\t' -k1 -nr | head -20
   ```

   With `cloc`: `cloc --exclude-dir=.git,node_modules,venv,.venv .`. With `tokei`:
   `tokei --exclude node_modules --exclude .git .`

4. **Fall back to the shell** when no counter is installed. It counts lines, not statements,
   so say so in the answer:

   ```bash
   find . -path ./.git -prune -o -name '*.py' -print0 | xargs -0 wc -l | tail -1
   find . -path ./node_modules -prune -o -type f -name '*.*' -print | \
     sed 's/.*\.//' | sort | uniq -c | sort -rn | head -15
   ```

5. **Read the table, then interpret it.** Columns are language, files, code lines, comment
   lines and percentage. The pseudo-languages matter: `__empty__`, `__binary__`,
   `__generated__`, `__duplicate__` and `__unknown__` are not languages — a large
   `__generated__` bucket means the real hand-written code is smaller than the total.
   Markdown counts entirely as comments, and JSON lines are counted conservatively. Report
   the numbers you measured and name the tool and exclusions you used.

## Pitfalls

- Running a counter without exclusions. Dependency trees are usually larger than the project
  and make the result meaningless.
- Reporting a `find | wc -l` total as "lines of code". It includes blanks, comments and
  generated files; call it what it is.
- Quoting a byte or line total as a size comparison when the two repos were counted with
  different tools or different exclusions.

## Verification

- [ ] The answer names the tool, the exclusions and the directory that was measured.
- [ ] Any fallback count is labelled as a line count, not a code count.
