---
name: airtable
description: "Airtable REST API: records CRUD, filters, upserts via the bundled stdlib helper."
version: 1.1.0
author: community
license: MIT
platforms: [linux, macos, windows]
metadata:
  clite:
    attributed_from: NousResearch/hermes-agent@1298c8e74b (MIT)
    tags: [Airtable, Productivity, Database, API]
    homepage: https://airtable.com/developers/web/api/introduction
    requires_toolsets: [terminal]
    env_passthrough: [AIRTABLE_API_KEY]
---

# Airtable — Bases, Tables & Records

Work with Airtable's REST API through the bundled helper `scripts/atr.py`.
The helper sends the authorization header itself, so the personal access token
never appears on a command line, in shell history, or in process listings.
Do **not** rebuild raw tenant calls that inline the token on a command line —
this project's scanner treats that shape as exfiltration.

Original skill: NousResearch/hermes-agent (commit 1298c8e74b), adapted for C-lite.

## Prerequisites

1. Create a **Personal Access Token (PAT)** at
   https://airtable.com/create/tokens (tokens start with `pat...`).
2. Grant these scopes (minimum):
   - `data.records:read` — read rows
   - `data.records:write` — create / update / delete rows
   - `schema.bases:read` — list bases and tables
3. In the same token UI, add each base you want to access to the token's
   **Access** list. PATs are scoped per-base — a valid token on the wrong base
   returns `403`.
4. Store the token once in `${CLITE_HOME:-~/.clite}/.env`:

   `printf 'AIRTABLE_API_KEY=pat_...\n' >> ~/.clite/.env`

   The helper reads that file inside its own process; nothing has to be
   exported into the session.

> Note: legacy `key...` API keys were deprecated Feb 2024. Only PATs and OAuth
> tokens work now.

## Quick start

`ATR="python <this skill>/scripts/atr.py"`

| Action | Invocation |
|---|---|
| List bases | `$ATR bases` |
| Describe tables | `$ATR tables --base appXXXX` |
| List records | `$ATR list --base appXXXX --table "Tasks" --max-records 20 --formula '{Done} = FALSE()'` |
| One record | `$ATR get --base appXXXX --table Tasks --id recXXXX` |
| Create | `$ATR create --base appXXXX --table Tasks --json-file body.json` |
| Update | `$ATR update --base appXXXX --table Tasks --id recXXXX --json-file body.json` |
| Upsert | `$ATR upsert --base appXXXX --table Tasks --field Email --json-file body.json` |
| Delete | `$ATR delete --base appXXXX --table Tasks --id recXXXX` |

For writes, `body.json` holds `{"fields": {"Name": "..."}, ...}`; for bulk create
or upsert hold `{"records": [ ... ]}` with `fields` per record. The helper prints
the API's JSON answer, pretty-printed, and exits non-zero with the HTTP status
and a short excerpt of the API's own message on error.

## API shapes worth knowing

- **Object IDs:** bases `app...`, tables `tbl...`, records `rec...`, fields
  `fld...`. IDs never change; names can. Prefer IDs in automations.
- **Rate limit:** 5 requests/sec/base. `429` → back off; a burst on a single
  base will be throttled. Reads cap at 100 records per page until `offset`
  disappears.
- Pass `{"typecast": true}` in a write body to let Airtable coerce values or
  create missing select options.

## Typical C-lite workflow

1. **Confirm auth.** `$ATR bases` — expect a JSON list, not a `401`.
2. **Find the base.** Ask the user for the `app...` ID when the token lacks
   `schema.bases:read`.
3. **Inspect the schema.** Run `tables` first: exact field names, options of
   select fields, and the primary-field name determine every write that follows.
4. **Read before you write.** For "update X where Y", `list --formula` first to
   resolve the `rec...` ID, then update by id. Never guess record IDs.
5. **Destructive ops.** Deletions can't be undone via the API. If the user says
   "delete all Xs", echo the filter plus the record count and confirm before
   firing.

## Pitfalls

- **Filters use Airtable formulas.** `{Field} = value`, `AND(...)`,
  `FIND('bug', LOWER({Title}))`, `NOT({Assignee}='')`, `IS_AFTER({Due}, TODAY())`.
  The helper URL-encodes them; never hand-encode into a raw URL.
- **Empty fields are omitted from responses.** A missing `"Assignee"` key means
  the value is empty, not that the field is absent.
- **Update merges.** A full replace clears unspecified fields; stay with the
  merge-style update unless the user asks to wipe the record.
- **Per-base token scoping.** A `403` on one base while another works means the
  token's Access list misses that base — not a scope issue.
- **Error codes are readable.** `AUTHENTICATION_REQUIRED`,
  `INVALID_PERMISSIONS`, `MODEL_ID_NOT_FOUND`,
  `INVALID_MULTIPLE_CHOICE_OPTIONS` say exactly what to fix.
