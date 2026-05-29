# Self-Healing Gemini Agent

> Built for the Arize hackathon — a Gemini agent that **learns from its own mistakes by reading its own logs**. [Live demo transcript](TRANSCRIPT.md) · [Submission notes](SUBMISSION.md)

## What is this?

Your app is a **Gemini agent that learns from its own mistakes**. When it runs,
every step (every line of code it writes, every error it hits) is recorded in a
logging system called **Phoenix**. On a *fresh* run — **before doing anything
else** — the agent reads its own log from earlier runs. So if it tried `numpy`
last time and failed, it skips `numpy` this time.

The demo proves it twice: **Run 1** (cold) tries numpy → fails → falls back to
`statistics` and recovers. **Run 2** (informed) reads Run 1's log, skips numpy
entirely, succeeds on the first try.

That's the whole product. Everything else — MCP, ADK, evals, annotations — is
the plumbing that makes it real.

## 30-second walkthrough

**Run 1 — cold start.** The agent has no history. It tries `numpy`. The sandbox
doesn't have numpy installed, so it crashes. The agent reads the error, falls
back to Python's `statistics` module, and succeeds.

```
🧠 Let me check what's failed for me before …
→ No past failures — this is a cold start.
💻 Trying this code:
   import numpy as np ...
❌ That failed — I'll fix it and try again.
💻 Trying this code:
   import statistics ...
✅ It worked!
🤖 Since numpy was not installed in this environment, I fell back to the
   Python standard library.
```

**Run 2 — informed.** A brand new agent process with **zero local memory**.
Its only way to know about Run 1 is to read its own Phoenix log via MCP.

```
🧠 Let me check what's failed for me before …
→ Found 1 past failure(s). Reading them.
💻 Trying this code:
   import statistics ...           ← numpy skipped entirely!
✅ It worked!
🤖 Based on the past execution failure I retrieved, I learned that numpy is
   not available here. I skipped numpy and used the standard library.
```

```
📊 Self-Improvement Summary
  Run 1 (cold):     attempts=2  FAILURES=1
  Run 2 (informed): attempts=1  FAILURES=0
  ✅ The agent read its OWN trace history and avoided repeating the failure.
```

The failure count dropping from **1 → 0** *is* the self-improvement loop, made
measurable and verifiable.

## Glossary

- **Phoenix** — Arize's open-source AI observability platform. It records
  every step the agent takes so you can inspect it later.
- **MCP** — Model Context Protocol. A standard way to give an AI agent tools.
  Phoenix exposes its data over MCP so the agent can read its own traces.
- **Trace / Span** — A trace is one full agent run; a span is one step inside
  it (an LLM call, a tool call, etc).
- **Annotation** — A score or label attached to a span (e.g. an eval result).
- **ADK** — Google's Agent Development Kit. The framework the agent runs on.

## Try it yourself

```bash
git clone https://github.com/jacquesbusiness15-code/self-healing-gemini-agent
cd self-healing-gemini-agent
make setup            # creates venv, installs deps
cp .env.example .env   # then fill in your Phoenix + Gemini keys
make check             # auto-picks a Gemini model with quota
make demo              # 🎬 watch the agent learn from itself
```

---

## 📖 For developers

Everything below is the technical detail. If you just wanted to know what the
project does, you can stop reading here.

## The idea in one picture

```
Run 1 (cold, no history):
  recall_failures() → nothing yet
  execute_python(import numpy ...) → ModuleNotFoundError   ← fails
  execute_python(import statistics ...) → OK               ← self-recovers in-run

Run 2 (fresh session, ZERO local memory — only its Phoenix traces):
  recall_failures() → "numpy failed before: ModuleNotFoundError"
  execute_python(import statistics ...) → OK               ← skips numpy entirely, 0 failures
```

The agent's only memory across sessions is its **observability data**. It reads that
data at runtime and gets better. That delta (`2 failures → 0 failures`) is the
self-improvement loop.

---

## Architecture

| Piece | What it is |
|-------|-----------|
| **Runtime** | Google ADK `LlmAgent` (model via `GEMINI_MODEL`, default `gemini-2.5-flash`) |
| **Tracing** | `openinference-instrumentation-google-adk` → Phoenix Cloud (OpenInference/OTel) |
| **Action tool** | `execute_python` — runs code in-process; failures are recorded on the trace |
| **Introspection** | `recall_failures()` — reads the agent's own Phoenix traces and returns a clean summary of past failed code + errors |
| **MCP server** | `@arizeai/phoenix-mcp` (via `npx`), wired in with ADK `McpToolset` — the agent can also query `list-traces` / `get-spans` at runtime |
| **Evals** | `evaluate_runs.py` (code eval) + `evaluate_llm_judge.py` (LLM-as-Judge) — both scored from traces and written back as Phoenix span annotations |

### Files
- `self_healing_agent.py` — the agent, its tools, and `run_task()`. Run directly for a quick MCP-introspection check.
- `demo_self_healing.py` — **the centerpiece**: runs the same task twice in fresh sessions and prints the cold→learned delta.
- `evaluate_runs.py` — code eval: scores each run from its traces and logs `self_healing_quality` annotations back to Phoenix.
- `evaluate_llm_judge.py` — LLM-as-Judge **(via `phoenix.evals.ClassificationEvaluator`)**: Gemini grades each run's answer vs ground truth and logs `answer_correctness` annotations.
- `init_dataset.py` — creates the **Phoenix Dataset** `self-healing-stats` (one row: the 40-number task + ground-truth expected output).
- `run_experiment.py` — runs the cold-vs-informed contrast as **two Phoenix Experiments** on that dataset, so the failure-count delta surfaces in the Experiments UI.
- `_check_traces.py` — handy CLI to list spans in a project.
- `hello_world.py` / `instrumentation.py` — minimal "first trace" smoke test.

---

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # then fill in your PHOENIX_* and GEMINI_API_KEY
.venv/bin/python check_setup.py   # preflight: verifies keys, Phoenix, npx, and
                                  # auto-selects a Gemini model that has quota
```

`check_setup.py` writes a working `GEMINI_MODEL` into `.env` for you. The free tier is
~20 requests/day **per model**; if one is exhausted it picks another automatically.

## Run

```bash
# 1. Quick check: agent calls a Phoenix MCP tool at runtime
.venv/bin/python self_healing_agent.py

# 2. The self-healing demo (two fresh runs; prints the improvement delta + next steps)
.venv/bin/python demo_self_healing.py

# 3. Evaluate the runs from their traces (writes annotations back to Phoenix).
#    The demo prints the exact project name to use here.
.venv/bin/python evaluate_runs.py <project>        # code eval
.venv/bin/python evaluate_llm_judge.py <project>   # LLM-as-Judge
```

---

## How the judging criteria are met

1. **Technical implementation** — a real ADK tool-calling agent that writes & runs code.
2. **Meaningful tracing** — full `invocation → agent_run → call_llm / execute_tool` span trees in Phoenix, including recorded failures.
3. **MCP integration** — `@arizeai/phoenix-mcp` is wired into the agent via `McpToolset`; the agent calls `list-traces`/`get-spans` at runtime (verified — it even self-corrected an invalid `limit` argument live).
4. **Self-improvement loop** — the agent reads its own failure history via `recall_failures` and avoids repeating it across sessions; failures drop `2 → 0`.
5. **Evals** — both a **code eval** (`evaluate_runs.py`: `clean`/`healed`/`unresolved`) and an **LLM-as-Judge** (`evaluate_llm_judge.py`: grades answer correctness vs ground truth) score runs and write annotations back to Phoenix — themselves readable via the MCP `get-span-annotations` tool, closing the loop.

---

## Notes on the Gemini free tier (gotchas we hit)

- Limits are **per model**: ~5–20 requests/min and ~20 requests/day **each**. When one
  model's daily bucket is exhausted, switch with `GEMINI_MODEL=` (e.g. `gemini-flash-latest`).
- `gemini-2.0-flash` is **not** on the free tier (`limit: 0`).
- `gemini-2.5-flash` needs a thinking budget (`thinking_config`) to emit well-formed
  function calls with detailed instructions — disabling thinking caused `MALFORMED_FUNCTION_CALL`.
- For a smooth live demo, **enabling billing** removes these caps entirely (Gemini 2.5 Flash is very cheap).

## Troubleshooting

**Got `429 RESOURCE_EXHAUSTED` mid-test?** A single model's free-tier daily cap
is ~20 requests. Other models have their own buckets. Just re-run:

```bash
make check    # auto-rotates GEMINI_MODEL to a model that has quota
```

If no model has quota: wait for the daily reset (~midnight US Pacific), or
enable billing on your Google AI Studio project.

**Want to peek at quota state without touching `.env`?**

```bash
make quota
```

**Got `503 UNAVAILABLE`?** Google capacity blip, transient. `make check` will
switch you to a different model immediately.
