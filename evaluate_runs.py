"""Code-based evaluation of self-healing runs — scored directly from Phoenix
traces and written BACK to Phoenix as span annotations (annotator_kind=CODE).
No LLM, no quota.

For each agent run (trace) it scores:
  - code attempts / how many execute_python calls errored
  - recovered:    did the run end with a successful execute_python despite errors?
  - introspected: did the agent call recall_failures to learn from history?
  - self_healing_quality: 1.0 if it ended successfully, else 0.0

The annotations it writes are queryable via the MCP `get-span-annotations` tool,
so the agent could read its own eval scores at runtime — closing the loop.

Run:  .venv/bin/python evaluate_runs.py [project_name]
"""
import os
import sys
from collections import defaultdict

from dotenv import load_dotenv
load_dotenv()
from phoenix.client import Client

px = Client(
    base_url=os.environ["PHOENIX_COLLECTOR_ENDPOINT"],
    api_key=os.environ["PHOENIX_API_KEY"],
)


def _latest_demo_project(default: str = "gemini-hackathon") -> str:
    """Auto-discover the most recent selfheal-demo-* project so the eval can run
    with no CLI args. Falls back to `default` if none exist."""
    try:
        names = [str(p.get("name", "")) for p in px.projects.list()]
        demos = sorted(n for n in names if n.startswith("selfheal-demo-"))
        return demos[-1] if demos else default
    except Exception:
        return default


PROJECT = (sys.argv[1] if len(sys.argv) > 1
           else os.getenv("PHOENIX_PROJECT_NAME") or _latest_demo_project())


def _status(attrs: dict) -> str | None:
    resp = str(attrs.get("gcp.vertex.agent.tool_response")
               or attrs.get("output.value") or "")
    if '"status": "error"' in resp or "'status': 'error'" in resp:
        return "error"
    if '"status": "ok"' in resp or "'status': 'ok'" in resp:
        return "ok"
    return None


def main() -> None:
    spans = px.spans.get_spans(project_identifier=PROJECT, limit=1000)
    if not spans:
        print(f"No spans found in project {PROJECT!r}.")
        return

    by_trace: dict[str, list] = defaultdict(list)
    for s in spans:
        by_trace[(s.get("context") or {}).get("trace_id")].append(s)

    print(f"\nEvaluating project {PROJECT!r} — {len(by_trace)} traces\n" + "=" * 74)
    scored = 0
    for tid, group in by_trace.items():
        group.sort(key=lambda s: s.get("start_time") or "")
        exec_spans = [s for s in group if "execute_python" in (s.get("name") or "")]
        if not exec_spans:
            continue  # not an agent run we care about
        scored += 1
        root = next((s for s in group if not s.get("parent_id")), group[0])
        statuses = [_status(s.get("attributes") or {}) for s in exec_spans]
        failures = statuses.count("error")
        introspected = any("recall_failures" in (s.get("name") or "") for s in group)
        recovered = bool(statuses) and statuses[-1] == "ok"
        score = 1.0 if recovered else 0.0
        label = ("clean" if failures == 0 and recovered
                 else "healed" if recovered else "unresolved")
        explanation = (f"{len(exec_spans)} code attempts, {failures} failed; "
                       f"{'recovered' if recovered else 'did NOT recover'}; "
                       f"introspected={introspected}")
        print(f"  {tid[:12]}…  {label:10s} score={score}  | {explanation}")
        try:
            px.spans.add_span_annotation(
                span_id=root["id"], annotation_name="self_healing_quality",
                annotator_kind="CODE", label=label, score=score,
                explanation=explanation,
            )
        except Exception as exc:
            print(f"      (could not write annotation: {exc})")

    print("=" * 74)
    print(f"Scored {scored} agent runs. Annotations written back to Phoenix "
          "(annotator_kind=CODE),\nqueryable via the MCP get-span-annotations tool.")


if __name__ == "__main__":
    main()
