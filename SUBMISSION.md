# Arize Hackathon Submission

**Repo:** https://github.com/jacquesbusiness15-code/self-healing-gemini-agent

## One-line hook
A Gemini agent that **reads its own observability data at runtime** to avoid
repeating past failures.

## What it does
A Google ADK + Gemini agent, fully traced to **Arize Phoenix** via OpenInference,
that uses the **Phoenix MCP server** to query its own past trace history at
runtime. When `recall_failures` shows it that a tool failed before, it skips
that approach entirely. **Failures drop from `2 → 0`** between a cold run and a
learned run.

## From toy demo to real product

The self-healing pattern isn't a one-trick demo here — it's a primitive that
scales. The same loop, the same Phoenix project family, applied to five
progressively more real surfaces:

| # | Stage | What it shows | How to see it |
|---|---|---|---|
| 1 | **Toy demo** (`self_healing_agent.py`) | The loop works end-to-end on a controlled numpy task. `2 → 0` failures, verifiable from Phoenix traces. | `make demo` |
| 2 | **Terminal product** (`dailybot/chat.py`) | Same loop applied to **9 tool families** — web search, shell, file ops, Python, calendar, Gmail, recall. | `make chat` |
| 3 | **Web product** (`dailybot/webapp.py`) | Streamlit UI on the same engine — tool calls visible inline, sidebar links to Phoenix. | `make webapp` |
| 4 | **Production evals** (`dailybot/evaluate_chat.py` + `…_judge.py`) | The same eval pipeline (CODE + LLM-Judge via `phoenix.evals.ClassificationEvaluator`) grading real chat traces. | `make chat-eval` |
| 5 | **Production self-improvement demo** (`demo_dailybot_selfheal.py`) | The loop works visibly on dailybot too — `shell_exec` blocked once, then skipped via `recall_failures` on a fresh session. | `make demo-dailybot` |

All five surfaces share the **same Phoenix project family** and the same
`recall_failures` tool. A failure in the web app on Tuesday becomes a lesson
the terminal bot uses on Wednesday. The eval annotations
(`chat_quality`, `answer_helpfulness`, `self_healing_quality`,
`answer_correctness`) are themselves queryable via the MCP
`get-span-annotations` tool — so a future agent session can read not just its
own past failures but its own past *grades*. The loop closes twice.

## Why it's novel
Most "self-improving" agents do it *offline*, after the fact. This one does it
**at runtime** — across fresh sessions, with zero local memory, using its
Phoenix traces as the only memory bridge. The introspection happens through
ADK's `McpToolset` connected to `@arizeai/phoenix-mcp`, alongside a small
`recall_failures` tool that returns a clean, weak-model-friendly summary of the
agent's own past errors.

## How the criteria are met
1. **Technical implementation** — Google ADK `LlmAgent` with custom tools.
2. **Meaningful tracing** — full `invocation → agent_run → call_llm / execute_tool`
   trees in Phoenix, including recorded failures with the failing code as a
   span attribute.
3. **MCP integration** — `@arizeai/phoenix-mcp` wired via `McpToolset`; the
   agent calls `list-traces` / `get-spans` / `recall_failures` at runtime
   (verified — it even self-corrected an invalid `limit` argument live).
4. **Self-improvement loop** — `recall_failures` lets the agent read its OWN
   failure history; verified `2 → 0` failure delta on the demo task.
5. **Evals** — both a **code eval** (`evaluate_runs.py`: clean / healed /
   unresolved) AND an **LLM-as-Judge** (`evaluate_llm_judge.py`: grades answer
   vs ground truth) score every run and write annotations back to Phoenix,
   themselves queryable via the MCP `get-span-annotations` tool. Loop closed.

## Try it in 60 seconds
See **[TRANSCRIPT.md](TRANSCRIPT.md)** for the verbatim agent reasoning, or:
```bash
git clone https://github.com/jacquesbusiness15-code/self-healing-gemini-agent
cd self-healing-gemini-agent
make setup
cp .env.example .env       # add your Phoenix + Gemini keys
make check                 # auto-picks a Gemini model with quota

# --- the toy demo (the original hackathon centerpiece) ---
make demo                  # 2-run self-healing demo; 2 → 0 failures
make eval                  # CODE + LLM-Judge over those runs

# --- the real product carrying the same loop forward ---
make webapp                # 💻 dailybot in a browser tab at localhost:8501
make demo-dailybot         # 🤖 prove the loop also works on dailybot's shell tool
make chat-eval             # score the dailybot chat traces with the same eval pattern
```

## Stack
Python 3.12 • Google ADK 2.1 • OpenInference for Google ADK • Arize Phoenix Cloud •
`@arizeai/phoenix-mcp` (npx) • `phoenix.evals.ClassificationEvaluator` (LLM-Judge)
• Streamlit (web UI) • Gemini (`gemini-flash-latest` / `gemini-2.5-flash` /
`gemini-flash-lite-latest`, auto-rotating on quota)

**dailybot's 14-tool toolbelt:** `web_search` · `read_file` · `write_file` ·
`list_dir` · `find_files` · `shell_exec` (destructive ops blocked) ·
`execute_python` · `calendar_today` · `calendar_week` · `calendar_search` ·
`gmail_inbox_recent` · `gmail_search` · `gmail_draft_reply` (drafts only,
never sends) · `recall_failures` (the self-healing memory) — plus Phoenix
MCP's `get-spans` and `get-span-annotations` for runtime introspection.
