"""LLM-as-a-Judge evaluation of self-healing runs.

For each agent run it pulls the computed result(s) from the trace, then asks Gemini
(the judge) whether the answer is CORRECT vs the ground truth, and writes the verdict
back to Phoenix as an LLM annotation. Complements the code eval in evaluate_runs.py.

Run:  .venv/bin/python evaluate_llm_judge.py [project_name]
      GEMINI_MODEL=gemini-flash-latest .venv/bin/python evaluate_llm_judge.py <proj>
"""
import os
import sys
import json
import statistics
from collections import defaultdict

from dotenv import load_dotenv
load_dotenv()
from phoenix.client import Client
from google import genai

JUDGE_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

# The dataset the demo uses → ground truth the judge compares against.
DATA = [12, 7, 22, 9, 14, 31, 5, 18, 27, 3, 19, 44, 8, 16, 25, 11, 38, 6, 21, 13,
        29, 2, 17, 33, 10, 24, 41, 4, 15, 28, 36, 1, 20, 23, 39, 7, 30, 18, 26, 9]
EXPECTED = {
    "mean": round(statistics.fmean(DATA), 2),
    "population_std": round(statistics.pstdev(DATA), 2),
    "median": round(statistics.median(DATA), 2),
}

px = Client(base_url=os.environ["PHOENIX_COLLECTOR_ENDPOINT"],
            api_key=os.environ["PHOENIX_API_KEY"])
genai_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def _latest_demo_project(default: str = "gemini-hackathon") -> str:
    """Auto-discover the most recent selfheal-demo-* project so the eval can run
    with no CLI args. Prefers the YYYYMMDD-HHMMSS format (correctly sortable);
    falls back to the old HHMMSS-only names if no new-format projects exist."""
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

JUDGE_PROMPT = """You are grading an AI agent's numerical answer.

Ground truth for the dataset:
  mean = {mean}
  population standard deviation = {population_std}
  median = {median}

The agent's computed output(s) were:
---
{answer}
---

Did the agent report ALL THREE values correctly (small rounding differences are fine)?
Respond with ONLY a JSON object, no markdown:
{{"label": "correct" | "partially_correct" | "incorrect", "explanation": "<one sentence>"}}"""


def computed_outputs(group: list) -> str:
    """Join every successful execute_python stdout in a run."""
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


def judge(answer: str) -> dict:
    prompt = JUDGE_PROMPT.format(answer=answer, **EXPECTED)
    try:
        resp = genai_client.models.generate_content(model=JUDGE_MODEL, contents=prompt)
    except Exception as exc:
        msg = str(exc)
        tag = "rate_limited" if ("429" in msg or "RESOURCE_EXHAUSTED" in msg) else "judge_error"
        return {"label": tag, "explanation": msg[:120]}
    text = (resp.text or "").strip().strip("`")
    if text.lower().startswith("json"):
        text = text[4:].strip()
    try:
        return json.loads(text)
    except Exception:
        return {"label": "unparseable", "explanation": text[:120]}


def main() -> None:
    spans = px.spans.get_spans(project_identifier=PROJECT, limit=1000)
    by_trace: dict[str, list] = defaultdict(list)
    for s in spans:
        by_trace[(s.get("context") or {}).get("trace_id")].append(s)

    print(f"\nLLM-as-Judge ({JUDGE_MODEL}) on project {PROJECT!r}")
    print(f"Ground truth: {EXPECTED}\n" + "=" * 74)
    score_map = {"correct": 1.0, "partially_correct": 0.5, "incorrect": 0.0}
    for tid, group in by_trace.items():
        if not any("execute_python" in (s.get("name") or "") for s in group):
            continue
        answer = computed_outputs(group)
        if not answer.strip():
            continue
        verdict = judge(answer)
        label = verdict.get("label", "unparseable")
        print(f"  {tid[:12]}…  {label:18s} | {verdict.get('explanation', '')[:80]}")
        root = next((s for s in group if not s.get("parent_id")), group[0])
        try:
            px.spans.add_span_annotation(
                span_id=root["id"], annotation_name="answer_correctness",
                annotator_kind="LLM", label=label,
                score=score_map.get(label, 0.0),
                explanation=verdict.get("explanation", ""),
            )
        except Exception as exc:
            print(f"      (could not write annotation: {exc})")
    print("=" * 74)
    print("LLM verdicts written to Phoenix as annotations (annotator_kind=LLM),")
    print("alongside the CODE annotations — both queryable via MCP get-span-annotations.")


if __name__ == "__main__":
    main()
