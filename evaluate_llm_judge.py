"""LLM-as-a-Judge — backed by `phoenix.evals` (not a hand-rolled genai call).

For each agent run in a project, it builds a pandas row containing the
computed output(s) from the run's execute_python spans + the ground-truth
values, then runs a `ClassificationEvaluator` over the dataframe with the
Phoenix evals library. Verdicts are written back as Phoenix span annotations
(`annotator_kind="LLM"`) on the root span of each trace.

Run:  .venv/bin/python evaluate_llm_judge.py [project_name]
      (no arg → auto-discovers the most recent selfheal-demo-* project)
"""
import os
import sys
import json
import statistics
from collections import defaultdict

from dotenv import load_dotenv
load_dotenv()

import pandas as pd
from phoenix.client import Client
from phoenix.evals import LLM, ClassificationEvaluator, evaluate_dataframe

JUDGE_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

# Ground truth for the statistics demo task.
DATA = [12, 7, 22, 9, 14, 31, 5, 18, 27, 3, 19, 44, 8, 16, 25, 11, 38, 6, 21, 13,
        29, 2, 17, 33, 10, 24, 41, 4, 15, 28, 36, 1, 20, 23, 39, 7, 30, 18, 26, 9]
EXPECTED = {
    "mean": round(statistics.fmean(DATA), 2),
    "population_std": round(statistics.pstdev(DATA), 2),
    "median": round(statistics.median(DATA), 2),
}

px = Client(base_url=os.environ["PHOENIX_COLLECTOR_ENDPOINT"],
            api_key=os.environ["PHOENIX_API_KEY"])


def _latest_demo_project(default: str = "gemini-hackathon") -> str:
    try:
        names = [str(p.get("name", "")) for p in px.projects.list()]
        demos = [n for n in names if n.startswith("selfheal-demo-")]
        new_fmt = [n for n in demos if "-" in n[len("selfheal-demo-"):]]
        pool = new_fmt or demos
        return sorted(pool)[-1] if pool else default
    except Exception:
        return default


PROJECT = (sys.argv[1] if len(sys.argv) > 1
           else os.getenv("PHOENIX_PROJECT_NAME") or _latest_demo_project())


# Mustache template for the classifier — input columns become {{var}} placeholders.
JUDGE_TEMPLATE = """You are grading an AI agent's numerical answer.

Ground truth for the dataset:
  mean = {{mean}}
  population standard deviation = {{population_std}}
  median = {{median}}

The agent's computed output(s) were:
---
{{answer}}
---

Did the agent report ALL THREE values correctly (small rounding differences are fine)?"""


def computed_outputs(group: list) -> str:
    """Concatenate every successful execute_python stdout in a run."""
    outs = []
    execs = sorted((s for s in group if "execute_python" in (s.get("name") or "")),
                   key=lambda s: s.get("start_time") or "")
    for s in execs:
        raw = (s.get("attributes") or {}).get("gcp.vertex.agent.tool_response")
        if not raw:
            continue
        try:
            d = json.loads(raw)
            if d.get("status") == "ok" and d.get("stdout"):
                outs.append(d["stdout"].strip())
        except Exception:
            pass
    return "\n".join(outs)


def main() -> None:
    spans = px.spans.get_spans(project_identifier=PROJECT, limit=1000)
    by_trace: dict[str, list] = defaultdict(list)
    for s in spans:
        by_trace[(s.get("context") or {}).get("trace_id")].append(s)

    rows = []
    for tid, group in by_trace.items():
        if not any("execute_python" in (s.get("name") or "") for s in group):
            continue
        answer = computed_outputs(group)
        if not answer.strip():
            continue
        group.sort(key=lambda s: s.get("start_time") or "")
        root = next((s for s in group if not s.get("parent_id")), group[0])
        rows.append({
            "trace_id": tid,
            "_root_span_id": root["id"],
            "answer": answer,
            "mean": EXPECTED["mean"],
            "population_std": EXPECTED["population_std"],
            "median": EXPECTED["median"],
        })

    if not rows:
        print(f"No scoreable traces in project {PROJECT!r}.")
        return

    print(f"\nLLM-as-Judge via phoenix.evals  (model: {JUDGE_MODEL})")
    print(f"Project:      {PROJECT}")
    print(f"Ground truth: {EXPECTED}")
    print("=" * 74)

    llm = LLM(
        provider="google",
        model=JUDGE_MODEL,
        sync_client_kwargs={"api_key": os.environ["GEMINI_API_KEY"]},
        async_client_kwargs={"api_key": os.environ["GEMINI_API_KEY"]},
    )
    evaluator = ClassificationEvaluator(
        name="answer_correctness",
        llm=llm,
        prompt_template=JUDGE_TEMPLATE,
        choices={"correct": 1.0, "partially_correct": 0.5, "incorrect": 0.0},
        include_explanation=True,
    )

    df = pd.DataFrame(rows)
    try:
        results = evaluate_dataframe(dataframe=df, evaluators=[evaluator],
                                     hide_tqdm_bar=True)
    except Exception as exc:
        print(f"❌ evaluate_dataframe failed: {type(exc).__name__}: {str(exc)[:200]}")
        return

    # phoenix.evals 3.x adds two columns per evaluator: `{name}_execution_details`
    # (run metadata) and `{name}_score` (the actual verdict dict with label,
    # score, explanation, …). We want the _score one.
    eval_col = next((c for c in results.columns
                     if c.startswith("answer_correctness") and c.endswith("_score")), None)
    if eval_col is None:
        print(f"❌ no answer_correctness_score column. cols={list(results.columns)}")
        return

    for _, row in results.iterrows():
        verdict = row[eval_col]
        v = verdict.to_dict() if hasattr(verdict, "to_dict") else (
            verdict if isinstance(verdict, dict) else {})
        label = str(v.get("label") or "unparseable")
        score_v = v.get("score")
        score = float(score_v) if isinstance(score_v, (int, float)) else 0.0
        explanation = str(v.get("explanation") or "")
        print(f"  {str(row['trace_id'])[:12]}…  {label:18s} score={score}  | "
              f"{explanation[:80]}")
        try:
            px.spans.add_span_annotation(
                span_id=row["_root_span_id"],
                annotation_name="answer_correctness",
                annotator_kind="LLM",
                label=label, score=score, explanation=explanation,
            )
        except Exception as exc:
            print(f"      (could not write annotation: {exc})")

    print("=" * 74)
    print("LLM verdicts written to Phoenix as annotations (annotator_kind=LLM),")
    print("produced by phoenix.evals.ClassificationEvaluator.")


if __name__ == "__main__":
    main()
