# NOTICE

C-lite
Copyright (c) 2026 C-lite contributors
Licensed under the MIT License (see `LICENSE`).

## Hermes Agent

The architecture of C-lite is derived from Hermes Agent by Nous Research:

- Repository: https://github.com/NousResearch/hermes-agent
- Commit studied: `1298c8e74baa73e1a2b90124228d017261ac6bc4`
- License: MIT, Copyright (c) 2025 Nous Research

What was taken from Hermes is its design: the module contracts, the engineering invariants
and the way capabilities attach at the edges. That study is written up in `docs/hermes/`.

The source code in this repository was written anew; no Hermes source file was copied into it
as of 5 October 2026. Names that form an interface were deliberately kept the same so that
material written for Hermes keeps working: tool names such as `terminal`, `read_file`, `patch`
and `skill_manage`, lifecycle hook names, the `SKILL.md` format with its `metadata.hermes`
block, and the wire format of shell hooks.

If you copy code, skills or other text from Hermes into this repository (roadmap task F6-T2
ports bundled skills, for example), the MIT License requires that the copyright notice and
the permission notice below stay with it. Record what was copied in the list at the end of
this file.

### Hermes Agent license

```
MIT License

Copyright (c) 2025 Nous Research

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### Copied from Hermes

Bundled skills ported (adapted) from `NousResearch/hermes-agent` at commit
`1298c8e74baa73e1a2b90124228d017261ac6bc4`, each marked with an
`attributed_from` entry in its frontmatter:

- `software-development/codebase-inspection`
- `software-development/github`
- `software-development/node-inspect-debugger`
- `software-development/python-debugpy`
- `software-development/requesting-code-review` (yang sendirinya mengadaptasi obra/superpowers dan MorAlekss)
- `software-development/simplify-code`
- `software-development/spike`
- `productivity/airtable`
- `productivity/box`
- `productivity/document-to-action-items`
- `productivity/docx`
- `productivity/google-workspace`
- `productivity/maps`
- `productivity/meeting-action-items`
- `productivity/notion`
- `productivity/pdf`
- `productivity/powerpoint`
- `productivity/product-price-monitor`
- `productivity/weekly-review-planning`
- `productivity/xlsx`
- `research/arxiv`
- `research/competitor-news-monitor`
- `research/grounded-citations`
- `research/llm-wiki`
