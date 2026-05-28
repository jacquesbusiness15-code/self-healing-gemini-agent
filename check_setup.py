"""Preflight: confirm the environment is ready to test, and auto-select a Gemini
model that currently has free-tier quota (written to .env as GEMINI_MODEL).

Run:  .venv/bin/python check_setup.py
"""
import os
import sys
import shutil

from dotenv import load_dotenv, set_key
load_dotenv()

OK, BAD = "✅", "❌"
ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")

print("Self-Healing Agent — preflight\n" + "=" * 52)

# 1) Required .env keys
missing = [k for k in ("PHOENIX_API_KEY", "PHOENIX_COLLECTOR_ENDPOINT", "GEMINI_API_KEY")
           if not os.environ.get(k, "").strip()]
for k in ("PHOENIX_API_KEY", "PHOENIX_COLLECTOR_ENDPOINT", "GEMINI_API_KEY"):
    print(f"{OK if k not in missing else BAD} {k}{'' if k not in missing else '  (MISSING in .env)'}")
if missing:
    print("\nFill the missing keys in .env (see .env.example), then re-run.")
    sys.exit(1)

# 2) Packages
try:
    import google.adk  # noqa
    import phoenix.otel  # noqa
    from phoenix.client import Client
    import openinference.instrumentation.google_adk  # noqa
    import mcp  # noqa
    from google import genai
    print(f"{OK} Python packages importable")
except Exception as exc:
    print(f"{BAD} import failed: {exc}")
    print("   → .venv/bin/pip install -r requirements.txt")
    sys.exit(1)

# 3) Phoenix reachable + authenticated
try:
    px = Client(base_url=os.environ["PHOENIX_COLLECTOR_ENDPOINT"],
                api_key=os.environ["PHOENIX_API_KEY"])
    px.spans.get_spans(project_identifier="gemini-hackathon", limit=1)
    print(f"{OK} Phoenix reachable + authenticated")
except Exception as exc:
    if "404" in str(exc):
        print(f"{OK} Phoenix reachable (no traces yet)")
    else:
        print(f"{BAD} Phoenix not reachable: {str(exc)[:80]}")
        sys.exit(1)

# 4) npx (for the Phoenix MCP server)
print(f"{OK} npx present" if shutil.which("npx")
      else f"{BAD} npx not found — install Node.js for the MCP server")

# 5) Pick a Gemini model that has quota right now
gc = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
preset = os.environ.get("GEMINI_MODEL", "").strip()
candidates = list(dict.fromkeys(
    ([preset] if preset else [])
    + ["gemini-2.5-flash", "gemini-flash-latest",
       "gemini-2.5-flash-lite", "gemini-flash-lite-latest"]))
print("\nProbing Gemini models for available quota …")
chosen = None
for m in candidates:
    try:
        gc.models.generate_content(model=m, contents="ok")
        print(f"  {OK} {m} — available")
        chosen = m
        break
    except Exception as exc:
        msg = str(exc)
        tag = ("limit 0 (not on free tier)" if "limit: 0" in msg
               else "daily quota used up" if ("429" in msg or "RESOURCE_EXHAUSTED" in msg)
               else msg[:50])
        print(f"  {BAD} {m} — {tag}")

if not chosen:
    print(f"\n{BAD} No Gemini model has free-tier quota right now.")
    print("   → wait for the daily reset (~midnight US Pacific), or enable billing.")
    sys.exit(1)

if preset:
    print(f"\n{OK} Using your pinned GEMINI_MODEL={chosen}")
else:
    set_key(ENV_PATH, "GEMINI_MODEL", chosen)
    print(f"\n{OK} Wrote GEMINI_MODEL={chosen} to .env")

print("=" * 52)
print("READY TO TEST. Next:")
print("  .venv/bin/python demo_self_healing.py     # the self-healing demo")
print("Then evaluate the project it prints:")
print("  .venv/bin/python evaluate_runs.py <project>")
print("  .venv/bin/python evaluate_llm_judge.py <project>")
