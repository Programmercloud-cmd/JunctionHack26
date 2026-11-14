"""Credential-safe local environment check. Does not make provider calls."""
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
print(f"Python: {sys.version.split()[0]}")
missing = []
for name in ("fastapi", "uvicorn", "google-genai", "openai", "pillow", "pypdfium2", "ifcopenshell", "shapely", "pytest"):
    try:
        print(f"{name}: {version(name)}")
    except PackageNotFoundError:
        missing.append(name)
        print(f"{name}: missing")
try:
    from dotenv import load_dotenv
    import os
    load_dotenv(ROOT / ".env.local")
    print("Selected provider: " + os.getenv("AI_PROVIDER", "gemini"))
    print("Gemini credential: " + ("configured (not verified)" if os.getenv("GEMINI_API_KEY") else "missing"))
    print("OpenAI credential: " + ("configured (not verified)" if os.getenv("OPENAI_API_KEY") else "missing"))
except ImportError:
    print("Configuration check unavailable; run bash scripts/bootstrap.sh")
raise SystemExit(bool(missing))
