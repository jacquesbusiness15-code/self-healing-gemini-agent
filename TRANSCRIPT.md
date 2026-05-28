# Demo transcript — the self-improvement loop, captured live

What you're looking at: a real, unedited transcript from running `make demo`
(verified end-to-end on `gemini-flash-latest`). Two **fresh sessions** with the
**same task**. Run 1 has no memory. Run 2 has no local memory either — its only
way to remember Run 1 is to read its own traces in Phoenix.

```
Phoenix project for this demo: selfheal-demo-202518
Model: gemini-flash-latest
========================================================================
RUN 1 — fresh agent, empty history (expect a numpy failure + recovery)
========================================================================

🧑 TASK: First call recall_failures to review your OWN past FAILED code so you
   don't repeat mistakes. Then compute the mean, population std, and median of
   this 40-number dataset, each rounded to 2 decimals. Use numpy first — UNLESS
   recall_failures shows numpy failed before, in which case skip it. Never give up.

🔍 introspect: recall_failures({})
📤 recall_failures -> {'past_failures': [], 'note': 'no trace history yet (cold start)'}
                                          ↑ empty — this is a TRULY cold run

🔧 execute_python:
import numpy as np
data = [12, 7, 22, ...]
mean = np.mean(data); std = np.std(data); median = np.median(data)
...

📤 execute_python -> {'status': 'error',
                     'error': "ModuleNotFoundError: No module named 'numpy'"}
                                                    ↑ the trap fires

🔧 execute_python:   ← self-recovers WITHIN the run, using the standard library
import statistics, math
data = [12, 7, 22, ...]
mean = sum(data)/len(data)
variance = sum((x-mean)**2 for x in data) / len(data)
pstd = math.sqrt(variance)
median = statistics.median(data)
print(f"Mean: {mean:.2f}\nPopulation Std Dev: {pstd:.2f}\nMedian: {median:.2f}")

📤 execute_python -> {'status': 'ok',
                     'stdout': 'Mean: 19.02\nPopulation Std Dev: 11.57\nMedian: 18.00\n'}

🤖 The calculations for the dataset have been successfully completed.
   Since `numpy` was not installed in this environment (resulting in a
   `ModuleNotFoundError`), I fell back to using the Python standard library
   as per the instructions.

   Mean: 19.02   |   Population Std Dev: 11.57   |   Median: 18.00

… waiting for Run 1 traces to be queryable in Phoenix …
… pacing 65s so the per-minute rate limit resets …

========================================================================
RUN 2 — fresh agent, SAME task, but it can now read Run 1's trace via MCP
========================================================================

🧑 TASK: (identical to Run 1)

🔍 introspect: recall_failures({})
📤 recall_failures -> {'past_failures': [{
       'failed_code': 'import numpy as np\ndata = [12, 7, 22, ...]...',
       'error':       "ModuleNotFoundError: No module named 'numpy'"
                    ↑ Run 2 — a fresh process with zero local memory —
                      sees Run 1's failure by reading its own Phoenix traces
   }]}

🔧 execute_python:   ← skips numpy entirely on the FIRST attempt
import statistics
data = [12, 7, 22, ...]
mean    = statistics.mean(data)
pstdev  = statistics.pstdev(data)
median  = statistics.median(data)
print(f"Mean: {round(mean,2)}\nPopulation Std Dev: {round(pstdev,2)}\nMedian: {round(median,2)}")

📤 execute_python -> {'status': 'ok',
                     'stdout': 'Mean: 19.02\nPopulation Std Dev: 11.57\nMedian: 18.0\n'}

🤖 Based on the past execution failure retrieved from `recall_failures`, I
   learned that `numpy` is not available in this environment
   (`ModuleNotFoundError`). Therefore, I skipped `numpy` entirely and directly
   used Python's standard `statistics` library to perform the calculations.

   Mean: 19.02   |   Population Standard Deviation: 11.57   |   Median: 18.00

########################################################################
SELF-IMPROVEMENT SUMMARY
  Run 1 (cold):     attempts=2  FAILURES=1  introspection_calls=1
  Run 2 (informed): attempts=1  FAILURES=0  introspection_calls=1
  ✅ The agent read its OWN trace history and avoided repeating the failure.
########################################################################
```

## Then the evals — both written back to Phoenix as annotations

```
$ make eval

Evaluating project 'selfheal-demo-202518' — 2 traces
==========================================================================
  c5b78257f21b…  clean      score=1.0  | 1 code attempts, 0 failed; recovered; introspected=True   ← Run 2
  136cbf3792f9…  healed     score=1.0  | 2 code attempts, 1 failed; recovered; introspected=True   ← Run 1
==========================================================================

LLM-as-Judge (gemini-flash-latest) — ground truth: mean=19.02, std=11.57, median=18.0
==========================================================================
  c5b78257f21b…  correct  | The agent correctly reported all three values...
  136cbf3792f9…  correct  | The agent correctly computed all three values...
==========================================================================
```

Both annotations land on the root spans in Phoenix and are queryable via the
MCP `get-span-annotations` tool — meaning the agent could even read its own
grades on its next run. The loop is fully closed.
