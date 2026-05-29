"""shell_exec — runs a shell command, with a hard denylist on destructive
operations. Blocked commands are returned to the agent as status="blocked"
so the agent can print them for the user to run manually."""
import re
import subprocess

from opentelemetry import trace as _otel_trace


# Block any command containing these tokens. Picked to cover the obviously
# destructive ones without being so broad that everyday `ls`/`cat`/`grep` etc
# trip the gate. Whitespace-anchored so substrings inside other words don't
# false-match (e.g. "format" doesn't match "mv").
_DANGER = re.compile(
    r"(?:^|[\s;&|])(rm|mv|dd|sudo|mkfs|chmod|chown|shutdown|reboot|halt|kill|killall|pkill)(?=$|[\s;&|])"
    r"|(?:^|\s)(>{1,2}|\|\s*(?:rm|mv|dd|sudo|chmod|chown))(?=\s|$)",
    re.IGNORECASE,
)

_TIMEOUT = 30
_STDOUT_CAP = 8_000
_STDERR_CAP = 2_000


def shell_exec(cmd: str) -> dict:
    """Run a shell command and return its stdout, stderr, and exit code.

    Destructive commands (rm, mv, sudo, dd, chmod, chown, shutdown, reboot,
    redirections like > and >>) are BLOCKED — status="blocked" is returned
    and the agent must print the command for the user to run manually.

    Args:
        cmd: The shell command, exactly as you'd type it in a terminal.
    """
    if _DANGER.search(cmd):
        return {
            "status": "blocked",
            "reason": "destructive command — print it for the user to run themselves",
            "command": cmd,
        }
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT,
        )
        return {
            "status": "ok" if result.returncode == 0 else "error",
            "command": cmd,
            "returncode": result.returncode,
            "stdout": (result.stdout or "")[:_STDOUT_CAP],
            "stderr": (result.stderr or "")[:_STDERR_CAP],
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "command": cmd,
            "error": f"timed out after {_TIMEOUT}s",
        }
    except Exception as exc:
        span = _otel_trace.get_current_span()
        try:
            span.record_exception(exc)
            span.set_attribute("dailybot.failed_input", cmd[:500])
            span.set_attribute("dailybot.tool", "shell_exec")
        except Exception:
            pass
        return {"status": "error", "command": cmd, "error": str(exc)[:300]}
