"""Sets up Phoenix tracing. Import this FIRST, before `google.genai`,
so every Gemini call gets recorded as a span and shipped to Phoenix Cloud."""
import os

from dotenv import load_dotenv

load_dotenv()  # reads PHOENIX_API_KEY, PHOENIX_COLLECTOR_ENDPOINT, GEMINI_API_KEY from .env

from phoenix.otel import register
from openinference.instrumentation.google_genai import GoogleGenAIInstrumentor

# register() auto-reads PHOENIX_API_KEY + PHOENIX_COLLECTOR_ENDPOINT from the env.
tracer_provider = register(
    project_name=os.getenv("PHOENIX_PROJECT_NAME", "gemini-hackathon"),
)

# Wire the Gemini SDK into the tracer so calls become spans automatically.
GoogleGenAIInstrumentor().instrument(tracer_provider=tracer_provider)

print("✅ Phoenix tracing initialized.")
