---
name: working-without-web-search
description: How to find information when the web_search tool is not available. Use when web_search is not offered and the user asks something that needs current information.
version: 1.0.0
author: C-lite
license: MIT
metadata:
  clite:
    tags: [web, fallback]
    category: web
    fallback_for_tools: [web_search]
---

# Working without web search

When `web_search` is not available, you cannot search the live web. Here is what you can do
instead.

## Read a known URL

If you know (or the user provides) a specific URL, use `web_fetch` to download the page as
text. `web_fetch` works without a search backend; it only needs the URL.

## Ask the user

If the question needs current information and you do not have a URL to fetch, ask the user
to provide a source URL or the relevant text. Do not guess at facts that may have changed.

## Use what you already know

For questions about stable concepts (programming language syntax, how a protocol works,
general explanations), your training knowledge is enough. Say that your answer may be dated
if the topic changes over time (API versions, current prices, news).

## How to get web search

A web-search plugin adds the tool. Enable `web-search-ddg` (no API key) or
`web-search-tavily` (needs `TAVILY_API_KEY`) in `config.yaml` under `plugins.enabled`, then
restart the session.
