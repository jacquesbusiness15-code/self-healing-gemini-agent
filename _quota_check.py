"""Quick probe of all candidate Gemini models — read-only, does NOT touch .env.
Useful for answering "is it me or them?" when debugging a 429.

Run:  .venv/bin/python _quota_check.py
"""
import os
from dotenv import load_dotenv
load_dotenv()
from google import genai

CANDIDATES = [
    "gemini-2.5-flash",
    "gemini-flash-latest",
    "gemini-2.5-flash-lite",
    "gemini-flash-lite-latest",
]

gc = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
for m in CANDIDATES:
    try:
        gc.models.generate_content(model=m, contents="ok")
        print(f"  ✅ {m} — available")
    except Exception as exc:
        msg = str(exc)
        tag = ("limit 0 (not on free tier)" if "limit: 0" in msg
               else "exhausted" if ("429" in msg or "RESOURCE_EXHAUSTED" in msg)
               else "503 (capacity blip)" if "503" in msg
               else msg[:50])
        print(f"  ❌ {m} — {tag}")
