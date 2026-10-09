---
name: spike
description: Run throwaway experiments to answer feasibility questions before committing to a build. Use when the user wants to see if something works, or to compare two approaches.
version: 1.0.0
author: C-lite
license: MIT
metadata:
  clite:
    category: software-development
    tags: [spike, prototype, experiment, feasibility]
    requires_toolsets: [terminal]
    attribution: "Adapted from the spike skill in Nous Research's hermes-agent (skills/software-development/spike, MIT, Copyright (c) 2025 Nous Research), which credits gsd-build/get-shit-done."
---

# Spike

A spike is a throwaway experiment that answers one question with evidence. It exists to kill a
bad idea cheaply, or to prove that the risky part of a good one works before the real build
starts. Once it has paid its debt, throw it away.

## When to use

- "Let me try this", "is this even possible?", "I want to see if X works".
- "Before I commit to Y", "quick prototype of Z", "compare A and B".
- A plan has one step nobody can estimate because nobody knows whether it works.

Do not spike when the answer is already in the docs or the code — that is research, not a
build. Do not spike the production path; plan it instead. Do not spike an idea that is already
validated — start building.

## Steps

1. **Decompose** the idea into 2–5 independent feasibility questions, one spike each. Write
   them as a table, with the spike most likely to kill the idea first:

   | # | Spike | Validates (Given / When / Then) | Risk |
   |---|---|---|---|
   | 001 | websocket-streaming | Given a websocket, when the model streams, then the client sees chunks in under 100 ms | high |
   | 002a | pdf-parse-pdfjs | Given a multi-page PDF, when parsed with pdfjs, then the text is extractable | medium |

   A comparison spike is one question answered by two approaches: `002a`, `002b`. A bad
   question is broad, has no observable output, or is really "read the docs about X".

2. **Align.** Show the table and ask whether to build all of it in that order or adjust.
   Skip this when the user already named the single thing they want spiked — then it is one
   spike.

3. **Research just enough** to pick an approach: two or three sentences on why this spike
   matters, a table of the credible options with their trade-offs, and a stated pick. Use
   `web_search` and `web_fetch` for candidates and docs, and `terminal` to see what is
   already installed (`python -m pip show <package>`). Skip this step when the spike has no
   external dependency.

4. **Build**, one directory per spike, standalone and hardcoded:

   ```
   spikes/001-websocket-streaming/
   ├── README.md
   └── main.py
   ```

   Prefer output the user can feel over a log line that says "it works", in this order: a
   runnable command with visible output, a small page, a single endpoint, or a test with
   real assertions. Test the edges — one happy-path run is not a verdict. Do not add package
   managers, bundlers, Docker or config files unless the question is about them.

   When two approaches both need real engineering, run them side by side with
   `delegate_task` and write the head-to-head yourself.

5. **Write the verdict** at the end of each spike's `README.md`:

   ```markdown
   ## Verdict: VALIDATED | PARTIAL | INVALIDATED

   ### What worked
   ### What didn't
   ### Surprises
   ### Recommendation for the real build
   ```

   `VALIDATED` means the question was answered yes, with evidence. `PARTIAL` means it works
   under constraints — name them. `INVALIDATED` means it does not work, for a stated reason,
   and that is a successful spike. For a comparison, add a table of the dimensions that
   matter and say which approach won and why.

## Pitfalls

- Declaring "it works" after one run. The verdict is worth something only when the
  investigation was honest.
- Building the easy half first. The spike that can kill the idea runs first.
- Letting the spike become the product. If "cleaning it up" would take days, it was the
  wrong spike; the real build starts fresh.
- Configuring instead of asking. Hardcode the values and answer the question.

## Verification

- [ ] Every spike directory has a `README.md` that closes with a verdict.
- [ ] The verdict reports what was observed, not what was expected.
- [ ] The user has the evidence, not only the conclusion.
