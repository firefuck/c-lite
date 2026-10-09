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
| `meeting-action-items` | productivity | Turn meeting notes or a transcript into cited decisions, owners and follow-ups. Use when asked to extract action items from a meeting, or to reconcile notes with existing work. |
| `plan-before-acting` | productivity | Break a large or ambiguous task into verifiable steps before starting. Use when a request spans several files or systems, or when the first step is not obvious. |
| `weekly-review-planning` | productivity | Run a bounded weekly review over the user's notes and tasks, then propose next week's plan. Use when asked what slipped, what is waiting, or to plan the coming week. |
| `arxiv` | research | Search arXiv and Semantic Scholar for papers by keyword, author, category or id, and read their metadata and citations. Use when the task needs academic papers or citation counts. |
| `competitor-news-monitor` | research | Watch a fixed set of companies for material news and report cited digests, or stay silent when nothing happened. Use when asked to track competitors, pricing changes or launches on a schedule. |
| `grounded-citations` | research | Ground an answer or document in numbered citations, with the source list rendered from a ledger instead of memory. Use when a deliverable reports outside facts and the reader will want to check them. |
| `llm-wiki` | research | Build and maintain a compounding knowledge base of interlinked markdown pages, and answer questions from it. Use when the user keeps a wiki or knowledge base, or asks to ingest a source into one. |
| `codebase-inspection` | software-development | Measure a codebase with pygount or the shell, to answer how big it is and what it is made of. Use when asked for lines of code, a language breakdown, or code-to-comment ratios. |
| `github` | software-development | Work GitHub end to end with the gh CLI: auth, issues, the pull-request lifecycle, reviews and repo management. Use when the task touches a GitHub repository's remote state. |
| `python-debugpy` | software-development | Debug Python with pdb, post-mortem inspection and debugpy remote attach. Use when a traceback does not explain a wrong value, or a long-running process misbehaves. |
| `requesting-code-review` | software-development | Verify a change before it is committed with a static scan, the test suite and an independent reviewer. Use when finishing a task, or when the user says commit, push, ship or review. |
| `simplify-code` | software-development | Clean up recent code changes with four focused reviewers running in parallel, then apply only the fixes worth applying. Use when the user says simplify, or asks for a cleanup of what was just written. |
| `spike` | software-development | Run throwaway experiments to answer feasibility questions before committing to a build. Use when the user wants to see if something works, or to compare two approaches. |
| `systematic-debugging` | software-development | Find the root cause of a bug before changing code. Use for any failing test, crash, or behaviour that does not match what the code appears to say. |
| `test-driven-development` | software-development | Implement a feature or fix by writing a failing test first. Use when adding behaviour to tested code or when a bug needs a regression test. |
| `working-without-web-search` | web | How to find information when the web_search tool is not available. Use when web_search is not offered and the user asks something that needs current information. |
