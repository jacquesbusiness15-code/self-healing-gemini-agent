"""Terminal REPL for the dailybot chat agent.

Flow:
  1. Preflight via check_setup.py — auto-rotates GEMINI_MODEL if exhausted.
  2. Spawn Phoenix MCP toolset + build agent + create one session.
  3. Loop: read user input -> chat_turn -> render reply in a rich Panel.

Slash commands: /help /tools /reset /quota /quit. Ctrl+D / Ctrl+C also exit.
The session_id is reused across all turns so ADK threads conversation
history through; /reset starts a fresh session_id."""
import asyncio
import os
import subprocess
import sys

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text


console = Console()
HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)


HELP_TEXT = """**Slash commands**
- `/help` — show this help
- `/tools` — list available tools
- `/reset` — start a fresh conversation (clears in-session memory)
- `/quota` — probe Gemini models for remaining quota
- `/quit` — exit (or Ctrl+D / Ctrl+C)

**Tip:** the bot remembers your past failures across chat sessions via
Phoenix. The more you use it, the more it avoids repeating mistakes."""


TOOLS_TEXT = """**Available tools**
- `web_search(query, n=5)` — search the web (DuckDuckGo)
- `read_file / write_file / list_dir / find_files` — file ops
- `shell_exec(cmd)` — run a shell command (destructive ones blocked)
- `execute_python(code)` — run Python in a sandbox
- `calendar_today / calendar_week / calendar_search` — Google Calendar (read-only)
- `gmail_inbox_recent / gmail_search` — read Gmail
- `gmail_draft_reply(thread_id, body)` — save a draft reply (NEVER sends)
- `recall_failures(limit, task_keyword)` — your own past failures from Phoenix
- `get_spans(...)` (via Phoenix MCP) — raw span query for advanced use

**Heads-up:** Google tools need a one-time setup. Run `make google-setup`
once if you haven't yet (or skip if you only want web/file/shell/code)."""


def _preflight() -> None:
    """Run check_setup.py before the agent loads. It auto-pins GEMINI_MODEL
    to a model with remaining free-tier quota and writes that back to .env."""
    script = os.path.join(PROJECT_ROOT, "check_setup.py")
    if not os.path.exists(script):
        return
    console.print("[dim]→ preflight (auto-pin a model with quota)…[/]")
    result = subprocess.run([sys.executable, script], capture_output=False)
    if result.returncode != 0:
        console.print("[red]Preflight failed — fix the errors above and try again.[/]")
        sys.exit(1)
    # check_setup may have rewritten .env. Reload so we pick up the new model.
    from dotenv import load_dotenv
    load_dotenv(override=True)


def _short(value, limit: int = 100) -> str:
    s = str(value)
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _make_event_printer():
    """Render streamed tool calls and responses live above the final reply."""
    def on_event(kind: str, payload) -> None:
        if kind == "call":
            name = payload.get("name", "?")
            args = payload.get("args") or {}
            console.print(
                f"[magenta]🔧 {name}[/][dim]({_short(args, 120)})[/]"
            )
        elif kind == "response":
            name = payload.get("name", "?")
            resp = payload.get("response")
            status = ""
            if isinstance(resp, dict):
                s = resp.get("status")
                if s == "ok":
                    status = "[green]✅[/]"
                elif s == "error":
                    status = "[red]❌[/]"
                elif s == "blocked":
                    status = "[yellow]⚠️ blocked[/]"
            console.print(f"   [dim]→ {name} {status} {_short(resp, 160)}[/]")
        # 'text' events are stitched into the final reply by chat_turn's return
    return on_event


async def run_repl() -> None:
    _preflight()  # may rewrite .env -- MUST be before importing the agent

    # Imported lazily so _preflight's .env reload takes effect on MODEL.
    from dailybot.agent import (
        APP_NAME, PROJECT_NAME, build_chat_agent, chat_turn,
        make_phoenix_toolset, new_session,
    )
    from google.adk.runners import InMemoryRunner

    console.print(Panel(
        Text.from_markup(
            f"[bold]💬 dailybot[/] — self-healing daily-tasks assistant\n\n"
            f"[dim]Phoenix project:[/] [cyan]{PROJECT_NAME}[/]\n"
            f"[dim]Model:[/] [cyan]{os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash')}[/]\n"
            f"[dim]Type [bold]/help[/] for commands. Ctrl+D to exit.[/]"
        ),
        border_style="green",
    ))

    phoenix_toolset = make_phoenix_toolset()
    agent = build_chat_agent(phoenix_toolset)
    runner = InMemoryRunner(agent=agent, app_name=APP_NAME)
    session_id = await new_session(runner)
    on_event = _make_event_printer()

    try:
        while True:
            try:
                user_text = console.input("\n[bold cyan]you>[/] ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[yellow]Bye![/]")
                return

            if not user_text:
                continue

            if user_text.startswith("/"):
                cmd = user_text[1:].split()[0].lower()
                if cmd in ("quit", "exit", "q"):
                    console.print("[yellow]Bye![/]")
                    return
                if cmd == "help":
                    console.print(Panel(Markdown(HELP_TEXT), border_style="blue"))
                    continue
                if cmd == "tools":
                    console.print(Panel(Markdown(TOOLS_TEXT), border_style="blue"))
                    continue
                if cmd == "reset":
                    session_id = await new_session(runner)
                    console.print("[green]🔄 New conversation started.[/]")
                    continue
                if cmd == "quota":
                    quota_script = os.path.join(PROJECT_ROOT, "_quota_check.py")
                    if os.path.exists(quota_script):
                        subprocess.run([sys.executable, quota_script])
                    else:
                        console.print("[red]_quota_check.py not found[/]")
                    continue
                console.print(f"[red]Unknown command: /{cmd}[/] — try /help")
                continue

            try:
                final_text = await chat_turn(
                    runner, session_id, user_text, on_event=on_event,
                )
                if final_text:
                    console.print(Panel(
                        Markdown(final_text),
                        title="🤖 dailybot", border_style="green",
                    ))
                else:
                    console.print("[dim](no reply text — the agent only made tool calls)[/]")
            except Exception as exc:
                console.print(
                    f"[red]turn failed:[/] {type(exc).__name__}: {_short(exc, 200)}\n"
                    "[dim]Hint: if this is 429 RESOURCE_EXHAUSTED, run [bold]/quota[/] "
                    "or restart `make chat` to auto-rotate to a model with fresh quota.[/]"
                )
    finally:
        try:
            await phoenix_toolset.close()
        except Exception:
            pass


def main() -> None:
    try:
        asyncio.run(run_repl())
    except KeyboardInterrupt:
        console.print("\n[yellow]Bye![/]")


if __name__ == "__main__":
    main()
