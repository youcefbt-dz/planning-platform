"""Print the model ids your GROQ_API_KEY can use.   Run from the project folder:  python scripts/list_groq_models.py"""
import json, os, sys, urllib.error, urllib.request
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except ImportError:
    pass

key = os.environ.get("GROQ_API_KEY", "").strip()
if not key:
    sys.exit("GROQ_API_KEY is empty: put it in .env first.")
req = urllib.request.Request("https://api.groq.com/openai/v1/models",
                             headers={"authorization": "Bearer " + key, "user-agent": "Mozilla/5.0 (compatible; Pilar/1.1)"})
try:
    data = json.load(urllib.request.urlopen(req, timeout=30))
except urllib.error.HTTPError as e:
    sys.exit(f"HTTP {e.code}: {e.read()[:300].decode('utf-8', 'replace')}")
skip = ("whisper", "guard", "orpheus", "tts", "safeguard")
ids = sorted(m["id"] for m in data.get("data", []) if not any(w in m["id"] for w in skip))
print("Chat models available to your key (put one in GROQ_MODEL):")
for i in ids:
    print("  ", i)
