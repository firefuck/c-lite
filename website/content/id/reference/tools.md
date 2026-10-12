# Rujukan tool

Halaman ini dibuat dari kode oleh `scripts/gen_docs.py`, jadi isinya tidak pernah tertinggal dari programnya. Jangan disunting dengan tangan: ubah kodenya, lalu jalankan skrip itu.

Apa yang bisa dipanggil model, apa isi tiap toolset, dan apa yang dibawa paket: plugin, skill, dan hook.

## Tool

| Tool | Toolset | Paralel | Deskripsi |
| --- | --- | --- | --- |
| `clarify` | `clarify` | never | Ask the user a question when you cannot proceed without their decision: the request is ambiguous in a way that changes the work, or a choice is theirs to make. |
| `cronjob` | `cronjob` | never | Schedule a task for later. |
| `delegate_task` | `delegation` | never | Run one or more subagents, each on a focused task, and get back only their final reports. |
| `patch` | `file` | path | Replace text in a file, or apply a multi-file V4A patch. |
| `read_file` | `file` | path | Read a text file with line numbers (`LINE\|content`). |
| `search_files` | `file` | safe | Search the project. |
| `write_file` | `file` | path | Create a file or replace its whole content. |
| `memory` | `memory` | never | Save durable facts to persistent memory. |
| `send_file` | `messaging` | never | Send a local file to the user through a connected chat platform, for example a report or a generated image. |
| `send_message` | `messaging` | never | Send a message to a chat on a connected platform, for example to tell the user something later on Telegram while working elsewhere. |
| `text_to_speech` | `messaging` | never | Turn text into an audio file with the configured speech provider and return the path. |
| `session_search` | `session_search` | safe | Search past conversations (all sessions, including parts that were summarised away) by keyword. |
| `skill_manage` | `skills` | never | Create and maintain skills: your procedural memory. |
| `skill_view` | `skills` | safe | Load a skill's full instructions. |
| `skills_list` | `skills` | safe | List available skills with their descriptions. |
| `execute_code` | `terminal` | never | Run a short Python program and get back its stdout, stderr and exit code. |
| `process` | `terminal` | never | Manage background processes started with terminal(background=true). |
| `terminal` | `terminal` | never | Run a shell command. |
| `todo` | `todo` | never | Read or update your task list for the current session. |
| `image_generate` | `vision` | never | Create an image from a text description (and optionally edit an existing one) and save it to a file. |
| `vision_analyze` | `vision` | safe | Look at an image file and return a description written by a helper model that can see. |
| `web_fetch` | `web` | safe | Fetch a URL and return its text content (HTML is converted to plain text with links kept as `text (url)`). |
| `web_search` | `web` | safe | Search the web for a query and return results: title, URL, and a short snippet for each. |

## Toolset

| Toolset | Deskripsi | Berisi (setelah `includes` diurai) |
| --- | --- | --- |
| `terminal` | Run shell commands, Python snippets and background processes | `terminal`, `process`, `execute_code` |
| `file` | Read, write, patch and search files | `read_file`, `write_file`, `patch`, `search_files` |
| `web` | Search and fetch web pages as text | `web_fetch`, `web_search` |
| `vision` | Look at images through a helper model | `vision_analyze`, `image_generate` |
| `todo` | Task list for multi-step work | `todo` |
| `memory` | Persistent notes across sessions | `memory` |
| `skills` | List, read and maintain skills | `skills_list`, `skill_view`, `skill_manage` |
| `session_search` | Search past conversations | `session_search` |
| `clarify` | Ask the user a question | `clarify` |
| `delegation` | Spawn subagents with isolated context | `delegate_task` |
| `cronjob` | Schedule recurring or one-off agent tasks | `cronjob` |
| `messaging` | Send messages and files to connected chat platforms, and speak | `send_message`, `send_file`, `text_to_speech` |
| `clite-cli` | Everything, for the interactive terminal | `terminal`, `process`, `execute_code`, `read_file`, `write_file`, `patch`, `search_files`, `web_fetch`, `web_search`, `vision_analyze`, `image_generate`, `todo`, `memory`, `skills_list`, `skill_view`, `skill_manage`, `session_search`, `clarify`, `delegate_task`, `cronjob`, `send_message`, `send_file`, `text_to_speech` |
| `clite-gateway` | Messaging platforms | `terminal`, `process`, `execute_code`, `read_file`, `write_file`, `patch`, `search_files`, `web_fetch`, `web_search`, `vision_analyze`, `image_generate`, `todo`, `memory`, `skills_list`, `skill_view`, `skill_manage`, `session_search`, `clarify`, `delegate_task`, `cronjob`, `send_message`, `send_file`, `text_to_speech` |
| `clite-cron` | Scheduled runs | `terminal`, `process`, `execute_code`, `read_file`, `write_file`, `patch`, `search_files`, `web_fetch`, `web_search`, `vision_analyze`, `image_generate`, `todo`, `memory`, `skills_list`, `skill_view`, `skill_manage`, `session_search`, `delegate_task` |
| `clite-subagent` | Delegated workers | `terminal`, `process`, `execute_code`, `read_file`, `write_file`, `patch`, `search_files`, `web_fetch`, `web_search`, `todo`, `skills_list`, `skill_view`, `skill_manage`, `session_search` |

## Hook

| Hook | Bisa dari shell hook | Gagal = blokir |
| --- | --- | --- |
| `api_request_error` | ya |  |
| `on_compaction` |  |  |
| `on_session_end` | ya |  |
| `on_session_reset` | ya |  |
| `on_session_start` | ya |  |
| `on_skill_lifecycle` | ya |  |
| `post_api_request` | ya |  |
| `post_approval_response` | ya |  |
| `post_llm_call` | ya |  |
| `post_tool_call` | ya |  |
| `pre_api_request` | ya |  |
| `pre_approval_request` | ya |  |
| `pre_gateway_dispatch` |  |  |
| `pre_llm_call` | ya |  |
| `pre_memory_write` |  | ya |
| `pre_tool_call` | ya | ya |
| `subagent_result` | ya |  |
| `subagent_start` | ya |  |
| `subagent_stop` | ya |  |
| `transform_llm_output` |  |  |
| `transform_terminal_output` |  |  |
| `transform_tool_result` |  |  |

## Plugin bawaan

| Plugin | Jenis | Deskripsi |
| --- | --- | --- |
| `audit-log` | standalone | Record every tool call to logs/tool-audit.jsonl and show recent ones with /audit |
| `context-sliding-window` | backend | Sliding-window context engine: drop the middle, keep a protected head and tail (no summariser call) |
| `email` | platform | Receive allowed email senders over IMAP and reply over SMTP |
| `image-gen-openai` | backend | Image generation via the OpenAI Images API (requires OPENAI_API_KEY) |
| `matrix` | platform | Receive and send Matrix room messages through the Client-Server API |
| `memory-sqlite` | backend | Long-term memory in SQLite: facts saved with a tool, found again with FTS5 search in later sessions |
| `signal` | platform | Receive and send Signal messages through a user-run signal-cli REST service |
| `speech-openai` | backend | Voice messages and spoken replies via the OpenAI Audio API (requires OPENAI_API_KEY) |
| `web-search-ddg` | backend | Web search via the DuckDuckGo HTML endpoint (no API key required) |
| `web-search-tavily` | backend | Web search via the Tavily API (requires TAVILY_API_KEY) |
| `whatsapp` | platform | Receive WhatsApp Cloud API webhooks and send replies through the Graph API |

## Skill bawaan

| Skill | Kategori | Deskripsi |
| --- | --- | --- |
| `skill-authoring` | meta | Write or improve a skill (SKILL.md). Use when saving a reusable procedure with skill_manage, or when a skill turned out wrong or incomplete. |
| `airtable` | productivity | Airtable REST API: records CRUD, filters, upserts via the bundled stdlib helper. |
| `box` | productivity | Box manages cloud files, sharing, search, and metadata. |
| `document-to-action-items` | productivity | Extract cited obligations, deadlines, tasks from documents. |
| `docx` | productivity | Create, read, edit, template, and review Word .docx files. |
| `google-workspace` | productivity | Gmail, Calendar, Drive, Docs, Sheets via gws CLI or Python. |
| `maps` | productivity | Geocode, POIs, routes, timezones via OpenStreetMap/OSRM. |
| `meeting-action-items` | productivity | Turn meeting notes into cited decisions, owners, tickets. |
| `notion` | productivity | Notion API + ntn CLI: pages, databases, markdown, Workers. |
| `pdf` | productivity | PDF files: create, read, merge, fill, OCR, edit text. |
| `plan-before-acting` | productivity | Break a large or ambiguous task into verifiable steps before starting. Use when a request spans several files or systems, or when the first step is not obvious. |
| `powerpoint` | productivity | Create, read, edit .pptx decks with python-pptx. |
| `product-price-monitor` | productivity | Watch product, flight, or listing prices; alert on target. |
| `weekly-review-planning` | productivity | Weekly reset: commitments, stalled work, next-week plan. |
| `xlsx` | productivity | Create, read, edit Excel .xlsx workbooks and CSVs. |
| `arxiv` | research | Search arXiv papers by keyword, author, category, or ID. |
| `competitor-news-monitor` | research | Watch named companies for material news; cited digests. |
| `grounded-citations` | research | Ground answers and documents in cited, verifiable sources. |
| `llm-wiki` | research | Karpathy's LLM Wiki: build/query interlinked markdown KB. |
| `codebase-inspection` | software-development | Inspect codebases w/ pygount: LOC, languages, ratios. |
| `github` | software-development | GitHub via gh CLI: PRs, issues, reviews, repos, auth. |
| `node-inspect-debugger` | software-development | Debug Node.js via --inspect + Chrome DevTools Protocol CLI. |
| `python-debugpy` | software-development | Debug Python: pdb REPL + debugpy remote (DAP). |
| `requesting-code-review` | software-development | Pre-commit review: security scan, quality gates, auto-fix. |
| `simplify-code` | software-development | Parallel 4-agent cleanup of recent code changes. |
| `spike` | software-development | Throwaway experiments to validate an idea before build. |
| `systematic-debugging` | software-development | Find the root cause of a bug before changing code. Use for any failing test, crash, or behaviour that does not match what the code appears to say. |
| `test-driven-development` | software-development | Implement a feature or fix by writing a failing test first. Use when adding behaviour to tested code or when a bug needs a regression test. |
| `working-without-web-search` | web | How to find information when the web_search tool is not available. Use when web_search is not offered and the user asks something that needs current information. |
