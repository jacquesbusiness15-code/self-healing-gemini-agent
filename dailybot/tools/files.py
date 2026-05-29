"""File-system tools. All return dicts with a `status` key for consistency
with execute_python's return shape, so the agent's logic stays uniform."""
from pathlib import Path

from opentelemetry import trace as _otel_trace

_READ_CAP = 60_000     # don't blow the context window on huge files
_LIST_CAP = 200        # don't return more than 200 entries
_FIND_CAP = 200


def _tag(tool: str, value: str, exc: Exception) -> None:
    span = _otel_trace.get_current_span()
    try:
        span.record_exception(exc)
        span.set_attribute("dailybot.failed_input", str(value)[:500])
        span.set_attribute("dailybot.tool", tool)
    except Exception:
        pass


def read_file(path: str) -> dict:
    """Read a text file and return its contents (truncated at 60k chars).

    Args:
        path: Path to the file. ~/ expands to the user's home.
    """
    try:
        p = Path(path).expanduser().resolve()
        text = p.read_text(errors="replace")
        truncated = len(text) > _READ_CAP
        return {
            "status": "ok",
            "path": str(p),
            "content": text[:_READ_CAP],
            "truncated": truncated,
            "bytes": len(text),
        }
    except Exception as exc:
        _tag("read_file", path, exc)
        return {"status": "error", "error": str(exc), "path": path}


def write_file(path: str, content: str) -> dict:
    """Write text to a file (overwrites existing). Creates parent dirs.

    Args:
        path: Destination path. ~/ expands to the user's home.
        content: The string to write.
    """
    try:
        p = Path(path).expanduser().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return {"status": "ok", "path": str(p), "bytes": len(content)}
    except Exception as exc:
        _tag("write_file", path, exc)
        return {"status": "error", "error": str(exc), "path": path}


def list_dir(path: str = ".") -> dict:
    """List entries in a directory (capped at 200, no recursion).

    Args:
        path: Directory to list. Defaults to the current working dir.
    """
    try:
        p = Path(path).expanduser().resolve()
        entries = []
        for item in sorted(p.iterdir())[:_LIST_CAP]:
            entries.append({
                "name": item.name,
                "type": "dir" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else None,
            })
        return {"status": "ok", "path": str(p), "entries": entries}
    except Exception as exc:
        _tag("list_dir", path, exc)
        return {"status": "error", "error": str(exc), "path": path}


def find_files(root: str, pattern: str) -> dict:
    """Recursively find files matching a glob pattern.

    Args:
        root: Directory to search from. ~/ expands to the user's home.
        pattern: Glob pattern, e.g. "*.pdf" or "**/notes/*.md".
    """
    try:
        p = Path(root).expanduser().resolve()
        matches = []
        for m in p.rglob(pattern):
            matches.append(str(m))
            if len(matches) >= _FIND_CAP:
                break
        return {
            "status": "ok",
            "root": str(p),
            "pattern": pattern,
            "matches": matches,
            "truncated": len(matches) >= _FIND_CAP,
        }
    except Exception as exc:
        _tag("find_files", f"{root} :: {pattern}", exc)
        return {"status": "error", "error": str(exc), "root": root, "pattern": pattern}
