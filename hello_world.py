"""Smallest possible test: call Gemini and confirm a trace lands in Phoenix.
Run with:  .venv/bin/python hello_world.py
"""
import os

import instrumentation  # noqa: F401 -- MUST be first; sets up tracing before genai loads

from google import genai

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Why is the ocean salty? Answer in two sentences.",
)

print("\nGemini says:\n", response.text)
print("\n👉 Now open your Phoenix Cloud space — a trace should appear within ~30s.")
