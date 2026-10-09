---
name: simplify-code
description: Clean up recent code changes with four focused reviewers running in parallel, then apply only the fixes worth applying. Use when the user says simplify, or asks for a cleanup of what was just written.
version: 1.0.0
author: C-lite
license: MIT
metadata:
  clite:
    category: software-development
    tags: [cleanup, refactor, delegation, parallel, review]
    requires_toolsets: [terminal]
    attribution: "Adapted from the simplify-code skill in Nous Research's hermes-agent (MIT, Copyright (c) 2025 Nous Research), inspired by Claude Code's /simplify."
---

# Simplify code

Review recent changes with four narrow reviewers, aggregate what they find, and apply the
fixes that are worth applying. This is a **cleanup pass, not a bug hunt** — it improves code
that already works. Correctness review is a different job; see `requesting-code-review`.

Four narrow reviewers beat one broad one: each digs into a single class of problem instead of
diluting its attention, and they run at the same time, so the cost is one review's latency.

## When to use

- "Simplify", "clean up my changes", "review my recent code".
- After a change that grew more complicated than the problem it solves.

The user may narrow it: a focus (`reuse`, `quality`, `efficiency`, `altitude`), a dry run
("just report, change nothing"), or a scope ("the last commit", "staged", `src/foo.py`).
Honour those. Do not run this after every edit — it costs four subagents, so invoke it only
when asked.

## Steps

1. **Pick the diff**, in this order: `git diff` (uncommitted), then `git diff HEAD`, then the
   scope the user named — `git diff --staged`, `git diff HEAD~1`, `git diff main...HEAD`,
   `git diff -- <path>`. If there is no repository or no change, say so and stop.

   Note the size. Past roughly 2,000 changed lines, say that four subagents each carrying the
   full diff will be expensive and offer to scope it down first.

2. **Launch four reviewers at once** with one `delegate_task` call, each on `terminal`, `file`
   and search tooling, and give **every** reviewer the **whole diff** plus the absolute repo
   path. Splitting the diff defeats the design: cross-file duplication only shows up with the
   full picture.

   Tell each one to search the codebase for evidence rather than reason from the diff alone,
   to run `git blame` before proposing a removal (Chesterton's fence), and to report each
   finding as:

   ```
   file:line -> problem -> cost -> suggested fix | confidence: high|medium|low | risk: SAFE|CAREFUL|RISKY
   ```

   The **cost** field is the filter: a finding that cannot say what the problem costs is a
   nit. `SAFE` means proven not to change behaviour (unused import, dead comment, pass-through
   wrapper). `CAREFUL` improves without changing semantics (rename a local, flatten a nested
   ternary, extract a helper). `RISKY` may change behaviour or a public contract.

   The four angles:

   - **Reuse** — new code that reimplements something the codebase already has. Name the
     existing function and where it lives; "there is probably a helper" is not a finding.
   - **Quality** — redundant state, parameter sprawl, near-duplicate blocks that should share
     an abstraction, leaky abstractions, stringly-typed code where a constant or registry
     exists, deeply nested conditionals, comments that restate the line below them.
   - **Efficiency** — repeated work, sequential work that could be concurrent, heavy work on a
     hot path, existence checks before an operation that could just be attempted, unbounded
     growth, leaked listeners, swallowed errors (`except: pass`, empty `catch`).
   - **Altitude** — a fix applied at the call site when the shared path is what needs
     changing: a special case bolted onto a generic path, a workaround stacked on a
     workaround, a flag added to route around a bad default. Say when the deeper fix is large
     enough to deserve its own task, and do not rebuild the shared mechanism inside a cleanup.

   Fold the repository's own rules (an `AGENTS.md`, a linter config) into the prompts so the
   suggestions match the house style instead of fighting it.

3. **Aggregate.** Merge the findings, collapsing two that target the same line or the same
   mechanism. Drop what you know to be wrong — you have the most context and you do not have
   to argue with a reviewer. Where reviewers disagree, resolve in this order: correctness,
   then the user's stated focus, then readability and reuse, then micro-performance.

4. **Apply by risk tier**, running the tests that cover the touched files after each batch and
   reverting any single fix that breaks one:

   - **SAFE** — apply directly.
   - **CAREFUL** — apply one file at a time, with verification.
   - **RISKY** — do not apply. Present it with the risk and the test coverage and let the user
     decide; altitude findings usually land here.

   On a dry run, present all three tiers and apply nothing. Keep every edit scoped to what the
   diff touched plus the minimum surrounding change the fix needs.

5. **Report** what was applied, grouped by reviewer angle and risk tier, plus what was
   deliberately skipped and why. If the review ran inline instead of as four subagents, say
   that plainly so the user knows what actually ran.

## Pitfalls

- Fanning out wider than four. More reviewers means more cost and more conflicting
  suggestions, not better coverage.
- Applying a finding with no `file:line` evidence. That is a guess.
- Drifting into bug hunting. A real correctness bug is worth reporting, but as a separate
  note, not folded into cleanup.
- Deleting an "unnecessary" empty `except`: it may be deliberate. Flag it, do not remove it.
- Trusting a dead-code tool (`knip`, `ts-prune`, `depcheck`) on its own — these flag symbols
  used dynamically. Grep for the name before removing it.
- Renaming a public contract (export, route, column, config key) because the name is bad.

## Verification

- [ ] Every applied fix has a `file:line` and a stated cost.
- [ ] The tests covering the touched files pass after the last edit.
- [ ] Nothing from the RISKY tier was applied without the user's say-so.
- [ ] The summary distinguishes what was applied from what was only proposed.
