---
name: systematic-debugging
description: Find the root cause of a bug before changing code. Use for any failing test, crash, or behaviour that does not match what the code appears to say.
version: 1.0.0
author: C-lite
license: MIT
metadata:
  clite:
    tags: [debugging, engineering]
    category: software-development
    requires_toolsets: [terminal]
---

# Systematic debugging

Do not change code until you can state the cause in one sentence and point to the line.

## Steps

1. **Reproduce.** Get one command that fails every time. Write it down. If the failure is
   intermittent, find what varies (order, time, environment) before anything else.
2. **Read the whole error.** The last line names the symptom; the cause is usually a few
   frames up. Open the file and line it names.
3. **State what you expected and what happened**, in terms of values, not feelings.
4. **Narrow.** Halve the distance between "known good" and "known bad": an earlier commit, a
   smaller input, a single test. Add a print or an assertion at the midpoint and rerun.
5. **Form one hypothesis and test it** with the cheapest experiment that could disprove it.
   One change per experiment.
6. **Fix the cause**, not the place the symptom showed up. If a value is wrong where it is
   read, find where it was written.
7. **Prove it.** Run the reproduction command again, then the surrounding tests.
8. **Remove the scaffolding** (prints, temporary files) you added.

## Pitfalls

- Fixing the first thing that looks wrong. If you cannot explain why it produced this exact
  failure, it is probably not the cause.
- Several changes at once. When the failure goes away you will not know which one mattered.
- Trusting a comment or a name over the code's behaviour. Run it.
- Stale state: caches, compiled artefacts, an old process still holding the port.

## Verification

The reproduction command passes, the test suite around the change passes, and you can
explain in one sentence why the bug happened.
