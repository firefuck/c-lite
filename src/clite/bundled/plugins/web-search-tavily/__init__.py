"""Tavily web search: a keyed provider using the Tavily Search API.

Tavily is an AI-oriented search API that returns clean results with snippets. An API key is
required (``TAVILY_API_KEY`` in ``.env``); get one at https://tavily.com. The key is
registered as a credential so it is stripped from commands the agent runs and redacted from
what the model reads.

This is a backend plugin (``kind: backend``): it is auto-loaded, but the ``web_search`` tool's
``check_fn`` checks whether the key is actually present before offering the tool.
"""

from __future__ import annotations

import json
import urllib.request

from clite.core.env import SecretSpec, register_secret
from clite.tools.web_search import WebSearchProvider

TAVILY_API_KEY_ENV = "TAVILY_API_KEY"
TAVILY_URL = "https://api.tavily.com/search"
_USER_AGENT = "clite (+web_search; tavily)"

# Register the key so it is known as a credential: stripped from child environments and
# redacted from tool results. This runs at import time, like provider profiles.
register_secret(
    SecretSpec(
        TAVILY_API_KEY_ENV,
        "Tavily API key: web search results with snippets",
        category="tool",
        url="https://tavily.com",
    )
)


class TavilyProvider(WebSearchProvider):
    name = "tavily"
    requires_api_key = True
    api_key_env = TAVILY_API_KEY_ENV

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    def search(self, query: str, *, max_results: int = 5) -> list[dict[str, str]]:
        from clite.core.env import get_secret

        key = self._api_key or get_secret(TAVILY_API_KEY_ENV) or ""
        if not key:
            return []
        body = json.dumps(
            {
                "query": query,
                "max_results": max_results,
                "api_key": key,
            }
        ).encode()
        request = urllib.request.Request(  # noqa: S310 - https is enforced
            TAVILY_URL,
            data=body,
            headers={"Content-Type": "application/json", "User-Agent": _USER_AGENT},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310 - https
            data = json.loads(response.read())
        results: list[dict[str, str]] = []
        for hit in data.get("results", []):
            results.append(
                {
                    "title": str(hit.get("title") or ""),
                    "url": str(hit.get("url") or ""),
                    "snippet": str(hit.get("content") or ""),
                }
            )
        return results[:max_results]


def register(ctx) -> None:
    ctx.register_web_search_provider("tavily", TavilyProvider)
