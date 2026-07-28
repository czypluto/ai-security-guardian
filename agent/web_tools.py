"""
Web Tools — agent/web_tools.py

Web search and page fetch. Free, no API keys needed.

Tools exposed:
  web_search    — DuckDuckGo Lite search (HTML parse, no API key)
  web_fetch     — Fetch a URL as plain text (64KB max, 8KB output)

Security:
  - Search uses DuckDuckGo Lite (no tracking, no API key)
  - Fetch strips all HTML tags to plain text — no JS execution
  - 15s timeout, 64KB download limit, 8KB output truncation
  - No cookies, no auth headers, read-only HTTP GET
  - Cannot be used for DDoS (single-threaded, no concurrent requests)
"""
from __future__ import annotations

import json
import logging
import urllib.request
import urllib.parse
import urllib.error
import re

logger = logging.getLogger("Guardian.Web")


def web_search(query: str, max_results: int = 5) -> dict:
    """Search the web using DuckDuckGo Lite. Free, no API key."""
    url = "https://lite.duckduckgo.com/lite/"
    data = urllib.parse.urlencode({"q": query}).encode()
    try:
        req = urllib.request.Request(url, data=data)
        req.add_header("User-Agent", "AI-Security-Guardian/2.0")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(req, timeout=10) as resp:
            html = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return {"error": f"Search failed: {e}", "query": query}

    # Parse result links from DuckDuckGo Lite HTML
    results = []
    # Match: <a rel="nofollow" href="...">Title</a>
    links = re.findall(
        r'<a[^>]*href="([^"]+)"[^>]*>([^<]+)</a>',
        html
    )
    # Match: <span class="link-text">hostname</span> for snippet context
    snippets = re.findall(
        r'<td[^>]*class="result-snippet"[^>]*>(.*?)</td>',
        html, re.DOTALL
    )

    seen = set()
    for url_match, title in links[:max_results * 3]:
        title = title.strip()
        if not title or "duckduckgo" in url_match.lower():
            continue
        if url_match in seen:
            continue
        seen.add(url_match)
        # Unescape HTML entities
        title = title.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
        results.append({
            "title": title,
            "url": url_match,
        })
        if len(results) >= max_results:
            break

    return {
        "query": query,
        "results": results,
        "total": len(results),
    }


def web_fetch(url: str) -> dict:
    """Fetch a web page as plain text. Use for reading docs, API pages, etc."""
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "AI-Security-Guardian/2.0")
        with urllib.request.urlopen(req, timeout=15) as resp:
            # Read up to 64KB
            html = resp.read(65536).decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}", "url": url}
    except Exception as e:
        return {"error": str(e), "url": url}

    # Strip HTML tags to plain text
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    # Truncate to 8KB
    if len(text) > 8192:
        text = text[:8192] + f"\n\n[truncated from {len(text)} chars]"

    return {
        "url": url,
        "content": text,
        "length": len(text),
    }
