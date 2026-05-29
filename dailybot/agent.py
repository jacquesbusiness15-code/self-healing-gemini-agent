"""Build the ADK chat agent + helper to run one turn.

Mirrors the hackathon project's wiring in self_healing_agent.py — same
Phoenix init, same ADK instrumentation, same MCP toolset, same thinking
budget — but with a multi-tool toolbelt and a free-form chat instruction."""
import os

from dotenv import load_dotenv

load_dotenv()

# ADK -> Gemini via google-genai SDK. Point it at AI Studio (not Vertex).
os.environ.setdefault("GOOGLE_API_KEY", os.environ["GEMINI_API_KEY"])
os.environ.setdefault("GOOGLE_GENAI_USE_VERTEXAI", "FALSE")

# --- Phoenix tracing must be wired up before any agent code runs ---
from phoenix.otel import register
from openinference.instrumentation.google_adk import GoogleADKInstrumentor

PROJECT_NAME = os.getenv("PHOENIX_PROJECT_NAME", "dailybot")
tracer_provider = register(project_name=PROJECT_NAME)
GoogleADKInstrumentor().instrument(tracer_provider=tracer_provider)

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.adk.tools.mcp_tool import McpToolset, StdioConnectionParams
from google.genai import types
from mcp import StdioServerParameters

from dailybot.prompt import INSTRUCTION
from dailybot.tools.code import execute_python
from dailybot.tools.files import read_file, write_file, list_dir, find_files
from dailybot.tools.recall import recall_failures
from dailybot.tools.shell import shell_exec
from dailybot.tools.web_search import web_search

APP_NAME = "dailybot"
USER_ID = "chat"

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

INTROSPECTION_TOOLS = ["get-spans"]


def make_phoenix_toolset() -> McpToolset:
    """Phoenix MCP server, spawned per chat session via npx."""
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


def build_chat_agent(phoenix_toolset: McpToolset) -> LlmAgent:
    """Same constructor shape as self_healing_agent.build_agent — just a
    wider toolbelt and a chat-flavored instruction."""
    return LlmAgent(
        name="dailybot",
        model=MODEL,
        instruction=INSTRUCTION,
        tools=[
            web_search,
            read_file, write_file, list_dir, find_files,
            shell_exec,
            execute_python,
            recall_failures,
            phoenix_toolset,
        ],
        # Same reason as in the hackathon agent: detailed instruction + no
        # thinking budget => MALFORMED_FUNCTION_CALL on gemini-2.5-flash.
        generate_content_config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_budget=1024),
        ),
    )


async def new_session(runner: InMemoryRunner) -> str:
    session = await runner.session_service.create_session(
        app_name=APP_NAME, user_id=USER_ID,
    )
    return session.id


async def chat_turn(runner: InMemoryRunner, session_id: str, user_text: str,
                    on_event=None) -> str:
    """One conversation turn. Streams tool-call / tool-response / text events
    to `on_event(kind, payload)` so the REPL can render them live. Returns
    the agent's final text reply."""
    message = types.Content(role="user", parts=[types.Part(text=user_text)])
    final_text = ""
    async for event in runner.run_async(
        user_id=USER_ID, session_id=session_id, new_message=message
    ):
        if not event.content or not event.content.parts:
            continue
        for part in event.content.parts:
            if part.text:
                final_text = part.text.strip()
                if on_event:
                    on_event("text", final_text)
            elif part.function_call:
                if on_event:
                    on_event("call", {
                        "name": part.function_call.name,
                        "args": dict(part.function_call.args or {}),
                    })
            elif part.function_response:
                if on_event:
                    on_event("response", {
                        "name": part.function_response.name,
                        "response": part.function_response.response,
                    })
    return final_text
