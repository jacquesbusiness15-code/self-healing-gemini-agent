"""Self-healing demo — the centerpiece.

Runs the SAME task twice, each in a FRESH session with no shared conversation
memory. The agent's ONLY way to remember the past is its Phoenix trace history,
which it reads at runtime via the Phoenix MCP server.

- Run 1: fresh agent, empty history. It reaches for numpy (not installed here),
  hits ModuleNotFoundError, and recovers within the run using pure Python.
- Run 2: fresh agent, SAME task, zero local memory. It reads Run 1's trace via
  MCP, learns "numpy isn't available here", and solves it correctly first try.

The drop in failures from Run 1 to Run 2 IS the self-improvement loop.

Run:  .venv/bin/python demo_self_healing.py
"""
import os
import time
import asyncio
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

# Use a FRESH Phoenix project for each demo so Run 1 starts genuinely cold (no
# prior failures to learn from). Must be set BEFORE importing the agent, since
# the agent reads PHOENIX_PROJECT_NAME at import time. Timestamp is full
# YYYYMMDD-HHMMSS so alphabetic sort = chronological for the eval auto-discovery.
os.environ["PHOENIX_PROJECT_NAME"] = (
    "selfheal-demo-" + datetime.now().strftime("%Y%m%d-%H%M%S")
)

from phoenix.client import Client
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from self_healing_agent import run_task, PROJECT_NAME

console = Console()

px = Client(
    base_url=os.environ["PHOENIX_COLLECTOR_ENDPOINT"],
    api_key=os.environ["PHOENIX_API_KEY"],
)

# A 40-number dataset: too large to do by hand, so the agent MUST run code.
# numpy is deliberately NOT installed -> a reliable, environment-specific failure
# the agent can only know about by reading its own traces.
DATA = [12, 7, 22, 9, 14, 31, 5, 18, 27, 3, 19, 44, 8, 16, 25, 11, 38, 6, 21, 13,
        29, 2, 17, 33, 10, 24, 41, 4, 15, 28, 36, 1, 20, 23, 39, 7, 30, 18, 26, 9]

# Same task for BOTH runs (fair comparison). It forces code use, mandates numpy
# (which springs the trap on a cold run), and tells the agent to introspect first
# and skip numpy if its own history shows numpy failed before.
TASK = (
    "First call recall_failures to review your OWN past FAILED code so you don't "
    "repeat mistakes. Then use the execute_python tool (never by hand) to compute the "
    f"mean, population standard deviation, and median of this dataset, each rounded to "
    f"2 decimals: {DATA}. "
    "Use numpy for the computation and attempt it first — UNLESS recall_failures shows "
    "numpy failed before, in which case skip numpy and use the Python standard library "
    "directly. If numpy fails at runtime, fall back to the standard library and "
    "continue. Never give up."
)


def span_count() -> int:
    try:
        return len(px.spans.get_spans(project_identifier=PROJECT_NAME, limit=1000))
    except Exception:
        return 0


async def wait_for_new_spans(baseline: int, min_new: int = 3, timeout: int = 120) -> None:
    """Block until Run 1's spans are queryable in Phoenix, so Run 2's MCP lookup
    is guaranteed to see them (avoids the ingestion-latency race)."""
    waited = 0
    while waited < timeout:
        if span_count() - baseline >= min_new:
            return
        await asyncio.sleep(4)
        waited += 4
    print("  (proceeding; ingestion wait timed out)")


async def main() -> None:
    intro = (
        f"[bold]Project:[/] {PROJECT_NAME}\n"
        f"[bold]Model:[/]   {os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')}\n\n"
        "Watch closely — the agent will run the SAME task twice in two FRESH "
        "sessions.\n"
        "Its only memory across runs is its own log in Phoenix."
    )
    console.print(Panel(intro, title="🤖 Self-Healing Agent — Live Demo",
                        border_style="cyan"))

    console.print(Panel(
        "[bold yellow]RUN 1 — cold start[/]\n"
        "Fresh agent, no history. We expect it to TRY numpy, FAIL, then "
        "self-recover with Python's standard library.",
        border_style="yellow"))
    baseline = span_count()
    r1 = await run_task(TASK, label="run-1-cold", narrate=True)

    t0 = time.time()
    console.print("\n[dim]… waiting for Run 1's traces to land in Phoenix …[/]")
    await wait_for_new_spans(baseline)
    elapsed = time.time() - t0
    if elapsed < 65:
        console.print(f"[dim]… pacing {65 - elapsed:.0f}s so the per-minute rate limit resets …[/]")
        await asyncio.sleep(65 - elapsed)

    console.print(Panel(
        "[bold cyan]RUN 2 — informed by Run 1's traces[/]\n"
        "Fresh agent again, ZERO local memory. It can only know about Run 1 by "
        "reading its own Phoenix logs. If it works, it'll skip numpy entirely.",
        border_style="cyan"))
    r2 = await run_task(TASK, label="run-2-informed", narrate=True)

    summary = (
        f"  [bold]Run 1 (cold):    [/]  attempts={r1['code_attempts']}  "
        f"FAILURES={r1['code_errors']}  introspection_calls={r1['introspection_calls']}\n"
        f"  [bold]Run 2 (informed):[/]  attempts={r2['code_attempts']}  "
        f"FAILURES={r2['code_errors']}  introspection_calls={r2['introspection_calls']}\n"
    )
    if r2["code_errors"] < r1["code_errors"]:
        verdict = "[bold green]✅ The agent read its OWN trace history and avoided repeating the failure.[/]"
        style = "green"
    elif r2["introspection_calls"] > 0:
        verdict = "[yellow]ℹ️  The agent introspected its history; inspect the runs above for the lesson it applied.[/]"
        style = "yellow"
    else:
        verdict = "[red]⚠️  No clear improvement this run — check the transcripts above.[/]"
        style = "red"
    console.print(Panel(summary + verdict, title="📊 Self-Improvement Summary",
                        border_style=style))

    console.print(
        f"\n[dim]Evaluate this run's traces (writes annotations back to Phoenix):[/]\n"
        f"  [bold cyan].venv/bin/python evaluate_runs.py[/] {PROJECT_NAME}\n"
        f"  [bold cyan].venv/bin/python evaluate_llm_judge.py[/] {PROJECT_NAME}\n"
    )


if __name__ == "__main__":
    asyncio.run(main())
