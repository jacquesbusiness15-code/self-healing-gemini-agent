"""execute_python — port of self_healing_agent.py:46-73.

Kept as a standalone copy (not imported) so the dailybot package doesn't
trigger self_healing_agent's Phoenix init on a different project name."""
import io
import contextlib
import traceback

from opentelemetry import trace as _otel_trace


def execute_python(code: str) -> dict:
    """Run a snippet of Python and return its stdout, or the full error
    traceback if it raised. Use print() to emit results.

    Args:
        code: A complete Python snippet.
    """
    buffer = io.StringIO()
    namespace: dict = {}
    try:
        with contextlib.redirect_stdout(buffer):
            exec(code, namespace)
        return {"status": "ok", "stdout": buffer.getvalue()}
    except Exception as exc:
        span = _otel_trace.get_current_span()
        try:
            span.record_exception(exc)
            span.set_attribute("self_healing.failed_code", code)
            span.set_attribute("dailybot.failed_input", code[:500])
            span.set_attribute("dailybot.tool", "execute_python")
        except Exception:
            pass
        return {
            "status": "error",
            "stdout": buffer.getvalue(),
            "error": traceback.format_exc(),
        }
