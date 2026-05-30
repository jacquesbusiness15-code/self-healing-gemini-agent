"""Streamlit web UI for dailybot.

Pure frontend — reuses the entire agent backend (LlmAgent, Phoenix tracing,
MCP toolset, recall_failures, all 14 tools) from dailybot/agent.py. Every
action in the web UI is traced to the same Phoenix `dailybot` project as
the terminal version, so the self-healing recall_failures loop reads back
failures across both UIs.

Launch with: make webapp
"""
import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import nest_asyncio
import streamlit as st

from dailybot.oauth import CREDS_PATH, TOKEN_PATH, _load_cached

# Streamlit runs synchronously; ADK is async. nest_asyncio lets asyncio.run
# work even when Streamlit already holds an event loop in some configs.
nest_asyncio.apply()

st.set_page_config(page_title="dailybot", page_icon="💬", layout="centered")

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _short(value, limit: int = 100) -> str:
    s = str(value)
    return s if len(s) <= limit else s[: limit - 1] + "…"


def _google_state() -> str:
    """Read-only check of the user's Google connection. Safe to call on
    every Streamlit rerun.

    Returns one of:
      - "not_started": no credentials.json on disk (user hasn't done GCP setup)
      - "needs_auth":  credentials.json exists, no valid token (need OAuth)
      - "connected":   valid token (calendar + gmail tools work)
    """
    if not CREDS_PATH.exists():
        return "not_started"
    creds = _load_cached()
    if creds and (creds.valid or creds.refresh_token):
        return "connected"
    return "needs_auth"


def _run_oauth_subprocess() -> tuple[bool, str]:
    """Spawn an OAuth dance in a subprocess (so Streamlit's main thread
    isn't blocked by Google's local-server redirect). Poll for token.json
    or subprocess exit. Returns (success, message)."""
    proc = subprocess.Popen(
        [sys.executable, "-c",
         "from dailybot.oauth import get_credentials; "
         "get_credentials(interactive=True)"],
        cwd=str(PROJECT_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    deadline = time.time() + 120
    while time.time() < deadline:
        if TOKEN_PATH.exists():
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.terminate()
            return True, "✅ Google connected — calendar + Gmail tools enabled."
        if proc.poll() is not None:
            err = (proc.stderr.read() or b"").decode("utf-8", "replace")[-500:]
            return False, f"OAuth subprocess exited without producing a token.\n\n{err}"
        time.sleep(1)
    proc.terminate()
    return False, "Timed out after 2 minutes waiting for Google consent."


def _preflight_once() -> None:
    """Run check_setup.py exactly once per Streamlit session so GEMINI_MODEL
    is freshly pinned to a model with quota."""
    if st.session_state.get("preflight_done"):
        return
    script = PROJECT_ROOT / "check_setup.py"
    if script.exists():
        with st.spinner("🚀 Preflight — auto-pinning a Gemini model with free-tier quota…"):
            result = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True, text=True,
            )
        if result.returncode != 0:
            st.error("Preflight failed — fix the errors below and reload.")
            st.code((result.stdout or "") + "\n" + (result.stderr or ""))
            st.stop()
        # check_setup may have rewritten .env. Reload so we pick up GEMINI_MODEL.
        from dotenv import load_dotenv
        load_dotenv(override=True)
    st.session_state.preflight_done = True


_preflight_once()

# Import the agent AFTER preflight so MODEL env-var is fresh
from dailybot.agent import (
    APP_NAME, PROJECT_NAME, build_chat_agent, chat_turn,
    make_phoenix_toolset, new_session,
)
from google.adk.runners import InMemoryRunner


def _init_state() -> None:
    """Build agent + runner exactly once per Streamlit session and stash
    everything in session_state so Streamlit's per-interaction reruns
    don't rebuild it."""
    if "messages" not in st.session_state:
        st.session_state.messages = []
    if "runner" not in st.session_state:
        with st.spinner("🚀 Starting agent (Phoenix MCP cold-start, ~5 s)…"):
            toolset = make_phoenix_toolset()
            agent = build_chat_agent(toolset)
            runner = InMemoryRunner(agent=agent, app_name=APP_NAME)
            session_id = asyncio.run(new_session(runner))
        st.session_state.toolset = toolset
        st.session_state.agent = agent
        st.session_state.runner = runner
        st.session_state.session_id = session_id


_init_state()


# --- Sidebar ---
with st.sidebar:
    st.markdown("### 💬 dailybot")
    st.caption(f"**Model:** `{os.environ.get('GEMINI_MODEL', '?')}`")
    st.caption(f"**Phoenix project:** `{PROJECT_NAME}`")
    base = os.environ.get("PHOENIX_COLLECTOR_ENDPOINT", "")
    if base:
        ui_url = base.rstrip("/").replace("/v1/traces", "")
        st.markdown(f"🔗 [Open Phoenix UI]({ui_url}/projects)")

    # --- Google connect status + setup ---
    gstate = _google_state()
    if gstate == "connected":
        st.markdown("🟢 **Google: connected**")
        if st.button("🔓 Disconnect Google", use_container_width=True,
                     help="Delete the cached OAuth token. You can re-authorize "
                          "later from this same sidebar."):
            try:
                TOKEN_PATH.unlink(missing_ok=True)
            except Exception as exc:
                st.warning(f"Could not delete token: {exc}")
            st.rerun()
    else:
        st.markdown("🟡 **Google: not connected** _(calendar + Gmail will fail)_")
        with st.expander("🔌 Connect Google", expanded=False):
            if gstate == "not_started":
                st.markdown(
                    "Google requires you to create a Cloud project once. Steps "
                    "1-4 happen in your browser at "
                    "[console.cloud.google.com](https://console.cloud.google.com) "
                    "and take ~5 min.\n\n"
                    "**1. Create a project**\n"
                    "Top bar → project dropdown → **New Project** → name it "
                    "`dailybot` → **Create**, then select it.\n\n"
                    "**2. Enable two APIs**\n"
                    "Left menu → **APIs & Services → Library** → search and "
                    "**Enable**:\n"
                    "- Google Calendar API\n"
                    "- Gmail API\n\n"
                    "**3. OAuth consent screen**\n"
                    "Left menu → **APIs & Services → OAuth consent screen** → "
                    "**External** → fill in app name `dailybot`, your own "
                    "email as support + developer contact, add your own "
                    "email as a test user. Save and continue through.\n\n"
                    "**4. Create the OAuth client + download JSON**\n"
                    "Left menu → **APIs & Services → Credentials** → "
                    "**+ Create Credentials → OAuth client ID** → "
                    "Application type: **Desktop app** → name `dailybot` → "
                    "**Create** → click **Download JSON** in the dialog.\n\n"
                    "**5. Place the file on disk**\n"
                    "In any terminal, copy-paste:\n"
                    "```bash\n"
                    "mkdir -p ~/.config/dailybot && \\\n"
                    "  mv ~/Downloads/client_secret_*.json \\\n"
                    "     ~/.config/dailybot/credentials.json\n"
                    "```\n\n"
                    "Then come back and click the button below."
                )
                if st.button("🔄 I placed credentials.json — check again",
                             use_container_width=True):
                    st.rerun()
            elif gstate == "needs_auth":
                st.markdown(
                    "✅ `credentials.json` found at "
                    f"`{CREDS_PATH}`.\n\n"
                    "Click **Authorize** below. A new browser tab will open "
                    "to Google's consent screen — click **Allow** there and "
                    "this badge will turn green. Scopes requested: "
                    "Calendar read-only, Gmail read-only, Gmail compose "
                    "(drafts only — never send).\n\n"
                    "You'll see Google's *'this app isn't verified'* warning — "
                    "that's normal for personal apps. Click **Advanced → "
                    "Go to dailybot (unsafe)**. It's your own project."
                )
                if st.button("🔐 Authorize with Google",
                             use_container_width=True):
                    with st.status("Opening Google consent screen in a new "
                                   "browser tab… click Allow there.",
                                   expanded=True) as status:
                        ok, msg = _run_oauth_subprocess()
                        if ok:
                            status.update(label=msg, state="complete")
                            time.sleep(1)
                            st.rerun()
                        else:
                            status.update(label="❌ OAuth failed",
                                          state="error")
                            st.code(msg)

    st.divider()
    if st.button("🔄 New chat", use_container_width=True):
        st.session_state.messages = []
        st.session_state.session_id = asyncio.run(
            new_session(st.session_state.runner)
        )
        st.rerun()

    if st.button("📊 Score this conversation", use_container_width=True,
                 help="Runs both eval pipelines (CODE + LLM-Judge) on this "
                      "Phoenix project and writes verdicts back as span "
                      "annotations. Uses ~1 Gemini call per chat turn."):
        with st.status("Scoring…", expanded=True) as status:
            st.write("Step 1 / 2 — CODE eval (no Gemini calls)")
            r1 = subprocess.run(
                [sys.executable, str(PROJECT_ROOT / "dailybot" / "evaluate_chat.py"),
                 PROJECT_NAME],
                capture_output=True, text=True,
            )
            st.code(r1.stdout or r1.stderr or "(no output)")
            st.write("Step 2 / 2 — LLM-Judge (one Gemini call per chat turn)")
            r2 = subprocess.run(
                [sys.executable, str(PROJECT_ROOT / "dailybot" / "evaluate_chat_judge.py"),
                 PROJECT_NAME],
                capture_output=True, text=True,
            )
            st.code(r2.stdout or r2.stderr or "(no output)")
            if r1.returncode == 0 and r2.returncode == 0:
                status.update(label="✅ Verdicts written to Phoenix",
                              state="complete")
                st.info(
                    "Annotations are now on each chat turn in Phoenix. "
                    "Click **🔗 Open Phoenix UI** above → this project → "
                    "any trace → **Annotations** tab to see them."
                )
            else:
                status.update(label="⚠️ Scoring had issues — see output above",
                              state="error")

    if st.button("📊 Check quota", use_container_width=True):
        quota_script = PROJECT_ROOT / "_quota_check.py"
        if quota_script.exists():
            result = subprocess.run(
                [sys.executable, str(quota_script)],
                capture_output=True, text=True,
            )
            with st.expander("Quota probe", expanded=True):
                st.code(result.stdout or result.stderr or "(no output)")
        else:
            st.warning("_quota_check.py not found")

    st.divider()
    st.markdown("**Tools**")
    st.markdown(
        "- 🔍 web_search\n"
        "- 📁 read_file · write_file · list_dir · find_files\n"
        "- 🐚 shell_exec _(destructive blocked)_\n"
        "- 🐍 execute_python\n"
        "- 📅 calendar_today · _week · _search _(needs `make google-setup`)_\n"
        "- 📧 gmail_inbox · _search · draft_reply _(needs `make google-setup`)_\n"
        "- 🧠 recall_failures — past failures from Phoenix"
    )
    st.caption(
        "Every message is traced to Phoenix. The bot reads its own past "
        "failures and avoids repeating them — the more you chat, the more "
        "it learns."
    )

    st.divider()
    with st.expander("ℹ️ About this submission"):
        st.markdown(
            "**What you're using:** a Google ADK + Gemini agent traced via "
            "OpenInference to **Arize Phoenix**.\n\n"
            "**What makes it special:** a tool called `recall_failures` reads "
            "this bot's own Phoenix log via the **Arize MCP server** before "
            "doing anything. Every fresh chat session starts already knowing "
            "what failed last time — that's the **self-improvement loop** "
            "the Arize hackathon brief asks for.\n\n"
            "**How to verify the claim:** click **📊 Score this conversation** "
            "above → CODE + LLM-Judge verdicts get written back to Phoenix. "
            "Judges (or you) inspect the whole trace tree, annotations and "
            "all, in the Phoenix UI.\n\n"
            "Full pitch: see "
            "[SUBMISSION.md](https://github.com/jacquesbusiness15-code/self-healing-gemini-agent/blob/master/SUBMISSION.md)."
        )


# --- Header ---
st.title("💬 dailybot")
st.caption(
    "Ask me to search the web, run code, read files, or check your "
    "calendar/email. The more you use me, the more I learn from my own "
    "mistakes."
)


# --- A1: Welcome panel (expanded once per session) ---
if "welcome_seen" not in st.session_state:
    st.session_state.welcome_seen = False

with st.expander(
    "👋 **What is this and why is it special?**",
    expanded=not st.session_state.welcome_seen,
):
    st.markdown(
        "**What it does.** dailybot is a chatbot like ChatGPT, except it has "
        "real tools wired in: it can search the web, run Python code, read "
        "and write files on your computer, run shell commands, and (if you "
        "set up Google) check your calendar and draft Gmail replies. You ask "
        "it a question in plain English; it picks the right tool and uses "
        "it."
        "\n\n"
        "**Why it's special.** Most chatbots forget what happened in past "
        "sessions. dailybot doesn't. Every action it takes — every tool it "
        "calls, every error it hits — is recorded in a database called "
        "**Arize Phoenix**. Before each new task, the bot first asks itself "
        "*'have I tried this before? Did it fail?'* by reading its own "
        "Phoenix log. If the answer is yes, it skips the approach that "
        "failed. **The more you use it, the smarter it gets.**"
        "\n\n"
        "**Why it fits the Arize hackathon.** This whole thing — the tracing, "
        "the self-introspection, the eval loop — is exactly what Arize "
        "Phoenix was built for. The Arize brief asks for *\"agents that can "
        "self-improve using their own observability data.\"* That's "
        "literally what `recall_failures` does on every turn. Click "
        "**📊 Score this conversation** in the sidebar to grade your own "
        "chat; the verdicts get written back to Phoenix as annotations that "
        "the bot can also read at runtime — closing the loop a second time."
        "\n\n"
        "**Want proof it actually learns?** From a terminal: `make demo` "
        "(toy demo, 2 → 0 failures) or `make demo-dailybot` (this bot, "
        "blocked shell command → recovered via recall_failures)."
    )
    st.session_state.welcome_seen = True


# --- A2: Suggested first prompts (only before user has chatted) ---
if not st.session_state.messages:
    st.caption("**Not sure what to ask? Try one of these:**")
    _suggestions = [
        ("🔍 Search the web", "What was a big tech news story this week?"),
        ("🐍 Run some Python", "Compute the 20th Fibonacci number using Python"),
        ("📁 Read my files", "List the files in my Downloads folder"),
        ("🧠 What can you do?",
         "Tell me what tools you have and the kinds of tasks I can ask you for."),
    ]
    cols = st.columns(len(_suggestions))
    for col, (label, text) in zip(cols, _suggestions):
        if col.button(label, use_container_width=True):
            st.session_state.pending_prompt = text
            st.rerun()


# --- Render existing message history ---
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        if msg.get("tool_calls"):
            with st.expander(
                f"🔧 {len(msg['tool_calls'])} tool call(s)", expanded=False,
            ):
                for tc in msg["tool_calls"]:
                    st.markdown(
                        f"**`{tc['name']}`**"
                        f"({_short(tc.get('args', {}), 200)})"
                    )
                    if "response" in tc:
                        resp = str(tc["response"])
                        st.code(resp[:600] + ("…" if len(resp) > 600 else ""))
        if msg.get("content"):
            st.markdown(msg["content"])


# --- Input + reply ---
prompt = (
    st.chat_input("ask me anything…")
    or st.session_state.pop("pending_prompt", None)
)
if prompt:
    st.session_state.messages.append(
        {"role": "user", "content": prompt, "tool_calls": []}
    )
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        tool_calls: list[dict] = []
        tool_box = st.empty()
        text_box = st.empty()
        latest_text = {"value": ""}

        def _render_tool_calls() -> None:
            with tool_box.container():
                if tool_calls:
                    with st.expander(
                        f"🔧 {len(tool_calls)} tool call(s)", expanded=True,
                    ):
                        for tc in tool_calls:
                            st.markdown(
                                f"**`{tc['name']}`**"
                                f"({_short(tc.get('args', {}), 200)})"
                            )
                            if "response" in tc:
                                resp = str(tc["response"])
                                st.code(
                                    resp[:400] + ("…" if len(resp) > 400 else "")
                                )

        def on_event(kind: str, payload) -> None:
            if kind == "call":
                tool_calls.append({
                    "name": payload.get("name", "?"),
                    "args": payload.get("args", {}),
                })
                _render_tool_calls()
            elif kind == "response":
                if tool_calls:
                    tool_calls[-1]["response"] = payload.get("response")
                _render_tool_calls()
            elif kind == "text":
                latest_text["value"] = payload
                text_box.markdown(payload)

        try:
            with st.spinner("Thinking…"):
                final_text = asyncio.run(chat_turn(
                    st.session_state.runner,
                    st.session_state.session_id,
                    prompt,
                    on_event=on_event,
                ))
            reply = (
                final_text
                or latest_text["value"]
                or "_(no reply text — the bot only made tool calls)_"
            )
            text_box.markdown(reply)
            st.session_state.messages.append({
                "role": "assistant",
                "content": reply,
                "tool_calls": tool_calls,
            })
        except Exception as exc:
            err = (
                f"❌ **{type(exc).__name__}**: {_short(exc, 240)}\n\n"
                "If this is a quota error (429 RESOURCE_EXHAUSTED), click "
                "**📊 Check quota** in the sidebar — restarting the app "
                "auto-rotates to a model with fresh quota."
            )
            text_box.error(err)
            st.session_state.messages.append({
                "role": "assistant",
                "content": err,
                "tool_calls": tool_calls,
            })
