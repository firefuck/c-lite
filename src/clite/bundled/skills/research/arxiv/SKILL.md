---
name: arxiv
description: Search arXiv and Semantic Scholar for papers by keyword, author, category or id, and read their metadata and citations. Use when the task needs academic papers or citation counts.
version: 1.0.0
author: C-lite
license: MIT
metadata:
  clite:
    category: research
    tags: [research, arxiv, papers, academic, api]
    requires_toolsets: [terminal]
    attribution: "Adapted from the arxiv skill in Nous Research's hermes-agent (skills/research/arxiv, MIT, Copyright (c) 2025 Nous Research)."
---

# arXiv research

arXiv has a free REST API with no key and no dependencies — it returns Atom XML, so the work
is parsing. Semantic Scholar, which returns JSON, answers the questions arXiv cannot: how many
times a paper was cited, what it cites, and what to read next.

## When to use

- "Find papers about X", "what is the latest work on Y".
- "Who cited this paper", "what does this paper build on".
- Tracking an author's output, or the papers in one category.

## Steps

1. **Search arXiv.** The `search_query` prefix decides which field is matched:

   ```bash
   curl -s "https://export.arxiv.org/api/query?search_query=all:GRPO+reinforcement+learning&max_results=5"
   ```

   | Prefix | Field | Prefix | Field |
   |---|---|---|---|
   | `all:` | every field | `abs:` | abstract |
   | `ti:` | title | `cat:` | category, e.g. `cat:cs.AI` |
   | `au:` | author | `co:` | comment, e.g. `co:accepted+NeurIPS` |

   Combine with `+` for AND, `OR` between terms, `ANDNOT` to exclude, and quotes for an exact
   phrase: `search_query=ti:"chain+of+thought"`, `search_query=au:hinton+AND+cat:cs.LG`.

   Sort and page with `sortBy=relevance|lastUpdatedDate|submittedDate`, `sortOrder=ascending|descending`,
   `start` (0-based offset) and `max_results` (default 10).

2. **Parse it into something readable** rather than reading raw XML:

   ```bash
   curl -s "https://export.arxiv.org/api/query?search_query=all:GRPO&max_results=5&sortBy=submittedDate&sortOrder=descending" \
   | python -c "
   import sys, xml.etree.ElementTree as ET
   ns = {'a': 'http://www.w3.org/2005/Atom'}
   for i, e in enumerate(ET.parse(sys.stdin).getroot().findall('a:entry', ns), 1):
       title = e.find('a:title', ns).text.strip().replace('\n', ' ')
       aid = e.find('a:id', ns).text.strip().split('/abs/')[-1]
       published = e.find('a:published', ns).text[:10]
       authors = ', '.join(a.find('a:name', ns).text for a in e.findall('a:author', ns))
       print(f'{i}. [{aid}] {title}\n   {authors}\n   {published}\n   https://arxiv.org/pdf/{aid}\n')
   "
   ```

   Fetch one or more papers directly by id: `?id_list=2402.03300` or
   `?id_list=2402.03300,2401.12345`.

3. **Read the abstract, then the paper.** `web_fetch` reads the abstract page. It does not
   extract a PDF, so for the full text download it and extract locally:

   ```
   web_fetch("https://arxiv.org/abs/2402.03300")
   ```

   ```bash
   curl -sL -o /tmp/paper.pdf "https://arxiv.org/pdf/2402.03300"
   python -c "import pypdf; print('\n'.join(p.extract_text() for p in pypdf.PdfReader('/tmp/paper.pdf').pages[:5]))"
   ```

4. **Measure impact and find related work** with Semantic Scholar (JSON, one request per
   second without a key):

   ```bash
   curl -s "https://api.semanticscholar.org/graph/v1/paper/arXiv:2402.03300?fields=title,year,citationCount,influentialCitationCount,abstract" | python -m json.tool
   curl -s "https://api.semanticscholar.org/graph/v1/paper/arXiv:2402.03300/citations?fields=title,year,citationCount&limit=10" | python -m json.tool
   curl -s "https://api.semanticscholar.org/graph/v1/paper/arXiv:2402.03300/references?fields=title,year&limit=10" | python -m json.tool
   curl -s "https://api.semanticscholar.org/graph/v1/author/search?query=Yann+LeCun&fields=name,hIndex,citationCount,paperCount" | python -m json.tool
   ```

5. **Cite what you actually read.** `arxiv.org/abs/1706.03762` always resolves to the newest
   version; `...v7` pins the one you read. Keep the version suffix you read in a citation — a
   later version can change the content substantially.

## Pitfalls

- **A withdrawn paper still returns.** Its `<summary>` carries the withdrawal notice. Read the
  summary before treating a result as a paper.
- **Old and new ids look different**: `hep-th/0601001` against `2402.03300`. Both work.
- **Rate limits**: arXiv tolerates roughly one request every three seconds, Semantic Scholar
  one per second. Slow down rather than retrying in a loop.
- **A search snippet is not the paper.** Cite the abstract page or the full text you fetched,
  not the one-line description a search returned.

## Verification

- [ ] Every paper cited has an id and a version suffix that was really read.
- [ ] Withdrawn or incomplete entries were checked and excluded.
- [ ] Citation counts name the source they came from (Semantic Scholar) and the date read.
