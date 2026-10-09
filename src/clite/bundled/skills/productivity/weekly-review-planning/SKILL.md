---
name: weekly-review-planning
description: Run a bounded weekly review over the user's notes and tasks, then propose next week's plan. Use when asked what slipped, what is waiting, or to plan the coming week.
version: 1.0.0
author: C-lite
license: MIT
metadata:
  clite:
    category: productivity
    tags: [weekly-review, planning, tasks]
    attribution: "Adapted from the weekly-review-planning skill in Nous Research's hermes-agent (MIT, Copyright (c) 2025 Nous Research) by Ben Barclay."
---

# Weekly review and planning

A concrete, bounded reset over the sources the user actually keeps — not a general
productivity methodology. It can be run by hand or fired by a `cronjob` tick.

## When to use

- "Run my weekly review."
- "What did I commit to, and what is slipping?"
- "Plan next week."
- "Find the projects that have gone quiet."
- A scheduled weekly job fires.

Not for a daily brief, and not for triaging one inbox.

## Steps

1. **Agree on the sources and the window.** Confirm the timezone, the period under review, the
   planning horizon, and which places are authoritative: task lists, notes, calendars,
   inboxes. Where two sources disagree about the same thing, decide and state which one wins.
   Default to proposals, not edits.

2. **Read the two halves of the calendar**: the week that finished (what was promised and
   what happened) and the one or two weeks ahead (deadlines, travel, preparation, capacity).
   Capture the follow-ups implied by what already happened, not only the scheduled items.

3. **Clear the capture points.** Walk the task list, the notes and anything else declared in
   step 1. Give each item one of: next action, project, waiting, scheduled, someday,
   reference, archive, delete. Count what is left unprocessed and say the number instead of
   quietly stopping.

4. **Reconcile the active projects.** For each one: the outcome wanted, the next action, the
   owner, the deadline, the blocker, the last time anything happened, and where it lives. Flag
   a project with no next action, a passed date, a duplicate record or a contradictory status.
   A project is either actionable or explicitly paused.

5. **Review what is waiting.** Separately list what the user owes others and what others owe
   the user. Propose a follow-up with a date and a channel for each. Silence is not
   completion; never treat it as one.

6. **Build a plan that fits the capacity.** Estimate the fixed load first, then pick a small
   set of outcomes for the week and their near-term next actions. Rank by consequence,
   deadline, dependency and effort. Do not fill every free hour, and name what was deferred —
   a plan that does not say what it dropped is not a plan.

7. **Apply only what was approved**, then read each changed record back.

## Output shape

1. Wins and commitments met
2. Overdue or at risk
3. Waiting on others, and follow-ups
4. Stalled or ambiguous projects
5. Next week's outcomes and the constraints on them
6. Proposed changes, awaiting approval
7. Gaps in coverage — what could not be read

## Pitfalls

- Planning from a task list without looking at the calendar.
- Carrying every unfinished item forward as top priority.
- Leaving a project marked active with no next action.
- Moving or deleting a personal commitment without asking.
- Reading silence from someone else as done.

## Verification

- [ ] Both the finished week and the horizon were covered, or the gaps are named.
- [ ] Every "stalled" or "waiting" flag points at a specific record, event or thread.
- [ ] Nothing was changed without approval, and every approved change was read back.
- [ ] The plan says what was deferred, not only what was chosen.
