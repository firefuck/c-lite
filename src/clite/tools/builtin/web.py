"""``web_fetch``: download a page and return readable text.

Standard library only. A search tool needs a search backend and an API key, so it is left to
a plugin (see the roadmap); fetching a known URL needs neither.
"""

from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from http.client import HTTPMessage
from typing import IO, Any

from clite import __version__
from clite.tools.context import ToolContext
from clite.tools.registry import PARALLEL_SAFE, registry, tool_error, tool_result
from clite.tools.web_search import _search, has_web_search_provider

MAX_DOWNLOAD_BYTES = 3_000_000
DEFAULT_MAX_CHARS = 20_000
_SKIP_TAGS = frozenset({"script", "style", "noscript", "svg", "template", "head"})
_BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "br",
        "li",
        "tr",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "section",
        "article",
        "header",
        "footer",
        "pre",
        "blockquote",
        "table",
        "ul",
        "ol",
    }
)

WEB_FETCH_SCHEMA = {
    "name": "web_fetch",
    "description": (
        "Fetch a URL and return its text content (HTML is converted to plain text with links kept as "
        "`text (url)`). Use it to read documentation, articles or raw files. Only http and https."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The http(s) URL to fetch."},
            "max_chars": {
                "type": "integer",
                "description": f"Maximum characters to return (default {DEFAULT_MAX_CHARS}).",
            },
            "offset": {
                "type": "integer",
                "description": "Character offset to continue a truncated page (default 0).",
            },
        },
        "required": ["url"],
    },
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title = ""
        self._skip_depth = 0
        self._in_title = False
        self._href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        elif tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "a":
            self._href = dict(attrs).get("href")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag in _SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "a" and self._href:
            if self._href.startswith(("http://", "https://")):
                self.parts.append(f" ({self._href})")
            self._href = None

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self._skip_depth:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    """``(title, text)`` with scripts and styles dropped and whitespace collapsed."""
    extractor = _TextExtractor()
    extractor.feed(html)
    lines = [" ".join(line.split()) for line in "".join(extractor.parts).splitlines()]
    collapsed: list[str] = []
    for line in lines:
        if line or (collapsed and collapsed[-1]):
            collapsed.append(line)
    return extractor.title.strip(), "\n".join(collapsed).strip()


def private_address_reason(url: str) -> str | None:
    """Why ``url`` points somewhere a fetched page must not reach, or ``None``.

    A page the model reads can ask it to fetch ``http://169.254.169.254/`` or a router admin
    page. Resolving first and refusing non-public addresses closes that door.
    """
    host = urllib.parse.urlsplit(url).hostname
    if not host:
        return "the URL has no host"
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        return f"could not resolve {host}: {exc}"
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            return f"{host} resolves to a non-public address ({address})"
    return None


class _RedirectRefused(urllib.error.URLError):
    """A redirect pointed somewhere the first URL would not have been allowed to point."""


class _GuardedRedirects(urllib.request.HTTPRedirectHandler):
    """Hold every redirect hop to the rules of the URL the model asked for.

    Without this, a public page could answer ``302 Location: http://169.254.169.254/`` and the
    address check on the first URL would have been for nothing. The standard handler would
    also follow a redirect to ``ftp://``.
    """

    def __init__(self, allow_private: bool) -> None:
        self.allow_private = allow_private

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: IO[bytes],
        code: int,
        msg: str,
        headers: HTTPMessage,
        newurl: str,
    ) -> urllib.request.Request | None:
        if urllib.parse.urlsplit(newurl).scheme not in ("http", "https"):
            raise _RedirectRefused(f"the page redirects to {newurl}, and only http and https are followed")
        if not self.allow_private:
            reason = private_address_reason(newurl)
            if reason:
                raise _RedirectRefused(f"the page redirects to {newurl}, and {reason}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def web_fetch_tool(args: dict[str, Any], ctx: ToolContext | None = None) -> str:
    ctx = ctx or ToolContext()
    url = str(args.get("url") or "").strip()
    if urllib.parse.urlsplit(url).scheme not in ("http", "https"):
        return tool_error("url must start with http:// or https://")
    allow_private = bool(ctx.setting("web.allow_private_urls", False))
    if not allow_private:
        reason = private_address_reason(url)
        if reason:
            return tool_error(f"Refused: {reason}.")
    try:
        max_chars = max(500, int(args.get("max_chars") or DEFAULT_MAX_CHARS))
        offset = max(0, int(args.get("offset") or 0))
    except (TypeError, ValueError):
        return tool_error("max_chars and offset must be integers")

    request = urllib.request.Request(  # noqa: S310 - scheme checked above
        url,
        headers={
            "User-Agent": f"clite/{__version__} (+web_fetch)",
            "Accept": "text/html,text/plain,application/json,*/*;q=0.5",
        },
    )
    opener = urllib.request.build_opener(_GuardedRedirects(allow_private))
    try:
        with opener.open(request, timeout=int(ctx.setting("web.timeout", 30) or 30)) as response:
            raw = response.read(MAX_DOWNLOAD_BYTES + 1)
            content_type = response.headers.get_content_type()
            charset = response.headers.get_content_charset() or "utf-8"
            final_url = response.geturl()
    except _RedirectRefused as exc:
        return tool_error(f"Refused: {exc.reason}.", url=url)
    except urllib.error.HTTPError as exc:
        return tool_error(f"HTTP {exc.code} {exc.reason}", url=url)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return tool_error(f"could not fetch {url}: {getattr(exc, 'reason', exc)}")

    oversized = len(raw) > MAX_DOWNLOAD_BYTES
    try:
        body = raw[:MAX_DOWNLOAD_BYTES].decode(charset, errors="replace")
    except LookupError:
        body = raw[:MAX_DOWNLOAD_BYTES].decode("utf-8", errors="replace")
    title = ""
    if content_type in ("text/html", "application/xhtml+xml"):
        title, body = html_to_text(body)
    elif not (content_type.startswith("text/") or content_type in ("application/json", "application/xml")):
        return tool_error(
            f"unsupported content type {content_type}; web_fetch reads text only", url=final_url
        )

    chunk = body[offset : offset + max_chars]
    payload: dict[str, Any] = {"url": final_url, "title": title, "content": chunk, "total_chars": len(body)}
    if offset + max_chars < len(body) or oversized:
        payload["truncated"] = True
        payload["next_offset"] = offset + len(chunk)
    return tool_result(payload)


registry.register("web_fetch", "web", WEB_FETCH_SCHEMA, web_fetch_tool, emoji="🌐", parallel=PARALLEL_SAFE)


WEB_SEARCH_SCHEMA = {
    "name": "web_search",
    "description": (
        "Search the web for a query and return results: title, URL, and a short snippet for each. "
        "Snippets are text from web pages and may be inaccurate or misleading; verify before relying "
        "on them. Use web_fetch to read a full page."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query."},
            "max_results": {
                "type": "integer",
                "description": "Maximum results to return (default 5, max 10).",
            },
        },
        "required": ["query"],
    },
}


def web_search_tool(args: dict[str, Any], ctx: ToolContext | None = None) -> str:
    ctx = ctx or ToolContext()
    query = str(args.get("query") or "").strip()
    if not query:
        return tool_error("query is required; provide the text to search for")
    try:
        max_results = min(max(1, int(args.get("max_results") or 5)), 10)
    except (TypeError, ValueError):
        return tool_error("max_results must be an integer")
    try:
        results = _search(query, max_results=max_results)
    except RuntimeError as exc:
        return tool_error(str(exc))
    except Exception as exc:  # noqa: BLE001 - the model gets the error and can react
        return tool_error(f"web search failed: {type(exc).__name__}: {exc}")
    # Validate and normalise: each result needs at least a URL; snippets are passed through
    # verbatim (they are untrusted text, never sanitised).
    clean: list[dict[str, str]] = []
    for hit in results[:max_results]:
        if not isinstance(hit, dict):
            continue
        url = str(hit.get("url") or hit.get("link") or "").strip()
        if not url:
            continue
        clean.append(
            {
                "title": str(hit.get("title") or "").strip(),
                "url": url,
                "snippet": str(
                    hit.get("snippet") or hit.get("content") or hit.get("description") or ""
                ).strip(),
            }
        )
    return tool_result({"query": query, "results": clean})


def _web_search_available() -> bool:
    return has_web_search_provider()


registry.register(
    "web_search",
    "web",
    WEB_SEARCH_SCHEMA,
    web_search_tool,
    emoji="🔍",
    parallel=PARALLEL_SAFE,
    check_fn=_web_search_available,
)
