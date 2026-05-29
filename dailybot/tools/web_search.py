"""DuckDuckGo web search — no API key required."""
from opentelemetry import trace as _otel_trace


def web_search(query: str, n: int = 5) -> dict:
    """Search the web and return the top results.

    Args:
        query: What to search for.
        n: How many results to return (default 5, max 10).
    """
    try:
        from ddgs import DDGS
    except ImportError:
        return {"status": "error", "error": "ddgs not installed — pip install ddgs"}

    n = max(1, min(int(n), 10))
    try:
        results = list(DDGS().text(query, max_results=n))
    except Exception as exc:
        span = _otel_trace.get_current_span()
        try:
            span.record_exception(exc)
            span.set_attribute("dailybot.failed_input", query[:300])
            span.set_attribute("dailybot.tool", "web_search")
        except Exception:
            pass
        return {"status": "error", "error": str(exc)[:300], "query": query}

    return {
        "status": "ok",
        "query": query,
        "results": [
            {
                "title": r.get("title", "")[:200],
                "url": r.get("href") or r.get("url", ""),
                "snippet": r.get("body", "")[:400],
            }
            for r in results
        ],
    }
