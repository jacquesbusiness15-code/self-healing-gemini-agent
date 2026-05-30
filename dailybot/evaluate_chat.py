"""Code-based eval of dailybot chat traces — scored directly from Phoenix
and written back as annotations (annotator_kind=CODE). No LLM, no quota.

Mirrors the pattern of evaluate_runs.py:30-95 from the hackathon project,
but retargeted at dailybot's multi-tool chat traces (1 trace per turn,
any of 14 tools possible per turn).

Per chat turn:
  - tool_use:    did the agent invoke at least one tool? (binary)
  - clean:       all tool calls returned status=ok        (binary)
  - healed:      had error/blocked but final call ok       (binary)
  - introspected: did the agent call recall_failures?      (binary)

Label: clean / healed / unresolved / no_tools
Score: 1.0     / 0.7    / 0.0        / 0.5 (neutral; chitchat turn)

Annotations written via px.spans.add_span_annotation are queryable via
the Phoenix MCP get-span-annotations tool, so the agent can read its own
eval scores at runtime — closing the loop a second time over.

Run:  .venv/bin/python dailybot/evaluate_chat.py [project_name]
      (no arg -> prefer dailybot-demo-* if any, else stable 'dailybot')
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


def _latest_dailybot_project(default: str = "dailybot") -> str:
    """Prefer the most recent dailybot-demo-* (newest demo, genuinely cold)
    over the stable 'dailybot' production project, so `make demo-dailybot
    && make chat-eval` evaluates the just-made demo."""
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


def _tool_status(attrs: dict) -> str | None:
    """Read the dailybot tool's `status` field out of its recorded response."""
    resp = str(attrs.get("gcp.vertex.agent.tool_response")
               or attrs.get("output.value") or "")
    if '"status": "blocked"' in resp or "'status': 'blocked'" in resp:
        return "blocked"
    if '"status": "error"' in resp or "'status': 'error'" in resp:
        return "error"
    if '"status": "ok"' in resp or "'status': 'ok'" in resp:
        return "ok"
    return None


def _tool_name(span: dict) -> str:
    """ADK names tool spans 'execute_tool <tool>'. Return the bare tool name."""
    return (span.get("name") or "").replace("execute_tool ", "").strip()


def _is_tool_span(s: dict) -> bool:
    kind = (s.get("span_kind") or "").upper()
    return kind == "TOOL" or "execute_tool" in (s.get("name") or "")


def main() -> None:
    spans = px.spans.get_spans(project_identifier=PROJECT, limit=1000)
    if not spans:
        print(f"No spans found in project {PROJECT!r}.")
        return

    by_trace: dict[str, list] = defaultdict(list)
    for s in spans:
        by_trace[(s.get("context") or {}).get("trace_id")].append(s)

    print(f"\nEvaluating dailybot project {PROJECT!r} — {len(by_trace)} traces")
    print("=" * 74)

    scored = 0
    counts = {"clean": 0, "healed": 0, "unresolved": 0, "no_tools": 0}

    for tid, group in by_trace.items():
        group.sort(key=lambda s: s.get("start_time") or "")
        root = next((s for s in group if not s.get("parent_id")), None)
        if not root:
            continue

        # Recall calls are introspection, not user-facing work — count them
        # separately rather than as tool quality.
        all_tools = [s for s in group if _is_tool_span(s)]
        introspected = any("recall_failures" in _tool_name(s) for s in all_tools)
        scoreable_tools = [s for s in all_tools
                           if "recall_failures" not in _tool_name(s)]
        statuses = [_tool_status(s.get("attributes") or {}) for s in scoreable_tools]
        num_tools = len(scoreable_tools)
        num_errors = sum(1 for st in statuses if st in ("error", "blocked"))

        if num_tools == 0:
            label, score = "no_tools", 0.5
            explanation = "no tool calls (conversational turn)"
        elif num_errors == 0:
            label, score = "clean", 1.0
            explanation = f"{num_tools} tool call(s), all ok"
        elif statuses and statuses[-1] == "ok":
            label, score = "healed", 0.7
            explanation = (
                f"{num_tools} tool call(s), {num_errors} failed but recovered to ok"
            )
        else:
            label, score = "unresolved", 0.0
            explanation = (
                f"{num_tools} tool call(s), {num_errors} failed, did not recover"
            )
        explanation += f"; introspected={introspected}"

        scored += 1
        counts[label] = counts.get(label, 0) + 1
        print(f"  {tid[:12]}…  {label:10s} score={score}  | {explanation}")

        try:
            px.spans.add_span_annotation(
                span_id=root["id"], annotation_name="chat_quality",
                annotator_kind="CODE", label=label, score=score,
                explanation=explanation,
            )
        except Exception as exc:
            print(f"      (could not write annotation: {exc})")

    print("=" * 74)
    print(f"Scored {scored} dailybot chat turns: "
          f"clean={counts['clean']}, healed={counts['healed']}, "
          f"unresolved={counts['unresolved']}, no_tools={counts['no_tools']}")
    print("Annotations written to Phoenix (annotator_kind=CODE), queryable via")
    print("the MCP get-span-annotations tool.")


if __name__ == "__main__":
    main()
