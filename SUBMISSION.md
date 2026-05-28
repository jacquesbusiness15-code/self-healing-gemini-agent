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
make test                  # full sequence: demo + both evals
```

## Stack
Python 3.12 • Google ADK 2.1 • OpenInference for Google ADK • Arize Phoenix Cloud •
`@arizeai/phoenix-mcp` (npx) • Gemini (`gemini-flash-latest` / `gemini-2.5-flash`)
