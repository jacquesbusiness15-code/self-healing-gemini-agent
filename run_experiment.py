"""Run the self-healing agent as a Phoenix Experiment.

Runs the SAME dataset example twice — once cold, once informed — as two
separate Phoenix experiments. The failure-count delta shows up natively in
the Phoenix Experiments UI.

Setup once: `make dataset` creates the dataset this script consumes.
Run:        `make experiment`  (or `.venv/bin/python run_experiment.py`)
"""
import os
import sys
import time
import asyncio
from datetime import datetime

from dotenv import load_dotenv
load_dotenv()

# Use a FRESH Phoenix project so the cold-run's traces don't include OLD failures.
# Must be set before importing the agent (it reads PHOENIX_PROJECT_NAME at import).
os.environ.setdefault(
    "PHOENIX_PROJECT_NAME",
    "selfheal-exp-" + datetime.now().strftime("%Y%m%d-%H%M%S"),
)

from phoenix.client import Client
from rich.console import Console
from rich.panel import Panel

from self_healing_agent import run_task, PROJECT_NAME

console = Console()
px = Client(base_url=os.environ["PHOENIX_COLLECTOR_ENDPOINT"],
            api_key=os.environ["PHOENIX_API_KEY"])

DATASET_NAME = "self-healing-stats"

TASK_TEMPLATE = (
    "First call get_spans via the Phoenix MCP server to review your OWN past "
    "FAILED code so you don't repeat mistakes. Then use execute_python (never "
    "by hand) to compute the mean, population standard deviation, and median "
    "of this dataset, each rounded to 2 decimals: {data}. "
    "Use numpy first — UNLESS your past traces show numpy failed — in which "
    "case skip it and go straight to the standard library. Never give up."
)


# --- the "task" passed to phoenix experiments ---------------------------------
def make_task(label: str):
    """Return a sync wrapper around run_task() that the experiments runner
    can invoke per dataset example."""
    def task(example) -> dict:
        # The Phoenix client gives us a DatasetExample with a .input dict.
        data = example.input["data"] if hasattr(example, "input") else example["input"]["data"]
        prompt = TASK_TEMPLATE.format(data=data)
        summary = asyncio.run(run_task(prompt, label=label))
        return {
            "final_text": summary["final_text"],
            "code_attempts": summary["code_attempts"],
            "code_errors":   summary["code_errors"],
            "introspection_calls": summary["introspection_calls"],
            "note": summary["note"],
        }
    return task


# --- evaluators ---------------------------------------------------------------
# Phoenix only accepts these parameter names: input, trace_id, example, expected,
# metadata, reference, output. So evaluators take `output` by name, no *args.
def failure_count(output) -> dict:
    """Lower errors = better. Score is 1.0 if zero failures, else 0.0."""
    errors = output.get("code_errors", 0)
    return {
        "score": 1.0 if errors == 0 else 0.0,
        "label": "clean" if errors == 0 else "healed",
        "explanation": f"{errors} code failure(s)",
    }


def used_introspection(output) -> dict:
    """Did the agent actually try to inspect its history?"""
    n = output.get("introspection_calls", 0)
    return {
        "score": 1.0 if n > 0 else 0.0,
        "label": "introspected" if n > 0 else "no_introspection",
        "explanation": f"{n} introspection call(s)",
    }


def main() -> None:
    console.print(Panel(
        f"[bold]Project:[/] {PROJECT_NAME}\n"
        f"[bold]Dataset:[/] {DATASET_NAME}\n"
        f"[bold]Model:[/]   {os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')}\n\n"
        "We'll run [yellow]cold[/] then [cyan]informed[/] as TWO separate Phoenix\n"
        "experiments, on the same dataset row. The failure-count drop should\n"
        "appear in the Phoenix Experiments UI.",
        title="🧪 Self-Healing Phoenix Experiment", border_style="cyan"))

    try:
        ds = px.datasets.get_dataset(dataset=DATASET_NAME)
    except Exception as exc:
        console.print(f"[red]Dataset {DATASET_NAME!r} not found. Run `make dataset` first.[/]\n  ({exc})")
        sys.exit(1)

    evaluators = [failure_count, used_introspection]

    console.print(Panel("[yellow]Experiment 1 — COLD (agent has no prior failures to learn from)[/]",
                        border_style="yellow"))
    cold = px.experiments.run_experiment(
        dataset=ds, task=make_task("exp-cold"),
        evaluators=evaluators,
        experiment_name=f"cold-{datetime.now().strftime('%H%M%S')}",
        experiment_description="Cold run; no prior numpy failures in this project's traces.",
        print_summary=True,
    )

    console.print("\n[dim]… pacing 65s so Phoenix ingestion catches up and the per-minute rate limit resets …[/]")
    time.sleep(65)

    console.print(Panel("[cyan]Experiment 2 — INFORMED (agent reads Run 1's failures via MCP)[/]",
                        border_style="cyan"))
    informed = px.experiments.run_experiment(
        dataset=ds, task=make_task("exp-informed"),
        evaluators=evaluators,
        experiment_name=f"informed-{datetime.now().strftime('%H%M%S')}",
        experiment_description="Informed run; agent reads its own past numpy failure via Phoenix MCP get-spans.",
        print_summary=True,
    )

    console.print("\n[bold green]✅ Both experiments recorded in Phoenix.[/]")
    console.print(f"[dim]Browse them in the Phoenix UI under project '{PROJECT_NAME}', "
                  f"dataset '{DATASET_NAME}' → Experiments tab.[/]")


if __name__ == "__main__":
    main()
