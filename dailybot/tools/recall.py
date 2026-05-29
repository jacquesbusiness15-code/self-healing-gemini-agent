"""recall_failures — extended version of self_healing_agent.py:87-119 that
filters past tool failures by a free-form keyword. Lets the agent ask
"what shell things have I broken before?" without also surfacing every
numpy mistake."""
import json
import os

from phoenix.client import Client as _PhoenixClient


PROJECT_NAME = os.getenv("PHOENIX_PROJECT_NAME", "dailybot")

_px = _PhoenixClient(
    base_url=os.environ["PHOENIX_COLLECTOR_ENDPOINT"],
    api_key=os.environ["PHOENIX_API_KEY"],
)


# Span attribute keys to check, in order, for the input that failed.
_INPUT_KEYS = (
    "dailybot.failed_input",
    "self_healing.failed_code",
    "tool.parameters.code",
    "tool.parameters.cmd",
    "tool.parameters.path",
    "tool.parameters.query",
)


def _short_error(tool_response: str) -> str:
    try:
        data = json.loads(tool_response)
        err = data.get("error") or (data.get("response") or {}).get("error") or ""
    except Exception:
        err = tool_response
    lines = [ln for ln in str(err).splitlines() if ln.strip()]
    return lines[-1][:200] if lines else str(err)[:200]


def _is_failure(resp_text: str) -> bool:
    return (
        '"status": "error"' in resp_text
        or "'status': 'error'" in resp_text
        or '"status": "blocked"' in resp_text
        or "'status': 'blocked'" in resp_text
    )


def recall_failures(limit: int = 5, task_keyword: str = "") -> dict:
    """Return your OWN past tool failures so you can avoid repeating them.

    Args:
        limit: maximum number of past failures to return, most recent first.
        task_keyword: optional substring to filter by (e.g. "calendar",
            "shell", "numpy"). Filters the failing input OR the tool name.
            Pass "" for no filter.
    """
    try:
        spans = _px.spans.get_spans(
            project_identifier=PROJECT_NAME, span_kind="TOOL", limit=200,
        )
    except Exception as exc:
        if "404" in str(exc):
            return {"past_failures": [], "note": "no trace history yet (cold start)"}
        return {"past_failures": [], "note": f"could not read trace history: {exc}"}

    spans.sort(key=lambda s: s.get("start_time") or "", reverse=True)
    kw = (task_keyword or "").strip().lower()
    failures = []
    for span in spans:
        name = span.get("name") or ""
        attrs = span.get("attributes") or {}
        resp = str(
            attrs.get("gcp.vertex.agent.tool_response")
            or attrs.get("output.value")
            or ""
        )
        if not _is_failure(resp):
            continue

        failed_input = ""
        for key in _INPUT_KEYS:
            if attrs.get(key):
                failed_input = str(attrs[key])
                break

        if kw:
            haystack = (failed_input + " " + name).lower()
            if kw not in haystack:
                continue

        failures.append({
            "tool": name.replace("execute_tool ", "") or "<unknown>",
            "failed_input": failed_input[:300],
            "error": _short_error(resp),
        })
        if len(failures) >= limit:
            break

    return {
        "past_failures": failures,
        "filter": task_keyword or "(none)",
        "note": "" if failures else "no matching past failures",
    }
