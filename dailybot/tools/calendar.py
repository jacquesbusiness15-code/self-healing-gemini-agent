"""Google Calendar tools — read-only (no event creation, no deletion)."""
from datetime import datetime, timedelta, timezone

from opentelemetry import trace as _otel_trace

from dailybot.oauth import MissingCredentialsError, get_service


_MAX_RESULTS = 50


def _tag(tool: str, value: str, exc: Exception) -> None:
    span = _otel_trace.get_current_span()
    try:
        span.record_exception(exc)
        span.set_attribute("dailybot.failed_input", str(value)[:500])
        span.set_attribute("dailybot.tool", tool)
    except Exception:
        pass


def _trim_event(ev: dict) -> dict:
    start = ev.get("start") or {}
    end = ev.get("end") or {}
    return {
        "summary": ev.get("summary", "(no title)"),
        "start": start.get("dateTime") or start.get("date") or "",
        "end": end.get("dateTime") or end.get("date") or "",
        "location": ev.get("location", ""),
        "attendees": [a.get("email") for a in ev.get("attendees") or [] if a.get("email")],
        "id": ev.get("id", ""),
    }


def _list_events(time_min: datetime, time_max: datetime, query: str = "",
                 max_results: int = 20) -> dict:
    try:
        service = get_service("calendar", "v3")
        params = {
            "calendarId": "primary",
            "timeMin": time_min.isoformat(),
            "timeMax": time_max.isoformat(),
            "singleEvents": True,
            "orderBy": "startTime",
            "maxResults": max(1, min(int(max_results), _MAX_RESULTS)),
        }
        if query:
            params["q"] = query
        events = service.events().list(**params).execute().get("items", [])
        return {
            "status": "ok",
            "window": {"from": time_min.isoformat(), "to": time_max.isoformat()},
            "events": [_trim_event(e) for e in events],
            "count": len(events),
        }
    except MissingCredentialsError as exc:
        return {"status": "error", "error": str(exc), "fix": "make google-setup"}
    except Exception as exc:
        _tag("calendar", f"{time_min} -> {time_max} | {query}", exc)
        return {"status": "error", "error": str(exc)[:300]}


def calendar_today() -> dict:
    """List events on your primary calendar for today (local timezone)."""
    now = datetime.now().astimezone()
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return _list_events(start, end)


def calendar_week() -> dict:
    """List events for the next 7 days from now."""
    now = datetime.now().astimezone()
    return _list_events(now, now + timedelta(days=7))


def calendar_search(query: str, max_results: int = 20) -> dict:
    """Search your calendar for events matching a query in the next 60 days.

    Args:
        query: Free-text search (matches title, description, attendees).
        max_results: Up to 50 results.
    """
    now = datetime.now().astimezone()
    return _list_events(now, now + timedelta(days=60), query=query,
                        max_results=max_results)
