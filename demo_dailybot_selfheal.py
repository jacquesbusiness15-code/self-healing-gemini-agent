"""dailybot self-healing demo — proves the loop generalizes past the toy
numpy task into the real chatbot, on a different tool family entirely.

Same SHAPE as demo_self_healing.py (rich narrator + Phoenix ingestion
wait + 65 s rate-limit pause), but applied to dailybot:

- Task (same for both runs): "delete /tmp/dailybot_demo_xyz.txt"
- Run 1 (cold): dailybot tries shell_exec("rm ...") -> status="blocked"
  (the dailybot denylist), then tells user the command. 1 blocked call.
- Run 2 (informed, fresh session): dailybot calls recall_failures
  first, sees the past block, and tells the user the command WITHOUT
  invoking shell_exec. 0 blocked calls.

The drop from 1 -> 0 blocked calls IS the self-improvement loop, applied
to a shell tool, in dailybot, with zero shared local memory between runs.

Run:  .venv/bin/python demo_dailybot_selfheal.py
"""
import asyncio
import os
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

# Fresh Phoenix project per demo so Run 1 is genuinely cold. Must be set
# BEFORE importing dailybot.agent, which reads PHOENIX_PROJECT_NAME at
# import time.
os.environ["PHOENIX_PROJECT_NAME"] = (
    "dailybot-demo-" + datetime.now().strftime("%Y%m%d-%H%M%S")
)

from phoenix.client import Client
from rich.console import Console
from rich.panel import Panel

from dailybot.agent import (
    APP_NAME, PROJECT_NAME, build_chat_agent, chat_turn,
    make_phoenix_toolset, new_session,
)
from google.adk.runners import InMemoryRunner

console = Console()

px = Client(
    base_url=os.environ["PHOENIX_COLLECTOR_ENDPOINT"],
    api_key=os.environ["PHOENIX_API_KEY"],
)


TASK = """Please delete the file `/tmp/dailybot_demo_xyz.txt` for me.

Step 1: BEFORE doing anything else, call
recall_failures(task_keyword="rm") to check whether you've already
tried similar things and they were blocked.

Step 2: If recall_failures shows that shell_exec was blocked on an `rm`
command before, DO NOT call shell_exec at all this time — just print
the exact rm command for me to run myself in my own terminal, and
explain in one sentence why you can't run it.

Step 3: Only if there are NO past `rm` failures, try
shell_exec("rm /tmp/dailybot_demo_xyz.txt") once. If it returns
status="blocked", print the command for me to run myself."""


def span_count() -> int:
    try:
        return len(px.spans.get_spans(project_identifier=PROJECT_NAME, limit=1000))
    except Exception:
        return 0


async def wait_for_new_spans(baseline: int, min_new: int = 3,
                             timeout: int = 120) -> None:
    """Block until Run 1's spans are queryable in Phoenix (avoids the
    ingestion-latency race). Same pattern as demo_self_healing.py:74-83."""
    waited = 0
    while waited < timeout:
        if span_count() - baseline >= min_new:
            return
        await asyncio.sleep(4)
        waited += 4
    console.print("  [dim](proceeding; ingestion wait timed out)[/]")


async def run_turn(label: str) -> dict:
    """One fresh session, one chat_turn call. Counts shell_exec calls,
    blocked statuses, and recall_failures invocations via on_event."""
    metrics = {
        "label": label,
        "shell_exec_calls": 0,
        "shell_exec_blocked": 0,
        "recall_calls": 0,
        "final_text": "",
    }
    toolset = make_phoenix_toolset()
    agent = build_chat_agent(toolset)
    runner = InMemoryRunner(agent=agent, app_name=APP_NAME)
    sid = await new_session(runner)

    def on_event(kind: str, payload) -> None:
        if kind == "call":
            name = payload.get("name", "")
            args = payload.get("args", {}) or {}
            if name == "shell_exec":
                metrics["shell_exec_calls"] += 1
                console.print(
                    f"  [cyan]🔧 shell_exec(cmd={args.get('cmd')!r})[/]"
                )
            elif name == "recall_failures":
                metrics["recall_calls"] += 1
                console.print(
                    f"  [magenta]🧠 recall_failures({args})[/]"
                )
            else:
                console.print(f"  [dim]🔧 {name}({str(args)[:80]})[/]")
        elif kind == "response":
            name = payload.get("name", "")
            resp = payload.get("response")
            if name == "shell_exec" and isinstance(resp, dict):
                st = resp.get("status")
                if st == "blocked":
                    metrics["shell_exec_blocked"] += 1
                    console.print("  [bold red]→ status=blocked[/]")
                else:
                    console.print(f"  [dim]→ status={st}[/]")
            elif name == "recall_failures" and isinstance(resp, dict):
                past = resp.get("past_failures") or []
                if past:
                    console.print(
                        f"  [magenta]→ Found {len(past)} past failure(s)[/]"
                    )
                else:
                    console.print("  [magenta]→ No past failures (cold start)[/]")
        elif kind == "text":
            metrics["final_text"] = payload

    try:
        await chat_turn(runner, sid, TASK, on_event=on_event)
    finally:
        try:
            await toolset.close()
        except Exception:
            pass
    return metrics


async def main() -> None:
    console.print(Panel(
        f"[bold]Phoenix project:[/] {PROJECT_NAME}\n"
        f"[bold]Model:[/]           "
        f"{os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')}\n\n"
        "Watch closely — dailybot will be asked the SAME task twice in two\n"
        "FRESH sessions. Its only memory across runs is its Phoenix log.\n\n"
        "[bold]The task touches the shell tool[/] (not execute_python), proving\n"
        "the self-healing loop generalizes past the toy numpy demo.",
        title="🤖 dailybot Self-Healing Demo",
        border_style="cyan",
    ))

    console.print(Panel(
        "[bold yellow]RUN 1 — cold start[/]\n"
        "Fresh agent, no `rm` failures in history yet. We expect dailybot to\n"
        "try shell_exec(rm) → get blocked by the denylist → print the\n"
        "command for the user.",
        border_style="yellow",
    ))
    baseline = span_count()
    r1 = await run_turn("run-1-cold")
    console.print(
        f"\n  [bold]Run 1:[/] shell_exec_calls={r1['shell_exec_calls']}  "
        f"shell_exec_blocked={r1['shell_exec_blocked']}  "
        f"recall_calls={r1['recall_calls']}"
    )

    console.print("\n[dim]Waiting for Phoenix to ingest run 1's spans + "
                  "free-tier rate-limit cooldown (65 s)…[/]")
    await wait_for_new_spans(baseline, min_new=3)
    await asyncio.sleep(65)

    console.print(Panel(
        "[bold cyan]RUN 2 — informed[/]\n"
        "Fresh session — zero local memory. Bot's only memory is its Phoenix\n"
        "log. We expect it to call recall_failures FIRST, find the past\n"
        "block, and skip shell_exec entirely on this run.",
        border_style="cyan",
    ))
    r2 = await run_turn("run-2-informed")
    console.print(
        f"\n  [bold]Run 2:[/] shell_exec_calls={r2['shell_exec_calls']}  "
        f"shell_exec_blocked={r2['shell_exec_blocked']}  "
        f"recall_calls={r2['recall_calls']}"
    )

    learned = (r2["shell_exec_blocked"] < r1["shell_exec_blocked"]
               and r2["recall_calls"] >= 1)
    verdict = (
        "[bold green]✅ dailybot read its own Phoenix log, called "
        "recall_failures, and SKIPPED the blocked tool entirely.[/]"
        if learned else
        "[yellow]⚠️  Improvement not yet visible — check Phoenix traces. "
        "(Quota or ingestion delay can cause this; re-run later.)[/]"
    )

    console.print(Panel(
        f"  Run 1 (cold):     shell_exec_blocked={r1['shell_exec_blocked']}  "
        f"recall_calls={r1['recall_calls']}\n"
        f"  Run 2 (informed): shell_exec_blocked={r2['shell_exec_blocked']}  "
        f"recall_calls={r2['recall_calls']}\n\n"
        f"  {verdict}\n\n"
        f"  [bold]Phoenix project:[/]  [cyan]{PROJECT_NAME}[/]\n"
        f"  [bold]Score it now:[/]    "
        f"[bold].venv/bin/python dailybot/evaluate_chat.py {PROJECT_NAME}[/]\n"
        f"  [bold]LLM-judge it:[/]    "
        f"[bold].venv/bin/python dailybot/evaluate_chat_judge.py {PROJECT_NAME}[/]",
        title="📊 dailybot Self-Improvement Summary",
        border_style="green",
    ))


if __name__ == "__main__":
    asyncio.run(main())
