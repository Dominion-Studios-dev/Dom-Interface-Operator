"""Web search plugin — search via DuckDuckGo (online only).

Uses the ddgs library if available, falls back to direct API.
"""

import urllib.request
import urllib.parse
import json


def search_duckduckgo(query: str, max_results: int = 5) -> list:
    """Search DuckDuckGo and return results."""
    try:
        # Try using ddgs library if installed
        from ddgs import DDGS
        results = DDGS().text(query, max_results=max_results)
        return [{"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")} for r in results]
    except ImportError:
        pass

    # Fallback: use DuckDuckGo instant answer API
    try:
        url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json&no_html=1"
        req = urllib.request.Request(url, headers={"User-Agent": "DomInterface/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            results = []
            if data.get("AbstractText"):
                results.append({"title": data.get("Heading", "Result"), "url": data.get("AbstractURL", ""), "snippet": data["AbstractText"]})
            for topic in data.get("RelatedTopics", [])[:max_results]:
                if isinstance(topic, dict) and "Text" in topic:
                    results.append({"title": topic.get("Text", "")[:80], "url": topic.get("FirstURL", ""), "snippet": topic.get("Text", "")})
            return results
    except Exception:
        return []


def handle_search(query: str) -> str:
    """Handle [SEARCH: query] tags."""
    results = search_duckduckgo(query)
    if not results:
        return f"[SEARCH] No results found for: {query}"

    output = f"Search results for '{query}':\n\n"
    for i, r in enumerate(results, 1):
        output += f"{i}. {r['title']}\n   {r['url']}\n   {r['snippet']}\n\n"
    return output.strip()


def register(registry):
    """Register search handlers with the tag registry."""
    from core.tags import TagRegistry
    registry.register("[SEARCH:", handle_search)
