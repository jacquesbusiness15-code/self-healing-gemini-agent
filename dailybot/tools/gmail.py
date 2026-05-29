"""Gmail tools — read inbox, search, and SAVE A DRAFT reply.

By design there is NO `gmail_send` tool. The OAuth scope is gmail.compose
(create drafts), not gmail.send. The user reviews and sends drafts from
Gmail itself. This is the load-bearing safety guarantee — the bot
cannot send mail on the user's behalf, period."""
import base64
from email.message import EmailMessage

from opentelemetry import trace as _otel_trace

from dailybot.oauth import MissingCredentialsError, get_service


_MAX_LIST = 25


def _tag(tool: str, value: str, exc: Exception) -> None:
    span = _otel_trace.get_current_span()
    try:
        span.record_exception(exc)
        span.set_attribute("dailybot.failed_input", str(value)[:500])
        span.set_attribute("dailybot.tool", tool)
    except Exception:
        pass


def _header(headers: list, name: str) -> str:
    for h in headers or []:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def _summarize(msg: dict) -> dict:
    payload = msg.get("payload") or {}
    headers = payload.get("headers") or []
    return {
        "id": msg.get("id", ""),
        "thread_id": msg.get("threadId", ""),
        "from": _header(headers, "From"),
        "to": _header(headers, "To"),
        "subject": _header(headers, "Subject") or "(no subject)",
        "snippet": (msg.get("snippet") or "")[:300],
        "date": _header(headers, "Date"),
    }


def _list(query: str, n: int) -> dict:
    try:
        service = get_service("gmail", "v1")
        n = max(1, min(int(n), _MAX_LIST))
        listing = service.users().messages().list(
            userId="me", q=query, maxResults=n,
        ).execute()
        ids = [m["id"] for m in listing.get("messages") or []]
        msgs = []
        for mid in ids:
            full = service.users().messages().get(
                userId="me", id=mid, format="metadata",
                metadataHeaders=["From", "To", "Subject", "Date"],
            ).execute()
            msgs.append(_summarize(full))
        return {"status": "ok", "query": query or "(inbox)", "messages": msgs,
                "count": len(msgs)}
    except MissingCredentialsError as exc:
        return {"status": "error", "error": str(exc), "fix": "make google-setup"}
    except Exception as exc:
        _tag("gmail", f"list({query}, n={n})", exc)
        return {"status": "error", "error": str(exc)[:300]}


def gmail_inbox_recent(n: int = 10) -> dict:
    """List the most recent N messages in the Inbox.

    Args:
        n: How many to return (max 25).
    """
    return _list(query="in:inbox", n=n)


def gmail_search(query: str, n: int = 10) -> dict:
    """Search Gmail with the standard Gmail query syntax (from:, subject:, etc).

    Args:
        query: Gmail search query, e.g. 'from:sarah is:unread'.
        n: How many results to return (max 25).
    """
    return _list(query=query, n=n)


def gmail_draft_reply(thread_id: str, body: str) -> dict:
    """Save a draft REPLY to a thread. NEVER SENDS — the user reviews it in
    Gmail's Drafts folder and sends from there.

    Args:
        thread_id: The thread ID from gmail_inbox_recent / gmail_search.
        body: The reply body (plain text).
    """
    try:
        service = get_service("gmail", "v1")
        thread = service.users().threads().get(
            userId="me", id=thread_id, format="metadata",
            metadataHeaders=["From", "To", "Subject", "Message-ID", "References"],
        ).execute()
        msgs = thread.get("messages") or []
        if not msgs:
            return {"status": "error", "error": f"thread {thread_id} has no messages"}
        last = msgs[-1]
        headers = (last.get("payload") or {}).get("headers") or []
        reply_to = _header(headers, "Reply-To") or _header(headers, "From")
        subject = _header(headers, "Subject") or ""
        msg_id_header = _header(headers, "Message-ID")
        refs = _header(headers, "References")

        em = EmailMessage()
        em["To"] = reply_to
        em["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        if msg_id_header:
            em["In-Reply-To"] = msg_id_header
            em["References"] = (refs + " " + msg_id_header).strip() if refs else msg_id_header
        em.set_content(body)
        raw = base64.urlsafe_b64encode(em.as_bytes()).decode()

        draft = service.users().drafts().create(
            userId="me",
            body={"message": {"raw": raw, "threadId": thread_id}},
        ).execute()
        return {
            "status": "ok",
            "draft_id": draft.get("id", ""),
            "thread_id": thread_id,
            "to": reply_to,
            "subject": em["Subject"],
            "note": "Draft saved to Gmail Drafts folder. Review and send from Gmail — the bot CANNOT send mail.",
        }
    except MissingCredentialsError as exc:
        return {"status": "error", "error": str(exc), "fix": "make google-setup"}
    except Exception as exc:
        _tag("gmail_draft_reply", f"thread={thread_id}", exc)
        return {"status": "error", "error": str(exc)[:300]}
