---
name: plan-before-acting
description: Break a large or ambiguous task into verifiable steps before starting. Use when a request spans several files or systems, or when the first step is not obvious.
version: 1.0.0
author: C-lite
license: MIT
metadata:
  clite:
    tags: [planning]
    category: productivity
---

# Plan before acting

## Steps

1. **Restate the goal** in one sentence, including how you will know it is done.
2. **Look before planning.** Read the files and run the read-only commands that tell you how
   things are now. A plan made without looking is a guess.
3. **List the steps** with the todo tool. Each step names its outcome and its check
   ("config loader reads the new key; `pytest tests/core -q` passes").
4. **Order by dependency**, and put the riskiest unknown first: if it fails, you want to
   know before the rest is built on it.
5. **Do one step at a time.** Mark it in progress, do it, run its check, mark it done.
6. **Re-plan when you learn something** that changes the remaining steps. Say what changed.

## When to ask instead

Ask the user before starting when a wrong guess would be expensive to undo: deleting data,
changing a public interface, spending money, or choosing between two readings of the request
that lead to different work. Otherwise choose the most reasonable reading, say which one you
chose, and proceed.

## Pitfalls

- A plan with steps you cannot check. "Improve error handling" has no finish line.
- Planning the whole thing in detail before looking at the code.
- Keeping to a plan after the facts have changed.
