"""DuckDuckGo web search: a keyless provider using the HTML endpoint.

DuckDuckGo does not require an API key, so this provider works out of the box. It is a
backend plugin (``kind: backend``), auto-loaded but inert until the ``web_search`` tool's
``check_fn`` sees that a provider is available.

The HTML endpoint is not an official API: it can change rate limits or markup at any time.
For production use, a keyed provider (Tavily, Brave, Exa) is more reliable.
"""

from __future__ import annotations

import html
import re
import urllib.parse
import urllib.request

from clite.tools.web_search import WebSearchProvider

DDG_URL = "https://html.duckduckgo.com/html/"
_USER_AGENT = "clite (+web_search; ddg)"

# DuckDuckGo wraps each result in <a class="result__a" href="...">title</a> and the snippet
# in <a class="result__snippet" href="...">snippet</a>. The href goes through a redirect:
# //duckduckgo.com/l/?uddg=<encoded url>.
_REDIRECT_RE = re.compile(r"//duckduckgo\.com/l/\?uddg=([^&\"']+)")
_RESULT_BLOCK_RE = re.compile(
    r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>'  # title link
    r'.*?<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',  # snippet
    re.DOTALL,
)


class DuckDuckGoProvider(WebSearchProvider):
    name = "ddg"
    requires_api_key = False

    def search(self, query: str, *, max_results: int = 5) -> list[dict[str, str]]:
        body = urllib.parse.urlencode({"q": query, "b": ""}).encode()
        request = urllib.request.Request(  # noqa: S310 - https is enforced
            DDG_URL, data=body,
            headers={"User-Agent": _USER_AGENT, "Accept": "text/html"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310 - https
                page = response.read(200_000).decode("utf-8", errors="replace")
        except OSError:
            return []
        results: list[dict[str, str]] = []
        for match in _RESULT_BLOCK_RE.finditer(page):
            href, title_html, snippet_html = match.group(1), match.group(2), match.group(3)
            url = _resolve_ddg_url(href)
            if not url:
                continue
            title = html.unescape(re.sub(r"<[^>]+>", "", title_html)).strip()
            snippet = html.unescape(re.sub(r"<[^>]+>", "", snippet_html)).strip()
            results.append({"title": title, "url": url, "snippet": snippet})
            if len(results) >= max_results:
                break
        return results


def _resolve_ddg_url(href: str) -> str:
    """Extract the real URL from DuckDuckGo's redirect wrapper."""
    redirect = _REDIRECT_RE.search(href)
    if redirect:
        return urllib.parse.unquote(redirect.group(1))
    return href


def register(ctx) -> None:
    ctx.register_web_search_provider("ddg", DuckDuckGoProvider)
