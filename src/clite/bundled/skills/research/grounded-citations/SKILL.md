---
name: grounded-citations
description: Ground an answer or document in numbered citations, with the source list rendered from a ledger instead of memory. Use when a deliverable reports outside facts and the reader will want to check them.
version: 1.0.0
author: C-lite
license: MIT
metadata:
  clite:
    category: research
    tags: [citations, grounding, sources, fact-checking]
    requires_toolsets: [web, terminal]
    attribution: "Adapted from the grounded-citations skill in Nous Research's hermes-agent (skills/research/grounded-citations, MIT, Copyright (c) 2025 Nous Research)."
---

# Grounded citations

Every claim taken from an outside source gets an inline numbered citation and a `Sources:`
list. The numbers come from a ledger written at retrieval time, never from memory: the model
only ever emits small integers it was handed, so a URL cannot be hallucinated into a citation.

## When to use

- Research, comparisons, news summaries, "what is the current state of X".
- Any deliverable written to disk that quotes or reports outside facts: a report, a brief, a
  document, a wiki page.
- Fact-finding the user will want to check.
- A synthesis of sources that disagree, where each position needs its own attribution.

Skip inline citations when the retrieval was incidental — a version number looked up mid-coding,
a chat answer, creative writing.

## The ledger

One JSON file per task, written with `write_file` and read back with `execute_code`. It maps a
normalised URL to an id, a title and the evidence attached to it. Give it a per-task path under
the working directory, for example `.citation-ledger.json`, and delete it when the task ends.

```python
# register after every fetch — the id is what you will cite
import json, pathlib
ledger = pathlib.Path(".citation-ledger.json")
seen = json.loads(ledger.read_text()) if ledger.exists() else {}
url = "https://example.com/a"
if url not in seen:
    seen[url] = {"id": len(seen) + 1, "url": url, "title": "A", "quotes": []}
ledger.write_text(json.dumps(seen, indent=2))
print(seen[url]["id"])
```

`add` is idempotent in the same way: the same URL always returns the same id, so the numbering
stays stable across many rounds of searching.

## Steps

1. **Start a fresh ledger** for a task that will produce a grounded answer. Do not reset one
   whose ids already appear in a draft — keep the numbering stable.

2. **Register every source at retrieval time.** After each `web_search`, `web_fetch` or `curl`,
   add its URL to the ledger. Do this *before* writing prose. Registering afterwards, from
   memory, is exactly the failure this skill exists to prevent.

3. **Cite while drafting.** Put the bracketed id immediately after the sentence it supports,
   no space before the bracket, one id per pair of brackets, at most three per sentence:

   ```
   Ice floats because it is less dense than liquid water.[1][2]
   ```

   Only ids the ledger returned. Never invent an id or a URL. Claims from your own knowledge
   carry no citation. When sources conflict, present both readings with their own ids. Quote
   figures, dates and names as the source states them, and when there is no source for
   something, write that down instead of smoothing over it.

4. **Render the `Sources` block from the ledger**, mechanically, with `execute_code`:

   ```python
   import json, pathlib, re
   led = json.loads(pathlib.Path(".citation-ledger.json").read_text())
   draft = pathlib.Path("report.md").read_text()
   cited = {int(n) for n in re.findall(r"\[(\d+)\]", draft)}
   for entry in sorted(led.values(), key=lambda e: e["id"]):
       if entry["id"] in cited:
           print(f'[{entry["id"]}] {entry["title"]} — {entry["url"]}')
   ```

   Never retype a URL into the block by hand; a hand-typed URL is an unverified claim.

5. **Check before delivering.** The same script, run as a check, should fail the draft when it
   cites an id the ledger does not have, or when the `Sources` block disagrees with the ledger.
   Fix and re-run.

6. **Chat answers follow the same shape**: register, cite inline, end with the rendered list.

## Fact-checking mode

For work the reader must be able to verify — medical, legal, financial, safety, or a disputed
claim — upgrade from citations to evidence:

- **Attach a verbatim quote per source.** Save the fetched page text to a file, then copy the
  sentence that carries the claim into the ledger's `quotes`. Copy it — never retype it from
  memory — and keep the sentence as a reader sees it.
- **Flag unsourced load-bearing claims** with `[unverified]` rather than leaving them bare.
  That is for what genuinely cannot be checked, not an escape hatch: a deliverable dominated by
  `[unverified]` needed more retrieval, not more markers.
- **Cross-check a disputed fact against a second independent source.** One source is a report;
  two independent sources are corroboration. Say which you weight and why.

## Multi-source sweeps

"Research X across the web" is not one search. Fan out — the open web, community discussion,
changelogs, code search, papers — and register every URL as it arrives. Keep opinion and
measurement apart: a forum thread is evidence that people *report* something, not that it is
true. Where a channel returned nothing, report the gap instead of quietly narrowing to what
worked.

## Pitfalls

- **Registering after writing.** It reintroduces the invented URL that the numbering removes.
- **Renumbering mid-task.** An id is an identity: if the draft cites `[4]`, `[4]` stays that
  source. Reset only between tasks.
- **Retyping an id or a URL.** Both come from the ledger.
- **Citing a search snippet as though you read the page.** A snippet supports only what it
  literally says; `web_fetch` the page when the claim needs the body.
- **Over-citing.** Three ids is the ceiling; a citation on every clause hides which source
  carries the load.
- **Putting citations into code or configuration.** They belong in prose, not in generated code.
- **Parallel subagents sharing a task.** Each gets its own ledger unless you point them all at
  one file; unshared ledgers colliding on ids produce nonsense.

## Verification

- [ ] Every `[n]` in the draft exists in the ledger.
- [ ] The `Sources` block was rendered, not typed, and lists exactly the cited ids.
- [ ] No URL in the deliverable came from memory.
- [ ] In fact-checking mode, every cited source has a verbatim quote attached.
