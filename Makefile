# Self-Healing Gemini Agent — convenience targets
# All commands assume the venv at .venv

PY := .venv/bin/python

.PHONY: setup check quota tutorial mcp-check demo dataset experiment eval test clean help

help:
	@echo "make setup      — create venv + install requirements"
	@echo "make tutorial   — 🟢 NEW HERE? Guided walkthrough, lesson by lesson"
	@echo "make check      — preflight (env vars, Phoenix, auto-pin a model with quota)"
	@echo "make quota      — probe all candidate models (read-only, does not touch .env)"
	@echo "make mcp-check  — quick agent run that calls Phoenix MCP at runtime"
	@echo "make demo       — the 2-run self-healing demo (narrated, the centerpiece)"
	@echo "make dataset    — create the Phoenix Dataset 'self-healing-stats' (idempotent)"
	@echo "make experiment — run cold-vs-informed as a Phoenix Experiment (uses quota)"
	@echo "make eval       — run code eval + LLM-as-Judge on the latest demo project"
	@echo "make test       — full sequence: check → demo → eval"

setup:
	python3 -m venv .venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -r requirements.txt
	@echo "→ now copy .env.example to .env and fill in your keys, then 'make check'"

check:
	$(PY) check_setup.py

quota:
	$(PY) _quota_check.py

tutorial:
	$(PY) tutorial.py

mcp-check:
	$(PY) self_healing_agent.py

demo:
	$(PY) demo_self_healing.py

dataset:
	$(PY) init_dataset.py

experiment:
	$(PY) run_experiment.py

eval:
	$(PY) evaluate_runs.py
	$(PY) evaluate_llm_judge.py

test: check demo eval
	@echo ""
	@echo "✅ Full test sequence complete. Open Phoenix Cloud to inspect the trace tree."

clean:
	rm -rf __pycache__ .venv
