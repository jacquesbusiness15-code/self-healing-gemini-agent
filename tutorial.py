"""Interactive tutorial — walks you through the whole project lesson by lesson.

Each lesson explains in plain English first, then asks "want to run it?" so
you can dive in or skip. Quota stays opt-in per lesson.

Run:  make tutorial
"""
import os
import sys
import subprocess

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

console = Console()
PYTHON = sys.executable
TOTAL = 8


def lesson(num: int, title: str, body: str,
           runner=None, run_prompt: str | None = None) -> None:
    """Print a lesson. If `runner` is provided, ask Y/N to run it."""
    console.clear()
    console.print(Panel(
        f"[bold]{title}[/]\n\n{body}",
        title=f"📘 Lesson {num} / {TOTAL}",
        border_style="cyan",
    ))
    if runner is not None:
        if Confirm.ask(f"\n{run_prompt or 'Run it now?'}", default=True):
            console.print()
            runner()
            console.print()
    Prompt.ask("\n[dim]Press Enter for the next lesson[/]", default="")


# --- runners (thin wrappers around the project's scripts) --------------------
def run_check():
    subprocess.run([PYTHON, "check_setup.py"])


def run_mcp_check():
    subprocess.run([PYTHON, "self_healing_agent.py"])


def run_demo():
    subprocess.run([PYTHON, "demo_self_healing.py"])


def run_evals():
    subprocess.run([PYTHON, "evaluate_runs.py"])
    subprocess.run([PYTHON, "evaluate_llm_judge.py"])


# --- the 8 lessons -----------------------------------------------------------
def main() -> None:
    console.clear()
    console.print(Panel(
        "[bold]Welcome 👋[/]\n\n"
        "This tutorial walks you through your project in 8 short lessons. "
        "After each one, you decide whether to actually run the thing or "
        "just keep reading. Total time: ~5 min reading, ~10 min if you run "
        "every step. Press [bold]Ctrl+C[/] anytime to bail out.",
        title="🤖 Self-Healing Gemini Agent — Tutorial",
        border_style="green",
    ))
    Prompt.ask("\n[dim]Press Enter to begin[/]", default="")

    lesson(1, "What this thing actually does",
        "You have an AI agent (Gemini) that solves problems by writing and "
        "running Python.\n\n"
        "The twist: every step the agent takes — every tool call, every error — "
        "gets [bold]recorded in a cloud database called Phoenix[/].\n\n"
        "The bigger twist: brand-new agent sessions (with no memory) can "
        "[bold]read those recordings before they start work[/]. So if "
        "yesterday's agent failed by trying [italic]numpy[/], today's agent "
        "reads that and skips numpy entirely.\n\n"
        "Think of Phoenix as a [bold]binder[/] on the counter that every new "
        "employee reads before starting their shift. That's the whole product. "
        "The rest is plumbing.")

    lesson(2, "Make sure you're plugged in",
        "Before running anything, the project needs:\n"
        "  • Your [bold]Phoenix Cloud[/] API key (already in .env)\n"
        "  • Your [bold]Gemini[/] API key (already in .env)\n"
        "  • A Gemini model with quota remaining today\n\n"
        "[bold]check_setup.py[/] verifies all of the above and auto-picks a "
        "model with quota. If your current model is exhausted, it rotates to "
        "another and updates [bold].env[/] automatically.\n\n"
        "[dim]Cost if you run it: 1 Gemini call (a tiny probe).[/]",
        runner=run_check,
        run_prompt="Run the preflight now?")

    lesson(3, "The agent in 3 lines",
        "The whole agent is ~30 lines of meaningful logic. Open "
        "[bold]self_healing_agent.py[/] and look at:\n\n"
        "  • [bold]def execute_python(code)[/] — the agent calls this to run "
        "    Python. When the code fails, the failure is recorded on the "
        "    Phoenix trace automatically.\n\n"
        "  • [bold]def recall_failures(limit=5)[/] — the agent calls this "
        "    BEFORE writing code, to query Phoenix for past failures.\n\n"
        "  • [bold]INSTRUCTION[/] — the system prompt. It tells the agent: "
        "    \"check Phoenix first; if a library failed before, don't use it.\"\n\n"
        "Everything else (MCP, ADK, OpenInference, evals) is wiring around "
        "those three things.")

    lesson(4, "Watch the agent introspect itself live",
        "We'll run a quick agent call. The task is simple: \"How many traces "
        "do you have in Phoenix?\" To answer that, the agent has to talk to "
        "[bold]the Phoenix MCP server[/] at runtime — exactly the introspection "
        "the project is built around.\n\n"
        "You'll see lines like:\n"
        "  [magenta]🔍 introspect: list-traces({...})[/]\n"
        "  [magenta]→ Got data back from Phoenix.[/]\n"
        "  [bold green]🤖 The agent's answer:[/] You have N traces.\n\n"
        "[dim]Cost: ~3 Gemini calls. Takes ~30 seconds.[/]",
        runner=run_mcp_check,
        run_prompt="Run the MCP introspection demo?")

    lesson(5, "The main event — the self-healing demo",
        "This is the centerpiece. The [bold]same task[/] runs [bold]twice[/], "
        "each in a fresh agent session with no shared memory.\n\n"
        "  • [yellow]Run 1 (cold)[/]: no history. Tries numpy → fails → falls "
        "    back to the standard library.\n"
        "  • [cyan]Run 2 (informed)[/]: reads Run 1's failure via Phoenix → "
        "    skips numpy entirely → succeeds first try.\n\n"
        "If you see [bold]FAILURES go from 1+ → 0[/] between the two runs, "
        "that's the self-healing loop working.\n\n"
        "[dim]Cost: ~5-7 Gemini calls. Takes ~4 minutes (has a 65s pause "
        "between runs so the rate limit resets).[/]",
        runner=run_demo,
        run_prompt="Run the full self-healing demo?")

    lesson(6, "Grade the runs you just did",
        "Two evaluation pipelines score the demo runs you just made:\n\n"
        "  1. [bold]Code eval[/] (evaluate_runs.py) — looks at the trace "
        "     structure (how many code attempts, how many failed) and labels "
        "     each run [italic]clean[/] / [italic]healed[/] / [italic]unresolved[/].\n\n"
        "  2. [bold]LLM-as-Judge[/] (evaluate_llm_judge.py) — uses Phoenix's "
        "     own [italic]ClassificationEvaluator[/] to ask Gemini whether the "
        "     agent's numerical answer matches ground truth.\n\n"
        "Both write their verdicts [bold]back into Phoenix as annotations[/] "
        "on the traces — closing the loop. Future agents can read those grades "
        "too.\n\n"
        "[dim]Cost: ~2 Gemini calls (only the LLM judge).[/]",
        runner=run_evals,
        run_prompt="Run both eval pipelines?")

    lesson(7, "See it in the Phoenix UI",
        "Now look at what just got recorded.\n\n"
        "Open: [bold cyan]https://app.phoenix.arize.com[/]\n\n"
        "Click the project the demo printed (named [italic]selfheal-demo-*[/]). "
        "You'll see:\n\n"
        "  • The [bold]traces[/] (two of them, one per run)\n"
        "  • Each trace's [bold]spans[/] (call_llm, execute_tool, …)\n"
        "  • Each root span's [bold]annotations[/] tab — both the CODE eval "
        "    (self_healing_quality) and the LLM-Judge (answer_correctness) "
        "    you just wrote\n\n"
        "Bonus: under [bold]Datasets[/] you'll find [italic]self-healing-stats[/] "
        "(from [bold]make dataset[/]), and under [bold]Experiments[/] the cold + "
        "informed runs from [bold]make experiment[/], if you ran them.")

    lesson(8, "Your cheat sheet",
        "That's the tour. From now on:\n\n"
        "  [bold cyan]make check[/]        — verify env, auto-pin a model with quota\n"
        "  [bold cyan]make quota[/]        — peek at which models have quota right now\n"
        "  [bold cyan]make demo[/]         — the 2-run self-healing demo\n"
        "  [bold cyan]make eval[/]         — write both annotations to Phoenix\n"
        "  [bold cyan]make experiment[/]   — formal Phoenix Experiment (cold + informed)\n"
        "  [bold cyan]make dataset[/]      — create the Phoenix Dataset (idempotent)\n"
        "  [bold cyan]make tutorial[/]     — run this tutorial again\n\n"
        "[bold]If anything 429s:[/] just run [bold]make check[/] again. It "
        "auto-rotates [bold].env[/] to whatever model has fresh quota.\n\n"
        "[bold green]You're done. Go ship it. 🚀[/]")

    console.print("\n[bold green]🎉 Tutorial complete. Open the Phoenix UI and play.[/]\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n\n[yellow]Bye! Run `make tutorial` again any time.[/]\n")
