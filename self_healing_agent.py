"""Self-Healing Agent — Milestone 1.

A multi-step Google ADK agent that solves tasks by writing and running Python,
fully traced to Phoenix. Later milestones add self-healing via trace introspection.

Run:  .venv/bin/python self_healing_agent.py
"""
import os
import io
import json
import contextlib
import traceback
import asyncio

from dotenv import load_dotenv

load_dotenv()

# ADK reaches Gemini through the google-genai SDK. Point it at the AI Studio
# API key we already have in .env (not Vertex), so no gcloud is needed.
os.environ.setdefault("GOOGLE_API_KEY", os.environ["GEMINI_API_KEY"])
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")

# --- Phoenix tracing must be wired up before the agent runs ---
from phoenix.otel import register
from openinference.instrumentation.google_adk import GoogleADKInstrumentor

PROJECT_NAME = os.getenv("PHOENIX_PROJECT_NAME", "gemini-hackathon")

tracer_provider = register(project_name=PROJECT_NAME)
GoogleADKInstrumentor().instrument(tracer_provider=tracer_provider)

# A read client for the agent's own introspection tool (recall_failures).
from phoenix.client import Client as _PhoenixClient

_px = _PhoenixClient(
    base_url=os.environ["PHOENIX_COLLECTOR_ENDPOINT"],
    api_key=os.environ["PHOENIX_API_KEY"],
)


from opentelemetry import trace as _otel_trace


# --- The one tool the agent uses to act on the world ---
def execute_python(code: str) -> dict:
    """Run a snippet of Python and return its stdout, or the full error
    traceback if it raised. The agent calls this to compute answers.

    Args:
        code: A complete Python snippet. Use print() to emit results.
    """
    buffer = io.StringIO()
    namespace: dict = {}
    try:
        with contextlib.redirect_stdout(buffer):
            exec(code, namespace)
        return {"status": "ok", "stdout": buffer.getvalue()}
    except Exception as exc:
        # Tag the failing code onto the trace span. (We don't set ERROR status —
        # the ADK instrumentor overwrites it to OK on normal return — so
        # recall_failures reads the recorded tool output instead.)
        span = _otel_trace.get_current_span()
        try:
            span.record_exception(exc)
            span.set_attribute("self_healing.failed_code", code)
        except Exception:
            pass
        return {
            "status": "error",
            "stdout": buffer.getvalue(),
            "error": traceback.format_exc(),
        }


def _short_error(tool_response: str) -> str:
    """Pull a one-line error summary out of a recorded execute_python response."""
    try:
        data = json.loads(tool_response)
        err = data.get("error") or (data.get("response") or {}).get("error") or ""
    except Exception:
        err = tool_response
    lines = [ln for ln in str(err).splitlines() if ln.strip()]
    return lines[-1][:200] if lines else str(err)[:200]


def recall_failures(limit: int = 5) -> dict:
    """Return your OWN past code executions that FAILED — the failing code and the
    exact error — so you can avoid repeating them. Reads your Phoenix trace history.

    Args:
        limit: maximum number of past failures to return, most recent first.
    """
    try:
        spans = _px.spans.get_spans(
            project_identifier=PROJECT_NAME, span_kind="TOOL", limit=100,
        )
    except Exception as exc:
        # A 404 just means this project has no traces yet (a cold start).
        if "404" in str(exc):
            return {"past_failures": [], "note": "no trace history yet (cold start)"}
        return {"past_failures": [], "note": f"could not read trace history: {exc}"}

    spans.sort(key=lambda s: s.get("start_time") or "", reverse=True)
    failures = []
    for span in spans:
        if "execute_python" not in (span.get("name") or ""):
            continue
        attrs = span.get("attributes") or {}
        resp = (attrs.get("gcp.vertex.agent.tool_response")
                or attrs.get("output.value") or "")
        if '"status": "error"' not in str(resp) and "'status': 'error'" not in str(resp):
            continue
        code = (attrs.get("self_healing.failed_code")
                or attrs.get("tool.parameters.code") or "")
        failures.append({"failed_code": str(code)[:300], "error": _short_error(str(resp))})
        if len(failures) >= limit:
            break
    return {"past_failures": failures}


# --- The agent's instruction ---
# The MCP tool names are exposed to the model with underscores (Gemini function
# names can't contain hyphens), so we reference them that way here.
INSTRUCTION = f"""You are a self-healing problem-solving agent running in a sandbox,
fully traced in Phoenix (project "{PROJECT_NAME}"). You can inspect your OWN past
behavior with the tools `get_spans` and `list_traces`.

HARD RULES — follow them exactly:
- ALWAYS compute with the `execute_python` tool. NEVER do arithmetic in your head or
  in prose. Every number you report must come from code you actually ran.
- NEVER give up. If a library import fails (e.g. ModuleNotFoundError), IMMEDIATELY
  rewrite the code using ONLY the Python standard library (math, statistics) and run
  it again. A missing library is never a reason to stop.
- LEARN FROM YOUR OWN HISTORY FIRST via the Phoenix MCP server. Before writing
  ANY code, call:
      get_spans(project_identifier="{PROJECT_NAME}",
                names=["execute_tool execute_python"],
                limit=5)
  Each returned span has an attribute `gcp.vertex.agent.tool_response` whose
  value is the JSON result of a past code attempt. Read those: if any contains
  '"status": "error"' with an error like `ModuleNotFoundError: numpy`, DO NOT
  use that library again — go straight to the Python standard library.

  Backup: if the get_spans output is too large for you to parse cleanly, call
  recall_failures() instead — it returns the same information already distilled
  to {{failed_code, error}} pairs.

Then: write & run code with execute_python applying those lessons; if it errors, fix
and retry; finally state the answer and mention any lesson you reused from your history."""

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from google.genai import types
from mcp import StdioServerParameters

APP_NAME = "self-healing"

# Override per run with GEMINI_MODEL. Free tier is ~5-20 req/min and 20 req/day
# PER MODEL, so when one model's daily bucket is exhausted, switch to another
# (e.g. GEMINI_MODEL=gemini-flash-latest). Billing removes these caps entirely.
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# A curated subset of the 27 tools the Phoenix MCP server offers — the ones
# relevant to an agent reading its own traces and eval results.
INTROSPECTION_TOOLS = [
    "get-spans",   # the agent's primary self-improvement loop runs through this
]


def make_phoenix_toolset() -> McpToolset:
    """Connect to the Phoenix MCP server (spawned via npx) so the agent can
    query its own traces, spans, and eval annotations at runtime."""
    return McpToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command="npx",
                args=[
                    "-y", "@arizeai/phoenix-mcp@latest",
                    "--baseUrl", os.environ["PHOENIX_COLLECTOR_ENDPOINT"],
                    "--apiKey", os.environ["PHOENIX_API_KEY"],
                ],
            ),
            timeout=60.0,
        ),
        tool_filter=INTROSPECTION_TOOLS,
    )


def build_agent(phoenix_toolset: McpToolset) -> LlmAgent:
    return LlmAgent(
        name="self_healer",
        model=MODEL,
        instruction=INSTRUCTION,
        tools=[execute_python, recall_failures, phoenix_toolset],
        # gemini-2.5-flash needs a thinking budget to emit well-formed function
        # calls with our detailed instruction — disabling thinking triggers
        # MALFORMED_FUNCTION_CALL (verified empirically).
        generate_content_config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_budget=1024),
        ),
    )


def _tool_status(resp) -> str | None:
    """Pull execute_python's 'status' out of a (possibly wrapped) tool response."""
    if isinstance(resp, dict):
        if "status" in resp:
            return resp["status"]
        for value in resp.values():
            if isinstance(value, dict) and "status" in value:
                return value["status"]
    return None


async def run_task(task: str, label: str = "task", narrate: bool = False) -> dict:
    """Run one task in a FRESH session (no memory carried between calls) and
    return a small summary so callers can measure self-improvement across runs.

    When `narrate=True`, prints a plain-English explanation line before each
    raw event — turns the demo into a story a non-coder can follow.
    """
    phoenix_toolset = make_phoenix_toolset()
    agent = build_agent(phoenix_toolset)
    runner = InMemoryRunner(agent=agent, app_name=APP_NAME)
    summary = {"label": label, "code_attempts": 0, "code_errors": 0,
               "introspection_calls": 0, "final_text": "", "note": ""}

    # Lazy import so the narrator stays optional. If rich isn't available, fall
    # back to plain print() — the narration is a display layer only.
    if narrate:
        from rich.console import Console
        import time
        _con = Console()
        def _say(markup: str) -> None:
            _con.print(markup)
            time.sleep(0.4)  # paces the story so a human can follow it
    else:
        def _say(markup: str) -> None: pass

    try:
        session = await runner.session_service.create_session(
            app_name=APP_NAME, user_id=label,
        )
        message = types.Content(role="user", parts=[types.Part(text=task)])
        print(f"\n🧑 [{label}] TASK: {task}\n" + "-" * 60)
        try:
            async for event in runner.run_async(
                user_id=label, session_id=session.id, new_message=message
            ):
                if not event.content or not event.content.parts:
                    continue
                for part in event.content.parts:
                    if part.text:
                        summary["final_text"] = part.text.strip()
                        _say(f"[bold green]🤖 The agent's answer:[/]")
                        print(f"🤖 {part.text.strip()}")
                    elif part.function_call:
                        name = part.function_call.name
                        args = part.function_call.args or {}
                        if name == "execute_python" or "code" in args:
                            summary["code_attempts"] += 1
                            _say("[cyan]💻 Trying this code …[/]")
                            print(f"🔧 execute_python:\n{args.get('code', '')}\n")
                        elif "recall_failures" in name:
                            summary["introspection_calls"] += 1
                            _say("[magenta]🧠 Let me check what's failed for me before …[/]")
                            print(f"🔍 introspect: {name}({args})")
                        else:
                            summary["introspection_calls"] += 1
                            _say("[magenta]🔭 Looking at my Phoenix traces …[/]")
                            print(f"🔍 introspect: {name}({args})")
                    elif part.function_response:
                        resp = part.function_response.response
                        rname = part.function_response.name
                        if rname == "execute_python":
                            status = _tool_status(resp)
                            if status == "error":
                                summary["code_errors"] += 1
                                _say("[bold red]❌ That failed — I'll fix it and try again.[/]")
                            elif status == "ok":
                                _say("[bold green]✅ It worked![/]")
                                if isinstance(resp, dict):
                                    summary["final_text"] = (
                                        (resp.get("stdout") or "").strip()
                                        or summary["final_text"]
                                    )
                        elif "recall_failures" in rname:
                            past = []
                            if isinstance(resp, dict):
                                past = resp.get("past_failures") or []
                            if past:
                                _say(f"[magenta]→ Found {len(past)} past failure(s). Reading them.[/]")
                            else:
                                _say("[magenta]→ No past failures — this is a cold start.[/]")
                        else:
                            _say(f"[magenta]→ Got data back from Phoenix.[/]")
                        print(f"📤 {rname} -> {str(resp)[:300]}\n")
        except Exception as exc:
            # Free tier is 5 req/min on this model; a burst can trip it after
            # ADK's retries. The key metrics are already captured, so don't crash.
            summary["note"] = f"interrupted ({type(exc).__name__}) — likely the 5 req/min free-tier limit"
            print(f"⚠️  run interrupted: {type(exc).__name__}: {str(exc)[:140]}")
        print("-" * 60)
    finally:
        await phoenix_toolset.close()
    return summary


if __name__ == "__main__":
    asyncio.run(run_task(
        "Use your introspection tools to tell me how many traces currently "
        f"exist in your Phoenix project '{PROJECT_NAME}'.",
        label="mcp-check",
    ))
