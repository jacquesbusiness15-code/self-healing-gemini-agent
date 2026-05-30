"""LLM-as-Judge for dailybot chat traces — uses phoenix.evals.ClassificationEvaluator
to grade the agent's reply against the user's question. Verdicts written
back as Phoenix span annotations (annotator_kind=LLM).

Mirrors evaluate_llm_judge.py:122-170 exactly, but adapted for free-form
chat (user_query + agent_reply) rather than the numpy ground-truth task.

Run:  .venv/bin/python dailybot/evaluate_chat_judge.py [project_name]
      (no arg -> prefer dailybot-demo-* if any, else stable 'dailybot')
"""
import json
import os
import sys
from collections import defaultdict

from dotenv import load_dotenv
load_dotenv()

import pandas as pd
from phoenix.client import Client
from phoenix.evals import LLM, ClassificationEvaluator, evaluate_dataframe

JUDGE_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")

px = Client(
    base_url=os.environ["PHOENIX_COLLECTOR_ENDPOINT"],
    api_key=os.environ["PHOENIX_API_KEY"],
)


def _latest_dailybot_project(default: str = "dailybot") -> str:
    try:
        names = [str(p.get("name", "")) for p in px.projects.list()]
        demos = sorted(n for n in names if n.startswith("dailybot-demo-"))
        if demos:
            return demos[-1]
        if "dailybot" in names:
            return "dailybot"
        return default
    except Exception:
        return default


PROJECT = (sys.argv[1] if len(sys.argv) > 1
           else os.getenv("PHOENIX_PROJECT_NAME") or _latest_dailybot_project())


# Mustache template — input columns become {{var}} placeholders.
JUDGE_TEMPLATE = """You are grading an AI assistant's reply to a user's
question in a daily-tasks chatbot.

The user asked:
---
{{user_query}}
---

The assistant replied:
---
{{agent_reply}}
---

Was the assistant's reply HELPFUL? Consider:
- Does it actually address the user's question?
- Is it accurate (no obvious hallucinations or false claims)?
- If a tool failed or was blocked, did the assistant tell the user what
  to do next (e.g. "run this command yourself") instead of pretending
  it succeeded?
- For chitchat / clarifying questions, a clear, friendly reply counts
  as helpful.

helpful: clearly addresses the question with accurate, useful content.
partially_helpful: addresses some of the question but is incomplete,
  partially incorrect, or vague.
unhelpful: doesn't address the question, gives wrong information, or
  claims success when a tool actually failed."""


def _extract_text(raw, prefer_keys: tuple) -> str:
    """Pull a human-readable text out of an input.value / output.value that
    might be raw string, JSON string, or a nested dict with ADK message
    structure. Defensive — never raises."""
    if not raw:
        return ""
    s = str(raw)
    # Fast path: not JSON-shaped
    if not (s.startswith("{") or s.startswith("[") or s.startswith('"')):
        return s
    try:
        data = json.loads(s)
    except Exception:
        return s
    if isinstance(data, str):
        return data
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, dict):
            return _extract_from_dict(first, prefer_keys)
        if isinstance(first, str):
            return first
        return str(first)
    if isinstance(data, dict):
        return _extract_from_dict(data, prefer_keys)
    return s


def _extract_from_dict(d: dict, prefer_keys: tuple) -> str:
    # Try the preferred top-level keys first
    for key in prefer_keys:
        v = d.get(key)
        if isinstance(v, str) and v.strip():
            return v
        if isinstance(v, list) and v:
            # ADK messages: [{"parts": [{"text": "..."}]}]
            for item in v:
                if isinstance(item, dict):
                    parts = item.get("parts") or [item]
                    for p in parts:
                        if isinstance(p, dict):
                            for k in ("text", "content"):
                                if p.get(k):
                                    return str(p[k])
                        elif isinstance(p, str):
                            return p
                elif isinstance(item, str):
                    return item
    # Fallback: serialize dict
    return json.dumps(d)[:2000]


def _user_text(root: dict) -> str:
    attrs = root.get("attributes") or {}
    raw = attrs.get("input.value", "")
    text = _extract_text(raw, ("content", "text", "messages", "input"))
    return text[:1500].strip()


def _agent_text(root: dict) -> str:
    attrs = root.get("attributes") or {}
    raw = attrs.get("output.value", "")
    text = _extract_text(raw, ("content", "text", "output", "response"))
    return text[:2000].strip()


def main() -> None:
    spans = px.spans.get_spans(project_identifier=PROJECT, limit=1000)
    if not spans:
        print(f"No spans found in project {PROJECT!r}.")
        return

    by_trace: dict[str, list] = defaultdict(list)
    for s in spans:
        by_trace[(s.get("context") or {}).get("trace_id")].append(s)

    rows = []
    for tid, group in by_trace.items():
        group.sort(key=lambda s: s.get("start_time") or "")
        root = next((s for s in group if not s.get("parent_id")), None)
        if not root:
            continue
        user_q = _user_text(root)
        agent_a = _agent_text(root)
        if not user_q or not agent_a:
            continue
        rows.append({
            "trace_id": tid,
            "_root_span_id": root["id"],
            "user_query": user_q,
            "agent_reply": agent_a,
        })

    if not rows:
        print(f"No scoreable chat turns in project {PROJECT!r} "
              "(missing input.value / output.value on roots).")
        return

    print(f"\nLLM-as-Judge via phoenix.evals  (model: {JUDGE_MODEL})")
    print(f"Project: {PROJECT}    {len(rows)} chat turn(s) to grade")
    print("=" * 74)

    llm = LLM(
        provider="google",
        model=JUDGE_MODEL,
        sync_client_kwargs={"api_key": os.environ["GEMINI_API_KEY"]},
        async_client_kwargs={"api_key": os.environ["GEMINI_API_KEY"]},
    )
    evaluator = ClassificationEvaluator(
        name="answer_helpfulness",
        llm=llm,
        prompt_template=JUDGE_TEMPLATE,
        choices={"helpful": 1.0, "partially_helpful": 0.5, "unhelpful": 0.0},
        include_explanation=True,
    )

    df = pd.DataFrame(rows)
    try:
        results = evaluate_dataframe(dataframe=df, evaluators=[evaluator],
                                     hide_tqdm_bar=True)
    except Exception as exc:
        print(f"❌ evaluate_dataframe failed: {type(exc).__name__}: {str(exc)[:200]}")
        return

    # phoenix.evals 3.x: `{name}_execution_details` (metadata) + `{name}_score`
    # (the actual verdict dict). We want the _score one.
    eval_col = next((c for c in results.columns
                     if c.startswith("answer_helpfulness") and c.endswith("_score")), None)
    if eval_col is None:
        print(f"❌ no answer_helpfulness_score column. cols={list(results.columns)}")
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
                annotation_name="answer_helpfulness",
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
