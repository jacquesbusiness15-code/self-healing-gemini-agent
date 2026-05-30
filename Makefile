# Self-Healing Gemini Agent — convenience targets
# All commands assume the venv at .venv

PY := .venv/bin/python

.PHONY: setup check quota tutorial mcp-check demo dataset experiment eval test chat webapp webapp-stop webapp-logs google-setup clean help

help:
	@echo "make setup        — create venv + install requirements"
	@echo "make webapp       — 💻 open the bot in a browser tab (background server, recommended)"
	@echo "make webapp-stop  — stop the background webapp server"
	@echo "make webapp-logs  — tail the background webapp server's log"
	@echo "make chat         — 💬 same bot in the terminal (foreground)"
	@echo "make tutorial     — 🟢 NEW HERE? Guided walkthrough, lesson by lesson"
	@echo "make google-setup — one-time: connect Google Calendar + Gmail (optional)"
	@echo "make check        — preflight (env vars, Phoenix, auto-pin a model with quota)"
	@echo "make quota        — probe all candidate models (read-only, does not touch .env)"
	@echo "make mcp-check    — quick agent run that calls Phoenix MCP at runtime"
	@echo "make demo         — the 2-run self-healing demo (narrated, the centerpiece)"
	@echo "make dataset      — create the Phoenix Dataset 'self-healing-stats' (idempotent)"
	@echo "make experiment   — run cold-vs-informed as a Phoenix Experiment (uses quota)"
	@echo "make eval         — run code eval + LLM-as-Judge on the latest demo project"
	@echo "make test         — full sequence: check → demo → eval"

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

chat:
	$(PY) -m dailybot

webapp:
	@if curl -sf http://localhost:8501/_stcore/health 2>/dev/null | grep -q ok; then \
		echo "✅ dailybot is already running at http://localhost:8501"; \
	else \
		mkdir -p .dailybot; \
		echo "🚀 Starting dailybot in the background…"; \
		nohup $(PY) -m streamlit run dailybot/webapp.py \
			--server.headless=true --server.port=8501 \
			--browser.gatherUsageStats=false \
			> .dailybot/webapp.log 2>&1 < /dev/null & \
		echo $$! > .dailybot/webapp.pid; \
		ready=0; \
		for i in $$(seq 1 30); do \
			if curl -sf http://localhost:8501/_stcore/health 2>/dev/null | grep -q ok; then \
				ready=1; break; \
			fi; \
			sleep 1; \
		done; \
		if [ "$$ready" = "0" ]; then \
			echo "❌ Server didn't come up within 30 s. Last 20 log lines:"; \
			tail -20 .dailybot/webapp.log 2>/dev/null || true; \
			exit 1; \
		fi; \
		echo "✅ Ready"; \
	fi
	@( xdg-open http://localhost:8501 >/dev/null 2>&1 || open http://localhost:8501 >/dev/null 2>&1 ) || true
	@echo ""
	@echo "📍 dailybot is running at http://localhost:8501"
	@echo "📍 The server keeps running even if you close this terminal."
	@echo "📍 Stop:  make webapp-stop"
	@echo "📍 Logs:  make webapp-logs"

webapp-stop:
	@if [ -f .dailybot/webapp.pid ]; then \
		pid=$$(cat .dailybot/webapp.pid); \
		if kill "$$pid" 2>/dev/null; then \
			rm -f .dailybot/webapp.pid; \
			echo "✅ stopped (pid $$pid)"; \
		else \
			rm -f .dailybot/webapp.pid; \
			echo "(stale pid file removed; nothing was running)"; \
		fi; \
	else \
		echo "(nothing was running)"; \
	fi

webapp-logs:
	@if [ -f .dailybot/webapp.log ]; then \
		tail -f .dailybot/webapp.log; \
	else \
		echo "No log yet — start with 'make webapp' first"; \
	fi

google-setup:
	$(PY) setup_google.py

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
